"""Checkout orchestration. Direct HTTP calls are replaced by events in a later stage."""

import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, field_validator

DB_PATH = Path(os.getenv("DB_PATH", "./order.db"))
PRODUCT_URL = os.getenv("PRODUCT_URL", "http://localhost:8001")
INVENTORY_URL = os.getenv("INVENTORY_URL", "http://localhost:8002")
NOTIFICATION_URL = os.getenv("NOTIFICATION_URL", "http://localhost:8004")


class Checkout(BaseModel):
    product_id: str = Field(min_length=1)
    quantity: int = Field(gt=0, le=99)
    email: str = Field(min_length=3, max_length=254)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str):
        value = value.strip().lower()
        if "@" not in value or "." not in value.split("@")[-1]:
            raise ValueError("Enter a valid email address")
        return value


def connect():
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def initialize():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect()) as connection:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE NOT NULL,
                product_id TEXT NOT NULL, product_name TEXT NOT NULL,
                quantity INTEGER NOT NULL, unit_price_cents INTEGER NOT NULL,
                total_cents INTEGER NOT NULL, email TEXT NOT NULL,
                status TEXT NOT NULL, notification_status TEXT NOT NULL,
                reason TEXT, created_at TEXT NOT NULL
            )"""
        )
        connection.commit()


initialize()
app = FastAPI(title="Retail Order Service")


def get_order_row(order_id: str):
    with closing(connect()) as connection:
        row = connection.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    return dict(row) if row else None


def update_order(order_id: str, **changes):
    if changes:
        columns = ", ".join(f"{column} = ?" for column in changes)
        with closing(connect()) as connection:
            connection.execute(
                f"UPDATE orders SET {columns} WHERE id = ?", (*changes.values(), order_id)
            )
            connection.commit()
    return get_order_row(order_id)


def send_notification(order):
    if order["notification_status"] == "RECORDED":
        return order
    try:
        with httpx.Client(timeout=3) as client:
            response = client.post(
                f"{NOTIFICATION_URL}/notifications",
                json={
                    "order_id": order["id"],
                    "email": order["email"],
                    "message": f"Your order for {order['quantity']} × {order['product_name']} is confirmed.",
                },
            )
            response.raise_for_status()
    except httpx.HTTPError:
        return order
    return update_order(order["id"], notification_status="RECORDED")


def process_order(order):
    if order["status"] == "PENDING":
        try:
            with httpx.Client(timeout=3) as client:
                response = client.post(
                    f"{INVENTORY_URL}/inventory/reservations",
                    json={
                        "order_id": order["id"],
                        "product_id": order["product_id"],
                        "quantity": order["quantity"],
                    },
                )
                response.raise_for_status()
                reservation = response.json()
        except (httpx.HTTPError, ValueError):
            return update_order(order["id"], reason="Inventory temporarily unavailable; retry this order")
        if not reservation["reserved"]:
            return update_order(order["id"], status="REJECTED", reason=reservation["reason"])
        order = update_order(order["id"], status="CONFIRMED", reason=None)
    if order["status"] == "CONFIRMED":
        order = send_notification(order)
    return order


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/orders")
def create_order(checkout: Checkout, idempotency_key: str | None = Header(default=None)):
    if idempotency_key and len(idempotency_key) > 100:
        raise HTTPException(400, "Idempotency key is too long")
    key = idempotency_key or str(uuid4())
    with closing(connect()) as connection:
        existing = connection.execute(
            "SELECT * FROM orders WHERE idempotency_key = ?", (key,)
        ).fetchone()
    if existing:
        if (existing["product_id"], existing["quantity"], existing["email"]) != (
            checkout.product_id, checkout.quantity, checkout.email
        ):
            raise HTTPException(409, "Idempotency key belongs to a different checkout")
        return process_order(dict(existing))

    try:
        with httpx.Client(timeout=3) as client:
            response = client.get(f"{PRODUCT_URL}/products/{checkout.product_id}")
            if response.status_code == 404:
                raise HTTPException(404, "Product not found")
            response.raise_for_status()
            product = response.json()
    except httpx.HTTPError:
        raise HTTPException(503, "Product service unavailable") from None

    order_id = str(uuid4())
    with closing(connect()) as connection:
        connection.execute(
            """INSERT OR IGNORE INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                order_id, key, checkout.product_id, product["name"], checkout.quantity,
                product["price_cents"], checkout.quantity * product["price_cents"],
                checkout.email, "PENDING", "PENDING", None,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM orders WHERE idempotency_key = ?", (key,)
        ).fetchone()
    return process_order(dict(row))


@app.get("/orders/{order_id}")
def get_order(order_id: str):
    order = get_order_row(order_id)
    if order is None:
        raise HTTPException(404, "Order not found")
    return order


@app.post("/orders/{order_id}/retry")
def retry_order(order_id: str):
    order = get_order_row(order_id)
    if order is None:
        raise HTTPException(404, "Order not found")
    return process_order(order)
