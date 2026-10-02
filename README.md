# Retail microservices: local and AWS deployment

A small ecommerce demo for the Week 3 EKS project. It has one storefront and four independent backend services. Docker Compose remains a learning/demo path. The `deploy/aws/` renderer, Helm chart, and GitHub Actions workflow now describe the AWS deployment, with infrastructure kept in the separate private `Retail-Platform-Infra` repository.

The Docker Compose app has been run and verified locally. The AWS code has been validated but has not been applied to an account yet. Cloud provisioning will use GitHub Actions OIDC after an AWS administrator creates the initial trust role; local AWS CLI sign-in is not part of this path. For the local order flow, read the [local walkthrough](docs/local-walkthrough.md).

## What happens when you place an order

```text
Browser → Storefront (Nginx, port 8080)
              ├── Product Service → local catalog database
              └── Order Service → local orders database (PENDING)
                     └── EventBridge → SQS → Inventory worker → local stock database
                            └── EventBridge → SQS → Order worker → order database
                                   └── Notification Service → local receipt record
```

The Order API returns while the order is `PENDING`. EventBridge routes `OrderCreated` to an SQS queue. The Inventory worker reserves stock and publishes either `InventoryReserved` or `InventoryFailed`; another EventBridge rule sends that result to the Order worker. The Order worker updates the order and asks Notification to record a receipt for confirmed orders. Workers acknowledge messages only after processing. Inventory reservations and notification records are keyed by order ID so retries do not repeat those effects.

## Run it

1. Start Docker Desktop.
2. In this repository, run `docker compose up --build -d`.
3. Open [http://localhost:8080](http://localhost:8080).
4. Choose a product, enter a quantity and an email, and place a **test order**.
5. To inspect services, run `docker compose ps`. To watch queue processing, run `docker compose logs -f storefront order inventory-worker order-worker`.
6. Stop with `docker compose down`. The named volumes keep the orders and stock for the next run. `docker compose down -v` removes this demo data and restores the initial catalog and stock on the next start.

Only the storefront port is published. The four backend services communicate over the private Compose network. The browser reaches Product and Order through the storefront's `/api/` reverse proxy.

## Run the integration test without Docker

With Python 3.12 installed:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest -q
```

The integration test starts all four HTTP APIs on temporary local ports in direct-call mode. It checks a confirmed order, stock reduction, the receipt record, repeated checkout, key conflict, and insufficient stock. The Docker Compose run exercises the separate EventBridge/SQS worker flow.

## Run the same app on local Kubernetes with Helm

This step follows the trainer's local-cluster practice. Enable Kubernetes in Docker Desktop, select its context (`kubectl config use-context docker-desktop`), and make sure `kubectl get nodes` works. Build the five images into Docker Desktop's image store:

```powershell
foreach ($service in 'product','inventory','order','notification') {
  docker build --build-arg SERVICE=$service -t "retail-${service}:local" backend
}
docker build -t retail-storefront:local frontend
helm lint deploy/helm/retail
helm template retail deploy/helm/retail
helm upgrade --install retail deploy/helm/retail --namespace retail --create-namespace --wait
kubectl -n retail port-forward svc/retail-storefront 8080:8080
```

Open [http://localhost:8080](http://localhost:8080). In another terminal, run `kubectl -n retail get pods,svc,pvc` and `helm -n retail history retail`. The chart keeps backend Services private (`ClusterIP`) and uses local persistent claims for the four SQLite databases; the local cluster needs a default StorageClass. This chart deliberately uses one replica per SQLite-backed service. Do not scale those services until the managed data stores replace SQLite. To remove the demo release, run `helm -n retail uninstall retail`; PVCs may remain for the local test data.

The chart's `values.yaml` holds the images, port numbers, service addresses, resources, and replica count. Helm renders `templates/` into ordinary Kubernetes manifests and tracks each release revision. Use `helm upgrade --install` for this chart; applying the template files directly with `kubectl apply` will not resolve `{{ ... }}` expressions. [Helm chart guide](https://helm.sh/docs/topics/charts/)

## Repository map

| Path | Purpose |
| --- | --- |
| `frontend/` | Static storefront and Nginx API proxy |
| `backend/services/product.py` | Product catalog API |
| `backend/services/inventory.py` | Stock and idempotent reservation API |
| `backend/services/order.py` | Checkout and order status API |
| `backend/services/notification.py` | Idempotent notification record API |
| `compose.yaml` | Local containers, private network, and persistent demo data |
| `deploy/helm/retail/` | Local and cloud Kubernetes chart, ConfigMaps, probes, HPA, and metrics dashboard |
| `docs/service-map.md` | Current local event flow and planned AWS event, permission, and network paths |
| `tests/` | End-to-end HTTP flow test |
| `.github/workflows/app-ci.yml` | App tests and image builds on PRs; no Terraform apply |
| `.github/workflows/deploy-dev.yml` | Build immutable ECR images and deploy to EKS from protected `main` using GitHub OIDC |
| `deploy/aws/render_values.py` | Turn Terraform SSM config into cloud Helm values and a per-release schema Job |
| `deploy/aws/run-vpc.sh` | Private VPC deployment, smoke test, rollback, and failure demonstration |

## AWS deployment path

The private infrastructure repository provisions the VPC, EKS, RDS MySQL, ElastiCache, DynamoDB, EventBridge, SQS, ECR, IAM, and supporting resources. Cloud engineers review Terraform there and trigger its GitHub Actions workflow, which assumes a separate infrastructure role through OIDC. The app repo receives only a scoped GitHub OIDC deploy role and a non-secret SSM deployment configuration. Merging an approved app PR to `main` builds five commit-tagged images and uses Helm to deploy them. Source code releases do **not** run Terraform.

On EKS, Product reads MySQL with a Redis cache, Order stores orders in a separate MySQL schema, Inventory uses DynamoDB transactions, and Notification records status updates in DynamoDB. Order, Inventory, and Notification workers consume their own SQS queues. The Storefront is the only workload behind the ALB; internal APIs use `ClusterIP` Services. The full [cloud service map](docs/service-map.md) shows each call and event. The GitHub workflow requires the `dev` environment variables `AWS_REGION` and `AWS_DEPLOY_ROLE_ARN` after the Terraform apply and platform setup.

Every cloud release runs an idempotent, version-recorded schema Job before Helm. It creates scoped SQL users, two schemas, catalog rows, and initial stock without resetting existing stock. Later schema changes need a backward-compatible migration step. A CIDR-restricted ALB can be used for a temporary HTTP demo; a hostname and ACM certificate are needed for the intended HTTPS route. Do not send real customer data through the unauthenticated demo.

## Current limits

The four SQLite files are **local test substitutes**. Moto provides local EventBridge and SQS APIs; no AWS account or Terraform is used. Notification is a local receipt record, not a real email, and no payment is collected. The APIs have no customer authentication, so this is for local development only and must not be exposed publicly as a production shop.

The cloud path has code and configuration, but no live AWS end-to-end proof yet. The initial AWS OIDC provider and infrastructure role still need one-time creation in the AWS Console. GitHub uses OIDC for AWS API calls and starts private-subnet CodeBuild projects for Helm; the EKS API stays restricted. The app does not process payments or send actual email. Schema version 1 is recorded, but future schema changes still require explicit migration functions and compatibility review. The order/event write path uses an explicit retry rather than a transactional outbox; that remains a reliability improvement after the first cloud run. Terraform changes have their own reviewed workflow in the separate infrastructure repository.
