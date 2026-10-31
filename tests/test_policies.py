import pytest

from emporio_agent.policies import MANUAL, consult_policies, load_policy_search, parse_manual


def top_sections(question, k=3):
    return [t["secao"] for t in consult_policies(question, k)["trechos"]]


def test_divide_o_manual_em_todas_as_secoes():
    numbers = [s.number for s in parse_manual(MANUAL.read_text(encoding="utf-8"))]
    for expected in ["1.2", "2", "3", "3.1", "4.1", "4.2", "4.3", "4.4", "5.1", "5.2", "5.3", "6.2", "7.1", "7.3", "8.1", "9", "10"]:
        assert expected in numbers
    assert len(numbers) == len(set(numbers))


def test_lista_numerada_do_fluxo_de_atendimento_nao_vira_secao():
    sections = {s.number: s for s in parse_manual(MANUAL.read_text(encoding="utf-8"))}
    assert "Saudação" in sections["7.2"].text and "Fechamento" in sections["7.2"].text


def test_horario_de_funcionamento_esta_correto():
    texto = load_policy_search().search("que horas a loja abre?")[0]["texto"]
    assert "Segunda a Sexta-feira 09:00 às 18:00" in texto
    assert "Sábado 09:00 às 13:00" in texto
    assert "Domingo e Feriados Fechado" in texto


@pytest.mark.parametrize(
    "pergunta, esperada",
    [
        ("Me arrependi da minha compra, posso devolver?", "4.1"),
        ("o produto veio com defeito, posso trocar?", "4.2"),
        ("quero trocar a cor do violão", "4.3"),
        ("quanto é o frete para Dourados?", "5.2"),
        ("frete grátis em Campo Grande", "5.1"),
        ("em quantas vezes posso parcelar?", "3.1"),
        ("qual o horário de funcionamento aos sábados?", "2"),
        ("quanto tempo dura a garantia?", "8.1"),
        ("o desconto do pix vale em produto em promoção?", "6.2"),
        ("vocês vendem corda de violão?", "7.1"),
        ("como funciona o código de rastreio?", "5.3"),
        ("vocês compartilham meus dados com terceiros?", "9"),
    ],
)
def test_trecho_certo_entre_os_tres_primeiros(pergunta, esperada):
    assert esperada in top_sections(pergunta)


def test_trecho_vem_com_numero_da_secao_e_titulo():
    trecho = consult_policies("posso devolver?")["trechos"][0]
    assert set(trecho) == {"secao", "titulo", "texto"}


def test_pergunta_sem_palavras_uteis_devolve_nao_encontrado():
    r = consult_policies("qual a capital da França?")
    assert r["encontrado"] is False
    assert "gerência" in r["mensagem"]
    assert consult_policies("   ")["encontrado"] is False
