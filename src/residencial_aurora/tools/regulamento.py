"""Tool do especialista de regulamento (Garantia 4: um capítulo por vez)."""

from .. import regulamento


def ler_capitulo(numero: int) -> dict:
    """Lê um único capítulo do regulamento interno.

    Args:
        numero: número do capítulo, conforme o índice.

    Returns:
        O título e o texto do capítulo pedido.
    """
    cap = regulamento.capitulo(int(numero))
    if cap is None:
        return {"status": "erro", "mensagem": "Capítulo inexistente."}
    return {"capitulo": cap.numero, "titulo": cap.titulo, "texto": cap.texto}
