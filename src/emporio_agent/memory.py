"""Histórico de conversas em SQLite, para retomar um atendimento com `--session`.

Fica em um arquivo separado dos dados da loja. Guarda as mensagens no formato
neutro de `llm.py`, uma linha por mensagem, na ordem em que aconteceram.
A validação do cliente (consulta de pedidos) não é salva de propósito: ao
retomar uma conversa, quem quiser ver dados de pedido precisa se identificar de novo.
"""

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    payload    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_session_id() -> str:
    return uuid.uuid4().hex[:8]


class ConversationStore:
    def __init__(self, path: str | Path = ":memory:", shared: bool = False):
        """`shared=True` permite usar o banco a partir de várias threads (servidor web)."""
        self.conn = sqlite3.connect(str(path), check_same_thread=not shared)
        self._lock = threading.RLock()
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)

    def exists(self, session_id: str) -> bool:
        return self.conn.execute("SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)).fetchone() is not None

    def create(self, session_id: str) -> None:
        now = _now()
        with self._lock:
            self.conn.execute("INSERT OR IGNORE INTO sessions VALUES (?, ?, ?)", (session_id, now, now))
            self.conn.commit()

    def load(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.conn.execute("SELECT payload FROM messages WHERE session_id = ? ORDER BY id", (session_id,)).fetchall()
        return [json.loads(r["payload"]) for r in rows]

    def append(self, session_id: str, messages: list[dict[str, Any]]) -> None:
        """Acrescenta mensagens (e cria a sessão se for a primeira vez)."""
        self.create(session_id)
        with self._lock:
            self.conn.executemany(
                "INSERT INTO messages (session_id, payload) VALUES (?, ?)",
                [(session_id, json.dumps(m, ensure_ascii=False)) for m in messages],
            )
            self.conn.execute("UPDATE sessions SET updated_at = ? WHERE session_id = ?", (_now(), session_id))
            self.conn.commit()

    def list_sessions(self) -> list[dict[str, Any]]:
        """Conversas da mais recente para a mais antiga, com a primeira mensagem do cliente."""
        rows = self.conn.execute(
            """
            SELECT s.session_id, s.updated_at,
                   (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.session_id) AS mensagens,
                   (SELECT payload FROM messages m WHERE m.session_id = s.session_id ORDER BY id LIMIT 1) AS primeira
            FROM sessions s ORDER BY s.updated_at DESC, s.rowid DESC
            """
        )
        result = []
        for r in rows:
            first = json.loads(r["primeira"])["text"] if r["primeira"] else ""
            result.append({"session_id": r["session_id"], "atualizada_em": r["updated_at"], "mensagens": r["mensagens"], "inicio": first})
        return result

    def close(self) -> None:
        self.conn.close()
