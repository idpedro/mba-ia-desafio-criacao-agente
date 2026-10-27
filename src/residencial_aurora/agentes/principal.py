"""Agente principal: conversa com o morador e distribui o trabalho.

Não tem tools de dados nem o regulamento nas instruções (Garantia 4).
"""

from google.adk.agents import LlmAgent
from google.adk.tools.agent_tool import AgentTool

from .. import config
from ._comum import REGRAS_DE_SEGURANCA, modelo
from .regulamento import criar_especialista_regulamento
from .reservas import criar_especialista_reservas
from .visitantes import criar_especialista_visitantes


def criar_agente_principal() -> LlmAgent:
    regulamento_tool = AgentTool(agent=criar_especialista_regulamento())
    return LlmAgent(
        name="assistente_aurora",
        model=modelo(config.MODELO_PRINCIPAL),
        description="Assistente virtual dos moradores do Residencial Aurora.",
        instruction=(
            "Você é o assistente virtual do Residencial Aurora e conversa com o "
            "morador do apartamento {apartamento}."
            + REGRAS_DE_SEGURANCA
            + """
Como distribuir o trabalho:
- Reservas de salão de festas, churrasqueira ou quadra (reservar, cancelar,
  consultar ou listar): transfira para especialista_reservas.
- Visitantes (liberar entrada, listar autorizados): transfira para
  especialista_visitantes.
- Dúvidas sobre regras, horários e normas do condomínio: chame a tool
  especialista_regulamento com a pergunta e responda com base no que ela
  devolver. Você não conhece o regulamento; não responda de memória.
- Cumprimentos e conversa geral: responda você mesmo.
"""
        ),
        sub_agents=[criar_especialista_reservas(), criar_especialista_visitantes()],
        tools=[regulamento_tool],
    )
