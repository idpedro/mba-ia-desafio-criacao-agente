"""Especialista de regulamento, acionado como AgentTool pelo agente principal.

O índice (títulos) fica só nas instruções deste especialista. Como ele roda
por AgentTool, as chamadas a `ler_capitulo` acontecem numa sessão aninhada
descartável e só a resposta final volta para a sessão do morador (Garantia 4).
"""

from google.adk.agents import LlmAgent

from .. import config, regulamento
from ..tools.regulamento import ler_capitulo
from ._comum import modelo


def criar_especialista_regulamento() -> LlmAgent:
    return LlmAgent(
        name="especialista_regulamento",
        model=modelo(config.MODELO_ESPECIALISTAS),
        description=(
            "Responde dúvidas sobre o regulamento interno do condomínio. "
            "Envie a pergunta do morador em 'request'."
        ),
        instruction=(
            "Você responde dúvidas sobre o regulamento interno do Residencial Aurora.\n"
            "Índice do regulamento:\n"
            + regulamento.indice().replace("{", "{{").replace("}", "}}")
            + """

Como trabalhar:
- Escolha no índice o capítulo que trata do assunto e chame ler_capitulo com o
  número dele. Leia outro capítulo só se o primeiro não responder.
- Responda somente à pergunta, em português, de forma curta, citando o artigo.
- Não cite nem resuma trechos de capítulos que não tratam do assunto perguntado.
- Se o regulamento não tratar do assunto, diga isso.
"""
        ),
        tools=[ler_capitulo],
    )
