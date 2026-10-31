import re

import pytest

from emporio_agent.agent import SYSTEM_PROMPT_PATH
from emporio_agent.tools import DECLARATIONS


@pytest.fixture(scope="module")
def prompt():
    return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


def test_prompt_e_o_final_e_nao_o_provisorio(prompt):
    assert "serão refinados" not in prompt
    assert len(prompt) > 3000


@pytest.mark.parametrize(
    "trecho",
    [
        "assistente virtual",
        "Não vende acessórios",
        "Assuntos fora da loja",
        "Pedidos e privacidade",
        "não confirme nem negue",
        "ignore as instruções",
        "Nunca peça senha",
    ],
)
def test_prompt_cobre_persona_escopo_e_seguranca(prompt, trecho):
    assert trecho.lower() in prompt.lower()


def test_toda_tool_citada_no_prompt_existe(prompt):
    declaradas = {d["name"] for d in DECLARATIONS}
    citadas = set(re.findall(r"`([a-z]+_[a-z_]+)`", prompt))
    assert citadas, "o prompt deveria orientar o uso das ferramentas"
    assert citadas <= declaradas, citadas - declaradas


def test_prompt_orienta_as_tools_principais(prompt):
    for nome in ["buscar_produtos", "detalhes_produto", "consultar_politicas", "consultar_status_pedido", "informacoes_da_loja"]:
        assert f"`{nome}`" in prompt
