# Retail microservices: stage 1

A small ecommerce demo for the Week 3 EKS project. It has one storefront and four independent backend services. This stage proves the shopping flow locally before adding AWS infrastructure.

## What happens when you place an order

```text
Browser → Storefront (Nginx, port 8080)
              ├── Product Service → local catalog database
              └── Order Service → local orders database
                     ├── Product Service (price lookup)
                     ├── Inventory Service → local stock database
                     └── Notification Service → local receipt record
```

The Order Service saves a `PENDING` order, asks Inventory to reserve stock, then marks the order `CONFIRMED` or `REJECTED`. A confirmed order gets one notification record. The inventory reservation and notification are keyed by order ID, so a retry does not reserve the same stock twice or record a second receipt.

## Run it

1. Start Docker Desktop.
2. In this repository, run `docker compose up --build -d`.
3. Open [http://localhost:8080](http://localhost:8080).
4. Choose a product, enter a quantity and an email, and place a **test order**.
5. To inspect service health, run `docker compose ps`. To see logs, run `docker compose logs -f order`.
6. Stop with `docker compose down`. The named volumes keep the orders and stock for the next run. `docker compose down -v` removes this demo data and restores the initial catalog and stock on the next start.

Only the storefront port is published. The four backend services communicate over the private Compose network. The browser reaches Product and Order through the storefront's `/api/` reverse proxy.

## Run the integration test without Docker

With Python 3.12 installed:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest -q
```

The test starts all four real HTTP services on temporary local ports. It checks a confirmed order, stock reduction, the receipt record, repeated checkout, key conflict, and insufficient stock.

## Repository map

| Path | Purpose |
| --- | --- |
| `frontend/` | Static storefront and Nginx API proxy |
| `backend/services/product.py` | Product catalog API |
| `backend/services/inventory.py` | Stock and idempotent reservation API |
| `backend/services/order.py` | Checkout and order status API |
| `backend/services/notification.py` | Idempotent notification record API |
| `compose.yaml` | Local containers, private network, and persistent demo data |
| `tests/` | End-to-end HTTP flow test |
| `.github/workflows/app-ci.yml` | App tests and image builds on PRs; no Terraform apply |

## Scope of this first stage

The four SQLite files are **local test substitutes**. No payment is collected and no actual email is sent. Order processing currently uses direct HTTP calls; it does not yet use EventBridge or SQS. The APIs have no customer authentication, so this is for local development only and must not be exposed publicly as a production shop.

Next stages: replace Product and Order storage with RDS/Aurora MySQL; replace Inventory and Notification storage with DynamoDB; add ElastiCache for catalog reads; move the order events to EventBridge and SQS with retries and DLQs; then add Kubernetes/Helm, EKS, ECR, Terraform, OIDC delivery, security, and monitoring. The frontend remains the public entry point. App PRs will run app checks and builds; Terraform changes will have their own reviewed infrastructure workflow in a separately permissioned infrastructure repository.
