"""Product catalog. SQLite is a local stand-in for the later MySQL database."""

import os
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from fastapi import FastAPI, HTTPException
from services.metrics import instrument

from services.cloud_data import mysql_connection, redis_client

DB_PATH = Path(os.getenv("DB_PATH", "./product.db"))
DATA_BACKEND = os.getenv("DATA_BACKEND", "sqlite")
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
    if DATA_BACKEND == "aws":
        return
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
instrument(app, "product")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/products")
def list_products():
    if DATA_BACKEND == "aws":
        try:
            cached = redis_client().get("products:list")
            if cached:
                return json.loads(cached)
        except Exception:
            pass  # The catalog stays available when the cache is down.
        connection = mysql_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT id, name, description, price_cents, icon FROM products ORDER BY name")
                products = cursor.fetchall()
        finally:
            connection.close()
        try:
            redis_client().setex("products:list", 60, json.dumps(products))
        except Exception:
            pass
        return products
    with closing(connect()) as connection:
        return [dict(row) for row in connection.execute("SELECT * FROM products ORDER BY name")]


@app.get("/products/{product_id}")
def get_product(product_id: str):
    if DATA_BACKEND == "aws":
        try:
            cached = redis_client().get(f"product:{product_id}")
            if cached:
                return json.loads(cached)
        except Exception:
            pass
        connection = mysql_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT id, name, description, price_cents, icon FROM products WHERE id = %s", (product_id,))
                row = cursor.fetchone()
        finally:
            connection.close()
        if row is None:
            raise HTTPException(404, "Product not found")
        try:
            redis_client().setex(f"product:{product_id}", 60, json.dumps(row))
        except Exception:
            pass
        return row
    with closing(connect()) as connection:
        row = connection.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Product not found")
    return dict(row)
