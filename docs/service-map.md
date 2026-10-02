# Service connections before infrastructure

This map connects each application service to its local test dependency and its AWS resource. The AWS resources are defined in the separate `Retail-Platform-Infra` repository; they have not been applied to an AWS account yet.

The Docker Compose deployment and a complete test order have been verified on this machine. A live local Kubernetes deployment and the AWS path have not yet been verified.

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
                Order → Product Service over HTTP; EventBridge → SQS → workers
```

Each Deployment gives its Pods `app.kubernetes.io/name` and `app.kubernetes.io/instance` labels. Its Kubernetes Service selects those same labels. The Service name gives callers a stable DNS address even when a Pod is replaced and its IP changes. Our [Helm workload template](../deploy/helm/retail/templates/workloads.yaml) already creates a `ClusterIP` Service for each of the five workloads. The browser has no direct route to the four backend Services. [Kubernetes Service documentation](https://kubernetes.io/docs/concepts/services-networking/service/)

| Caller | Stable in-cluster destination | Port | Reason |
| --- | --- | --- | --- |
| ALB Ingress | `retail-storefront` | 8080 | Deliver the customer page |
| Storefront | `retail-product`, `retail-order` | 8000 | Proxy browser API requests |
| Order API | `retail-product` | 8000 | Read the product and price before creating an order |
| Workers | AWS EventBridge, SQS, DynamoDB, SNS | HTTPS 443 | Publish and process events; SNS is used by the Notification worker only |

The worker-to-queue connections use AWS API endpoints, not Kubernetes Services. All API Services remain internal to the cluster.

The cloud Helm chart creates **one** public ALB Ingress naming only the storefront Service. The AWS Load Balancer Controller and its Pod Identity must be installed first. The Ingress uses `ingressClassName: alb` and IP targets, so the storefront Service stays `ClusterIP`. Terraform supplies a restricted source CIDR. When an ACM certificate ARN is supplied, the Ingress enables HTTPS on 443 and redirects HTTP to HTTPS. A public hostname and DNS record are still needed for the complete HTTPS path. [AWS ALB ingress guidance](https://docs.aws.amazon.com/eks/latest/userguide/alb-ingress.html)

The AWS Load Balancer Controller is a platform component; the application's Helm release will own its Ingress rule, subject to cloud-engineer review. An Ingress without a matching controller does not create a fallback Classic Load Balancer. A `LoadBalancer` Service is a different approach; we are not using one for the storefront. Installing the controller with Helm and terminating TLS at the ALB with ACM does not make `cert-manager` an automatic requirement. EKS Pod Identity grants AWS API permissions to Kubernetes service accounts; GitHub OIDC is a separate connection for deployment workflows. Kubernetes RBAC separately controls Kubernetes API access. [AWS controller installation](https://docs.aws.amazon.com/eks/latest/userguide/lbc-helm.html), [controller chart defaults](https://github.com/aws/eks-charts/blob/master/stable/aws-load-balancer-controller/values.yaml)

## AWS event route: EventBridge and SQS

| Event | Producer | Route | Consumer and action |
| --- | --- | --- | --- |
| `OrderCreated` | Order Service | EventBridge rule → inventory request SQS queue | Inventory Service polls, conditionally reserves stock in DynamoDB |
| `InventoryReserved` / `InventoryFailed` | Inventory Service | EventBridge rule → order result SQS queue | Order Service polls, sets `CONFIRMED` or `REJECTED` in MySQL |
| `OrderStatusUpdated` | Order worker | EventBridge rule → notification SQS queue | Notification worker stores a DynamoDB record and publishes an SNS update |
| `OrderStatusUpdated` | Order Service | EventBridge rule → lightweight Lambda | Lambda writes a structured audit/metric record for the demo |
| `NotificationRecorded` | Notification Service | EventBridge rule → order result SQS queue | Order worker marks notification status `RECORDED` |

Each SQS queue gets a dead-letter queue. Consumers delete messages only after processing and must tolerate redelivery. The inventory reservation and DynamoDB notification record use the order ID to avoid repeated database changes. The SNS publish is a separate side effect: if the worker publishes and then retries before deleting the SQS message, the demo mailbox can get a duplicate email. SQS does not initiate a connection to a service; workers poll it. The frontend, Product Service, and database resources do not need SQS permissions for this flow.

The optional `NOTIFICATION_EMAIL` setting on the private infrastructure repo creates **one** SNS email subscription. The recipient must click the AWS confirmation link before SNS can deliver messages. It is a shared demo mailbox; the email entered by a shopper is saved with the order but is not a dynamic SNS subscriber. If no email is configured or confirmed, the Notification worker still records the update and the order can reach `notification_status=RECORDED`.

## AWS workload permissions and network paths

| Workload | Intended AWS permissions | Network destination |
| --- | --- | --- |
| Order | Its MySQL app credential; EventBridge `PutEvents`; receive/delete on order result queue | RDS endpoint, EventBridge API, SQS API |
| Inventory | DynamoDB stock/reservation tables; EventBridge `PutEvents`; receive/delete on inventory request queue | DynamoDB API, EventBridge API, SQS API |
| Notification | DynamoDB notification table; EventBridge `PutEvents`; receive/delete on notification queue; publish to the one order-update SNS topic | DynamoDB API, EventBridge API, SQS API, SNS API |
| Product | Read-only MySQL app credential; Redis credential | RDS endpoint, Redis endpoint |
| Storefront | No direct database or queue permission | Product and Order Kubernetes Services |
| Audit Lambda | Resource policy allows the selected EventBridge rule to invoke it; execution role writes audit logs/metrics | CloudWatch APIs as needed |

On EKS, Pod Identity gives each workload short-lived AWS credentials scoped to the resources it uses. EventBridge rules have queue policies that permit only their own rule ARNs to send messages. The dev VPC uses NAT or configured VPC endpoints for HTTPS calls to EventBridge, SQS, DynamoDB, SNS, and Secrets Manager. RDS and Redis accept traffic only from EKS nodes. [AWS SQS network guidance](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/troubleshooting-network-errors.html)

## Data ownership and deployment order

Product and Order use separate MySQL schemas and scoped SQL accounts on a Multi-AZ RDS instance. Inventory owns DynamoDB stock and reservation tables; Notification owns its table. Product reads Redis first, falls back to MySQL on a cache miss or outage, and caches results for 60 seconds. Local SQLite and Moto remain available for offline testing.

1. In AWS account `866934333672`, an administrator updates the existing GitHub OIDC role to trust the **private infrastructure repo**. Cloud engineers set `AWS_INFRA_ROLE_ARN` and restricted `ADMIN_CIDRS` on its `infra-dev` GitHub environment. The target Region is `us-east-1`.
2. Run the private repo's Terraform workflow with `operation=plan`. Review its output and copy `plan_ref`, `plan_sha256`, and `audit_sha256` from the run summary. From the **same commit**, run `operation=apply` with all three values. The workflow fetches and verifies the saved plan and Lambda package before applying; the remote state stays encrypted in S3.
3. The infrastructure workflow starts a private-subnet CodeBuild project to install the AWS Load Balancer Controller, Metrics Server, and Prometheus/Grafana. Terraform installs the EKS Pod Identity and CloudWatch Observability add-ons.
4. Set the Terraform output `github_deploy_role_arn` as `AWS_DEPLOY_ROLE_ARN` in the app repo's protected `dev` environment. Merge a reviewed app PR to `main`; GitHub Actions pushes immutable images to ECR, and a separate private-subnet CodeBuild project runs the schema Job, Helm, and a smoke test.
5. Verify the ALB, private backend Services, complete order event flow, worker logs, DLQs, dashboards, SNS subscription and mailbox, and Helm rollback. Add an ACM certificate and DNS for HTTPS. App-only releases do not run Terraform; infrastructure changes do.
