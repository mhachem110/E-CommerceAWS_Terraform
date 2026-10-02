"""Connections to the managed data services used on EKS."""

import json
import os
from functools import lru_cache

import boto3
import pymysql
import redis


@lru_cache(maxsize=16)
def secret(arn: str) -> dict:
    response = boto3.client("secretsmanager").get_secret_value(SecretId=arn)
    return json.loads(response["SecretString"])


def mysql_connection():
    credentials = secret(os.environ["MYSQL_SECRET_ARN"])
    return pymysql.connect(
        host=os.environ["MYSQL_HOST"],
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=credentials["username"],
        password=credentials["password"],
        database=os.environ["MYSQL_DATABASE"],
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
        connect_timeout=5,
        read_timeout=5,
        write_timeout=5,
        ssl_ca=os.getenv("MYSQL_SSL_CA", "/app/certs/global-bundle.pem"),
        ssl_verify_cert=True,
        ssl_verify_identity=True,
    )


@lru_cache(maxsize=1)
def redis_client():
    credentials = secret(os.environ["REDIS_SECRET_ARN"])
    return redis.Redis(
        host=os.environ["REDIS_HOST"],
        port=int(os.getenv("REDIS_PORT", "6379")),
        ssl=True,
        password=credentials["password"],
        socket_connect_timeout=1,
        socket_timeout=1,
        decode_responses=True,
    )
