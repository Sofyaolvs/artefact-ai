import pytest

from emporio_agent.db import build_database
from emporio_agent.formatting import format_brl
from emporio_agent.products import (
    DESCONTINUADO,
    DISPONIVEL,
    EM_BREVE,
    SEM_ESTOQUE,
    product_details,
    search_products,
)


@pytest.fixture(scope="module")
def conn():
    return build_database()


def test_format_brl():
    assert format_brl(59990) == "R$ 599,90"
    assert format_brl(219900) == "R$ 2.199,00"
    assert format_brl(1149900) == "R$ 11.499,00"


def test_violoes_ate_mil_reais(conn):
    result = search_products(conn, category="violões", max_price=1000)
    assert result
    assert all(p["categoria"] == "Violões" for p in result)
    assert all(p["preco_centavos"] <= 100000 for p in result)
    assert all(p["disponibilidade"] == DISPONIVEL for p in result)


def test_categoria_aceita_singular_e_sem_acento(conn):
    assert search_products(conn, category="violao") == search_products(conn, category="Violões")


def test_categoria_por_id(conn):
    assert {p["categoria"] for p in search_products(conn, category=9)} == {"Ukuleles"}


def test_busca_por_texto_nas_especificacoes(conn):
    result = search_products(conn, query="nylon", category="violao")
    assert result and all("nylon" in str(p["especificacoes"]).lower() for p in result)


def test_busca_exige_todas_as_palavras(conn):
    assert search_products(conn, query="takamine gd20")[0]["nome"].startswith("Takamine GD20")
    assert search_products(conn, query="takamine zzz") == []


def test_ordenacao_por_preco(conn):
    precos = [p["preco_centavos"] for p in search_products(conn, order_by="preco_desc", limit=50)]
    assert precos == sorted(precos, reverse=True)


def test_limite(conn):
    assert len(search_products(conn, limit=3)) == 3


def test_busca_oculta_indisponiveis_por_padrao(conn):
    nomes = {p["nome"] for p in search_products(conn, limit=100)}
    assert "Giannini GF-3D Dreadnought Sunburst" not in nomes  # sem estoque
    assert "Shelby SN-7C 7 Cordas Nylon Natural" not in nomes  # descontinuado
    assert "Ibanez Bass 2X Electric Bass" not in nomes  # descontinuado, mesmo com estoque
    assert "Kala KA-ABP-CTG Barítono Cedar" not in nomes  # em breve, mesmo com estoque


def test_busca_pode_incluir_indisponiveis(conn):
    nomes = {p["nome"] for p in search_products(conn, include_unavailable=True, limit=100)}
    assert "Giannini GF-3D Dreadnought Sunburst" in nomes


def test_detalhes_do_takamine_gd20(conn):
    p = product_details(conn, "Takamine GD20")
    assert p["encontrado"] and not p["ambiguo"]
    assert p["preco"] == "R$ 2.199,00"
    assert p["disponibilidade"] == DISPONIVEL
    assert "alternativas" not in p


def test_detalhes_por_id(conn):
    assert product_details(conn, 95)["nome"].startswith("Takamine GD20")
    assert product_details(conn, "95")["id"] == 95


def test_produto_sem_estoque_traz_alternativas_a_venda(conn):
    p = product_details(conn, "Giannini GF-3D")
    assert p["disponibilidade"] == SEM_ESTOQUE and p["estoque"] == 0
    assert p["alternativas"]
    assert all(a["disponibilidade"] == DISPONIVEL and a["categoria"] == p["categoria"] for a in p["alternativas"])


def test_produto_descontinuado_com_estoque_nao_conta_como_disponivel(conn):
    p = product_details(conn, 136)
    assert p["disponibilidade"] == DESCONTINUADO and p["estoque"] == 0
    assert p["alternativas"]


def test_produto_em_breve(conn):
    assert product_details(conn, 130)["disponibilidade"] == EM_BREVE


def test_busca_ambigua_lista_opcoes(conn):
    r = product_details(conn, "Yamaha")
    assert r["ambiguo"] and len(r["opcoes"]) > 1


def test_produto_inexistente(conn):
    assert product_details(conn, "Saxofone Selmer") == {"encontrado": False}
