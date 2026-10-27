"""Especialista de reservas, acionado por transferência (sub-agente).

É sub-agente, e não AgentTool, porque `reservar_area` pede confirmação e o ADK
só retoma a confirmação no agente que a pediu, dentro da sessão do morador.
"""

from google.adk.agents import LlmAgent

from .. import config
from ..tools import reservas
from ._comum import REGRAS_DE_SEGURANCA, modelo


def criar_especialista_reservas() -> LlmAgent:
    return LlmAgent(
        name="especialista_reservas",
        model=modelo(config.MODELO_ESPECIALISTAS),
        description=(
            "Reservas de áreas comuns (salão de festas, churrasqueira, quadra): "
            "reservar, cancelar, consultar disponibilidade e listar as reservas "
            "do apartamento."
        ),
        instruction=(
            "Você é o especialista de reservas de áreas comuns do Residencial Aurora."
            + REGRAS_DE_SEGURANCA
            + """
Como trabalhar:
- Ids das áreas: salao-de-festas, churrasqueira, quadra. Use listar_areas se
  precisar das taxas. Datas sempre no formato AAAA-MM-DD.
- Para reservar, chame reservar_area direto (ela confere a agenda). Se o status
  for "aguardando_confirmacao", diga que a reserva gera cobrança e que ficou
  pendente de aprovação no aplicativo. Se for "indisponivel", diga apenas que a
  data está ocupada e sugira outra data, sem dizer de quem é a reserva.
- Para cancelar, chame cancelar_reserva com o código ou com área e data.
  Cancelamento não precisa de confirmação. Se a reserva não for do apartamento,
  diga só que não há reserva sua com esses dados.
- Para listar, use listar_minhas_reservas.
- Se o pedido também envolver visitantes, transfira para especialista_visitantes.
"""
        ),
        tools=[
            reservas.listar_areas,
            reservas.consultar_disponibilidade,
            reservas.listar_minhas_reservas,
            reservas.reservar_area,
            reservas.cancelar_reserva,
        ],
        # Depois de responder, a próxima mensagem volta ao agente principal.
        disallow_transfer_to_parent=True,
    )
