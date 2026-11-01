"""Caminhos e configuração do projeto."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"

load_dotenv(ROOT_DIR / ".env")

CONVERSATIONS_DB = Path(os.getenv("EMPORIO_DB", ROOT_DIR / "conversas.db"))

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
