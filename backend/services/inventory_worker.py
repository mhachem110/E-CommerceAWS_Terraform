"""Consume OrderCreated events and reserve inventory."""

from services.inventory import Reservation, reserve_stock
from services.messaging import INVENTORY_QUEUE_NAME, publish_event, run_worker


def process_event(event):
    detail = event["detail"]
    order_id = detail["order_id"]
    print(f"Inventory received OrderCreated for order {order_id}", flush=True)
    result = reserve_stock(Reservation(**detail))
    result_type = "InventoryReserved" if result["reserved"] else "InventoryFailed"
    publish_event(
        result_type,
        "retail.inventory",
        {
            "order_id": order_id,
            "product_id": detail["product_id"],
            "quantity": detail["quantity"],
            "reason": result["reason"],
        },
    )
    print(f"Inventory published {result_type} for order {order_id}", flush=True)


if __name__ == "__main__":
    run_worker(INVENTORY_QUEUE_NAME, process_event, "inventory-worker")
