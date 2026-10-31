import pytest

from emporio_agent.db import build_database, to_cents


@pytest.fixture(scope="module")
def conn():
    return build_database()


def count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_to_cents_nao_usa_float():
    assert to_cents("599.9") == 59990
    assert to_cents("11499") == 1149900
    assert to_cents("159.9") == 15990


def test_carrega_todas_as_tabelas(conn):
    assert count(conn, "categories") == 9
    assert count(conn, "customers") == 50
    assert count(conn, "products") == 65
    assert count(conn, "promotions") == 25
    assert count(conn, "orders") == 20
    assert count(conn, "order_items") == 22


def test_precos_em_centavos(conn):
    row = conn.execute("SELECT price_cents FROM products WHERE name LIKE '%Takamine GD20%'").fetchone()
    assert row["price_cents"] == 219900


def test_campos_vazios_viram_null(conn):
    row = conn.execute("SELECT tracking_code, estimated_delivery, notes FROM orders WHERE order_id = 9").fetchone()
    assert tuple(row) == (None, None, None)


def test_status_de_produto_conhecidos(conn):
    status = {r[0] for r in conn.execute("SELECT DISTINCT status FROM products")}
    assert status == {"active", "discontinued", "coming_soon"}
