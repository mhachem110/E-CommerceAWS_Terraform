"""Small AWS SDK helpers for the local EventBridge and SQS learning flow."""

import json
import os
import time
from functools import lru_cache

import boto3
from botocore.exceptions import BotoCoreError, ClientError

ENDPOINT_URL = os.getenv("EVENTS_ENDPOINT_URL")
REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
EVENT_BUS_NAME = os.getenv("EVENT_BUS_NAME", "retail-local")
INVENTORY_QUEUE_NAME = os.getenv("INVENTORY_QUEUE_NAME", "retail-inventory-requests")
ORDER_RESULTS_QUEUE_NAME = os.getenv("ORDER_RESULTS_QUEUE_NAME", "retail-order-results")
_CLIENT_OPTIONS = {"region_name": REGION}
if ENDPOINT_URL:
    _CLIENT_OPTIONS["endpoint_url"] = ENDPOINT_URL
if os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY"):
    _CLIENT_OPTIONS["aws_access_key_id"] = os.environ["AWS_ACCESS_KEY_ID"]
    _CLIENT_OPTIONS["aws_secret_access_key"] = os.environ["AWS_SECRET_ACCESS_KEY"]


def event_client():
    return boto3.client("events", **_CLIENT_OPTIONS)


def queue_client():
    return boto3.client("sqs", **_CLIENT_OPTIONS)


def publish_event(detail_type: str, source: str, detail: dict) -> None:
    response = event_client().put_events(
        Entries=[
            {
                "EventBusName": EVENT_BUS_NAME,
                "Source": source,
                "DetailType": detail_type,
                "Detail": json.dumps(detail),
            }
        ]
    )
    if response.get("FailedEntryCount", 0):
        raise RuntimeError(f"EventBridge rejected {detail_type}: {response.get('Entries')}")


@lru_cache(maxsize=None)
def queue_url(queue_name: str) -> str:
    response = queue_client().get_queue_url(QueueName=queue_name)
    return response["QueueUrl"]


def receive_one(queue_name: str):
    response = queue_client().receive_message(
        QueueUrl=queue_url(queue_name),
        MaxNumberOfMessages=1,
        WaitTimeSeconds=5,
        VisibilityTimeout=10,
    )
    return response.get("Messages", [])


def delete_message(queue_name: str, receipt_handle: str) -> None:
    queue_client().delete_message(QueueUrl=queue_url(queue_name), ReceiptHandle=receipt_handle)


def run_worker(queue_name: str, process_message, worker_name: str) -> None:
    print(f"{worker_name} polling SQS queue {queue_name}", flush=True)
    while True:
        try:
            for message in receive_one(queue_name):
                try:
                    process_message(json.loads(message["Body"]))
                    delete_message(queue_name, message["ReceiptHandle"])
                except Exception:
                    # Leave failed work on the queue. SQS retries it and moves
                    # it to the configured DLQ after the receive limit.
                    print(f"{worker_name} could not process a message; it will be retried", flush=True)
                    raise
        except (BotoCoreError, ClientError, RuntimeError) as error:
            print(f"{worker_name} queue error: {error}", flush=True)
            time.sleep(2)
        except Exception as error:
            print(f"{worker_name} processing error: {error}", flush=True)
            time.sleep(1)
