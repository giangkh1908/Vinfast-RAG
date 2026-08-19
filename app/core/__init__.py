"""
app/core — Enterprise Domain Modules:
- `storage`: Database (Neon Postgres), Session Store, Multi-tier Cache (Redis).
- `telemetry`: Observability, Request Metrics, Kafka Cloud Producer, HTML Email Alerting.
- `rag`: Knowledge Base Hybrid Search (Qdrant) and Dynamic Prompt Registry.
- `security`: Token-Bucket Rate Limiter & Concurrency Guard.
"""

from app.core import rag, security, storage, telemetry

__all__ = [
    "storage",
    "telemetry",
    "rag",
    "security",
]
