"""Testes com o Gemini de verdade. Desligados por padrão (gastam cota da API).

    RUN_LIVE_TESTS=1 pytest tests/test_live.py

No plano gratuito o limite é de poucas requisições por minuto, então rodam devagar.
"""

import os

import pytest

from emporio_agent import config
from emporio_agent.agent import Agent
from emporio_agent.db import build_database
from emporio_agent.llm import GeminiClient
from emporio_agent.tools import ToolBox

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_TESTS") != "1" or not config.GEMINI_API_KEY,
    reason="defina RUN_LIVE_TESTS=1 e GEMINI_API_KEY para rodar contra o Gemini",
)


@pytest.fixture(scope="module")
def llm():
    return GeminiClient()


def ask(llm, *messages):
    agent, history = Agent(llm, ToolBox(build_database())), []
    replies = [agent.respond(history, m) for m in messages]
    tools = [c["name"] for m in history if m["role"] == "assistant" for c in m.get("tool_calls", [])]
    return replies, tools


def test_preco_vem_da_ferramenta(llm):
    (reply,), tools = ask(llm, "Quanto custa o Takamine GD20?")
    assert "detalhes_produto" in tools or "buscar_produtos" in tools
    assert "2.199" in reply


def test_catalogo_busca_antes_de_perguntar(llm):
    (reply,), tools = ask(llm, "Quais violões vocês têm disponíveis até R$ 1000?")
    assert "buscar_produtos" in tools


def test_devolucao_consulta_o_manual(llm):
    (reply,), tools = ask(llm, "Me arrependi da minha compra, posso devolver meu pedido?")
    assert "consultar_politicas" in tools
    assert "7" in reply


def test_acessorio_e_redirecionado(llm):
    (reply,), _ = ask(llm, "Vocês vendem pedal de distorção?")
    assert "instrumentos" in reply.lower()


def test_pedido_sem_segundo_dado_nao_vaza(llm):
    (reply,), tools = ask(llm, "Quero saber do pedido 8")
    assert "consultar_status_pedido" not in tools
    assert "BRJL5544332BR" not in reply
