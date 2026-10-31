from datetime import datetime
from zoneinfo import ZoneInfo

from emporio_agent.store import STORE, store_info, store_status


def at(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm)  # sem fuso: lido como horário de Campo Grande


def test_aberta_em_dia_util():
    s = store_status(at(2026, 10, 28, 10, 30))  # quarta-feira
    assert s["aberta_agora"] is True
    assert s["horario_de_hoje"] == "09:00 às 18:00"
    assert s["fecha_as"] == "18:00"
    assert "proxima_abertura" not in s


def test_fechada_antes_de_abrir_diz_que_abre_hoje():
    s = store_status(at(2026, 10, 28, 8, 59))
    assert s["aberta_agora"] is False
    assert s["proxima_abertura"] == "hoje, 28/10, às 09:00"


def test_horario_de_fechamento_ja_esta_fechada():
    assert store_status(at(2026, 10, 28, 18, 0))["aberta_agora"] is False
    assert store_status(at(2026, 10, 28, 17, 59))["aberta_agora"] is True


def test_depois_do_expediente_abre_amanha():
    s = store_status(at(2026, 10, 28, 19, 0))
    assert s["proxima_abertura"] == "amanhã, 29/10, às 09:00"


def test_sabado_fecha_ao_meio_dia():
    assert store_status(at(2026, 10, 31, 12, 59))["aberta_agora"] is True  # sábado
    s = store_status(at(2026, 10, 31, 13, 0))
    assert s["aberta_agora"] is False
    assert s["proxima_abertura"] == "terça-feira, 03/11, às 09:00"  # 02/11 é Finados


def test_domingo_fechado_abre_na_segunda():
    s = store_status(at(2026, 10, 25, 11, 0))
    assert s["aberta_agora"] is False
    assert s["horario_de_hoje"] == "fechada"
    assert s["proxima_abertura"] == "amanhã, 26/10, às 09:00"


def test_feriado_nacional_fecha_mesmo_em_dia_util():
    s = store_status(at(2026, 9, 7, 10, 0))  # segunda-feira, Independência
    assert s["aberta_agora"] is False
    assert s["feriado_hoje"] == "Independência do Brasil"
    assert s["proxima_abertura"] == "amanhã, 08/09, às 09:00"


def test_feriado_pula_para_o_proximo_dia_util():
    s = store_status(at(2026, 10, 31, 14, 0))  # sábado; 02/11 (segunda) é Finados
    assert s["proxima_abertura"] == "terça-feira, 03/11, às 09:00"


def test_aniversario_de_campo_grande_e_feriado_local():
    s = store_status(at(2026, 8, 26, 10, 0))  # quarta-feira
    assert s["aberta_agora"] is False and s["feriado_hoje"] == "Aniversário de Campo Grande"


def test_converte_outro_fuso_para_campo_grande():
    utc = datetime(2026, 10, 28, 13, 30, tzinfo=ZoneInfo("UTC"))  # 09:30 em Campo Grande (UTC-4)
    s = store_status(utc)
    assert s["aberta_agora"] is True and "09:30" in s["agora"]


def test_dados_da_loja():
    info = store_info(at(2026, 10, 28, 10, 0))
    assert info["endereco"] == "Rua 14 de Maio, 3200 — Centro, Campo Grande - MS, CEP 79202-333"
    assert info["telefone"] == "(67) 3341-4444"
    assert info["whatsapp"] == "(67) 3321-4500"
    assert info["situacao_atual"]["aberta_agora"] is True
    assert STORE["horario_de_funcionamento"]["sábado"] == "09:00 às 13:00"
