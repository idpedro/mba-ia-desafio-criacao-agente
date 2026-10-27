"""Volta reservas e visitantes ao estado dos arquivos de `dados/`.

Uso:
    uv run aurora-restaurar             # só os dados do condomínio
    uv run aurora-restaurar --sessoes   # também apaga as sessões e os eventos

O histórico de códigos de reserva já emitidos é mantido, para que um código
nunca se repita, nem depois de uma restauração.
"""

import argparse

from . import banco, config


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--sessoes",
        action="store_true",
        help="apaga também as sessões e eventos das conversas",
    )
    args = parser.parse_args()

    config.VAR_DIR.mkdir(parents=True, exist_ok=True)
    banco.restaurar()
    print(f"Reservas e visitantes restaurados a partir de {config.DADOS_DIR}.")

    if args.sessoes:
        banco.apagar_vinculos_de_sessao()
        for sufixo in ("", "-wal", "-shm"):
            caminho = config.SESSOES_PATH.with_name(config.SESSOES_PATH.name + sufixo)
            caminho.unlink(missing_ok=True)
        print("Sessões apagadas.")


if __name__ == "__main__":
    main()
