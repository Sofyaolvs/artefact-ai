"""Interface de linha de comando do agente.

    emporio                      # nova conversa
    emporio --session abc123     # retoma (ou cria) a conversa abc123
    emporio --list               # lista as conversas salvas
"""

import argparse
import sys
from typing import Callable

from google.genai import errors
from rich.console import Console

from emporio_agent import config
from emporio_agent.agent import Agent
from emporio_agent.db import build_database
from emporio_agent.llm import ConfigError, GeminiClient, LLMClient
from emporio_agent.memory import ConversationStore, new_session_id
from emporio_agent.tools import ToolBox

EXIT_COMMANDS = {"/sair", "/exit", "sair", "exit"}
GREETING = "Oi! Aqui é o Lásol, assistente virtual da Empório da Música. Como posso te ajudar?"
API_ERROR_MESSAGE = "Não consegui falar com o modelo agora ({detail}). Tente enviar a mensagem de novo em instantes."


def chat(
    agent: Agent,
    store: ConversationStore,
    session_id: str,
    console: Console,
    read: Callable[[str], str] = input,
) -> None:
    """Conversa até o cliente sair. Cada turno concluído é salvo no banco."""
    history = store.load(session_id)
    if history:
        console.print(f"[dim]Retomando a conversa {session_id} ({len(history)} mensagens).[/dim]")
    else:
        console.print(GREETING, markup=False, highlight=False)
    console.print("[dim]Digite /sair para encerrar.[/dim]")

    while True:
        try:
            text = read("\nVocê: ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            break
        if not text:
            continue
        if text.lower() in EXIT_COMMANDS:
            break
        turn_start = len(history)
        try:
            with console.status("digitando..."):
                reply = agent.respond(history, text)
        except errors.APIError as exc:
            del history[turn_start:]  # o turno falhou: não fica pela metade no histórico
            console.print(API_ERROR_MESSAGE.format(detail=f"erro {exc.code}"), markup=False, highlight=False)
            continue
        store.append(session_id, history[turn_start:])
        console.print(f"\nAssistente: {reply}", markup=False, highlight=False)
    console.print(f"[dim]Conversa salva. Para retomar: emporio --session {session_id}[/dim]")


def build_agent(llm: LLMClient | None = None) -> Agent:
    return Agent(llm or GeminiClient(), ToolBox(build_database()))


def main(argv: list[str] | None = None, llm: LLMClient | None = None) -> int:
    parser = argparse.ArgumentParser(prog="emporio", description="Atendimento da Empório da Música no terminal.")
    parser.add_argument("--session", help="id da conversa para retomar (ou criar com esse nome)")
    parser.add_argument("--list", action="store_true", help="lista as conversas salvas e sai")
    parser.add_argument("--db", default=str(config.CONVERSATIONS_DB), help="arquivo SQLite do histórico")
    args = parser.parse_args(argv)

    console = Console()
    store = ConversationStore(args.db)
    try:
        if args.list:
            sessions = store.list_sessions()
            if not sessions:
                console.print("Nenhuma conversa salva ainda.", markup=False)
            for s in sessions:
                console.print(f"{s['session_id']}  {s['atualizada_em']}  {s['mensagens']:>3} msgs  {s['inicio'][:50]}", markup=False, highlight=False)
            return 0
        try:
            agent = build_agent(llm)
        except ConfigError as exc:
            console.print(str(exc), markup=False)
            return 2
        chat(agent, store, args.session or new_session_id(), console)
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
