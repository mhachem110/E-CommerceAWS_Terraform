"""Consume inventory result events and update order status."""

from services.messaging import ORDER_RESULTS_QUEUE_NAME, run_worker
from services.order import get_order_row, send_notification, update_order


def process_event(event):
    detail = event["detail"]
    order_id = detail["order_id"]
    event_type = event["detail-type"]
    order = get_order_row(order_id)
    if order is None:
        raise ValueError(f"Order {order_id} does not exist")
    if order["status"] != "PENDING":
        print(f"Order {order_id} is already {order['status']}; ignoring duplicate result", flush=True)
        return

    if event_type == "InventoryReserved":
        order = update_order(order_id, status="CONFIRMED", reason=None)
        print(f"Order {order_id} updated to CONFIRMED", flush=True)
        order = send_notification(order)
        if order["notification_status"] == "RECORDED":
            print(f"Receipt record saved for order {order_id}", flush=True)
    elif event_type == "InventoryFailed":
        order = update_order(order_id, status="REJECTED", reason=detail.get("reason") or "Inventory unavailable")
        print(f"Order {order_id} updated to REJECTED", flush=True)
    else:
        raise ValueError(f"Unexpected inventory event type: {event_type}")


if __name__ == "__main__":
    run_worker(ORDER_RESULTS_QUEUE_NAME, process_event, "order-worker")
