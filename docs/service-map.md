# Service connections before infrastructure

This map connects each application service to its local test dependency and its AWS resource. The AWS resources are defined in the separate `Retail-Platform-Infra` repository; they have not been applied to an AWS account yet.

The Docker Compose deployment and a complete test order have been verified on this machine. A live local Kubernetes deployment has not yet been verified.

## Working now: local Compose event flow

| From | To | Purpose |
| --- | --- | --- |
| Browser | Storefront only | Public entry point; Nginx proxies `/api/products` and `/api/orders` |
| Order API | Product API | Read product name and price before accepting checkout |
| Order API | Order SQLite | Save a `PENDING` order before publishing an event |
| Order API | Local EventBridge | Publish `OrderCreated` |
| EventBridge rule | Inventory request SQS queue | Route matching order events to Inventory |
| Inventory worker | Inventory SQLite | Reserve stock once per order ID |
| Inventory worker | Local EventBridge | Publish `InventoryReserved` or `InventoryFailed` |
| EventBridge rule | Order result SQS queue | Route inventory results to Order |
| Order worker | Order SQLite | Mark the order `CONFIRMED` or `REJECTED` |
| Order worker | Notification API | Record one receipt after confirmation |
| Each backend | Its own SQLite file | Local test data; no shared database |

Moto runs local EventBridge and SQS API endpoints so the services use the AWS SDK message path without AWS credentials or Terraform. SQS workers poll independently; EventBridge routes events to queues. Notification remains a direct internal HTTP call in this learning stage. The storefront polls the Order API while the event workers finish, then displays the final status. The normal API integration test still uses direct calls to keep it independent of the local emulator.

## Kubernetes traffic path

```text
Local Kubernetes test: browser → kubectl port-forward → storefront Service → storefront Pod

AWS: browser → CIDR-restricted public ALB → storefront Pods
                              ↑
                   Ingress names storefront Service

Inside cluster: storefront → Product / Order Services → their Pods
                Order → Inventory / Notification Services → their Pods
```

Each Deployment gives its Pods `app.kubernetes.io/name` and `app.kubernetes.io/instance` labels. Its Kubernetes Service selects those same labels. The Service name gives callers a stable DNS address even when a Pod is replaced and its IP changes. Our [Helm workload template](../deploy/helm/retail/templates/workloads.yaml) already creates a `ClusterIP` Service for each of the five workloads. The browser has no direct route to the four backend Services. [Kubernetes Service documentation](https://kubernetes.io/docs/concepts/services-networking/service/)

The cloud Helm chart creates **one** public ALB Ingress naming only the storefront Service. The AWS Load Balancer Controller and its Pod Identity must be installed first. The Ingress uses `ingressClassName: alb` and IP targets, so the storefront Service stays `ClusterIP`. Terraform supplies a restricted source CIDR. When an ACM certificate ARN is supplied, the Ingress enables HTTPS on 443 and redirects HTTP to HTTPS. A public hostname and DNS record are still needed for the complete HTTPS path. [AWS ALB ingress guidance](https://docs.aws.amazon.com/eks/latest/userguide/alb-ingress.html)

The AWS Load Balancer Controller is a platform component; the application's Helm release will own its Ingress rule, subject to cloud-engineer review. An Ingress without a matching controller does not create a fallback Classic Load Balancer. A `LoadBalancer` Service is a different approach; we are not using one for the storefront. Installing the controller with Helm and terminating TLS at the ALB with ACM does not make `cert-manager` an automatic requirement. EKS Pod Identity grants AWS API permissions to Kubernetes service accounts; GitHub OIDC is a separate connection for deployment workflows. Kubernetes RBAC separately controls Kubernetes API access. [AWS controller installation](https://docs.aws.amazon.com/eks/latest/userguide/lbc-helm.html), [controller chart defaults](https://github.com/aws/eks-charts/blob/master/stable/aws-load-balancer-controller/values.yaml)

## AWS event route: EventBridge and SQS

| Event | Producer | Route | Consumer and action |
| --- | --- | --- | --- |
| `OrderCreated` | Order Service | EventBridge rule → inventory request SQS queue | Inventory Service polls, conditionally reserves stock in DynamoDB |
| `InventoryReserved` / `InventoryFailed` | Inventory Service | EventBridge rule → order result SQS queue | Order Service polls, sets `CONFIRMED` or `REJECTED` in MySQL |
| `OrderStatusUpdated` | Order Service | EventBridge rule → notification SQS queue | Notification Service polls and records/sends one notification in DynamoDB |
| `OrderStatusUpdated` | Order Service | EventBridge rule → lightweight Lambda | Lambda writes a structured audit/metric record for the demo |
| `NotificationRecorded` | Notification Service | EventBridge rule → order result SQS queue | Order worker marks notification status `RECORDED` |

Each SQS queue gets a dead-letter queue. Consumers must delete messages only after processing, tolerate redelivery, and use the order/event ID to avoid duplicate business effects. SQS does not initiate a connection to a service: workers poll it. The frontend, Product Service, and database resources do not need SQS permissions for this flow.

## AWS workload permissions and network paths

| Workload | Intended AWS permissions | Network destination |
| --- | --- | --- |
| Order | Its MySQL app credential; EventBridge `PutEvents`; receive/delete on order result queue | RDS endpoint, EventBridge API, SQS API |
| Inventory | DynamoDB stock/reservation tables; EventBridge `PutEvents`; receive/delete on inventory request queue | DynamoDB API, EventBridge API, SQS API |
| Notification | DynamoDB notification table; EventBridge `PutEvents`; receive/delete on notification queue | DynamoDB API, EventBridge API, SQS API |
| Product | Read-only MySQL app credential; Redis credential | RDS endpoint, Redis endpoint |
| Storefront | No direct database or queue permission | Product and Order Kubernetes Services |
| Audit Lambda | Resource policy allows the selected EventBridge rule to invoke it; execution role writes audit logs/metrics | CloudWatch APIs as needed |

On EKS, Pod Identity gives each workload short-lived AWS credentials scoped to the resources it uses. EventBridge rules have queue policies that permit only their own rule ARNs to send messages. The dev VPC uses NAT for HTTPS calls to EventBridge, SQS, DynamoDB, and Secrets Manager. RDS and Redis accept traffic only from EKS nodes. [AWS SQS network guidance](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/troubleshooting-network-errors.html)

## Data ownership and deployment order

Product and Order use separate MySQL schemas and scoped SQL accounts on a Multi-AZ RDS instance. Inventory owns DynamoDB stock and reservation tables; Notification owns its table. Product reads Redis first, falls back to MySQL on a cache miss or outage, and caches results for 60 seconds. Local SQLite and Moto remain available for offline testing.

1. An AWS administrator creates the GitHub OIDC provider and infrastructure role once in the AWS Console. Cloud engineers configure the private repo's `infra-dev` GitHub environment, then review and apply Terraform through its OIDC workflow. The workflow initializes encrypted remote state.
2. Establish an approved network path from the deployment runner to the restricted EKS API, then install the AWS Load Balancer Controller and Metrics Server. Terraform installs the EKS Pod Identity and CloudWatch Observability add-ons.
3. Configure the app repo's protected GitHub `dev` environment with the deploy role ARN and region. Merge a reviewed app PR to `main`; GitHub Actions pushes immutable images to ECR, runs first-install data bootstrap, and deploys Helm.
4. Verify the ALB, private backend Services, order event flow, worker logs, DLQs, and Helm rollback. Add an ACM certificate and DNS for HTTPS. App-only releases do not run Terraform; infrastructure changes do.
