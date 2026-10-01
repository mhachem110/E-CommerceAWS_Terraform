# Local walkthrough: follow one order

This is the first learning stage of the retail project. It runs entirely on your computer. It does not create AWS resources or run Terraform.

## Start here

From the repository folder, start Docker Desktop and run:

```powershell
docker compose up --build -d
docker compose ps
```

Open <http://localhost:8080>. Choose a product, enter a quantity and a test email address, and place an order. No payment is collected and no email is sent. `docker compose ps` should show five running containers: storefront, product, order, inventory, and notification.

## What just happened?

```text
Browser
  -> Storefront (Nginx on localhost:8080)
  -> Order Service
       -> Product Service: get the current product and price
       -> its own SQLite database: save a PENDING order
       -> Inventory Service: reserve the requested quantity
            -> its own SQLite database: reduce available stock
       -> its own SQLite database: mark CONFIRMED or REJECTED
       -> Notification Service: record a receipt for a confirmed order
            -> its own SQLite database: save the receipt record
  <- order status shown in the browser
```

The browser also asks Product for the catalog when the page opens. Only the storefront is published to your computer; the four backend services talk over Docker Compose's private network. Each service owns its own local data file. The email address is only stored in the demo order and receipt record.

**Important difference from the final design:** Today Order calls Inventory and Notification directly over HTTP and waits for their answers. There is no EventBridge, SQS, Lambda, RDS, DynamoDB, or ElastiCache in this local run. Those are future stages, not hidden behind the demo.

## See the flow yourself

In a second PowerShell terminal in this folder, watch the backend requests while placing an order in the browser:

```powershell
docker compose logs -f order product inventory notification
```

Press Ctrl+C to stop following logs; this does not stop the app. To check the stock for the coffee mug inside the private Inventory container:

```powershell
docker compose exec inventory python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/inventory/coffee-mug').read().decode())"
```

Run that stock command before and after buying a mug. You should see the available number decrease by the quantity ordered. For a failure example, try ordering more desk lamps than the available stock; the order should be `REJECTED` and stock should stay the same.

You can also inspect the storefront's public API response:

```powershell
Invoke-RestMethod http://localhost:8080/api/products
```

## What comes next?

1. **Docker Compose** proves that the five containers and the customer flow work together locally. This step has been run successfully on this machine.
2. **Local Kubernetes and Helm** will run the same five images as separate Deployments and internal Services. Helm fills in the values in `deploy/helm/retail/values.yaml` and sends ordinary Kubernetes manifests to the local cluster. The repo has a chart, but its live deployment has not yet been verified. Select a local Kubernetes context before using it; the machine also has an unrelated AKS context.
3. **One local event flow** will replace one direct call with a producer, queue, and consumer so we can observe pending work, processing, retries, and failures. We will verify that behavior before choosing the AWS resources and permissions.
4. **AWS and Terraform** come after the application paths and resource needs are clear.

To stop the local app, run `docker compose down`. Its named volumes keep the demo data. For a fresh demo dataset, run `docker compose down -v` and then start it again; `-v` deletes the local demo data.
