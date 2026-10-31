from datetime import date

import pytest

from emporio_agent.db import build_database
from emporio_agent.orders import MAX_FAILED_ATTEMPTS, NOT_VERIFIED, OrderService, payment_label


@pytest.fixture(scope="module")
def conn():
    return build_database()


@pytest.fixture
def service(conn):
    return OrderService(conn, today=date(2026, 3, 20))


def email_of(conn, customer_id):
    return conn.execute("SELECT email FROM customers WHERE customer_id = ?", (customer_id,)).fetchone()[0]


def phone_of(conn, customer_id):
    return conn.execute("SELECT phone FROM customers WHERE customer_id = ?", (customer_id,)).fetchone()[0]


def test_pedido_enviado_com_email_correto(conn, service):
    r = service.order_status(8, email=email_of(conn, 2))  # pedido 8 é da cliente 2
    assert r["verificado"] is True
    assert r["status"] == "Enviado"
    assert r["codigo_de_rastreio"] == "BRJL5544332BR"
    assert r["previsao_de_entrega"] == "2026-02-28"
    assert r["total"] == "R$ 349,90"
    assert r["forma_de_pagamento"] == "cartão de débito"
    assert r["cliente"] == "Ana"
    assert r["itens"] == [{"produto": "Kala KA-C Concert Mogno", "quantidade": 1}]


def test_email_ignora_caixa_e_espacos(conn, service):
    assert service.order_status(8, email=f"  {email_of(conn, 2).upper()} ")["verificado"] is True


def test_telefone_aceita_formatos_diferentes(conn, service):
    # (67) 98432-1098 é o telefone do cliente 3, dono do pedido 1
    assert service.order_status(1, phone="67984321098")["verificado"] is True
    assert OrderService(conn).order_status(1, phone="+55 (67) 98432-1098")["verificado"] is True
    assert OrderService(conn).order_status(1, phone="98432-1098")["verificado"] is True


def test_sem_segundo_fator_nao_revela_nada(service):
    assert service.order_status(8) == NOT_VERIFIED


def test_dado_de_outro_cliente_e_recusado(conn, service):
    assert service.order_status(8, email=email_of(conn, 3)) == NOT_VERIFIED


def test_pedido_inexistente_tem_a_mesma_resposta_de_dado_errado(conn, service):
    assert service.order_status(9999, email=email_of(conn, 2)) == NOT_VERIFIED
    assert service.order_status("abc", email=email_of(conn, 2)) == NOT_VERIFIED


def test_telefone_muito_curto_nao_valida(service):
    assert service.order_status(8, phone="1098") == NOT_VERIFIED


def test_bloqueia_apos_muitas_tentativas_mesmo_com_dado_correto(conn, service):
    for _ in range(MAX_FAILED_ATTEMPTS):
        service.order_status(8, email="errado@jmail.com")
    r = service.order_status(8, email=email_of(conn, 2))
    assert r["verificado"] is False and r["bloqueado"] is True


def test_depois_de_verificado_outros_pedidos_do_mesmo_cliente_liberam(conn, service):
    # a cliente 3 fez os pedidos 1 e 19
    assert service.order_status(1, email=email_of(conn, 3))["verificado"] is True
    assert service.order_status(19)["verificado"] is True
    assert service.order_status(8) == NOT_VERIFIED  # pedido de outro cliente continua protegido


def test_pedido_ainda_sem_rastreio(conn, service):
    r = service.order_status(9, email=email_of(conn, 6))
    assert r["status"] == "Confirmado"
    assert r["codigo_de_rastreio"] == "ainda não disponível"
    assert r["previsao_de_entrega"] == "ainda não definida"


def test_pedido_cancelado_traz_o_motivo(conn, service):
    r = service.order_status(18, email=email_of(conn, 17))
    assert r["status"] == "Cancelado"
    assert r["observacao_do_pedido"] == "Item fora de estoque no momento do pedido"


def test_pedido_entregue_traz_prazos_de_devolucao(conn):
    # pedido 7: entrega prevista em 2026-02-17; em 2026-02-20 o arrependimento ainda cabe
    r = OrderService(conn, today=date(2026, 2, 20)).order_status(7, email=email_of(conn, 14))
    assert r["prazos_de_devolucao"]["arrependimento_7_dias"] == {"limite": "2026-02-24", "aberto": True, "dias_restantes": 4}
    r = OrderService(conn, today=date(2026, 3, 20)).order_status(7, email=email_of(conn, 14))
    assert r["prazos_de_devolucao"]["arrependimento_7_dias"]["aberto"] is False
    assert r["prazos_de_devolucao"]["garantia_legal_90_dias"]["aberto"] is True


def test_pedido_nao_entregue_nao_traz_prazos_de_devolucao(conn, service):
    assert "prazos_de_devolucao" not in service.order_status(8, email=email_of(conn, 2))


def test_meus_pedidos_exige_verificacao(conn, service):
    assert service.my_orders()["verificado"] is False
    service.order_status(1, phone=phone_of(conn, 3))
    pedidos = service.my_orders()["pedidos"]
    assert [p["pedido"] for p in pedidos] == [1, 19]


def test_formas_de_pagamento():
    assert payment_label("credit_12x") == "cartão de crédito em 12x"
    assert payment_label("pix") == "PIX"
    assert payment_label("boleto") == "boleto bancário"
