"""Run the real HTTP services together, without needing Docker or AWS."""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
HTTP_TIMEOUT = 15


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    data = tmp_path_factory.mktemp("retail")
    ports = {name: free_port() for name in ("product", "inventory", "order", "notification")}
    processes = []
    base_env = os.environ.copy()
    base_env["PYTHONPATH"] = str(BACKEND)
    base_env.update({
        "PRODUCT_URL": f"http://127.0.0.1:{ports['product']}",
        "INVENTORY_URL": f"http://127.0.0.1:{ports['inventory']}",
        "NOTIFICATION_URL": f"http://127.0.0.1:{ports['notification']}",
    })
    try:
        for name in ("product", "inventory", "notification", "order"):
            env = base_env.copy()
            env["DB_PATH"] = str(data / f"{name}.db")
            process = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", f"services.{name}:app", "--host", "127.0.0.1", "--port", str(ports[name])],
                cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            )
            processes.append(process)
            url = f"http://127.0.0.1:{ports[name]}"
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f"{name} exited: {process.stderr.read().decode()}")
                try:
                    if httpx.get(f"{url}/health", timeout=0.3).status_code == 200:
                        break
                except httpx.HTTPError:
                    time.sleep(0.1)
            else:
                raise RuntimeError(f"{name} did not become healthy")
        yield {name: f"http://127.0.0.1:{port}" for name, port in ports.items()}
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            if process.stderr:
                process.stderr.close()


def test_checkout_reservation_and_notification(stack):
    catalog = httpx.get(f"{stack['product']}/products", timeout=HTTP_TIMEOUT).json()
    assert len(catalog) == 3
    product = next(item for item in catalog if item["id"] == "coffee-mug")
    before = httpx.get(f"{stack['inventory']}/inventory/coffee-mug", timeout=HTTP_TIMEOUT).json()["available"]

    key = str(uuid4())
    checkout = {"product_id": product["id"], "quantity": 2, "email": "shopper@example.com"}
    response = httpx.post(f"{stack['order']}/orders", json=checkout, headers={"Idempotency-Key": key}, timeout=HTTP_TIMEOUT)
    assert response.status_code == 200
    order = response.json()
    assert order["status"] == "CONFIRMED"
    assert order["notification_status"] == "RECORDED"
    assert order["total_cents"] == product["price_cents"] * 2
    assert httpx.get(f"{stack['inventory']}/inventory/coffee-mug", timeout=HTTP_TIMEOUT).json()["available"] == before - 2
    assert httpx.get(f"{stack['notification']}/notifications/{order['id']}", timeout=HTTP_TIMEOUT).json()["email"] == checkout["email"]

    repeated = httpx.post(f"{stack['order']}/orders", json=checkout, headers={"Idempotency-Key": key}, timeout=HTTP_TIMEOUT).json()
    assert repeated["id"] == order["id"]
    assert httpx.get(f"{stack['inventory']}/inventory/coffee-mug", timeout=HTTP_TIMEOUT).json()["available"] == before - 2
    assert httpx.post(f"{stack['order']}/orders/{order['id']}/retry", timeout=HTTP_TIMEOUT).json()["notification_status"] == "RECORDED"
    assert httpx.get(f"{stack['inventory']}/inventory/coffee-mug", timeout=HTTP_TIMEOUT).json()["available"] == before - 2

    conflict = httpx.post(f"{stack['order']}/orders", json={**checkout, "quantity": 3}, headers={"Idempotency-Key": key}, timeout=HTTP_TIMEOUT)
    assert conflict.status_code == 409

    sold_out = httpx.post(
        f"{stack['order']}/orders",
        json={"product_id": "desk-lamp", "quantity": 99, "email": "shopper@example.com"},
        timeout=HTTP_TIMEOUT,
    ).json()
    assert sold_out["status"] == "REJECTED"
    assert httpx.get(f"{stack['inventory']}/inventory/desk-lamp", timeout=HTTP_TIMEOUT).json()["available"] == 4

    unknown = httpx.post(
        f"{stack['order']}/orders",
        json={"product_id": "missing", "quantity": 1, "email": "shopper@example.com"},
        timeout=HTTP_TIMEOUT,
    )
    assert unknown.status_code == 404
