"""Carga dos CSVs da loja em um banco SQLite.

Os dados são pequenos, então o banco é reconstruído a cada execução (em memória
por padrão). Valores monetários viram centavos inteiros para evitar erro de
ponto flutuante, e campos vazios viram NULL.
"""

import csv
import json
import sqlite3
from decimal import Decimal
from pathlib import Path

from emporio_agent.config import DATA_DIR

SCHEMA = """
CREATE TABLE categories (
    category_id INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT
);
CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    phone       TEXT,
    email       TEXT,
    city        TEXT
);
CREATE TABLE products (
    product_id     INTEGER PRIMARY KEY,
    name           TEXT NOT NULL,
    category_id    INTEGER NOT NULL REFERENCES categories(category_id),
    description    TEXT,
    price_cents    INTEGER NOT NULL,
    stock_quantity INTEGER NOT NULL,
    status         TEXT NOT NULL,
    specs          TEXT NOT NULL,
    created_at     TEXT
);
CREATE TABLE promotions (
    promotion_id     INTEGER PRIMARY KEY,
    product_id       INTEGER NOT NULL REFERENCES products(product_id),
    discount_percent INTEGER NOT NULL,
    description      TEXT,
    is_active        INTEGER NOT NULL
);
CREATE TABLE orders (
    order_id           INTEGER PRIMARY KEY,
    customer_id        INTEGER NOT NULL REFERENCES customers(customer_id),
    order_date         TEXT NOT NULL,
    status             TEXT NOT NULL,
    total_cents        INTEGER NOT NULL,
    payment_method     TEXT,
    tracking_code      TEXT,
    estimated_delivery TEXT,
    notes              TEXT
);
CREATE TABLE order_items (
    order_id   INTEGER NOT NULL REFERENCES orders(order_id),
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    quantity   INTEGER NOT NULL
);
"""


def to_cents(value: str) -> int:
    """Converte '599.9' em 59990 sem passar por float."""
    return int((Decimal(value) * 100).to_integral_value())


def _text(value: str | None) -> str | None:
    """Texto sem espaços nas pontas; vazio vira None."""
    value = (value or "").strip()
    return value or None


def _read(data_dir: Path, name: str) -> list[dict[str, str]]:
    with open(data_dir / f"{name}.csv", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _specs(raw: str) -> str:
    """Valida o JSON de specs e o devolve normalizado (vazio vira {})."""
    return json.dumps(json.loads(raw or "{}"), ensure_ascii=False)


def build_database(data_dir: Path = DATA_DIR, path: str = ":memory:") -> sqlite3.Connection:
    """Cria o banco e carrega todos os CSVs de `data_dir`."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)

    conn.executemany(
        "INSERT INTO categories VALUES (?, ?, ?)",
        [
            (int(r["category_id"]), r["name"].strip(), _text(r["description"]))
            for r in _read(data_dir, "categories")
        ],
    )
    conn.executemany(
        "INSERT INTO customers VALUES (?, ?, ?, ?, ?)",
        [
            (int(r["customer_id"]), r["name"].strip(), _text(r["phone"]), _text(r["email"]), _text(r["city"]))
            for r in _read(data_dir, "customers")
        ],
    )
    conn.executemany(
        "INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                int(r["product_id"]),
                r["name"].strip(),
                int(r["category_id"]),
                _text(r["description"]),
                to_cents(r["price_brl"]),
                int(r["stock_quantity"]),
                r["status"].strip().lower(),
                _specs(r["specs"]),
                _text(r["created_at"]),
            )
            for r in _read(data_dir, "products")
        ],
    )
    conn.executemany(
        "INSERT INTO promotions VALUES (?, ?, ?, ?, ?)",
        [
            (
                int(r["promotion_id"]),
                int(r["product_id"]),
                int(r["discount_percent"]),
                _text(r["description"]),
                int(r["is_active"]),
            )
            for r in _read(data_dir, "promotions")
        ],
    )
    conn.executemany(
        "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                int(r["order_id"]),
                int(r["customer_id"]),
                r["order_date"].strip(),
                r["status"].strip().lower(),
                to_cents(r["total_brl"]),
                _text(r["payment_method"]),
                _text(r["tracking_code"]),
                _text(r["estimated_delivery"]),
                _text(r["notes"]),
            )
            for r in _read(data_dir, "orders")
        ],
    )
    conn.executemany(
        "INSERT INTO order_items VALUES (?, ?, ?)",
        [
            (int(r["order_id"]), int(r["product_id"]), int(r["quantity"]))
            for r in _read(data_dir, "order_items")
        ],
    )
    conn.commit()
    return conn
