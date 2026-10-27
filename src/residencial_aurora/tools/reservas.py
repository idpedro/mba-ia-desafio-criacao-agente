"""Tools do especialista de reservas.

- Garantia 1: `reservar_area` em área com taxa pede confirmação com
  `tool_context.request_confirmation` e só grava quando o ADK a executa de novo
  com `tool_context.tool_confirmation.confirmed`, o que só acontece quando a
  rota de confirmações da API envia a resposta.
- Garantia 2: o apartamento vem de `apartamento_da_sessao`, e a agenda só
  informa "livre/ocupada", nunca de quem é a reserva.
- Garantia 5: a gravação passa por `banco.criar_reserva`, protegida pelo
  índice único do banco.
"""

import re
import unicodedata
from typing import Optional

from google.adk.tools.tool_context import ToolContext

from .. import banco
from .sessao import apartamento_da_sessao
from .validacao import ERRO_DATA, validar_data


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", texto.lower()).strip("-")


def _resolver_area(area: str) -> banco.Area | None:
    chave = _normalizar(area or "")
    if not chave:
        return None
    for a in banco.AREAS.values():
        if chave in (a.id, _normalizar(a.nome)):
            return a
    candidatas = [
        a
        for a in banco.AREAS.values()
        if chave in _normalizar(a.nome) or a.id in chave
    ]
    return candidatas[0] if len(candidatas) == 1 else None


def _erro_area(area: str) -> dict:
    return {
        "status": "erro",
        "mensagem": f"Área '{area}' não existe.",
        "areas_validas": [a.id for a in banco.AREAS.values()],
    }


def listar_areas() -> dict:
    """Lista as áreas comuns que podem ser reservadas, com a taxa de cada uma.

    Returns:
        As áreas com id, nome, taxa em reais e se a reserva gera cobrança.
    """
    return {
        "areas": [
            {"id": a.id, "nome": a.nome, "taxa": a.taxa, "gera_cobranca": a.gera_cobranca}
            for a in banco.AREAS.values()
        ]
    }


async def consultar_disponibilidade(area: str, data: str) -> dict:
    """Informa se uma área comum está livre ou ocupada em uma data.

    Args:
        area: id da área (salao-de-festas, churrasqueira ou quadra).
        data: data no formato AAAA-MM-DD.

    Returns:
        Apenas se a data está livre ou ocupada, sem dizer de quem é a reserva.
    """
    info = _resolver_area(area)
    if info is None:
        return _erro_area(area)
    dia = validar_data(data)
    if dia is None:
        return ERRO_DATA
    livre = await banco.area_livre(info.id, dia)
    return {"area": info.id, "data": dia, "situacao": "livre" if livre else "ocupada"}


async def listar_minhas_reservas(tool_context: ToolContext) -> dict:
    """Lista as reservas ativas do apartamento do morador desta conversa.

    Returns:
        As reservas ativas do apartamento da sessão (código, área e data).
    """
    apartamento = apartamento_da_sessao(tool_context)
    return {"reservas": await banco.reservas_do_apartamento(apartamento)}


async def reservar_area(area: str, data: str, tool_context: ToolContext) -> dict:
    """Reserva uma área comum para o apartamento do morador desta conversa.

    Áreas com taxa ficam pendentes até o morador aprovar a cobrança pelo
    aplicativo; o morador não consegue confirmar pelo chat.

    Args:
        area: id da área (salao-de-festas, churrasqueira ou quadra).
        data: data da reserva no formato AAAA-MM-DD.

    Returns:
        O resultado da reserva: criada (com o código), aguardando confirmação,
        não confirmada ou indisponível.
    """
    apartamento = apartamento_da_sessao(tool_context)
    info = _resolver_area(area)
    if info is None:
        return _erro_area(area)
    dia = validar_data(data)
    if dia is None:
        return ERRO_DATA

    confirmacao = tool_context.tool_confirmation
    if confirmacao is None:
        if not await banco.area_livre(info.id, dia):
            return {
                "status": "indisponivel",
                "mensagem": f"{info.nome} já está reservado(a) em {dia}. Escolha outra data.",
            }
        if info.gera_cobranca:
            tool_context.request_confirmation(
                hint=(
                    f"Reservar {info.nome} em {dia} gera cobrança de "
                    f"R$ {info.taxa:.2f} para o apartamento {apartamento}."
                ),
                payload={
                    "area": info.id,
                    "nome_area": info.nome,
                    "data": dia,
                    "taxa": info.taxa,
                },
            )
            return {
                "status": "aguardando_confirmacao",
                "mensagem": (
                    f"A reserva de {info.nome} em {dia} gera cobrança de "
                    f"R$ {info.taxa:.2f} e só será feita depois que o morador "
                    "aprovar a confirmação no aplicativo."
                ),
            }
    elif not confirmacao.confirmed:
        return {
            "status": "nao_confirmada",
            "mensagem": f"O morador recusou a cobrança. A reserva de {info.nome} em {dia} não foi feita.",
        }

    # Área sem taxa, ou cobrança aprovada pela rota de confirmações.
    try:
        reserva = await banco.criar_reserva(apartamento, info.id, dia)
    except banco.DataIndisponivel:
        return {
            "status": "indisponivel",
            "mensagem": f"{info.nome} já foi reservado(a) em {dia} por outra unidade. A reserva não foi feita.",
        }
    return {
        "status": "reservada",
        "codigo": reserva["codigo"],
        "area": info.id,
        "data": dia,
        "cobranca": info.taxa if info.gera_cobranca else 0,
    }


async def cancelar_reserva(
    tool_context: ToolContext,
    codigo: Optional[str] = None,
    area: Optional[str] = None,
    data: Optional[str] = None,
) -> dict:
    """Cancela uma reserva do apartamento do morador desta conversa.

    Informe o código da reserva, ou a área e a data. Só reservas do próprio
    apartamento podem ser canceladas.

    Args:
        codigo: código da reserva, se o morador souber.
        area: id da área da reserva (quando não houver código).
        data: data da reserva no formato AAAA-MM-DD (quando não houver código).

    Returns:
        A reserva cancelada, ou o aviso de que não há reserva do apartamento
        com esses dados.
    """
    apartamento = apartamento_da_sessao(tool_context)
    minhas = await banco.reservas_do_apartamento(apartamento)

    if codigo:
        alvo = [r for r in minhas if r["codigo"].upper() == codigo.strip().upper()]
    else:
        info = _resolver_area(area) if area else None
        dia = validar_data(data) if data else None
        if area and info is None:
            return _erro_area(area)
        if data and dia is None:
            return ERRO_DATA
        if info is None and dia is None:
            return {"status": "erro", "mensagem": "Informe o código ou a área e a data da reserva."}
        alvo = [
            r
            for r in minhas
            if (info is None or r["area"] == info.id) and (dia is None or r["data"] == dia)
        ]

    if not alvo:
        return {
            "status": "nao_encontrada",
            "mensagem": "Não há reserva ativa do seu apartamento com esses dados.",
        }
    if len(alvo) > 1:
        return {
            "status": "ambigua",
            "mensagem": "Há mais de uma reserva sua com esses dados. Informe o código.",
            "reservas": alvo,
        }
    reserva = alvo[0]
    if not await banco.cancelar_reserva(apartamento, reserva["codigo"]):
        return {"status": "nao_encontrada", "mensagem": "A reserva já não está ativa."}
    return {"status": "cancelada", **reserva}
