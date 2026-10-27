"""Caminhos e configurações lidos do ambiente (.env)."""

import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[2]
load_dotenv(RAIZ / ".env")

DADOS_DIR = RAIZ / "dados"
VAR_DIR = Path(os.getenv("AURORA_VAR_DIR") or RAIZ / "var")

# Dados do condomínio (reservas, visitantes, vínculo sessão -> apartamento).
BANCO_PATH = VAR_DIR / "condominio.db"
# Sessões e eventos do ADK (SqliteSessionService).
SESSOES_PATH = VAR_DIR / "sessoes.db"

APP_NAME = "residencial_aurora"

MODELO_PRINCIPAL = os.getenv("AURORA_MODELO_PRINCIPAL") or "gemini-3.8-flash"
MODELO_ESPECIALISTAS = os.getenv("AURORA_MODELO_ESPECIALISTAS") or MODELO_PRINCIPAL

API_HOST = os.getenv("AURORA_HOST") or "0.0.0.0"
API_PORT = int(os.getenv("AURORA_PORT") or "8000")
