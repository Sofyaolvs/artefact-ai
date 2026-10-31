"""Consulta ao catálogo de produtos."""

import json
import sqlite3
from typing import Any

from emporio_agent.formatting import format_brl, tokens

# Disponibilidade vem primeiro do status: produto descontinuado ou "em breve"
# não é vendido mesmo que ainda conste estoque no cadastro.
DISPONIVEL = "disponivel"
SEM_ESTOQUE = "sem_estoque"
DESCONTINUADO = "descontinuado"
EM_BREVE = "em_breve"

_ORDENACOES = {
    "preco_asc": lambda p: (p["preco_centavos"], p["nome"]),
    "preco_desc": lambda p: (-p["preco_centavos"], p["nome"]),
    "nome": lambda p: p["nome"],
}

_BASE_QUERY = """
    SELECT p.*, c.name AS category_name
    FROM products p JOIN categories c USING (category_id)
"""


def availability(status: str, stock: int) -> str:
    if status == "discontinued":
        return DESCONTINUADO
    if status == "coming_soon":
        return EM_BREVE
    return DISPONIVEL if stock > 0 else SEM_ESTOQUE


def _to_dict(row: sqlite3.Row) -> dict[str, Any]:
    disponibilidade = availability(row["status"], row["stock_quantity"])
    return {
        "id": row["product_id"],
        "nome": row["name"],
        "categoria": row["category_name"],
        "descricao": row["description"],
        "especificacoes": json.loads(row["specs"]),
        "preco": format_brl(row["price_cents"]),
        "preco_centavos": row["price_cents"],
        "disponibilidade": disponibilidade,
        "estoque": row["stock_quantity"] if disponibilidade == DISPONIVEL else 0,
    }


def _matches_text(row: sqlite3.Row, query: str) -> bool:
    """Todas as palavras da busca precisam aparecer no nome, categoria, descrição ou specs."""
    text = " ".join([row["name"], row["category_name"], row["description"] or "", row["specs"]])
    haystack = " ".join(tokens(text))
    return all(t in haystack for t in tokens(query))


def _matches_category(row: sqlite3.Row, category: str | int) -> bool:
    if str(category).strip().isdigit():
        return row["category_id"] == int(category)
    name = " ".join(tokens(row["category_name"]))
    return all(t in name for t in tokens(category))


def search_products(
    conn: sqlite3.Connection,
    query: str | None = None,
    category: str | int | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    include_unavailable: bool = False,
    order_by: str = "preco_asc",
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Busca produtos por texto, categoria e faixa de preço (em reais).

    Por padrão devolve só o que dá para vender agora (ativo e com estoque).
    """
    found = []
    for row in conn.execute(_BASE_QUERY):
        if query and not _matches_text(row, query):
            continue
        if category is not None and not _matches_category(row, category):
            continue
        if min_price is not None and row["price_cents"] < round(min_price * 100):
            continue
        if max_price is not None and row["price_cents"] > round(max_price * 100):
            continue
        product = _to_dict(row)
        if not include_unavailable and product["disponibilidade"] != DISPONIVEL:
            continue
        found.append(product)
    found.sort(key=_ORDENACOES.get(order_by, _ORDENACOES["preco_asc"]))
    return found[:limit]


def find_product(conn: sqlite3.Connection, product: str | int) -> list[dict[str, Any]]:
    """Localiza produto por id ou nome (ex.: 'Takamine GD20'), inclusive os indisponíveis."""
    if str(product).strip().isdigit():
        row = conn.execute(_BASE_QUERY + " WHERE p.product_id = ?", (int(product),)).fetchone()
        return [_to_dict(row)] if row else []
    return [_to_dict(row) for row in conn.execute(_BASE_QUERY) if _matches_text(row, product)]


def similar_products(conn: sqlite3.Connection, product: dict[str, Any], limit: int = 3) -> list[dict[str, Any]]:
    """Alternativas à venda na mesma categoria, das mais próximas em preço."""
    rows = conn.execute(
        _BASE_QUERY + " WHERE c.name = ? AND p.product_id != ?",
        (product["categoria"], product["id"]),
    )
    candidates = [c for c in map(_to_dict, rows) if c["disponibilidade"] == DISPONIVEL]
    candidates.sort(key=lambda c: abs(c["preco_centavos"] - product["preco_centavos"]))
    return candidates[:limit]


def product_details(conn: sqlite3.Connection, product: str | int) -> dict[str, Any]:
    """Detalhes de um produto; se não estiver à venda, já inclui alternativas."""
    matches = find_product(conn, product)
    if not matches:
        return {"encontrado": False}
    if len(matches) > 1:
        return {
            "encontrado": True,
            "ambiguo": True,
            "opcoes": [{"id": m["id"], "nome": m["nome"], "preco": m["preco"]} for m in matches[:8]],
        }
    result = {"encontrado": True, "ambiguo": False, **matches[0]}
    if result["disponibilidade"] != DISPONIVEL:
        result["alternativas"] = similar_products(conn, result)
    return result
