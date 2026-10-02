"""Run one real order through the EKS storefront and asynchronous workers."""

import os
import time
from uuid import uuid4

import httpx


def main():
    storefront = os.getenv("STOREFRONT_URL", "http://retail-storefront:8080")
    with httpx.Client(timeout=10) as client:
        products = client.get(f"{storefront}/api/products")
        products.raise_for_status()
        mug = next(product for product in products.json() if product["id"] == "coffee-mug")
        response = client.post(
            f"{storefront}/api/orders",
            headers={"Idempotency-Key": str(uuid4())},
            json={"product_id": mug["id"], "quantity": 1, "email": "smoke@example.invalid"},
        )
        response.raise_for_status()
        order = response.json()
        print(f"Smoke order {order['id']} started as {order['status']}", flush=True)
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            response = client.get(f"{storefront}/api/orders/{order['id']}")
            response.raise_for_status()
            order = response.json()
            if order["status"] == "CONFIRMED" and order["notification_status"] == "RECORDED":
                print(f"Smoke order {order['id']} confirmed and notification recorded", flush=True)
                return
            if order["status"] == "REJECTED":
                raise RuntimeError(f"Smoke order rejected: {order.get('reason')}")
            time.sleep(2)
        raise TimeoutError(f"Smoke order {order['id']} did not complete: {order}")


if __name__ == "__main__":
    main()
