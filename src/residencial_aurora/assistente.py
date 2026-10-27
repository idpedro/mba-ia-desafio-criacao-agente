"""Execução do assistente: Runner, sessões persistidas e confirmações.

Garantia 1: as confirmações pendentes são calculadas a partir dos eventos
gravados na sessão (chamadas `adk_request_confirmation` sem resposta). A rota
de confirmações só aceita um `id` dessa lista; qualquer outro recebe 409 antes
de qualquer coisa chegar ao Runner. A resposta aceita vira um FunctionResponse
`adk_request_confirmation`, que o Runner entrega ao especialista que pediu a
confirmação, e o ADK executa de novo a tool original com `tool_confirmation`.

Garantia 3: sessões e eventos ficam no SqliteSessionService (var/sessoes.db)
e os dados do condomínio em var/condominio.db, então um reinício não perde nada.
"""

import asyncio
import logging
import uuid
from collections import defaultdict
from typing import Any

from google.adk.apps import App
from google.adk.runners import Runner
from google.adk.sessions import Session
from google.adk.sessions.sqlite_session_service import SqliteSessionService
from google.genai import errors as genai_errors
from google.genai import types

from . import banco, config
from .agentes import criar_agente_principal
from .tools.sessao import CHAVE_APARTAMENTO

logger = logging.getLogger(__name__)

PEDIDO_DE_CONFIRMACAO = "adk_request_confirmation"


class SessaoNaoEncontrada(Exception):
    pass


class ConfirmacaoNaoPendente(Exception):
    pass


def confirmacoes_pendentes(sessao: Session) -> list[dict[str, Any]]:
    """Pedidos de confirmação gravados na sessão que ainda não têm resposta."""
    pedidos: dict[str, types.FunctionCall] = {}
    respondidos: set[str] = set()
    for evento in sessao.events:
        for chamada in evento.get_function_calls():
            if chamada.name == PEDIDO_DE_CONFIRMACAO and chamada.id:
                pedidos[chamada.id] = chamada
        for resposta in evento.get_function_responses():
            if resposta.name == PEDIDO_DE_CONFIRMACAO and resposta.id:
                respondidos.add(resposta.id)

    pendentes = []
    for id_, chamada in pedidos.items():
        if id_ in respondidos:
            continue
        args = chamada.args or {}
        original = args.get("originalFunctionCall") or {}
        confirmacao = args.get("toolConfirmation") or {}
        detalhes = dict(confirmacao.get("payload") or original.get("args") or {})
        if confirmacao.get("hint"):
            detalhes["descricao"] = confirmacao["hint"]
        pendentes.append(
            {"id": id_, "acao": original.get("name", ""), "detalhes": detalhes}
        )
    return pendentes


def _texto_da_resposta(eventos: list) -> str:
    textos = []
    for evento in eventos:
        if evento.author == "user" or evento.partial or not evento.content:
            continue
        for parte in evento.content.parts or []:
            if parte.text and not parte.thought:
                textos.append(parte.text.strip())
    return "\n\n".join(t for t in textos if t)


def _texto_de_contingencia(eventos: list) -> str:
    """Resumo vindo das tools quando o modelo falha depois de executá-las."""
    mensagens = []
    for evento in eventos:
        for resposta in evento.get_function_responses():
            dados = resposta.response or {}
            if resposta.name == PEDIDO_DE_CONFIRMACAO:
                continue
            if dados.get("status") == "reservada":
                mensagens.append(
                    f"Reserva {dados['codigo']} confirmada: {dados['area']} em {dados['data']}."
                )
            elif dados.get("status") in ("autorizado", "ja_autorizado"):
                mensagens.append(
                    f"Entrada de {dados['nome']} autorizada para {dados['data']}."
                )
            elif dados.get("mensagem"):
                mensagens.append(str(dados["mensagem"]))
    return " ".join(mensagens) or (
        "Não consegui concluir o atendimento agora. Tente novamente em instantes."
    )


class Assistente:
    def __init__(self) -> None:
        config.VAR_DIR.mkdir(parents=True, exist_ok=True)
        banco.inicializar()
        self.session_service = SqliteSessionService(str(config.SESSOES_PATH))
        self.app = App(name=config.APP_NAME, root_agent=criar_agente_principal())
        self.runner = Runner(app=self.app, session_service=self.session_service)
        # Uma execução por sessão de cada vez.
        self._travas: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def fechar(self) -> None:
        await self.runner.close()

    # -- sessões ------------------------------------------------------------

    async def criar_sessao(self, apartamento: str) -> str:
        session_id = uuid.uuid4().hex
        # O apartamento é gravado uma única vez: como user_id da sessão e no
        # state. Nenhuma rota ou tool altera esses valores depois.
        await self.session_service.create_session(
            app_name=config.APP_NAME,
            user_id=apartamento,
            session_id=session_id,
            state={CHAVE_APARTAMENTO: apartamento},
        )
        await banco.vincular_sessao(session_id, apartamento)
        return session_id

    async def obter_sessao(self, session_id: str) -> Session:
        apartamento = await banco.apartamento_da_sessao(session_id)
        if apartamento is None:
            raise SessaoNaoEncontrada(session_id)
        sessao = await self.session_service.get_session(
            app_name=config.APP_NAME, user_id=apartamento, session_id=session_id
        )
        if sessao is None:
            raise SessaoNaoEncontrada(session_id)
        return sessao

    async def eventos(self, session_id: str) -> list[dict[str, Any]]:
        sessao = await self.obter_sessao(session_id)
        return [
            evento.model_dump(mode="json", exclude_none=True, by_alias=True)
            for evento in sessao.events
        ]

    # -- conversa -----------------------------------------------------------

    async def enviar_mensagem(self, session_id: str, texto: str) -> dict[str, Any]:
        async with self._travas[session_id]:
            sessao = await self.obter_sessao(session_id)
            mensagem = types.Content(role="user", parts=[types.Part(text=texto)])
            return await self._executar(sessao, mensagem)

    async def responder_confirmacao(
        self, session_id: str, confirmacao_id: str, confirmado: bool
    ) -> dict[str, Any]:
        async with self._travas[session_id]:
            sessao = await self.obter_sessao(session_id)
            pendentes = {p["id"] for p in confirmacoes_pendentes(sessao)}
            if confirmacao_id not in pendentes:
                raise ConfirmacaoNaoPendente(confirmacao_id)
            resposta = types.Content(
                role="user",
                parts=[
                    types.Part(
                        function_response=types.FunctionResponse(
                            id=confirmacao_id,
                            name=PEDIDO_DE_CONFIRMACAO,
                            response={"confirmed": confirmado},
                        )
                    )
                ],
            )
            return await self._executar(sessao, resposta)

    async def _executar(self, sessao: Session, mensagem: types.Content) -> dict[str, Any]:
        eventos = []
        try:
            async for evento in self.runner.run_async(
                user_id=sessao.user_id, session_id=sessao.id, new_message=mensagem
            ):
                eventos.append(evento)
            resposta = _texto_da_resposta(eventos)
        except genai_errors.APIError:
            logger.exception("Falha ao chamar o modelo na sessão %s", sessao.id)
            resposta = _texto_de_contingencia(eventos)

        atualizada = await self.obter_sessao(sessao.id)
        return {
            "resposta": resposta,
            "confirmacoes_pendentes": confirmacoes_pendentes(atualizada),
        }
