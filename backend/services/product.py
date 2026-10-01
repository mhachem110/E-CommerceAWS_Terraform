"""Product catalog. SQLite is a local stand-in for the later MySQL database."""

import os
import sqlite3
from contextlib import closing
from pathlib import Path

from fastapi import FastAPI, HTTPException

DB_PATH = Path(os.getenv("DB_PATH", "./product.db"))
PRODUCTS = [
    ("coffee-mug", "Ceramic Coffee Mug", "A sturdy mug for the morning brew.", 1599, "☕"),
    ("canvas-tote", "Canvas Tote Bag", "A reusable bag for everyday errands.", 2499, "👜"),
    ("desk-lamp", "Desk Lamp", "A warm light for a focused workspace.", 3999, "💡"),
]


def connect():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect()) as connection:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS products (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL,
                price_cents INTEGER NOT NULL, icon TEXT NOT NULL
            )"""
        )
        connection.executemany(
            "INSERT OR IGNORE INTO products VALUES (?, ?, ?, ?, ?)", PRODUCTS
        )
        connection.commit()


initialize()
app = FastAPI(title="Retail Product Service")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/products")
def list_products():
    with closing(connect()) as connection:
        return [dict(row) for row in connection.execute("SELECT * FROM products ORDER BY name")]


@app.get("/products/{product_id}")
def get_product(product_id: str):
    with closing(connect()) as connection:
        row = connection.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Product not found")
    return dict(row)
