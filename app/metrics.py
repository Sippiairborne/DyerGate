import logging
from prometheus_client import (
    CollectorRegistry, Counter, Histogram, Gauge,
    generate_latest, CONTENT_TYPE_LATEST,
)
from starlette.responses import Response

logger = logging.getLogger("dyergate.metrics")

REGISTRY = CollectorRegistry()

REQUEST_COUNT = Counter(
    "dyergate_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
    registry=REGISTRY,
)
REQUEST_LATENCY = Histogram(
    "dyergate_request_duration_seconds",
    "Request latency in seconds",
    ["endpoint"],
    registry=REGISTRY,
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)
TOKENS_BILLED = Counter(
    "dyergate_tokens_total",
    "Tokens billed",
    ["direction", "model"],
    registry=REGISTRY,
)
REVENUE_CENTS = Counter(
    "dyergate_revenue_cents_total",
    "Credits consumed (in credit units)",
    ["endpoint"],
    registry=REGISTRY,
)
ACTIVE_CLIENTS = Gauge(
    "dyergate_active_clients",
    "Number of active client accounts",
    registry=REGISTRY,
)
OUTSTANDING_BALANCE = Gauge(
    "dyergate_outstanding_credit_balance",
    "Sum of credit balances held across all clients",
    registry=REGISTRY,
)
RATE_LIMITED = Counter(
    "dyergate_rate_limited_total",
    "Number of requests rejected by the rate limiter",
    ["endpoint"],
    registry=REGISTRY,
)
UPSTREAM_FAILURES = Counter(
    "dyergate_upstream_failures_total",
    "Number of upstream failures",
    ["endpoint"],
    registry=REGISTRY,
)


def metrics_response() -> Response:
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
