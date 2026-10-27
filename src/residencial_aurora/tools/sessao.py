"""Garantia 2: o apartamento que as tools usam vem da sessão, nunca do modelo.

Nenhuma tool recebe apartamento como parâmetro. Todas as que tocam dados de
um apartamento chamam `apartamento_da_sessao`, que lê o `user_id` da sessão
(fixado pela API na criação) e confere com o `state["apartamento"]`.
"""

from google.adk.tools.tool_context import ToolContext

CHAVE_APARTAMENTO = "apartamento"


class SessaoSemApartamento(Exception):
    pass


def apartamento_da_sessao(tool_context: ToolContext) -> str:
    apartamento = tool_context.user_id
    if not apartamento or tool_context.state.get(CHAVE_APARTAMENTO) != apartamento:
        raise SessaoSemApartamento("Sessão sem apartamento válido.")
    return apartamento
