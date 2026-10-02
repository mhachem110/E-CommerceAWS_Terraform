"""Render the EKS Helm values and initial database Job from Terraform's SSM config."""

import argparse
import json
from pathlib import Path


def service(name, image, env, *, replicas=1):
    return {
        "name": name, "image": image, "port": 8080 if name == "storefront" else 8000,
        "healthPath": "/" if name == "storefront" else "/health",
        "replicas": replicas, "env": env,
    }


def render(config, tag):
    images = {name: f"{url}:{tag}" for name, url in config["ecr_repository_urls"].items()}
    region = {"AWS_DEFAULT_REGION": config["region"]}
    events = {**region, "EVENT_BUS_NAME": config["event_bus_name"]}
    mysql = {"MYSQL_HOST": config["mysql_host"]}
    stock = {"STOCK_TABLE": config["stock_table"], "RESERVATION_TABLE": config["reservation_table"]}

    values = {
        "imagePullPolicy": "Always",
        "replicaCount": 1,
        "resources": {
            "requests": {"cpu": "100m", "memory": "128Mi"},
            "limits": {"cpu": "500m", "memory": "512Mi"},
        },
        "services": [
            service("product", images["product"], {
                "DATA_BACKEND": "aws", **mysql, "MYSQL_DATABASE": "retail_product",
                "MYSQL_SECRET_ARN": config["product_db_secret_arn"],
                "REDIS_HOST": config["redis_host"], "REDIS_SECRET_ARN": config["redis_secret_arn"],
            }),
            service("inventory", images["inventory"], {
                "DATA_BACKEND": "aws", **region, **stock,
            }),
            service("order", images["order"], {
                "DATA_BACKEND": "aws", **mysql, "MYSQL_DATABASE": "retail_order",
                "MYSQL_SECRET_ARN": config["order_db_secret_arn"],
                "PRODUCT_URL": "http://retail-product:8000", "ORDER_FLOW": "events",
                "NOTIFICATION_FLOW": "events", **events,
            }),
            service("notification", images["notification"], {
                "DATA_BACKEND": "aws", **region, "NOTIFICATION_TABLE": config["notification_table"],
            }),
            service("storefront", images["storefront"], {
                "PRODUCT_HOST": "retail-product", "ORDER_HOST": "retail-order",
                "NGINX_ENVSUBST_FILTER": "^(PRODUCT_HOST|ORDER_HOST|DNS_RESOLVER)$",
            }, replicas=2),
        ],
        "workers": [
            {
                "name": "inventory-worker", "image": images["inventory"],
                "command": ["python", "-m", "services.inventory_worker"],
                "env": {"DATA_BACKEND": "aws", **events, **stock,
                        "INVENTORY_QUEUE_NAME": config["inventory_queue_name"]},
            },
            {
                "name": "order-worker", "image": images["order"],
                "command": ["python", "-m", "services.order_worker"],
                "env": {"DATA_BACKEND": "aws", **events, **mysql,
                        "MYSQL_DATABASE": "retail_order", "MYSQL_SECRET_ARN": config["order_db_secret_arn"],
                        "NOTIFICATION_FLOW": "events",
                        "ORDER_RESULTS_QUEUE_NAME": config["order_results_queue_name"]},
            },
            {
                "name": "notification-worker", "image": images["notification"],
                "command": ["python", "-m", "services.notification_worker"],
                "env": {"DATA_BACKEND": "aws", **events,
                        "NOTIFICATION_TABLE": config["notification_table"],
                        "NOTIFICATION_QUEUE_NAME": config["notification_queue_name"]},
            },
        ],
        "ingress": {
            "enabled": True, "allowedCidrs": config["ingress_allowed_cidrs"],
            "certificateArn": config.get("certificate_arn", ""),
        },
        "hpa": {"storefront": {"enabled": True}},
    }
    bootstrap = {
        "apiVersion": "batch/v1", "kind": "Job",
        "metadata": {"name": "retail-db-bootstrap", "namespace": "retail"},
        "spec": {
            "backoffLimit": 3,
            "template": {"spec": {
                "restartPolicy": "OnFailure",
                "serviceAccountName": "retail-db-bootstrap",
                "containers": [{
                    "name": "db-bootstrap", "image": images["product"],
                    "command": ["python", "-m", "services.db_bootstrap"],
                    "env": [{"name": key, "value": str(value)} for key, value in {
                        "DATA_BACKEND": "aws", "AWS_DEFAULT_REGION": config["region"],
                        "MYSQL_HOST": config["mysql_host"],
                        "MYSQL_ROOT_SECRET_ARN": config["mysql_root_secret_arn"],
                        "PRODUCT_DB_SECRET_ARN": config["product_db_secret_arn"],
                        "ORDER_DB_SECRET_ARN": config["order_db_secret_arn"],
                        "STOCK_TABLE": config["stock_table"],
                    }.items()],
                }],
            }},
        },
    }
    return values, bootstrap


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    values, bootstrap = render(config, args.tag)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "values.json").write_text(json.dumps(values, indent=2), encoding="utf-8")
    (args.output_dir / "bootstrap-job.json").write_text(json.dumps(bootstrap, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
