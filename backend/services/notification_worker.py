"""Consume order status events and store an idempotent notification record."""

import os

import boto3

from services.messaging import NOTIFICATION_QUEUE_NAME, publish_event, run_worker
from services.notification import Notification, record_notification


def process_event(event):
    if event["detail-type"] != "OrderStatusUpdated":
        raise ValueError("Unexpected notification event")
    detail = event["detail"]
    order_id = detail["order_id"]
    status = detail["status"]
    message = (
        f"Your order for {detail['quantity']} x {detail['product_name']} is confirmed."
        if status == "CONFIRMED" else "Your order could not be completed because stock was unavailable."
    )
    record_notification(Notification(order_id=order_id, email=detail["email"], message=message))
    topic_arn = os.getenv("NOTIFICATION_TOPIC_ARN")
    if topic_arn:
        boto3.client("sns", region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1")).publish(
            TopicArn=topic_arn,
            Subject="Retail order update",
            Message=f"Order {order_id}: {message}",
        )
    publish_event("NotificationRecorded", "retail.notification", {"order_id": order_id})
    print(f"Notification recorded for order {order_id}", flush=True)


if __name__ == "__main__":
    run_worker(NOTIFICATION_QUEUE_NAME, process_event, "notification-worker")
