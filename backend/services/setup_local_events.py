"""Create the local event bus, event rules, SQS queues, and dead-letter queues."""

import json
import time

from botocore.exceptions import BotoCoreError, ClientError

from services.messaging import (
    EVENT_BUS_NAME,
    event_client,
    queue_client,
    INVENTORY_QUEUE_NAME,
    ORDER_RESULTS_QUEUE_NAME,
)

def create_queue(sqs, name: str, dlq_arn: str | None = None) -> str:
    attributes = {"VisibilityTimeout": "10"}
    if dlq_arn:
        attributes["RedrivePolicy"] = json.dumps({"deadLetterTargetArn": dlq_arn, "maxReceiveCount": "3"})
    response = sqs.create_queue(QueueName=name, Attributes=attributes)
    url = response["QueueUrl"]
    return url


def queue_arn(sqs, queue_url: str) -> str:
    return sqs.get_queue_attributes(QueueUrl=queue_url, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]


def main():
    events = event_client()
    sqs = queue_client()
    for attempt in range(60):
        try:
            events.list_event_buses()
            break
        except (BotoCoreError, ClientError):
            if attempt == 59:
                raise
            time.sleep(2)

    try:
        events.create_event_bus(Name=EVENT_BUS_NAME)
    except events.exceptions.ResourceAlreadyExistsException:
        pass

    inventory_dlq_url = create_queue(sqs, f"{INVENTORY_QUEUE_NAME}-dlq")
    order_dlq_url = create_queue(sqs, f"{ORDER_RESULTS_QUEUE_NAME}-dlq")
    inventory_url = create_queue(sqs, INVENTORY_QUEUE_NAME, queue_arn(sqs, inventory_dlq_url))
    order_url = create_queue(sqs, ORDER_RESULTS_QUEUE_NAME, queue_arn(sqs, order_dlq_url))

    rules = [
        {
            "name": "retail-order-created",
            "pattern": {"source": ["retail.order"], "detail-type": ["OrderCreated"]},
            "queue_url": inventory_url,
        },
        {
            "name": "retail-inventory-result",
            "pattern": {"source": ["retail.inventory"], "detail-type": ["InventoryReserved", "InventoryFailed"]},
            "queue_url": order_url,
        },
    ]

    for rule in rules:
        rule_response = events.put_rule(
            Name=rule["name"],
            EventBusName=EVENT_BUS_NAME,
            EventPattern=json.dumps(rule["pattern"]),
            State="ENABLED",
        )
        target_arn = queue_arn(sqs, rule["queue_url"])
        events.put_targets(
            Rule=rule["name"],
            EventBusName=EVENT_BUS_NAME,
            Targets=[{"Id": "sqs-target", "Arn": target_arn}],
        )
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": f"Allow{rule['name']}",
                    "Effect": "Allow",
                    "Principal": {"Service": "events.amazonaws.com"},
                    "Action": "sqs:SendMessage",
                    "Resource": target_arn,
                    "Condition": {"ArnEquals": {"aws:SourceArn": rule_response["RuleArn"]}},
                }
            ],
        }
        sqs.set_queue_attributes(QueueUrl=rule["queue_url"], Attributes={"Policy": json.dumps(policy)})

    print(f"Created EventBridge bus: {EVENT_BUS_NAME}", flush=True)
    print(f"OrderCreated -> SQS: {INVENTORY_QUEUE_NAME}", flush=True)
    print(f"InventoryReserved/InventoryFailed -> SQS: {ORDER_RESULTS_QUEUE_NAME}", flush=True)
    print("Each SQS queue has a dead-letter queue after three failed receives.", flush=True)


if __name__ == "__main__":
    main()
