"""Stock reservation with one reservation per order."""

import os
import sqlite3
from contextlib import closing
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel, Field

DB_PATH = Path(os.getenv("DB_PATH", "./inventory.db"))
INITIAL_STOCK = [("coffee-mug", 12), ("canvas-tote", 8), ("desk-lamp", 4)]


class Reservation(BaseModel):
    order_id: str = Field(min_length=1)
    product_id: str = Field(min_length=1)
    quantity: int = Field(gt=0, le=99)


def connect():
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def initialize():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect()) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS stock (product_id TEXT PRIMARY KEY, available INTEGER NOT NULL)")
        connection.execute(
            """CREATE TABLE IF NOT EXISTS reservations (
                order_id TEXT PRIMARY KEY, product_id TEXT NOT NULL, quantity INTEGER NOT NULL
            )"""
        )
        connection.executemany("INSERT OR IGNORE INTO stock VALUES (?, ?)", INITIAL_STOCK)
        connection.commit()


initialize()
app = FastAPI(title="Retail Inventory Service")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/inventory/{product_id}")
def get_stock(product_id: str):
    with closing(connect()) as connection:
        row = connection.execute("SELECT available FROM stock WHERE product_id = ?", (product_id,)).fetchone()
    return {"product_id": product_id, "available": row["available"] if row else 0}


@app.post("/inventory/reservations")
def reserve(request: Reservation):
    with closing(connect()) as connection:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT product_id, quantity FROM reservations WHERE order_id = ?", (request.order_id,)
        ).fetchone()
        if existing:
            connection.commit()
            same_request = existing["product_id"] == request.product_id and existing["quantity"] == request.quantity
            return {"reserved": same_request, "reason": None if same_request else "order_id already used"}

        changed = connection.execute(
            "UPDATE stock SET available = available - ? WHERE product_id = ? AND available >= ?",
            (request.quantity, request.product_id, request.quantity),
        ).rowcount
        if not changed:
            connection.commit()
            return {"reserved": False, "reason": "Insufficient stock"}
        connection.execute(
            "INSERT INTO reservations VALUES (?, ?, ?)",
            (request.order_id, request.product_id, request.quantity),
        )
        connection.commit()
    return {"reserved": True, "reason": None}
