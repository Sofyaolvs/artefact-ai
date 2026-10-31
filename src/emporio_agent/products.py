"""Consulta ao catálogo de produtos."""

import json
import sqlite3
from typing import Any

from emporio_agent.business_rules import payment_options, pix_price, price_with_promotion
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

# Com mais de uma promoção ativa no mesmo produto vale a de maior desconto.
_BASE_QUERY = """
    SELECT p.*, c.name AS category_name,
           (SELECT MAX(discount_percent) FROM promotions pr
             WHERE pr.product_id = p.product_id AND pr.is_active = 1) AS promo_percent,
           (SELECT description FROM promotions pr
             WHERE pr.product_id = p.product_id AND pr.is_active = 1
             ORDER BY discount_percent DESC LIMIT 1) AS promo_description
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
    price = price_with_promotion(row["price_cents"], row["promo_percent"])
    final = price["preco_final_centavos"]
    product = {
        "id": row["product_id"],
        "nome": row["name"],
        "categoria": row["category_name"],
        "descricao": row["description"],
        "especificacoes": json.loads(row["specs"]),
        "preco": format_brl(final),
        "preco_centavos": final,
        "disponibilidade": disponibilidade,
        "estoque": row["stock_quantity"] if disponibilidade == DISPONIVEL else 0,
    }
    if price["em_promocao"]:
        product.update(
            em_promocao=True,
            preco_original=format_brl(row["price_cents"]),
            desconto_percent=price["desconto_percent"],
            promocao=row["promo_description"],
        )
    else:
        product["em_promocao"] = False
    product["preco_no_pix"] = format_brl(pix_price(final, price["em_promocao"]))
    return product


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

    A faixa de preço considera o preço final, já com a promoção ativa.
    Por padrão devolve só o que dá para vender agora (ativo e com estoque).
    """
    found = []
    for row in conn.execute(_BASE_QUERY):
        if query and not _matches_text(row, query):
            continue
        if category is not None and not _matches_category(row, category):
            continue
        product = _to_dict(row)
        if min_price is not None and product["preco_centavos"] < round(min_price * 100):
            continue
        if max_price is not None and product["preco_centavos"] > round(max_price * 100):
            continue
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
    if result["disponibilidade"] == DISPONIVEL:
        result["formas_de_pagamento"] = payment_options(result["preco_centavos"], result["em_promocao"])
    else:
        result["alternativas"] = similar_products(conn, result)
    return result
