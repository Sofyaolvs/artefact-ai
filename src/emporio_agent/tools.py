"""Ferramentas que o agente pode chamar.

Cada tool é uma consulta determinística aos dados da loja: o modelo escolhe qual
chamar e com quais argumentos, mas preços, estoque, status de pedido, contas e
regras vêm sempre do código.
"""

import sqlite3
from datetime import datetime
from typing import Any, Callable

from emporio_agent import business_rules, policies, products, store
from emporio_agent.orders import OrderService

DECLARATIONS: list[dict[str, Any]] = [
    {
        "name": "buscar_produtos",
        "description": (
            "Busca instrumentos no catálogo por tipo, texto e faixa de preço. Devolve só produtos à venda "
            "(com estoque), com preço final já considerando promoção ativa. Use para perguntas como "
            "'quais violões até R$ 1000?' ou 'tem guitarra Fender?'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "categoria": {
                    "type": "string",
                    "description": "Categoria: Guitarras, Baixos, Baterias e Percussão, Teclados e Pianos, Violões, Instrumentos de Sopro, Cordas Orquestrais, Ukuleles.",
                },
                "consulta": {"type": "string", "description": "Palavras do nome, marca ou característica (ex.: 'yamaha', 'nylon', 'canhoto')."},
                "preco_min": {"type": "number", "description": "Preço mínimo em reais."},
                "preco_max": {"type": "number", "description": "Preço máximo em reais."},
                "incluir_indisponiveis": {"type": "boolean", "description": "Incluir também produtos sem estoque, descontinuados ou em breve."},
                "ordenar_por": {"type": "string", "enum": ["preco_asc", "preco_desc", "nome"]},
                "limite": {"type": "integer", "description": "Máximo de resultados (padrão 10)."},
            },
        },
    },
    {
        "name": "detalhes_produto",
        "description": (
            "Detalhes de um produto específico (preço, promoção, estoque, especificações, formas de pagamento). "
            "Aceita o nome (ex.: 'Takamine GD20') ou o id. Use sempre que o cliente perguntar por um produto específico pelo nome: "
            "informa também se está sem estoque, descontinuado ou em breve, e nesses casos já traz alternativas."
        ),
        "parameters": {
            "type": "object",
            "properties": {"produto": {"type": "string", "description": "Nome ou id do produto."}},
            "required": ["produto"],
        },
    },
    {
        "name": "consultar_status_pedido",
        "description": (
            "Status de um pedido (situação, itens, rastreio, previsão de entrega, prazos de devolução). "
            "Exige o número do pedido E o e-mail ou telefone cadastrado na compra; nunca chame sem o segundo dado."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "numero_pedido": {"type": "integer"},
                "email": {"type": "string", "description": "E-mail cadastrado na compra."},
                "telefone": {"type": "string", "description": "Telefone cadastrado na compra."},
            },
            "required": ["numero_pedido"],
        },
    },
    {
        "name": "listar_meus_pedidos",
        "description": "Lista os pedidos do cliente que já foi validado nesta conversa. Só funciona depois de uma consulta de pedido validada.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "consultar_politicas",
        "description": (
            "Busca no manual de políticas da loja: trocas e devoluções, arrependimento, defeito, garantia, "
            "formas de pagamento e parcelamento, frete e entrega, promoções, privacidade, regras de atendimento. "
            "Passe a pergunta com as palavras-chave do assunto."
        ),
        "parameters": {
            "type": "object",
            "properties": {"pergunta": {"type": "string"}},
            "required": ["pergunta"],
        },
    },
    {
        "name": "informacoes_da_loja",
        "description": "Endereço, telefone, WhatsApp, e-mail, horário de funcionamento e se a loja está aberta agora.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "simular_pagamento",
        "description": "Calcula PIX, débito, boleto e parcelamento no crédito (sem juros, com parcela mínima) para um valor.",
        "parameters": {
            "type": "object",
            "properties": {
                "valor_total": {"type": "number", "description": "Valor em reais (preço final do produto ou do carrinho)."},
                "em_promocao": {"type": "boolean", "description": "True se o valor já é preço promocional (PIX não dá desconto extra)."},
            },
            "required": ["valor_total"],
        },
    },
    {
        "name": "calcular_frete",
        "description": "Frete e prazo de entrega para uma cidade. Em Campo Grande calcula o valor; em outras cidades informa as modalidades (o valor depende do CEP).",
        "parameters": {
            "type": "object",
            "properties": {
                "valor_total": {"type": "number", "description": "Valor do pedido em reais."},
                "cidade": {"type": "string"},
                "categorias": {"type": "array", "items": {"type": "string"}, "description": "Categorias dos itens (para detectar frete especial)."},
            },
            "required": ["valor_total", "cidade"],
        },
    },
]


_SUMMARY_FIELDS = ("id", "nome", "categoria", "preco", "em_promocao", "preco_original", "desconto_percent", "preco_no_pix", "disponibilidade", "estoque")


def _summary(product: dict[str, Any]) -> dict[str, Any]:
    """Versão enxuta do produto para listas; os detalhes ficam em `detalhes_produto`."""
    return {k: product[k] for k in _SUMMARY_FIELDS if k in product}


def _integer_if_whole(value: Any) -> Any:
    """O modelo costuma mandar o número do pedido como 8.0."""
    return int(value) if isinstance(value, float) and value.is_integer() else value


class ToolBox:
    """Executa as tools de uma conversa; guarda o estado dela (cliente validado)."""

    def __init__(self, conn: sqlite3.Connection, now: Callable[[], datetime] | None = None):
        self.conn = conn
        self._now = now
        self.orders = OrderService(conn)
        self._handlers: dict[str, Callable[..., Any]] = {
            "buscar_produtos": self.buscar_produtos,
            "detalhes_produto": self.detalhes_produto,
            "consultar_status_pedido": self.consultar_status_pedido,
            "listar_meus_pedidos": self.orders.my_orders,
            "consultar_politicas": self.consultar_politicas,
            "informacoes_da_loja": self.informacoes_da_loja,
            "simular_pagamento": self.simular_pagamento,
            "calcular_frete": self.calcular_frete,
        }

    @property
    def declarations(self) -> list[dict[str, Any]]:
        return DECLARATIONS

    def now(self) -> datetime | None:
        return self._now() if self._now else None

    def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Executa uma tool; erros viram um resultado que o modelo consegue ler e contornar."""
        handler = self._handlers.get(name)
        if handler is None:
            return {"erro": f"ferramenta desconhecida: {name}"}
        try:
            return handler(**args)
        except TypeError as exc:
            return {"erro": f"argumentos inválidos para {name}: {exc}"}
        except Exception as exc:  # a conversa não pode cair por falha numa consulta
            return {"erro": f"falha ao executar {name}: {exc}"}

    def buscar_produtos(
        self,
        categoria: str | None = None,
        consulta: str | None = None,
        preco_min: float | None = None,
        preco_max: float | None = None,
        incluir_indisponiveis: bool = False,
        ordenar_por: str = "preco_asc",
        limite: int = 10,
    ) -> dict[str, Any]:
        found = products.search_products(
            self.conn, consulta, categoria, preco_min, preco_max, incluir_indisponiveis, ordenar_por, int(limite)
        )
        result = {"total": len(found), "produtos": [_summary(p) for p in found]}
        if not found and not incluir_indisponiveis:
            # Nada à venda com esse filtro: avisa se o produto existe mas está indisponível,
            # para o agente não dizer que ele "não existe no catálogo".
            hidden = products.search_products(
                self.conn, consulta, categoria, preco_min, preco_max, True, ordenar_por, int(limite)
            )
            if hidden:
                result["indisponiveis_com_esse_filtro"] = [_summary(p) for p in hidden]
                result["observacao"] = (
                    "Nenhum item à venda, mas estes existem no catálogo e estão indisponíveis. "
                    "Use detalhes_produto para informar a situação e sugerir alternativas."
                )
        return result

    def detalhes_produto(self, produto: str | int) -> dict[str, Any]:
        return products.product_details(self.conn, _integer_if_whole(produto))

    def consultar_status_pedido(self, numero_pedido: int, email: str | None = None, telefone: str | None = None) -> dict[str, Any]:
        return self.orders.order_status(_integer_if_whole(numero_pedido), email=email, phone=telefone)

    def consultar_politicas(self, pergunta: str) -> dict[str, Any]:
        return policies.consult_policies(pergunta)

    def informacoes_da_loja(self) -> dict[str, Any]:
        return store.store_info(self.now())

    def simular_pagamento(self, valor_total: float, em_promocao: bool = False) -> dict[str, Any]:
        return business_rules.payment_options(round(valor_total * 100), em_promocao)

    def calcular_frete(self, valor_total: float, cidade: str, categorias: list[str] | None = None) -> dict[str, Any]:
        return business_rules.shipping_info(round(valor_total * 100), cidade, categorias)
