import base64

import pytest
from google.genai import types

from emporio_agent.llm import ConfigError, GeminiClient, parse_response, to_gemini_contents


def test_converte_historico_para_formato_do_gemini():
    signature = base64.b64encode(b"sig").decode()
    contents = to_gemini_contents(
        [
            {"role": "user", "text": "preço do GD20?"},
            {"role": "assistant", "text": "", "tool_calls": [{"name": "detalhes_produto", "args": {"produto": "GD20"}, "signature": signature}]},
            {"role": "tool", "name": "detalhes_produto", "result": {"preco": "R$ 2.199,00"}},
            {"role": "assistant", "text": "Custa R$ 2.199,00."},
        ]
    )
    assert [c.role for c in contents] == ["user", "model", "user", "model"]
    call = contents[1].parts[0]
    assert call.function_call.name == "detalhes_produto" and call.thought_signature == b"sig"
    assert contents[2].parts[0].function_response.response == {"result": {"preco": "R$ 2.199,00"}}
    assert contents[3].parts[0].text == "Custa R$ 2.199,00."


def test_respostas_de_tools_seguidas_viram_um_unico_turno():
    contents = to_gemini_contents(
        [
            {"role": "user", "text": "oi"},
            {"role": "assistant", "text": "", "tool_calls": [{"name": "a", "args": {}}, {"name": "b", "args": {}}]},
            {"role": "tool", "name": "a", "result": {}},
            {"role": "tool", "name": "b", "result": {}},
        ]
    )
    assert [c.role for c in contents] == ["user", "model", "user"]
    assert [p.function_response.name for p in contents[2].parts] == ["a", "b"]


def test_papel_desconhecido_e_erro():
    with pytest.raises(ValueError):
        to_gemini_contents([{"role": "system", "text": "x"}])


def make_response(*parts):
    return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role="model", parts=list(parts)))])


def test_parse_de_texto_ignora_raciocinio():
    r = parse_response(make_response(types.Part(text="pensando...", thought=True), types.Part(text="Olá!")))
    assert r.text == "Olá!" and r.tool_calls == []


def test_parse_de_chamada_de_funcao_guarda_a_assinatura():
    part = types.Part(function_call=types.FunctionCall(name="buscar_produtos", args={"categoria": "violão"}), thought_signature=b"abc")
    r = parse_response(make_response(part))
    assert r.tool_calls[0].name == "buscar_produtos"
    assert r.tool_calls[0].args == {"categoria": "violão"}
    assert base64.b64decode(r.tool_calls[0].signature) == b"abc"


def test_parse_de_resposta_bloqueada_ou_vazia():
    assert parse_response(types.GenerateContentResponse(candidates=[])).text == ""
    assert parse_response(types.GenerateContentResponse(candidates=[types.Candidate()])).tool_calls == []


def test_sem_chave_da_erro_claro(monkeypatch):
    monkeypatch.setattr("emporio_agent.config.GEMINI_API_KEY", "")
    with pytest.raises(ConfigError, match="GEMINI_API_KEY"):
        GeminiClient()
