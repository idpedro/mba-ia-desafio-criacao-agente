"""Armazenamento dos dados do condomínio em SQLite.

Os arquivos de `dados/` são só o estado inicial: o comando de restauração os
copia para `var/condominio.db`, e é nesse banco que as tools leem e gravam.

Garantia 5 (dois moradores, uma reserva): a exclusividade de área+data não é
uma consulta feita antes de gravar. Ela é o índice único parcial
`ux_reservas_area_data_ativa`, que o SQLite verifica dentro do próprio INSERT.
Se duas aprovações chegam juntas, uma grava e a outra recebe IntegrityError,
que vira a resposta "data indisponível".
"""

import asyncio
import json
import secrets
import sqlite3
import string
from dataclasses import dataclass
from pathlib import Path

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS reservas (
    codigo       TEXT PRIMARY KEY,
    apartamento  TEXT NOT NULL,
    area         TEXT NOT NULL,
    data         TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'ativa' CHECK (status IN ('ativa', 'cancelada')),
    criada_em    TEXT NOT NULL DEFAULT (datetime('now')),
    cancelada_em TEXT
);

-- No máximo uma reserva ATIVA por área e data, garantido no instante da gravação.
CREATE UNIQUE INDEX IF NOT EXISTS ux_reservas_area_data_ativa
    ON reservas (area, data) WHERE status = 'ativa';

-- Todo código já emitido (inclusive de reservas canceladas ou apagadas pela
-- restauração). Nunca é limpo, então um código nunca se repete.
CREATE TABLE IF NOT EXISTS codigos_emitidos (
    codigo TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS visitantes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    apartamento TEXT NOT NULL,
    nome        TEXT NOT NULL,
    data        TEXT NOT NULL,
    criado_em   TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (apartamento, nome, data)
);

-- Vínculo fixo sessão -> apartamento, definido uma única vez na criação.
CREATE TABLE IF NOT EXISTS sessoes (
    session_id  TEXT PRIMARY KEY,
    apartamento TEXT NOT NULL,
    criada_em   TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


@dataclass(frozen=True)
class Area:
    id: str
    nome: str
    taxa: float

    @property
    def gera_cobranca(self) -> bool:
        return self.taxa > 0


class DataIndisponivel(Exception):
    """A área já tem reserva ativa na data."""


def _ler_json(nome: str):
    return json.loads((config.DADOS_DIR / nome).read_text(encoding="utf-8"))


def carregar_apartamentos() -> dict[str, str]:
    return {a["numero"]: a["morador"] for a in _ler_json("apartamentos.json")}


def carregar_areas() -> dict[str, Area]:
    return {
        a["id"]: Area(id=a["id"], nome=a["nome"], taxa=float(a["taxa"]))
        for a in _ler_json("areas.json")
    }


APARTAMENTOS = carregar_apartamentos()
AREAS = carregar_areas()


def _conectar(caminho: Path | None = None) -> sqlite3.Connection:
    caminho = caminho or config.BANCO_PATH
    caminho.parent.mkdir(parents=True, exist_ok=True)
    # isolation_level=None: transações explícitas com BEGIN IMMEDIATE.
    conn = sqlite3.connect(caminho, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.executescript(SCHEMA)
    return conn


def _novo_codigo() -> str:
    alfabeto = string.ascii_uppercase + string.digits
    return "RSV-" + "".join(secrets.choice(alfabeto) for _ in range(6))


# ---------------------------------------------------------------------------
# Operações síncronas (rodam em thread via asyncio.to_thread)
# ---------------------------------------------------------------------------


def _restaurar() -> None:
    reservas = _ler_json("reservas.json")
    visitantes = _ler_json("visitantes.json")
    conn = _conectar()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM reservas")
        conn.execute("DELETE FROM visitantes")
        for r in reservas:
            conn.execute(
                "INSERT INTO reservas (codigo, apartamento, area, data) VALUES (?, ?, ?, ?)",
                (r["codigo"], r["apartamento"], r["area"], r["data"]),
            )
            conn.execute(
                "INSERT OR IGNORE INTO codigos_emitidos (codigo) VALUES (?)",
                (r["codigo"],),
            )
        for v in visitantes:
            conn.execute(
                "INSERT INTO visitantes (apartamento, nome, data) VALUES (?, ?, ?)",
                (v["apartamento"], v["nome"], v["data"]),
            )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def _apagar_vinculos_de_sessao() -> None:
    conn = _conectar()
    try:
        conn.execute("DELETE FROM sessoes")
    finally:
        conn.close()


def _area_livre(area: str, data: str) -> bool:
    conn = _conectar()
    try:
        row = conn.execute(
            "SELECT 1 FROM reservas WHERE area = ? AND data = ? AND status = 'ativa'",
            (area, data),
        ).fetchone()
        return row is None
    finally:
        conn.close()


def _criar_reserva(apartamento: str, area: str, data: str) -> dict:
    conn = _conectar()
    try:
        for _ in range(20):
            codigo = _novo_codigo()
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    "INSERT INTO codigos_emitidos (codigo) VALUES (?)", (codigo,)
                )
            except sqlite3.IntegrityError:
                # Código já emitido alguma vez: sorteia outro.
                conn.execute("ROLLBACK")
                continue
            try:
                conn.execute(
                    "INSERT INTO reservas (codigo, apartamento, area, data) VALUES (?, ?, ?, ?)",
                    (codigo, apartamento, area, data),
                )
            except sqlite3.IntegrityError as exc:
                conn.execute("ROLLBACK")
                # Violação de ux_reservas_area_data_ativa: outra reserva venceu.
                raise DataIndisponivel(str(exc)) from exc
            conn.execute("COMMIT")
            return {"codigo": codigo, "area": area, "data": data}
        raise RuntimeError("Não foi possível gerar um código de reserva único.")
    finally:
        conn.close()


def _reservas_do_apartamento(apartamento: str) -> list[dict]:
    conn = _conectar()
    try:
        rows = conn.execute(
            "SELECT codigo, area, data FROM reservas "
            "WHERE apartamento = ? AND status = 'ativa' ORDER BY data, area",
            (apartamento,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _cancelar_reserva(apartamento: str, codigo: str) -> bool:
    conn = _conectar()
    try:
        # O filtro por apartamento está no próprio UPDATE: não há como
        # cancelar a reserva de outra unidade, mesmo com o código certo.
        cur = conn.execute(
            "UPDATE reservas SET status = 'cancelada', cancelada_em = datetime('now') "
            "WHERE codigo = ? AND apartamento = ? AND status = 'ativa'",
            (codigo, apartamento),
        )
        return cur.rowcount == 1
    finally:
        conn.close()


def _autorizar_visitante(apartamento: str, nome: str, data: str) -> bool:
    """Grava a autorização. Retorna False se ela já existia."""
    conn = _conectar()
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO visitantes (apartamento, nome, data) VALUES (?, ?, ?)",
            (apartamento, nome, data),
        )
        return cur.rowcount == 1
    finally:
        conn.close()


def _visitantes_do_apartamento(apartamento: str) -> list[dict]:
    conn = _conectar()
    try:
        rows = conn.execute(
            "SELECT nome, data FROM visitantes WHERE apartamento = ? ORDER BY data, id",
            (apartamento,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _vincular_sessao(session_id: str, apartamento: str) -> None:
    conn = _conectar()
    try:
        conn.execute(
            "INSERT INTO sessoes (session_id, apartamento) VALUES (?, ?)",
            (session_id, apartamento),
        )
    finally:
        conn.close()


def _apartamento_da_sessao(session_id: str) -> str | None:
    conn = _conectar()
    try:
        row = conn.execute(
            "SELECT apartamento FROM sessoes WHERE session_id = ?", (session_id,)
        ).fetchone()
        return row["apartamento"] if row else None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# API assíncrona usada pelas tools e pela API HTTP
# ---------------------------------------------------------------------------


def inicializar() -> None:
    _conectar().close()


def restaurar() -> None:
    _restaurar()


def apagar_vinculos_de_sessao() -> None:
    _apagar_vinculos_de_sessao()


async def area_livre(area: str, data: str) -> bool:
    return await asyncio.to_thread(_area_livre, area, data)


async def criar_reserva(apartamento: str, area: str, data: str) -> dict:
    return await asyncio.to_thread(_criar_reserva, apartamento, area, data)


async def reservas_do_apartamento(apartamento: str) -> list[dict]:
    return await asyncio.to_thread(_reservas_do_apartamento, apartamento)


async def cancelar_reserva(apartamento: str, codigo: str) -> bool:
    return await asyncio.to_thread(_cancelar_reserva, apartamento, codigo)


async def autorizar_visitante(apartamento: str, nome: str, data: str) -> bool:
    return await asyncio.to_thread(_autorizar_visitante, apartamento, nome, data)


async def visitantes_do_apartamento(apartamento: str) -> list[dict]:
    return await asyncio.to_thread(_visitantes_do_apartamento, apartamento)


async def vincular_sessao(session_id: str, apartamento: str) -> None:
    await asyncio.to_thread(_vincular_sessao, session_id, apartamento)


async def apartamento_da_sessao(session_id: str) -> str | None:
    return await asyncio.to_thread(_apartamento_da_sessao, session_id)
