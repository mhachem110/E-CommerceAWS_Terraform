"""One-time database schemas, scoped users, and demo catalog for an EKS release."""

import os

import boto3
import pymysql

from services.cloud_data import secret
from services.product import PRODUCTS


def main():
    root = secret(os.environ["MYSQL_ROOT_SECRET_ARN"])
    product = secret(os.environ["PRODUCT_DB_SECRET_ARN"])
    order = secret(os.environ["ORDER_DB_SECRET_ARN"])
    connection = pymysql.connect(
        host=os.environ["MYSQL_HOST"],
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=root["username"],
        password=root["password"],
        autocommit=False,
        charset="utf8mb4",
        ssl_ca=os.getenv("MYSQL_SSL_CA", "/app/certs/global-bundle.pem"),
        ssl_verify_cert=True,
        ssl_verify_identity=True,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute("CREATE DATABASE IF NOT EXISTS retail_product CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
            cursor.execute("CREATE DATABASE IF NOT EXISTS retail_order CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
            cursor.execute("""CREATE TABLE IF NOT EXISTS retail_product.products (
                id VARCHAR(64) PRIMARY KEY, name VARCHAR(255) NOT NULL,
                description TEXT NOT NULL, price_cents INT NOT NULL,
                icon VARCHAR(16) NOT NULL
            )""")
            cursor.execute("""CREATE TABLE IF NOT EXISTS retail_order.orders (
                id VARCHAR(36) PRIMARY KEY,
                idempotency_key VARCHAR(100) NOT NULL UNIQUE,
                product_id VARCHAR(64) NOT NULL,
                product_name VARCHAR(255) NOT NULL,
                quantity INT NOT NULL,
                unit_price_cents INT NOT NULL,
                total_cents INT NOT NULL,
                email VARCHAR(254) NOT NULL,
                status VARCHAR(20) NOT NULL,
                notification_status VARCHAR(20) NOT NULL,
                reason VARCHAR(255) NULL,
                created_at VARCHAR(40) NOT NULL,
                INDEX (created_at)
            )""")
            cursor.executemany(
                "INSERT IGNORE INTO retail_product.products (id, name, description, price_cents, icon) VALUES (%s, %s, %s, %s, %s)",
                PRODUCTS,
            )
            for credentials, database, privileges in (
                (product, "retail_product", "SELECT"),
                (order, "retail_order", "SELECT, INSERT, UPDATE"),
            ):
                username = credentials["username"]
                if username not in ("product_app", "order_app"):
                    raise ValueError("Unexpected database user")
                quoted_user = connection.escape(username)
                cursor.execute(f"CREATE USER IF NOT EXISTS {quoted_user}@'%' IDENTIFIED BY %s", (credentials["password"],))
                cursor.execute(f"ALTER USER {quoted_user}@'%' IDENTIFIED BY %s", (credentials["password"],))
                cursor.execute(f"GRANT {privileges} ON {database}.* TO {quoted_user}@'%'")
        connection.commit()
    finally:
        connection.close()
    stock = boto3.resource("dynamodb").Table(os.environ["STOCK_TABLE"])
    for product_id, quantity in (("coffee-mug", 10000), ("canvas-tote", 8), ("desk-lamp", 4)):
        try:
            stock.put_item(
                Item={"product_id": product_id, "available": quantity},
                ConditionExpression="attribute_not_exists(product_id)",
            )
        except stock.meta.client.exceptions.ConditionalCheckFailedException:
            pass
    print("MySQL schemas and application users are ready", flush=True)


if __name__ == "__main__":
    main()
