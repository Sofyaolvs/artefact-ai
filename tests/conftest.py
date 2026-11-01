"""Utilidades compartilhadas pelos testes."""

from datetime import datetime

import pytest

from emporio_agent.db import build_database
from emporio_agent.llm import LLMResponse, ToolCall
from emporio_agent.tools import ToolBox

NOW = datetime(2026, 3, 20, 10, 30)  # sexta-feira, loja aberta


class ScriptedLLM:
    """Modelo falso: devolve respostas prontas, na ordem, e guarda o que recebeu."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def generate(self, system, messages, tools):
        self.calls.append({"system": system, "messages": [dict(m) for m in messages], "tools": tools})
        return self.responses.pop(0)


def says(text):
    return LLMResponse(text=text)


def calls(*tool_calls):
    return LLMResponse(tool_calls=[ToolCall(name, args) for name, args in tool_calls])


@pytest.fixture
def toolbox():
    return ToolBox(build_database(), now=lambda: NOW)
