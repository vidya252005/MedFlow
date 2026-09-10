from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

HTTP_REQUESTS = Counter(
    "http_requests_total",
    "HTTP requests",
    ["service", "method", "path", "status"],
)
HTTP_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration",
    ["service", "method", "path"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
)
HTTP_ERRORS = Counter("http_errors_total", "HTTP 5xx responses", ["service"])

MESSAGES_CONSUMED = Counter(
    "messages_consumed_total",
    "Kafka messages consumed",
    ["service", "topic"],
)
MESSAGES_FAILED = Counter(
    "messages_failed_total",
    "Kafka messages failed",
    ["service", "topic", "code"],
)
MESSAGES_PRODUCED = Counter(
    "messages_produced_total",
    "Kafka messages produced",
    ["service", "topic"],
)
CONSUMER_LAG = Gauge("consumer_lag", "Approximate consumer lag", ["service", "topic"])

MODEL_INFERENCE = Counter(
    "model_inference_total",
    "Model inference attempts",
    ["model", "status"],
)
MODEL_LATENCY = Histogram(
    "model_inference_latency_seconds",
    "Model inference latency",
    ["model"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.2, 0.5, 1),
)
MODEL_TIMEOUTS = Counter("model_timeout_total", "Model timeouts", ["model"])
MODEL_ERRORS = Counter("model_error_total", "Model errors", ["model"])

QUEUE_DEPTH = Gauge("queue_depth", "In-process worker queue depth", ["service"])
ACTIVE_WORKERS = Gauge("active_workers", "Active in-flight workers", ["service"])

EVENTS_INGESTED = Counter("events_ingested_total", "Accepted events", ["event_type"])
ALERTS_CREATED = Counter("alerts_created_total", "Alerts created", ["severity", "alert_type"])
ALERTS_ACKNOWLEDGED = Counter("alerts_acknowledged_total", "Alerts acknowledged")
PREDICTIONS_GENERATED = Counter("predictions_generated_total", "Predictions generated", ["model", "status"])
DUPLICATES_SUPPRESSED = Counter("duplicates_suppressed_total", "Duplicate events suppressed")
DLQ_MESSAGES = Counter("dlq_messages_total", "Dead-letter messages", ["code"])

PIPELINE_LATENCY = Histogram(
    "pipeline_stage_latency_seconds",
    "Per-stage processing latency",
    ["stage"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2),
)
END_TO_END_LATENCY = Histogram(
    "end_to_end_latency_seconds",
    "Ingest timestamp to alert/decision",
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5),
)
