"""Stock reservation with one reservation per order."""

import os
import sqlite3
from contextlib import closing
from pathlib import Path

from fastapi import FastAPI
from services.metrics import instrument
from pydantic import BaseModel, Field
import boto3
from botocore.exceptions import ClientError

DB_PATH = Path(os.getenv("DB_PATH", "./inventory.db"))
DATA_BACKEND = os.getenv("DATA_BACKEND", "sqlite")
STOCK_TABLE = os.getenv("STOCK_TABLE", "retail-stock")
RESERVATION_TABLE = os.getenv("RESERVATION_TABLE", "retail-reservations")
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
    if DATA_BACKEND == "aws":
        return
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
instrument(app, "inventory")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/inventory/{product_id}")
def get_stock(product_id: str):
    if DATA_BACKEND == "aws":
        response = boto3.client("dynamodb").get_item(
            TableName=STOCK_TABLE,
            Key={"product_id": {"S": product_id}},
            ConsistentRead=True,
        )
        item = response.get("Item")
        return {"product_id": product_id, "available": int(item["available"]["N"]) if item else 0}
    with closing(connect()) as connection:
        row = connection.execute("SELECT available FROM stock WHERE product_id = ?", (product_id,)).fetchone()
    return {"product_id": product_id, "available": row["available"] if row else 0}


@app.post("/inventory/reservations")
def reserve(request: Reservation):
    return reserve_stock(request)


def reserve_stock(request: Reservation):
    if DATA_BACKEND == "aws":
        dynamo = boto3.client("dynamodb")
        existing = dynamo.get_item(
            TableName=RESERVATION_TABLE,
            Key={"order_id": {"S": request.order_id}},
            ConsistentRead=True,
        ).get("Item")
        if existing:
            same = existing["product_id"]["S"] == request.product_id and int(existing["quantity"]["N"]) == request.quantity
            return {"reserved": same, "reason": None if same else "order_id already used"}
        try:
            dynamo.transact_write_items(TransactItems=[
                {"Update": {
                    "TableName": STOCK_TABLE,
                    "Key": {"product_id": {"S": request.product_id}},
                    "UpdateExpression": "SET available = available - :quantity",
                    "ConditionExpression": "attribute_exists(product_id) AND available >= :quantity",
                    "ExpressionAttributeValues": {":quantity": {"N": str(request.quantity)}},
                }},
                {"Put": {
                    "TableName": RESERVATION_TABLE,
                    "Item": {
                        "order_id": {"S": request.order_id},
                        "product_id": {"S": request.product_id},
                        "quantity": {"N": str(request.quantity)},
                    },
                    "ConditionExpression": "attribute_not_exists(order_id)",
                }},
            ])
            return {"reserved": True, "reason": None}
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") != "TransactionCanceledException":
                raise
            existing = dynamo.get_item(
                TableName=RESERVATION_TABLE,
                Key={"order_id": {"S": request.order_id}},
                ConsistentRead=True,
            ).get("Item")
            if existing:
                same = existing["product_id"]["S"] == request.product_id and int(existing["quantity"]["N"]) == request.quantity
                return {"reserved": same, "reason": None if same else "order_id already used"}
            reasons = error.response.get("CancellationReasons", [])
            if reasons and reasons[0].get("Code") == "ConditionalCheckFailed":
                return {"reserved": False, "reason": "Insufficient stock"}
            raise
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
