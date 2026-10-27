"""Agentes do assistente: um principal e três especialistas.

- principal.py: assistente_aurora, conversa com o morador e distribui o trabalho.
- reservas.py: especialista_reservas (sub-agente, por transferência).
- visitantes.py: especialista_visitantes (sub-agente, por transferência).
- regulamento.py: especialista_regulamento (AgentTool).
"""

from .principal import criar_agente_principal

__all__ = ["criar_agente_principal"]
