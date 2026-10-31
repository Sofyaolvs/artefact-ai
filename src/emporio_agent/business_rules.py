"""Regras comerciais do manual de políticas, calculadas em código.

O LLM nunca faz conta: preço promocional, desconto PIX, parcelamento e frete
vêm daqui, em centavos inteiros. Seções citadas referem-se ao manual v2.1.
"""

from datetime import date, timedelta
from typing import Any

from emporio_agent.formatting import format_brl, normalize

PIX_DISCOUNT_PERCENT = 5  # §3
MAX_INSTALLMENTS = 12  # §3

# §3.1: (até N parcelas, valor mínimo da parcela em centavos). A tabela da §3
# diz R$ 100 para qualquer crédito; vale a regra detalhada da §3.1.
_INSTALLMENT_MINIMUMS = ((3, 5000), (6, 8000), (12, 10000))
COMBINED_PAYMENT_MIN_CENTS = 200000  # §3.1: combinar formas só acima de R$ 2.000,00

LOCAL_CITY = "campo grande"  # §5.1
FREE_SHIPPING_MIN_CENTS = 50000  # §5.1
LOCAL_SHIPPING_FEE_CENTS = 3500  # §5.1
LOCAL_DELIVERY_DAYS = "1 a 3 dias úteis"

CARRIERS = (  # §5.2
    {"modalidade": "PAC (Correios)", "prazo": "5 a 12 dias úteis"},
    {"modalidade": "SEDEX (Correios)", "prazo": "2 a 5 dias úteis"},
    {"modalidade": "Jadlog (.package)", "prazo": "3 a 8 dias úteis"},
)
_BULKY_CATEGORIES = ("bateria", "piano", "contrabaixo")  # §5.2: frete com cotação individual

REGRET_WINDOW_DAYS = 7  # §4.1 e §4.3, a partir do recebimento
DEFECT_EXCHANGE_DAYS = 30  # §4.2, a partir da compra
LEGAL_WARRANTY_DAYS = 90  # §8.1, a partir do recebimento


def percent_of(cents: int, percent: int) -> int:
    """`percent`% de um valor em centavos, arredondando para cima na metade."""
    return (cents * percent + 50) // 100


def apply_discount(cents: int, percent: int) -> int:
    return cents - percent_of(cents, percent)


def price_with_promotion(price_cents: int, discount_percent: int | None) -> dict[str, Any]:
    """Preço final com a promoção ativa, se houver (§6.2: mostrar original, % e final)."""
    if not discount_percent:
        return {"preco_final_centavos": price_cents, "em_promocao": False}
    return {
        "preco_final_centavos": apply_discount(price_cents, discount_percent),
        "em_promocao": True,
        "desconto_percent": discount_percent,
    }


def pix_price(price_cents: int, on_promotion: bool) -> int:
    """5% no PIX sobre o preço de tabela; não acumula com preço promocional (§6.2)."""
    return price_cents if on_promotion else apply_discount(price_cents, PIX_DISCOUNT_PERCENT)


def min_installment(parcelas: int) -> int:
    for up_to, minimum in _INSTALLMENT_MINIMUMS:
        if parcelas <= up_to:
            return minimum
    raise ValueError(f"parcelas acima de {MAX_INSTALLMENTS}")


def installment_options(total_cents: int) -> list[dict[str, Any]]:
    """Parcelamentos permitidos no crédito (sem juros), respeitando a parcela mínima."""
    options = []
    for n in range(2, MAX_INSTALLMENTS + 1):
        parcela = -(-total_cents // n)  # arredonda para cima
        if parcela >= min_installment(n):
            options.append({"parcelas": n, "valor_parcela": format_brl(parcela), "valor_parcela_centavos": parcela})
    return options


def payment_options(price_cents: int, on_promotion: bool) -> dict[str, Any]:
    """Resumo das formas de pagamento para um valor (preço final do produto ou do carrinho)."""
    parcelas = installment_options(price_cents)
    pix = pix_price(price_cents, on_promotion)
    return {
        "pix": {
            "valor": format_brl(pix),
            "valor_centavos": pix,
            "observacao": "preço promocional, sem desconto extra no PIX" if on_promotion else "5% de desconto sobre o preço de tabela",
        },
        "debito": {"valor": format_brl(price_cents)},
        "boleto": {"valor": format_brl(price_cents), "observacao": "compensação em até 3 dias úteis"},
        "credito": {
            "a_vista": format_brl(price_cents),
            "max_parcelas_sem_juros": parcelas[-1]["parcelas"] if parcelas else 1,
            "parcelas": parcelas,
        },
        "combinar_formas_de_pagamento": price_cents > COMBINED_PAYMENT_MIN_CENTS,
    }


def is_local_delivery(city: str | None) -> bool:
    return normalize(city or "").strip() == LOCAL_CITY


def shipping_info(total_cents: int, city: str | None, category_names: list[str] | None = None) -> dict[str, Any]:
    """Frete e prazo. Fora de Campo Grande o valor depende do CEP e não é inventado."""
    if is_local_delivery(city):
        free = total_cents >= FREE_SHIPPING_MIN_CENTS
        fee = 0 if free else LOCAL_SHIPPING_FEE_CENTS
        return {
            "regiao": "Campo Grande e região metropolitana",
            "frete": "grátis" if free else format_brl(fee),
            "frete_centavos": fee,
            "prazo": LOCAL_DELIVERY_DAYS,
            "observacao": "entrega por motoboy próprio; o cliente é contatado por telefone antes",
        }
    info: dict[str, Any] = {
        "regiao": "outras cidades",
        "frete": "calculado pelo CEP de destino, peso e dimensões",
        "frete_centavos": None,
        "modalidades": list(CARRIERS),
        "observacao": "todos os envios têm rastreamento e seguro",
    }
    if any(b in normalize(c) for c in category_names or [] for b in _BULKY_CATEGORIES):
        info["cotacao_individual"] = True
        info["observacao"] += "; instrumentos de grande porte exigem frete especial com cotação individual"
    return info


def return_windows(purchase_date: date, received_date: date, today: date) -> dict[str, Any]:
    """Prazos de arrependimento, troca por defeito e garantia legal, e se ainda estão abertos."""

    def window(start: date, days: int) -> dict[str, Any]:
        deadline = start + timedelta(days=days)
        return {"limite": deadline.isoformat(), "aberto": today <= deadline, "dias_restantes": max((deadline - today).days, 0)}

    return {
        "arrependimento_7_dias": window(received_date, REGRET_WINDOW_DAYS),
        "troca_por_defeito_30_dias": window(purchase_date, DEFECT_EXCHANGE_DAYS),
        "garantia_legal_90_dias": window(received_date, LEGAL_WARRANTY_DAYS),
    }
