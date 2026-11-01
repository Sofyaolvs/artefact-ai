import io

import pytest
from google.genai import errors
from rich.console import Console

from conftest import ScriptedLLM, calls, says
from emporio_agent.agent import Agent
from emporio_agent.cli import chat, main
from emporio_agent.memory import ConversationStore, new_session_id


def inputs(*lines):
    it = iter(lines)

    def read(_prompt):
        try:
            return next(it)
        except StopIteration:
            raise EOFError

    return read


def make_console():
    return Console(file=io.StringIO(), force_terminal=False, width=100)


def output(console):
    return console.file.getvalue()


class FailingLLM:
    def generate(self, system, messages, tools):
        raise errors.APIError(503, {"error": {"message": "indisponível"}})


# --- memory ---------------------------------------------------------------


def test_salva_e_recarrega_mensagens_na_ordem():
    store = ConversationStore()
    msgs = [
        {"role": "user", "text": "olá"},
        {"role": "assistant", "text": "", "tool_calls": [{"name": "informacoes_da_loja", "args": {}, "signature": None}]},
        {"role": "tool", "name": "informacoes_da_loja", "result": {"endereço": "Rua 14 de Maio"}},
        {"role": "assistant", "text": "Oi!"},
    ]
    store.append("abc", msgs[:2])
    store.append("abc", msgs[2:])
    assert store.load("abc") == msgs


def test_conversas_sao_independentes():
    store = ConversationStore()
    store.append("a", [{"role": "user", "text": "um"}])
    store.append("b", [{"role": "user", "text": "dois"}])
    assert store.load("a") == [{"role": "user", "text": "um"}]
    assert store.load("nao-existe") == []
    assert store.exists("a") and not store.exists("nao-existe")


def test_lista_conversas_da_mais_recente_para_a_mais_antiga():
    store = ConversationStore()
    store.append("velha", [{"role": "user", "text": "primeira conversa"}])
    store.append("nova", [{"role": "user", "text": "segunda conversa"}, {"role": "assistant", "text": "oi"}])
    sessions = store.list_sessions()
    assert [s["session_id"] for s in sessions] == ["nova", "velha"]
    assert sessions[0]["mensagens"] == 2 and sessions[0]["inicio"] == "segunda conversa"


def test_arquivo_persiste_entre_aberturas(tmp_path):
    path = tmp_path / "conversas.db"
    first = ConversationStore(path)
    first.append("s1", [{"role": "user", "text": "ficou salvo"}])
    first.close()
    assert ConversationStore(path).load("s1") == [{"role": "user", "text": "ficou salvo"}]


def test_ids_de_sessao_sao_unicos():
    assert len({new_session_id() for _ in range(50)}) == 50


# --- cli ------------------------------------------------------------------


def test_chat_responde_salva_e_encerra(toolbox):
    store, console = ConversationStore(), make_console()
    agent = Agent(ScriptedLLM(says("Estamos abertos até as 18h!")), toolbox)
    chat(agent, store, "s1", console, read=inputs("até que horas abre?", "/sair"))
    assert "Estamos abertos até as 18h!" in output(console)
    assert "emporio --session s1" in output(console)
    assert [m["role"] for m in store.load("s1")] == ["user", "assistant"]


def test_chat_ignora_linha_vazia_e_encerra_no_ctrl_d(toolbox):
    store, console = ConversationStore(), make_console()
    llm = ScriptedLLM(says("oi"))
    chat(Agent(llm, toolbox), store, "s1", console, read=inputs("", "   ", "oi"))  # acaba em EOF
    assert len(llm.calls) == 1


def test_chat_salva_tambem_as_chamadas_de_tool(toolbox):
    store = ConversationStore()
    llm = ScriptedLLM(calls(("detalhes_produto", {"produto": "GD20"})), says("R$ 2.199,00"))
    chat(Agent(llm, toolbox), store, "s1", make_console(), read=inputs("preço do GD20?", "/sair"))
    assert [m["role"] for m in store.load("s1")] == ["user", "assistant", "tool", "assistant"]


def test_retoma_a_conversa_com_o_historico(toolbox):
    store = ConversationStore()
    chat(Agent(ScriptedLLM(says("primeira")), toolbox), store, "s1", make_console(), read=inputs("um", "/sair"))
    llm = ScriptedLLM(says("segunda"))
    console = make_console()
    chat(Agent(llm, toolbox), store, "s1", console, read=inputs("dois", "/sair"))
    assert [m["text"] for m in llm.calls[0]["messages"]] == ["um", "primeira", "dois"]
    assert "Retomando a conversa s1" in output(console)
    assert len(store.load("s1")) == 4


def test_erro_da_api_nao_deixa_turno_pela_metade(toolbox):
    store, console = ConversationStore(), make_console()
    chat(Agent(FailingLLM(), toolbox), store, "s1", console, read=inputs("oi", "/sair"))
    assert "Não consegui falar com o modelo" in output(console)
    assert store.load("s1") == []  # nada salvo


def test_depois_do_erro_a_conversa_continua(toolbox):
    store, console = ConversationStore(), make_console()

    class FlakyLLM:
        def __init__(self):
            self.n = 0

        def generate(self, system, messages, tools):
            self.n += 1
            if self.n == 1:
                raise errors.APIError(429, {"error": {"message": "cota"}})
            assert [m["text"] for m in messages] == ["oi"]  # a tentativa que falhou não ficou no histórico
            return says("Olá!")

    chat(Agent(FlakyLLM(), toolbox), store, "s1", console, read=inputs("oi", "oi", "/sair"))
    assert [m["role"] for m in store.load("s1")] == ["user", "assistant"]


def test_validacao_do_cliente_nao_sobrevive_a_retomada(toolbox):
    """Ao retomar uma conversa, quem quer ver um pedido precisa se identificar de novo."""
    from emporio_agent.tools import ToolBox

    email = toolbox.conn.execute("SELECT email FROM customers WHERE customer_id = 3").fetchone()[0]
    store = ConversationStore()
    llm = ScriptedLLM(calls(("consultar_status_pedido", {"numero_pedido": 1, "email": email})), says("ok"))
    chat(Agent(llm, toolbox), store, "s1", make_console(), read=inputs("pedido 1", "/sair"))
    assert [m for m in store.load("s1") if m["role"] == "tool"][0]["result"]["verificado"] is True

    new_box = ToolBox(toolbox.conn)  # novo processo: estado de validação zerado
    llm2 = ScriptedLLM(calls(("consultar_status_pedido", {"numero_pedido": 1})), says("preciso confirmar seu e-mail"))
    chat(Agent(llm2, new_box), store, "s1", make_console(), read=inputs("e o pedido 1?", "/sair"))
    assert [m for m in store.load("s1") if m["role"] == "tool"][-1]["result"]["verificado"] is False


def test_main_lista_conversas(tmp_path, capsys):
    db = tmp_path / "c.db"
    store = ConversationStore(db)
    store.append("abc123", [{"role": "user", "text": "quero um violão"}])
    store.close()
    assert main(["--list", "--db", str(db)]) == 0


def test_main_sem_chave_explica_o_que_fazer(tmp_path, monkeypatch):
    monkeypatch.setattr("emporio_agent.config.GEMINI_API_KEY", "")
    assert main(["--db", str(tmp_path / "c.db")]) == 2
