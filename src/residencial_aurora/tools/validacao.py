"""Validações compartilhadas pelas tools."""

import re
from datetime import date

ERRO_DATA = {"status": "erro", "mensagem": "Data inválida. Use o formato AAAA-MM-DD."}


def validar_data(data: str) -> str | None:
    """Devolve a data normalizada (AAAA-MM-DD) ou None se for inválida."""
    if not isinstance(data, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", data.strip()):
        return None
    try:
        return date.fromisoformat(data.strip()).isoformat()
    except ValueError:
        return None
