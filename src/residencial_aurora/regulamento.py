"""Leitura do regulamento interno, dividido em capítulos.

Garantia 4: o texto nunca é carregado inteiro. O especialista de regulamento
recebe só o índice (números e títulos) e lê um capítulo por vez pela tool
`ler_capitulo`.
"""

import re
from dataclasses import dataclass
from functools import cache

from . import config


@dataclass(frozen=True)
class Capitulo:
    numero: int
    titulo: str
    texto: str


@cache
def capitulos() -> tuple[Capitulo, ...]:
    texto = (config.DADOS_DIR / "regulamento.md").read_text(encoding="utf-8")
    partes = re.split(r"^## ", texto, flags=re.MULTILINE)[1:]
    resultado = []
    for numero, parte in enumerate(partes, start=1):
        titulo, _, corpo = parte.partition("\n")
        resultado.append(
            Capitulo(numero=numero, titulo=titulo.strip(), texto=corpo.strip())
        )
    return tuple(resultado)


def indice() -> str:
    return "\n".join(f"{c.numero}. {c.titulo}" for c in capitulos())


def capitulo(numero: int) -> Capitulo | None:
    for c in capitulos():
        if c.numero == numero:
            return c
    return None
