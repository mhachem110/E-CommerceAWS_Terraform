# Local walkthrough: follow an order through EventBridge and SQS

This stage runs on your computer with Docker Compose. Moto supplies local AWS-style EventBridge and SQS APIs, so this does not use AWS credentials, Terraform, or an AWS account. Product, Order, Inventory, and Notification still use separate SQLite files.

## Start the app

Open Command Prompt or PowerShell in the repository folder, then run:

```text
docker compose up --build -d
docker compose ps
```

Open <http://localhost:8080>. The five app containers are joined by two worker containers and the local event service. `events-setup` is a one-time setup container; it exits after creating the local event bus, rules, queues, and dead-letter queues.

## Follow the event path

In a second terminal at the same repository folder, run:

```text
docker compose logs -f --tail=0 storefront order inventory-worker order-worker
```

Place a test order in the browser. The page briefly shows that the order is pending, then checks the Order API until a worker updates it.

```text
Browser → Storefront → Order API → Order SQLite (PENDING)
                                  → EventBridge: OrderCreated
                                      → rule → inventory SQS queue
                                          → Inventory worker polls queue
                                              → Inventory SQLite reserves stock
                                              → EventBridge: InventoryReserved/InventoryFailed
                                                  → rule → order-results SQS queue
                                                      → Order worker polls queue
                                                          → Order SQLite (CONFIRMED/REJECTED)
                                                          → Notification API records receipt if confirmed
Browser ← Storefront ← GET order status ← Order API
```

The log lines make each handoff visible. Look for `OrderCreated`, `InventoryReserved` or `InventoryFailed`, then the Order worker’s final status. SQS does not call the worker; the worker polls SQS. EventBridge matches the event type and sends it to the right queue.

## See stock change

Before and after an order, check coffee mug inventory from inside the Inventory container:

```text
docker compose exec inventory python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/inventory/coffee-mug').read().decode())"
```

One confirmed mug order reduces stock by one. To see the failure path, order 99 desk lamps. The final order should be `REJECTED`, and desk lamp stock should remain unchanged.

To view the setup messages that created the event infrastructure:

```text
docker compose logs events-setup
```

## Which code does what?

| Path | Role in this flow |
| --- | --- |
| `compose.yaml` | Starts the local AWS emulator, setup job, APIs, workers, and storefront |
| `backend/services/order.py` | Saves the order and publishes `OrderCreated` |
| `backend/services/messaging.py` | Creates AWS SDK clients, sends events, and polls/deletes SQS messages |
| `backend/services/setup_local_events.py` | Creates the local event bus, EventBridge rules, SQS queues, and DLQs |
| `backend/services/inventory_worker.py` | Consumes order events, reserves stock, publishes the result |
| `backend/services/order_worker.py` | Consumes the inventory result and updates order status |
| `backend/services/inventory.py` | Owns inventory data and the idempotent stock reservation |
| `frontend/app.js` | Submits checkout and polls the Order API while the order is pending |

## Important limits and reset

The EventBridge and SQS APIs are emulated locally by Moto; this is a learning environment, not AWS. Notification is still a direct service call and records a receipt only. The app uses fake local AWS credentials and the Compose-only `EVENTS_ENDPOINT_URL`; on AWS, the endpoint and credentials will come from AWS configuration and workload identity. Terraform will later create the real bus, rules, queues, DLQs, database resources, network paths, and permissions.

Stop the app with `docker compose down`. Named volumes keep SQLite data. Starting the full Compose project again reruns `events-setup` and recreates the local bus and queues. Use `docker compose down -v` only if you also want to delete the local database data.
