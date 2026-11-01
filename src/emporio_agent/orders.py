"""Consulta de pedidos com verificação do cliente (LGPD, §9 do manual).

Número de pedido sozinho não basta: é preciso informar também o e-mail ou o
telefone cadastrado. Pedido inexistente e dado errado recebem a mesma resposta,
para não revelar quais pedidos existem, e tentativas erradas são limitadas por
sessão para impedir adivinhação.
"""

import re
import sqlite3
from datetime import date
from typing import Any

from emporio_agent.business_rules import return_windows
from emporio_agent.formatting import format_brl

MAX_FAILED_ATTEMPTS = 5
_MIN_PHONE_DIGITS = 8

STATUS_INFO = {
    "pending": ("Aguardando confirmação do pagamento", "O pedido ainda não foi confirmado; ele só segue para separação depois da confirmação do pagamento."),
    "confirmed": ("Confirmado", "Pagamento confirmado. O pedido está sendo preparado e o código de rastreio é enviado por e-mail e WhatsApp assim que for despachado."),
    "shipped": ("Enviado", "O pedido já foi despachado e pode ser acompanhado pelo código de rastreio."),
    "delivered": ("Entregue", "O pedido consta como entregue."),
    "cancelled": ("Cancelado", "O pedido foi cancelado."),
}

NOT_VERIFIED = {
    "verificado": False,
    "mensagem": (
        "Não foi possível validar esse pedido com os dados informados. "
        "Diga apenas que não conseguiu validar (nunca 'não encontrei o pedido') e peça ao cliente "
        "para conferir o número do pedido e o e-mail ou telefone cadastrado na compra. "
        "Não confirme se o pedido existe nem revele qualquer dado dele."
    ),
}
LOCKED = {
    "verificado": False,
    "bloqueado": True,
    "mensagem": (
        "Muitas tentativas de validação nesta conversa. Encaminhe o cliente para o atendimento humano "
        "pelo WhatsApp (67) 3321-4500 ou pelo telefone (67) 3341-4444."
    ),
}


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text or "")


def _same_email(given: str | None, stored: str | None) -> bool:
    return bool(given and stored) and given.strip().casefold() == stored.strip().casefold()


def _same_phone(given: str | None, stored: str | None) -> bool:
    """Compara só os dígitos, aceitando DDD e +55 presentes ou ausentes."""
    a, b = _digits(given or ""), _digits(stored or "")
    if len(a) < _MIN_PHONE_DIGITS or len(b) < _MIN_PHONE_DIGITS:
        return False
    return a.endswith(b) or b.endswith(a)


def payment_label(method: str | None) -> str | None:
    if not method:
        return None
    if method.startswith("credit_"):
        return f"cartão de crédito em {method.removeprefix('credit_').removesuffix('x')}x"
    return {"pix": "PIX", "debit": "cartão de débito", "boleto": "boleto bancário"}.get(method, method)


class OrderService:
    """Consultas de pedido de uma conversa; guarda quem já foi verificado."""

    def __init__(self, conn: sqlite3.Connection, today: date | None = None):
        self.conn = conn
        self.today = today
        self.verified_customers: set[int] = set()
        self.failed_attempts = 0

    def _today(self) -> date:
        return self.today or date.today()

    def _fail(self) -> dict[str, Any]:
        self.failed_attempts += 1
        return LOCKED if self.failed_attempts >= MAX_FAILED_ATTEMPTS else NOT_VERIFIED

    def order_status(self, order_id: int | str, email: str | None = None, phone: str | None = None) -> dict[str, Any]:
        """Status de um pedido, se o cliente se identificar como dono dele."""
        if self.failed_attempts >= MAX_FAILED_ATTEMPTS:
            return LOCKED
        if not str(order_id).strip().isdigit():
            return self._fail()
        order = self.conn.execute(
            "SELECT o.*, c.name AS customer_name, c.email, c.phone, c.city FROM orders o "
            "JOIN customers c USING (customer_id) WHERE o.order_id = ?",
            (int(order_id),),
        ).fetchone()
        if order is None:
            return self._fail()
        already = order["customer_id"] in self.verified_customers
        if not already and not (_same_email(email, order["email"]) or _same_phone(phone, order["phone"])):
            return self._fail()
        self.verified_customers.add(order["customer_id"])
        return self._describe(order)

    def my_orders(self) -> dict[str, Any]:
        """Resumo dos pedidos dos clientes já verificados nesta conversa."""
        if not self.verified_customers:
            return {
                "verificado": False,
                "mensagem": "Cliente ainda não validado. Peça o número de um pedido e o e-mail ou telefone cadastrado.",
            }
        marks = ",".join("?" * len(self.verified_customers))
        rows = self.conn.execute(
            f"SELECT order_id, order_date, status, total_cents FROM orders WHERE customer_id IN ({marks}) ORDER BY order_date",
            tuple(self.verified_customers),
        ).fetchall()
        return {
            "verificado": True,
            "pedidos": [
                {
                    "pedido": r["order_id"],
                    "data": r["order_date"],
                    "status": STATUS_INFO[r["status"]][0],
                    "total": format_brl(r["total_cents"]),
                }
                for r in rows
            ],
        }

    def _items(self, order_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT p.name, oi.quantity FROM order_items oi JOIN products p USING (product_id) WHERE oi.order_id = ?",
            (order_id,),
        )
        return [{"produto": r["name"], "quantidade": r["quantity"]} for r in rows]

    def _describe(self, order: sqlite3.Row) -> dict[str, Any]:
        label, guidance = STATUS_INFO[order["status"]]
        result: dict[str, Any] = {
            "verificado": True,
            "pedido": order["order_id"],
            "cliente": order["customer_name"].split()[0],
            "data_do_pedido": order["order_date"],
            "status": label,
            "orientacao": guidance,
            "itens": self._items(order["order_id"]),
            "total": format_brl(order["total_cents"]),
            "forma_de_pagamento": payment_label(order["payment_method"]),
            "codigo_de_rastreio": order["tracking_code"] or "ainda não disponível",
            "previsao_de_entrega": order["estimated_delivery"] or "ainda não definida",
        }
        if order["notes"]:
            result["observacao_do_pedido"] = order["notes"]
        if order["status"] == "delivered" and order["estimated_delivery"]:
            # Só existe a data prevista; ela é usada como data de recebimento.
            result["prazos_de_devolucao"] = {
                "data_de_recebimento_considerada": order["estimated_delivery"],
                "aviso": "a data real de recebimento não está no sistema; foi usada a previsão de entrega",
                **return_windows(
                    date.fromisoformat(order["order_date"]),
                    date.fromisoformat(order["estimated_delivery"]),
                    self._today(),
                ),
            }
        return result
