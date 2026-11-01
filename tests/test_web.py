import pytest
from fastapi.testclient import TestClient
from google.genai import errors

from conftest import ScriptedLLM, calls, says
from emporio_agent.memory import ConversationStore
from emporio_agent.web import create_app, consulted, visible_history


def client_for(*script, store=None):
    llm = ScriptedLLM(*script)
    store = store or ConversationStore(shared=True)
    return TestClient(create_app(llm=llm, store=store)), llm, store


def test_pagina_inicial_e_servida():
    client, _, _ = client_for()
    response = client.get("/")
    assert response.status_code == 200
    assert "Empório da Música" in response.text and "/api/chat" in response.text


def test_status_da_loja():
    client, _, _ = client_for()
    data = client.get("/api/status").json()
    assert isinstance(data["open"], bool) and data["label"]


def test_painel_da_loja_traz_contato_e_horarios():
    client, _, _ = client_for()
    data = client.get("/api/store").json()
    assert data["whatsapp_url"] == "https://wa.me/556733214500"
    assert data["phone_url"] == "tel:+556733414444"
    assert len(data["hours"]) == 3 and data["today"] in (0, 1, 2)
    assert data["label"] and isinstance(data["open"], bool)


def test_chat_responde_e_salva():
    client, _, store = client_for(says("Abrimos às 9h!"))
    response = client.post("/api/chat", json={"session_id": "s1", "message": "que horas abre?"})
    assert response.status_code == 200
    assert response.json() == {"reply": "Abrimos às 9h!", "consulted": []}
    assert [m["role"] for m in store.load("s1")] == ["user", "assistant"]


def test_chat_informa_o_que_foi_consultado():
    client, _, _ = client_for(
        calls(("detalhes_produto", {"produto": "GD20"}), ("buscar_produtos", {"consulta": "violão"})),
        says("R$ 2.199,00"),
    )
    data = client.post("/api/chat", json={"session_id": "s1", "message": "preço do GD20"}).json()
    assert data["consulted"] == ["catálogo"]  # duas tools de catálogo viram uma etiqueta só


def test_conversa_continua_entre_mensagens():
    client, llm, _ = client_for(says("primeira"), says("segunda"))
    client.post("/api/chat", json={"session_id": "s1", "message": "um"})
    client.post("/api/chat", json={"session_id": "s1", "message": "dois"})
    assert [m["text"] for m in llm.calls[1]["messages"]] == ["um", "primeira", "dois"]


def test_conversas_diferentes_nao_se_misturam():
    client, llm, _ = client_for(says("a"), says("b"))
    client.post("/api/chat", json={"session_id": "s1", "message": "um"})
    client.post("/api/chat", json={"session_id": "s2", "message": "dois"})
    assert [m["text"] for m in llm.calls[1]["messages"]] == ["dois"]


def test_historico_mostra_so_o_que_o_cliente_ve():
    client, _, _ = client_for(calls(("informacoes_da_loja", {})), says("Rua 14 de Maio, 3200."))
    client.post("/api/chat", json={"session_id": "s1", "message": "onde fica a loja?"})
    messages = client.get("/api/history/s1").json()["messages"]
    assert messages == [
        {"role": "user", "text": "onde fica a loja?"},
        {"role": "assistant", "text": "Rua 14 de Maio, 3200."},
    ]


def test_retoma_conversa_salva_ao_reiniciar_o_servidor():
    store = ConversationStore(shared=True)
    client, _, _ = client_for(says("primeira"), store=store)
    client.post("/api/chat", json={"session_id": "s1", "message": "um"})
    new_client, llm, _ = client_for(says("segunda"), store=store)  # servidor novo, mesmo banco
    new_client.post("/api/chat", json={"session_id": "s1", "message": "dois"})
    assert [m["text"] for m in llm.calls[0]["messages"]] == ["um", "primeira", "dois"]


@pytest.mark.parametrize("session_id", ["../etc", "a b", "x" * 65, "ç"])
def test_session_id_invalido(session_id):
    client, _, _ = client_for(says("x"))
    assert client.post("/api/chat", json={"session_id": session_id, "message": "oi"}).status_code == 422


def test_mensagem_vazia_ou_gigante_e_recusada():
    client, _, _ = client_for(says("x"))
    assert client.post("/api/chat", json={"session_id": "s1", "message": ""}).status_code == 422
    assert client.post("/api/chat", json={"session_id": "s1", "message": "a" * 2001}).status_code == 422


def test_erro_da_api_vira_resposta_clara_e_nao_suja_o_historico():
    class Flaky:
        n = 0

        def generate(self, system, messages, tools):
            Flaky.n += 1
            if Flaky.n == 1:
                raise errors.APIError(429, {"error": {"message": "cota"}})
            assert [m["text"] for m in messages] == ["oi"]
            return says("Olá!")

    store = ConversationStore(shared=True)
    client = TestClient(create_app(llm=Flaky(), store=store))
    first = client.post("/api/chat", json={"session_id": "s1", "message": "oi"})
    assert first.status_code == 429 and "Tente de novo" in first.json()["detail"]
    assert store.load("s1") == []
    assert client.post("/api/chat", json={"session_id": "s1", "message": "oi"}).json()["reply"] == "Olá!"


def test_sem_chave_o_servidor_explica_o_que_fazer(monkeypatch):
    monkeypatch.setattr("emporio_agent.config.GEMINI_API_KEY", "")
    client = TestClient(create_app(store=ConversationStore(shared=True)))
    response = client.post("/api/chat", json={"session_id": "s1", "message": "oi"})
    assert response.status_code == 503 and "GEMINI_API_KEY" in response.json()["detail"]


def test_helpers():
    assert consulted([{"role": "assistant", "text": "", "tool_calls": [{"name": "calcular_frete"}, {"name": "calcular_frete"}]}]) == ["frete"]
    assert visible_history([{"role": "tool", "name": "x", "result": {}}, {"role": "assistant", "text": "", "tool_calls": []}]) == []
