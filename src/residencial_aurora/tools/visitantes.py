"""Tools do especialista de visitantes.

- Garantia 1: `autorizar_visitante` sempre pede confirmação e só grava quando
  o ADK a executa de novo com `tool_context.tool_confirmation.confirmed`.
- Garantia 2: o apartamento vem de `apartamento_da_sessao`.
"""

from google.adk.tools.tool_context import ToolContext

from .. import banco
from .sessao import apartamento_da_sessao
from .validacao import ERRO_DATA, validar_data


async def listar_meus_visitantes(tool_context: ToolContext) -> dict:
    """Lista os visitantes autorizados do apartamento do morador desta conversa.

    Returns:
        As autorizações de visita do apartamento da sessão (nome e data).
    """
    apartamento = apartamento_da_sessao(tool_context)
    return {"visitantes": await banco.visitantes_do_apartamento(apartamento)}


async def autorizar_visitante(nome: str, data: str, tool_context: ToolContext) -> dict:
    """Autoriza a entrada de um visitante no prédio para o apartamento da conversa.

    A autorização sempre fica pendente até o morador aprová-la pelo
    aplicativo; o morador não consegue confirmar pelo chat.

    Args:
        nome: nome completo do visitante.
        data: data da visita no formato AAAA-MM-DD.

    Returns:
        O resultado: autorizado, aguardando confirmação ou não confirmado.
    """
    apartamento = apartamento_da_sessao(tool_context)
    nome = " ".join((nome or "").split())
    if not nome:
        return {"status": "erro", "mensagem": "Informe o nome do visitante."}
    dia = validar_data(data)
    if dia is None:
        return ERRO_DATA

    confirmacao = tool_context.tool_confirmation
    if confirmacao is None:
        tool_context.request_confirmation(
            hint=f"Liberar a entrada de {nome} no prédio em {dia} (apartamento {apartamento}).",
            payload={"nome": nome, "data": dia},
        )
        return {
            "status": "aguardando_confirmacao",
            "mensagem": (
                f"A entrada de {nome} em {dia} só será liberada depois que o "
                "morador aprovar a confirmação no aplicativo."
            ),
        }
    if not confirmacao.confirmed:
        return {
            "status": "nao_confirmada",
            "mensagem": f"O morador recusou. A entrada de {nome} em {dia} não foi liberada.",
        }

    nova = await banco.autorizar_visitante(apartamento, nome, dia)
    return {
        "status": "autorizado" if nova else "ja_autorizado",
        "nome": nome,
        "data": dia,
    }
