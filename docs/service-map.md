# Service connections before infrastructure

This is the application-first map for the Week 3 project. It separates the working local demo from the AWS event design we will implement later. We will use it to derive Terraform networking and IAM rather than guessing those permissions in advance.

The HTTP integration test passes. A live Compose or local Kubernetes deployment has not yet been verified on this machine because its Docker engine is off.

## Working now: local demo

| From | To | Purpose |
| --- | --- | --- |
| Browser | Storefront only | Public entry point; Nginx proxies `/api/products` and `/api/orders` |
| Order | Product | Read product name and price before accepting checkout |
| Order | Inventory | Reserve stock by order ID; retry is idempotent |
| Order | Notification | Record one receipt by order ID after confirmation |
| Each backend | Its own SQLite file | Local test data; no shared database |

The direct Order-to-Inventory and Order-to-Notification HTTP calls are temporary. A failed inventory call leaves an order `PENDING` for a manual retry. A failed notification call leaves its notification status `PENDING` for retry. These limitations make the missing queue/recovery behavior visible instead of pretending that the AWS event path already exists.

## Kubernetes traffic path

```text
Local test: browser → kubectl port-forward → storefront Service → storefront Pod

AWS later: browser → public ALB → storefront Pods
                              ↑
                   Ingress names storefront Service

Inside cluster: storefront → Product / Order Services → their Pods
                Order → Inventory / Notification Services → their Pods
```

Each Deployment gives its Pods `app.kubernetes.io/name` and `app.kubernetes.io/instance` labels. Its Kubernetes Service selects those same labels. The Service name gives callers a stable DNS address even when a Pod is replaced and its IP changes. Our [Helm workload template](../deploy/helm/retail/templates/workloads.yaml) already creates a `ClusterIP` Service for each of the five workloads. The browser has no direct route to the four backend Services. [Kubernetes Service documentation](https://kubernetes.io/docs/concepts/services-networking/service/)

For EKS, use **one** public ALB Ingress that names only the storefront Service. Install the AWS Load Balancer Controller and its scoped AWS IAM identity first; then enable the application Ingress after the storefront Service exists. Use `ingressClassName: alb` and `alb.ingress.kubernetes.io/target-type: ip`. With IP targets, the controller discovers the storefront Pods through the Service and registers their Pod IPs with the ALB. This lets the storefront Service remain `ClusterIP`; it does not need a public `NodePort`. Configure public subnet discovery, an ACM certificate, HTTPS on 443, an HTTP-to-HTTPS redirect, and DNS when we build the EKS environment. [AWS ALB ingress guidance](https://docs.aws.amazon.com/eks/latest/userguide/alb-ingress.html)

The AWS Load Balancer Controller is a platform component; the application's Helm release will own its Ingress rule, subject to cloud-engineer review. An Ingress without a matching controller does not create a fallback Classic Load Balancer. A `LoadBalancer` Service is a different approach; we are not using one for the storefront. Installing the controller with Helm and terminating TLS at the ALB with ACM does not make `cert-manager` an automatic requirement. IRSA/OIDC grants AWS API permissions to a Kubernetes service account; Kubernetes RBAC separately controls Kubernetes API access. [AWS controller installation](https://docs.aws.amazon.com/eks/latest/userguide/lbc-helm.html), [controller chart defaults](https://github.com/aws/eks-charts/blob/master/stable/aws-load-balancer-controller/values.yaml)

## Planned AWS route: EventBridge and SQS

| Event | Producer | Route | Consumer and action |
| --- | --- | --- | --- |
| `OrderCreated` | Order Service | EventBridge rule → inventory request SQS queue | Inventory Service polls, conditionally reserves stock in DynamoDB |
| `InventoryReserved` / `InventoryFailed` | Inventory Service | EventBridge rule → order result SQS queue | Order Service polls, sets `CONFIRMED` or `REJECTED` in MySQL |
| `OrderStatusUpdated` | Order Service | EventBridge rule → notification SQS queue | Notification Service polls and records/sends one notification in DynamoDB |
| `OrderStatusUpdated` | Order Service | EventBridge rule → lightweight Lambda | Lambda writes a structured audit/metric record for the demo |

Each SQS queue gets a dead-letter queue. Consumers must delete messages only after processing, tolerate redelivery, and use the order/event ID to avoid duplicate business effects. SQS does not initiate a connection to a service: workers poll it. The frontend, Product Service, and database resources do not need SQS permissions for this flow.

## Permissions and network paths to derive later

| Workload | Intended AWS permissions | Network destination |
| --- | --- | --- |
| Order | MySQL access; EventBridge `PutEvents`; receive/delete on order result queue | RDS endpoint, EventBridge API, SQS API |
| Inventory | DynamoDB inventory table; EventBridge `PutEvents`; receive/delete on inventory request queue | DynamoDB API, EventBridge API, SQS API |
| Notification | DynamoDB notification table; receive/delete on notification queue; eventual email provider permission if selected | DynamoDB API, SQS API |
| Product | MySQL product data; ElastiCache catalog cache | RDS endpoint, Redis endpoint |
| Storefront | No direct database or queue permission | Product and Order Kubernetes Services |
| Audit Lambda | Resource policy allows the selected EventBridge rule to invoke it; execution role writes audit logs/metrics | CloudWatch APIs as needed |

On EKS, give each workload a dedicated AWS identity and only the actions/resources it needs. The SQS queue policies must allow the matching EventBridge rules to send messages. SQS and EventBridge are reached over HTTPS through NAT or the relevant VPC endpoints. A queue itself has no security group; if we use an interface endpoint, its security group must allow the clients' HTTPS traffic. Terraform should follow the selected route and IAM map. [AWS SQS network guidance](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/troubleshooting-network-errors.html)

## Data ownership and implementation order

Product and Order will own separate schemas/tables in RDS/Aurora MySQL. Inventory and Notification will own separate DynamoDB tables. Product will add explicit cache read/miss/populate logic for ElastiCache. We will first prove these adapters and the event consumers locally, then define the AWS resources, Helm values, and IAM they actually require. The local SQLite Helm chart is a learning bridge, not the EKS production storage design.

1. Finish the local app proof: run Compose and then the five-image Helm release on a **local** Kubernetes context. Verify Pod readiness, Service DNS, order flow, and `kubectl port-forward` to the storefront. Do not use the unrelated AKS context configured on this machine.
2. Implement and test the intended database/cache adapters and event consumers with local or test substitutes. Confirm the producer, queue, consumer, retry, and failure behavior before creating AWS resources.
3. Freeze the connection, IAM, and network map above. In the separate restricted infrastructure repository, use reviewed Terraform plans to create EKS, data services, event resources, VPC paths, and controller IAM. Install and verify the AWS Load Balancer Controller.
4. Deploy approved images with Helm and connect the real AWS dependencies. Before enabling the public ALB Ingress, add access control or constrain the demo audience and keep real customer data out of the unauthenticated demo APIs. Verify HTTPS, DNS, health checks, and that the backend Services remain private.
5. Demonstrate a new image release, scaling after SQLite is removed, failure recovery, Helm history/rollback, monitoring, and the complete order event path. App-only releases do not run Terraform; infrastructure changes do.
