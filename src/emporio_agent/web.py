"""Interface web do agente: uma página de chat servida por FastAPI.

    emporio-web                  # http://127.0.0.1:8000
    emporio-web --port 8080

Cada conversa (identificada por um `session_id` guardado no navegador) mantém o
próprio agente na memória e é salva no mesmo banco de histórico do terminal.
"""

import argparse
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from google.genai import errors
from pydantic import BaseModel, Field

from emporio_agent import config
from emporio_agent.agent import Agent
from emporio_agent.db import build_database
from emporio_agent.llm import ConfigError, GeminiClient, LLMClient
from emporio_agent.memory import ConversationStore
from emporio_agent.store import STORE, TIMEZONE, store_info, store_status
from emporio_agent.tools import ToolBox

STATIC_DIR = Path(__file__).parent / "static"
SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MAX_MESSAGE_CHARS = 2000

# Nome amigável do que o agente consultou, mostrado sob a resposta.
TOOL_LABELS = {
    "buscar_produtos": "catálogo",
    "detalhes_produto": "catálogo",
    "consultar_status_pedido": "pedidos",
    "listar_meus_pedidos": "pedidos",
    "consultar_politicas": "políticas da loja",
    "informacoes_da_loja": "dados da loja",
    "simular_pagamento": "pagamento",
    "calcular_frete": "frete",
}


class ChatRequest(BaseModel):
    session_id: str
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


@dataclass
class ChatSession:
    agent: Agent
    history: list[dict[str, Any]]
    lock: threading.Lock = field(default_factory=threading.Lock)


def consulted(messages: list[dict[str, Any]]) -> list[str]:
    """Fontes consultadas em um turno, sem repetição e na ordem em que apareceram."""
    labels = [TOOL_LABELS.get(c["name"], c["name"]) for m in messages for c in m.get("tool_calls", [])]
    return list(dict.fromkeys(labels))


def visible_history(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Só o que o cliente vê: as falas dele e as respostas do assistente."""
    return [
        {"role": "user" if m["role"] == "user" else "assistant", "text": m["text"]}
        for m in messages
        if m["role"] in ("user", "assistant") and m.get("text")
    ]


def status_summary(info: dict[str, Any]) -> dict[str, Any]:
    label = f"Aberta até {info['fecha_as']}" if info["aberta_agora"] else f"Fechada · abre {info['proxima_abertura']}"
    return {"open": info["aberta_agora"], "label": label}


def store_card_data() -> dict[str, Any]:
    """Dados da loja para o painel lateral: contato, horários e qual faixa vale hoje."""
    status = store_info()["situacao_atual"]
    hours = [{"days": days, "hours": value} for days, value in STORE["horario_de_funcionamento"].items()]
    weekday = datetime.now(TIMEZONE).weekday()
    today = 2 if "feriado_hoje" in status else (0 if weekday < 5 else weekday - 4)  # seg-sex, sáb, dom/feriado
    whatsapp_digits = re.sub(r"\D", "", STORE["whatsapp"])
    phone_digits = re.sub(r"\D", "", STORE["telefone"])
    return {
        **status_summary(status),
        "name": STORE["nome"],
        "slogan": STORE["slogan"],
        "address": STORE["endereco"],
        "phone": STORE["telefone"],
        "phone_url": f"tel:+55{phone_digits}",
        "whatsapp": STORE["whatsapp"],
        "whatsapp_url": f"https://wa.me/55{whatsapp_digits}",
        "map_url": f"https://www.google.com/maps/search/?api=1&query={quote(STORE['endereco'])}",
        "hours": hours,
        "today": today,
        "holiday": status.get("feriado_hoje"),
        "not_sold": "cordas, palhetas, cabos, cases, pedais e amplificadores",
    }


def create_app(llm: LLMClient | None = None, store: ConversationStore | None = None) -> FastAPI:
    app = FastAPI(title="Empório da Música — atendimento", docs_url=None, redoc_url=None)
    state: dict[str, Any] = {"llm": llm, "store": store, "conn": None}
    sessions: dict[str, ChatSession] = {}
    sessions_lock = threading.Lock()

    def get_llm() -> LLMClient:
        if state["llm"] is None:
            state["llm"] = GeminiClient()
        return state["llm"]

    def get_store() -> ConversationStore:
        if state["store"] is None:
            state["store"] = ConversationStore(config.CONVERSATIONS_DB, shared=True)
        return state["store"]

    def get_session(session_id: str) -> ChatSession:
        if not SESSION_ID.match(session_id):
            raise HTTPException(422, "session_id inválido")
        with sessions_lock:
            if session_id not in sessions:
                if state["conn"] is None:
                    state["conn"] = build_database(check_same_thread=False)
                agent = Agent(get_llm(), ToolBox(state["conn"]))
                sessions[session_id] = ChatSession(agent, get_store().load(session_id))
            return sessions[session_id]

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        return status_summary(store_status())

    @app.get("/api/store")
    def store_card() -> dict[str, Any]:
        return store_card_data()

    @app.get("/api/history/{session_id}")
    def history(session_id: str) -> dict[str, Any]:
        if not SESSION_ID.match(session_id):
            raise HTTPException(422, "session_id inválido")
        return {"messages": visible_history(get_store().load(session_id))}

    @app.post("/api/chat")
    def chat(request: ChatRequest) -> dict[str, Any]:
        try:
            session = get_session(request.session_id)
        except ConfigError as exc:
            raise HTTPException(503, str(exc)) from exc
        with session.lock:  # uma mensagem por vez em cada conversa
            turn_start = len(session.history)
            try:
                reply = session.agent.respond(session.history, request.message.strip())
            except errors.APIError as exc:
                del session.history[turn_start:]
                status = 429 if exc.code == 429 else 502
                raise HTTPException(status, f"O modelo não respondeu (erro {exc.code}). Tente de novo em instantes.") from exc
            new_messages = session.history[turn_start:]
            get_store().append(request.session_id, new_messages)
        return {"reply": reply, "consulted": consulted(new_messages)}

    return app


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="emporio-web", description="Interface web do atendimento da Empório da Música.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    uvicorn.run(create_app(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
