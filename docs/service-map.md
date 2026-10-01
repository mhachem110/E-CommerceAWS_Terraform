# Service connections before infrastructure

This is the application-first map for the Week 3 project. It separates the working local demo from the AWS event design we will implement later. We will use it to derive Terraform networking and IAM rather than guessing those permissions in advance.

## Working now: local demo

| From | To | Purpose |
| --- | --- | --- |
| Browser | Storefront only | Public entry point; Nginx proxies `/api/products` and `/api/orders` |
| Order | Product | Read product name and price before accepting checkout |
| Order | Inventory | Reserve stock by order ID; retry is idempotent |
| Order | Notification | Record one receipt by order ID after confirmation |
| Each backend | Its own SQLite file | Local test data; no shared database |

The direct Order-to-Inventory and Order-to-Notification HTTP calls are temporary. A failed inventory call leaves an order `PENDING` for a manual retry. A failed notification call leaves its notification status `PENDING` for retry. These limitations make the missing queue/recovery behavior visible instead of pretending that the AWS event path already exists.

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

## Data ownership and the next implementation order

Product and Order will own separate schemas/tables in RDS/Aurora MySQL. Inventory and Notification will own separate DynamoDB tables. Product will add explicit cache read/miss/populate logic for ElastiCache. We will first prove these adapters and the event consumers locally, then define the AWS resources, Helm values, and IAM they actually require. The local SQLite Helm chart is a learning bridge, not the EKS production storage design.
