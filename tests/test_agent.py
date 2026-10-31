from datetime import datetime

import pytest

from emporio_agent.agent import FALLBACK_REPLY, Agent
from emporio_agent.db import build_database
from emporio_agent.llm import LLMResponse, ToolCall
from emporio_agent.tools import DECLARATIONS, ToolBox

NOW = datetime(2026, 10, 28, 10, 30)  # quarta-feira


class ScriptedLLM:
    """LLM falso: devolve respostas prontas e guarda o que recebeu."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def generate(self, system, messages, tools):
        self.calls.append({"system": system, "messages": [dict(m) for m in messages], "tools": tools})
        return self.responses.pop(0)


@pytest.fixture
def toolbox():
    return ToolBox(build_database(), now=lambda: NOW)


def test_resposta_direta_sem_tools(toolbox):
    llm = ScriptedLLM(LLMResponse(text="Oi! Como posso ajudar?"))
    history = []
    assert Agent(llm, toolbox).respond(history, "oi") == "Oi! Como posso ajudar?"
    assert history == [{"role": "user", "text": "oi"}, {"role": "assistant", "text": "Oi! Como posso ajudar?"}]


def test_executa_a_tool_e_devolve_o_resultado_ao_modelo(toolbox):
    llm = ScriptedLLM(
        LLMResponse(tool_calls=[ToolCall("detalhes_produto", {"produto": "Takamine GD20"})]),
        LLMResponse(text="O Takamine GD20 custa R$ 2.199,00."),
    )
    history = []
    reply = Agent(llm, toolbox).respond(history, "quanto custa o Takamine GD20?")
    assert reply == "O Takamine GD20 custa R$ 2.199,00."
    assert [m["role"] for m in history] == ["user", "assistant", "tool", "assistant"]
    assert history[1]["tool_calls"] == [{"name": "detalhes_produto", "args": {"produto": "Takamine GD20"}, "signature": None}]
    assert history[2]["result"]["preco"] == "R$ 2.199,00"
    # na segunda ida ao modelo, o resultado da tool já está no histórico
    assert llm.calls[1]["messages"][-1]["role"] == "tool"


def test_varias_tools_na_mesma_rodada(toolbox):
    llm = ScriptedLLM(
        LLMResponse(tool_calls=[ToolCall("informacoes_da_loja", {}), ToolCall("calcular_frete", {"valor_total": 300, "cidade": "Campo Grande"})]),
        LLMResponse(text="ok"),
    )
    history = []
    Agent(llm, toolbox).respond(history, "endereço e frete de R$ 300?")
    assert [m["role"] for m in history] == ["user", "assistant", "tool", "tool", "assistant"]
    assert history[3]["result"]["frete"] == "R$ 35,00"


def test_prompt_do_sistema_leva_data_e_hora_e_tools(toolbox):
    llm = ScriptedLLM(LLMResponse(text="oi"))
    Agent(llm, toolbox, system_prompt="Você é o assistente.").respond([], "oi")
    call = llm.calls[0]
    assert call["system"].startswith("Você é o assistente.")
    assert "quarta-feira, 28/10/2026 10:30" in call["system"]
    assert call["tools"] is DECLARATIONS


def test_limite_de_passos_evita_loop_infinito(toolbox):
    loop = LLMResponse(tool_calls=[ToolCall("informacoes_da_loja", {})])
    llm = ScriptedLLM(*[loop] * 3)
    history = []
    assert Agent(llm, toolbox, max_steps=3).respond(history, "oi") == FALLBACK_REPLY
    assert history[-1] == {"role": "assistant", "text": FALLBACK_REPLY}
    assert len(llm.calls) == 3


def test_resposta_vazia_do_modelo_vira_mensagem_de_contorno(toolbox):
    assert Agent(ScriptedLLM(LLMResponse(text="")), toolbox).respond([], "oi") == FALLBACK_REPLY


def test_o_historico_continua_entre_turnos(toolbox):
    llm = ScriptedLLM(LLMResponse(text="primeira"), LLMResponse(text="segunda"))
    agent, history = Agent(llm, toolbox), []
    agent.respond(history, "um")
    agent.respond(history, "dois")
    assert [m["text"] for m in llm.calls[1]["messages"]] == ["um", "primeira", "dois"]


def test_cliente_validado_vale_pelo_resto_da_conversa(toolbox):
    email = toolbox.conn.execute("SELECT email FROM customers WHERE customer_id = 3").fetchone()[0]
    llm = ScriptedLLM(
        LLMResponse(tool_calls=[ToolCall("consultar_status_pedido", {"numero_pedido": 1.0, "email": email})]),
        LLMResponse(text="a"),
        LLMResponse(tool_calls=[ToolCall("consultar_status_pedido", {"numero_pedido": 19})]),  # sem e-mail, mesmo cliente
        LLMResponse(text="b"),
    )
    agent, history = Agent(llm, toolbox), []
    agent.respond(history, "pedido 1")
    agent.respond(history, "e o 19?")
    results = [m["result"] for m in history if m["role"] == "tool"]
    assert results[0]["verificado"] is True and results[1]["verificado"] is True
