"""Check the cloud values wired from Terraform's SSM deployment config."""

import importlib.util
import json
from pathlib import Path


def test_cloud_values_and_migration_job():
    root = Path(__file__).resolve().parents[1]
    source = root / "deploy/aws/render_values.py"
    spec = importlib.util.spec_from_file_location("render_values", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    config = json.loads((root / "deploy/aws/example-config.json").read_text(encoding="utf-8"))
    values, job = module.render(config, "abc123")
    assert values["monitoring"]["enabled"]
    assert len(values["services"]) == 5
    assert len(values["workers"]) == 3
    assert all(service["image"].endswith(":abc123") for service in values["services"])
    notification_worker = next(worker for worker in values["workers"] if worker["name"] == "notification-worker")
    assert notification_worker["env"]["NOTIFICATION_TOPIC_ARN"] == config["notification_topic_arn"]
    assert notification_worker["env"]["AWS_DEFAULT_REGION"] == config["region"]
    product = next(service for service in values["services"] if service["name"] == "product")
    assert product["env"]["AWS_DEFAULT_REGION"] == config["region"]
    assert job["spec"]["template"]["spec"]["serviceAccountName"] == "retail-db-bootstrap"
    assert job["spec"]["template"]["spec"]["containers"][0]["command"] == ["python", "-m", "services.db_bootstrap"]
