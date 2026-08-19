"""
app/core/telemetry — Observability, Request Metrics, Kafka Cloud Producer, and Email Alerts.
"""

from app.core.telemetry.email_alert import (
    ensure_alerts_schema,
    record_alert_direct,
    send_email_alert,
)
from app.core.telemetry.kafka_producer import (
    KafkaProducerService,
    produce_alert_bg,
    produce_telemetry_bg,
)
from app.core.telemetry.telemetry import (
    build_metric_payload,
    calculate_cost,
    ensure_telemetry_schema,
    get_metrics_intents,
    get_metrics_logs,
    get_metrics_overview,
    get_metrics_sessions,
    get_metrics_timeseries,
    get_metrics_top_ips,
    log_metric_background,
    record_metric,
)

__all__ = [
    "record_metric",
    "build_metric_payload",
    "log_metric_background",
    "calculate_cost",
    "ensure_telemetry_schema",
    "get_metrics_overview",
    "get_metrics_timeseries",
    "get_metrics_intents",
    "get_metrics_top_ips",
    "get_metrics_sessions",
    "get_metrics_logs",
    "KafkaProducerService",
    "produce_telemetry_bg",
    "produce_alert_bg",
    "send_email_alert",
    "record_alert_direct",
    "ensure_alerts_schema",
]
