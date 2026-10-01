"""A local notification record; no real email is sent in stage one."""

import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel, Field

DB_PATH = Path(os.getenv("DB_PATH", "./notification.db"))


class Notification(BaseModel):
    order_id: str = Field(min_length=1)
    email: str = Field(min_length=3)
    message: str = Field(min_length=1)


def connect():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect()) as connection:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS notifications (
                order_id TEXT PRIMARY KEY, email TEXT NOT NULL, message TEXT NOT NULL,
                created_at TEXT NOT NULL
            )"""
        )
        connection.commit()


initialize()
app = FastAPI(title="Retail Notification Service")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/notifications")
def record_notification(request: Notification):
    created_at = datetime.now(timezone.utc).isoformat()
    with closing(connect()) as connection:
        connection.execute(
            "INSERT OR IGNORE INTO notifications VALUES (?, ?, ?, ?)",
            (request.order_id, request.email, request.message, created_at),
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM notifications WHERE order_id = ?", (request.order_id,)
        ).fetchone()
    return dict(row)


@app.get("/notifications/{order_id}")
def get_notification(order_id: str):
    with closing(connect()) as connection:
        row = connection.execute(
            "SELECT * FROM notifications WHERE order_id = ?", (order_id,)
        ).fetchone()
    return dict(row) if row else {"order_id": order_id, "recorded": False}
