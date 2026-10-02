"""Verify the cloud notification side effect and retry behavior without AWS."""

import importlib
from pathlib import Path

import pytest


@pytest.fixture
def worker(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "backend"))
    monkeypatch.setenv("DATA_BACKEND", "aws")
    module = importlib.import_module("services.notification_worker")
    return module


def order_event():
    return {
        "detail-type": "OrderStatusUpdated",
        "detail": {
            "order_id": "order-123", "status": "CONFIRMED", "quantity": 2,
            "product_name": "Coffee mug", "email": "shopper@example.test",
        },
    }


def test_sns_publish_before_recorded_event(worker, monkeypatch):
    operations = []
    monkeypatch.setenv("NOTIFICATION_TOPIC_ARN", "arn:aws:sns:us-east-1:866934333672:demo")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setattr(worker, "record_notification", lambda record: operations.append(("record", record.order_id)))

    class FakeSNS:
        def publish(self, **kwargs):
            operations.append(("sns", kwargs))
            return {"MessageId": "message-1"}

    def client(name, **kwargs):
        assert name == "sns"
        assert kwargs["region_name"] == "us-east-1"
        return FakeSNS()

    monkeypatch.setattr(worker.boto3, "client", client)
    monkeypatch.setattr(worker, "publish_event", lambda name, source, detail: operations.append(("event", name)))

    worker.process_event(order_event())
    assert [operation[0] for operation in operations] == ["record", "sns", "event"]
    assert operations[1][1]["Subject"] == "Retail order update"
    assert "order-123" in operations[1][1]["Message"]


def test_sns_failure_leaves_event_for_sqs_retry(worker, monkeypatch):
    operations = []
    monkeypatch.setenv("NOTIFICATION_TOPIC_ARN", "arn:aws:sns:us-east-1:866934333672:demo")
    monkeypatch.setattr(worker, "record_notification", lambda record: operations.append("record"))

    class FailedSNS:
        def publish(self, **kwargs):
            raise RuntimeError("temporary SNS failure")

    monkeypatch.setattr(worker.boto3, "client", lambda *args, **kwargs: FailedSNS())
    monkeypatch.setattr(worker, "publish_event", lambda *args: operations.append("event"))

    with pytest.raises(RuntimeError, match="temporary SNS failure"):
        worker.process_event(order_event())
    assert operations == ["record"]


def test_local_no_topic_still_records_event(worker, monkeypatch):
    operations = []
    monkeypatch.delenv("NOTIFICATION_TOPIC_ARN", raising=False)
    monkeypatch.setattr(worker, "record_notification", lambda record: operations.append("record"))
    monkeypatch.setattr(worker.boto3, "client", lambda *args, **kwargs: pytest.fail("SNS was called"))
    monkeypatch.setattr(worker, "publish_event", lambda *args: operations.append("event"))

    worker.process_event(order_event())
    assert operations == ["record", "event"]
