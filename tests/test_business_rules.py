from datetime import date

import pytest

from emporio_agent.business_rules import (
    apply_discount,
    installment_options,
    payment_options,
    pix_price,
    price_with_promotion,
    return_windows,
    shipping_info,
)
from emporio_agent.db import build_database
from emporio_agent.products import product_details, search_products


@pytest.fixture(scope="module")
def conn():
    return build_database()


def max_parcelas(total_cents):
    options = installment_options(total_cents)
    return options[-1]["parcelas"] if options else 1


def test_desconto_arredonda_em_centavos():
    assert apply_discount(599900, 8) == 551908
    assert apply_discount(54900, 20) == 43920


def test_preco_sem_promocao():
    assert price_with_promotion(219900, None) == {"preco_final_centavos": 219900, "em_promocao": False}


def test_pix_da_5_por_cento_no_preco_de_tabela():
    assert pix_price(219900, on_promotion=False) == 208905


def test_pix_nao_acumula_com_promocao():
    assert pix_price(439200, on_promotion=True) == 439200


def test_parcela_minima_por_faixa():
    assert max_parcelas(429_90) == 5  # 6x = R$ 71,65 < R$ 80 (caso do pedido 16 dos dados)
    assert max_parcelas(599_90) == 6  # 7x = R$ 85,70 < R$ 100
    assert max_parcelas(1200_00) == 12


def test_parcelas_valores_pequenos():
    assert [o["parcelas"] for o in installment_options(120_00)] == [2]  # 3x = R$ 40 < R$ 50
    assert [o["parcelas"] for o in installment_options(40_00)] == []


def test_parcela_arredonda_para_cima():
    assert installment_options(100_00 * 2 + 1)[0]["valor_parcela_centavos"] == 10001


def test_combinar_formas_de_pagamento_so_acima_de_2000():
    assert payment_options(200000, False)["combinar_formas_de_pagamento"] is False
    assert payment_options(200001, False)["combinar_formas_de_pagamento"] is True


def test_frete_local_gratis_a_partir_de_500():
    assert shipping_info(50000, "Campo Grande")["frete"] == "grátis"
    assert shipping_info(49990, "campo grande")["frete"] == "R$ 35,00"
    assert shipping_info(49990, "Campo Grande")["prazo"] == "1 a 3 dias úteis"


def test_frete_outra_cidade_nao_inventa_valor():
    info = shipping_info(300000, "Dourados")
    assert info["frete_centavos"] is None
    assert len(info["modalidades"]) == 3
    assert "cotacao_individual" not in info


def test_frete_de_bateria_exige_cotacao():
    assert shipping_info(1328500, "Corumbá", ["Baterias e Percussão"])["cotacao_individual"] is True


def test_prazos_de_devolucao():
    w = return_windows(date(2026, 1, 5), date(2026, 1, 18), today=date(2026, 1, 25))
    assert w["arrependimento_7_dias"] == {"limite": "2026-01-25", "aberto": True, "dias_restantes": 0}
    w = return_windows(date(2026, 1, 5), date(2026, 1, 18), today=date(2026, 1, 26))
    assert w["arrependimento_7_dias"]["aberto"] is False
    assert w["troca_por_defeito_30_dias"]["aberto"] is True
    assert w["garantia_legal_90_dias"]["aberto"] is True
    w = return_windows(date(2026, 1, 5), date(2026, 1, 18), today=date(2026, 2, 5))
    assert w["troca_por_defeito_30_dias"]["aberto"] is False
    assert w["garantia_legal_90_dias"]["aberto"] is True


def test_produto_em_promocao_mostra_original_percentual_e_final(conn):
    p = product_details(conn, "Taylor 110e")  # promoção ativa de 8%
    assert p["em_promocao"] is True
    assert (p["preco_original"], p["desconto_percent"], p["preco"]) == ("R$ 5.999,00", 8, "R$ 5.519,08")
    assert p["preco_no_pix"] == p["preco"]
    assert "sem desconto extra" in p["formas_de_pagamento"]["pix"]["observacao"]


def test_promocao_inativa_e_ignorada(conn):
    p = product_details(conn, "Martin D-28 Dreadnought")  # só tem promoção inativa
    assert p["em_promocao"] is False
    assert p["preco"] == "R$ 11.499,00"
    assert p["preco_no_pix"] == "R$ 10.924,05"


def test_produto_sem_promocao_tem_pix_com_5_por_cento(conn):
    p = product_details(conn, "Takamine GD20")
    assert p["preco_no_pix"] == "R$ 2.089,05"
    assert p["formas_de_pagamento"]["credito"]["max_parcelas_sem_juros"] == 12


def test_faixa_de_preco_usa_preco_com_promocao(conn):
    # Ohana CK-20: R$ 549 de tabela, 20% de desconto ativo -> R$ 439,20
    nomes = [p["nome"] for p in search_products(conn, category="ukulele", max_price=440)]
    assert "Ohana CK-20 Concert Natural" in nomes
    nomes = [p["nome"] for p in search_products(conn, category="ukulele", min_price=500, max_price=600)]
    assert "Ohana CK-20 Concert Natural" not in nomes
