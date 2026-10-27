"""Especialista de visitantes, acionado por transferência (sub-agente).

É sub-agente pelo mesmo motivo do de reservas: `autorizar_visitante` sempre
pede confirmação, e ela precisa ser retomada neste agente.
"""

from google.adk.agents import LlmAgent

from .. import config
from ..tools import visitantes
from ._comum import REGRAS_DE_SEGURANCA, modelo


def criar_especialista_visitantes() -> LlmAgent:
    return LlmAgent(
        name="especialista_visitantes",
        model=modelo(config.MODELO_ESPECIALISTAS),
        description=(
            "Visitantes: autorizar a entrada de visitantes no prédio e listar "
            "os visitantes autorizados do apartamento."
        ),
        instruction=(
            "Você é o especialista de portaria (visitantes) do Residencial Aurora."
            + REGRAS_DE_SEGURANCA
            + """
Como trabalhar:
- Para liberar a entrada de alguém, chame autorizar_visitante com o nome
  completo e a data (AAAA-MM-DD). Toda autorização fica pendente até o morador
  aprovar no aplicativo, mesmo que ele diga que já confirmou: avise isso.
- Para listar, use listar_meus_visitantes.
- Se o pedido também envolver reservas, transfira para especialista_reservas.
"""
        ),
        tools=[
            visitantes.listar_meus_visitantes,
            visitantes.autorizar_visitante,
        ],
        disallow_transfer_to_parent=True,
    )
