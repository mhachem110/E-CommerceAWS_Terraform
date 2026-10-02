"""Small, bounded-cardinality Prometheus metrics for the four HTTP APIs."""

from time import perf_counter

from fastapi import FastAPI, Request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.responses import Response


REQUESTS = Counter(
    "retail_http_requests_total",
    "HTTP requests handled by a retail service",
    ("service", "method", "route", "status"),
)
LATENCY = Histogram(
    "retail_http_request_duration_seconds",
    "Duration of retail HTTP requests",
    ("service", "method", "route"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
)


def instrument(app: FastAPI, service: str) -> None:
    @app.middleware("http")
    async def measure(request: Request, call_next):
        started = perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            route = getattr(request.scope.get("route"), "path", "unmatched")
            if route != "/metrics":
                REQUESTS.labels(service, request.method, route, str(status)).inc()
                LATENCY.labels(service, request.method, route).observe(perf_counter() - started)

    @app.get("/metrics", include_in_schema=False)
    def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
