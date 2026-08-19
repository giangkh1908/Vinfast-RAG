"""Prometheus metrics — realtime export cho Grafana/Loki, bổ trợ (không thay thế)
hệ metrics REST/PG trong `app/core/telemetry/telemetry.py`.

Lazy-import: nếu `prometheus-client` chưa được cài hoặc `PROMETHEUS_ENABLED=false`,
mọi hàm thành no-op → không ảnh hưởng hot path.
"""

import logging

logger = logging.getLogger("bds.prometheus")

# ── Lazy singleton registry + metrics ──────────────────────────────────────
_metrics: dict | None = None


def _registry():
    global _metrics
    if _metrics is not None:
        return _metrics
    from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

    reg = CollectorRegistry(auto_describe=False)

    http_requests = Counter("http_requests_total", "HTTP requests", ["method", "path"], registry=reg)
    http_duration = Histogram(
        "http_request_duration_seconds",
        "HTTP request duration",
        ["method", "path"],
        buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
        registry=reg,
    )
    llm_requests = Counter("llm_requests_total", "LLM calls", ["model"], registry=reg)
    llm_latency = Histogram(
        "llm_latency_seconds",
        "LLM call latency",
        ["model"],
        buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0),
        registry=reg,
    )
    llm_cost_usd = Counter("llm_cost_usd_total", "LLM cost (USD)", registry=reg)
    cache_hits = Counter("cache_hits_total", "Cache hits", ["kind"], registry=reg)
    cache_misses = Counter("cache_misses_total", "Cache misses", ["kind"], registry=reg)
    embed_latency = Histogram(
        "embedding_latency_seconds",
        "Embedding call latency",
        buckets=(0.1, 0.5, 1.0, 2.0, 3.0, 5.0, 10.0),
        registry=reg,
    )
    kafka_buffer_depth = Gauge(
        "kafka_consumer_buffer_depth", "Kafka telemetry buffer (records pending flush)", registry=reg
    )
    kafka_batches = Counter("kafka_consumer_batches_total", "Kafka telemetry batches flushed", ["ok"], registry=reg)
    kafka_failures = Counter("kafka_consumer_flush_failures_total", "Kafka flush failures", registry=reg)

    _metrics = {
        "registry": reg,
        "http_requests": http_requests,
        "http_duration": http_duration,
        "llm_requests": llm_requests,
        "llm_latency": llm_latency,
        "llm_cost_usd": llm_cost_usd,
        "cache_hits": cache_hits,
        "cache_misses": cache_misses,
        "embed_latency": embed_latency,
        "kafka_buffer_depth": kafka_buffer_depth,
        "kafka_batches": kafka_batches,
        "kafka_failures": kafka_failures,
    }
    return _metrics


def _enabled() -> bool:
    try:
        from app.config import settings

        return bool(settings.prometheus_enabled)
    except Exception:
        return True


# ── Record helpers (no-op khi tắt / chưa cài) ──────────────────────────────
def record_http(method: str, path: str, duration_s: float) -> None:
    if not _enabled():
        return
    try:
        m = _registry()
        m["http_requests"].labels(method=method, path=path).inc()
        m["http_duration"].labels(method=method, path=path).observe(duration_s)
    except Exception as e:
        logger.debug("prometheus record_http skip: %s", e)


def record_llm(model: str, duration_s: float) -> None:
    if not _enabled():
        return
    try:
        m = _registry()
        m["llm_requests"].labels(model=model).inc()
        m["llm_latency"].labels(model=model).observe(duration_s)
    except Exception as e:
        logger.debug("prometheus record_llm skip: %s", e)


def record_llm_cost(usd: float) -> None:
    if not _enabled() or not usd:
        return
    try:
        _registry()["llm_cost_usd"].inc(usd)
    except Exception as e:
        logger.debug("prometheus record_llm_cost skip: %s", e)


def record_cache(kind: str, hit: bool) -> None:
    if not _enabled():
        return
    try:
        m = _registry()
        (m["cache_hits"] if hit else m["cache_misses"]).labels(kind=kind).inc()
    except Exception as e:
        logger.debug("prometheus record_cache skip: %s", e)


def record_embedding(duration_s: float) -> None:
    if not _enabled():
        return
    try:
        _registry()["embed_latency"].observe(duration_s)
    except Exception as e:
        logger.debug("prometheus record_embedding skip: %s", e)


def set_kafka_buffer(depth: int) -> None:
    if not _enabled():
        return
    try:
        _registry()["kafka_buffer_depth"].set(depth)
    except Exception as e:
        logger.debug("prometheus set_kafka_buffer skip: %s", e)


def record_kafka_batch(ok: bool) -> None:
    if not _enabled():
        return
    try:
        m = _registry()
        m["kafka_batches"].labels(ok=str(ok).lower()).inc()
        if not ok:
            m["kafka_failures"].inc()
    except Exception as e:
        logger.debug("prometheus record_kafka_batch skip: %s", e)


def generate() -> bytes:
    """Trả payload text/plain Prometheus. Nếu tắt → body rỗng (200)."""
    if not _enabled():
        return b"# prometheus disabled\n"
    from prometheus_client import generate_latest

    return generate_latest(_registry()["registry"])
