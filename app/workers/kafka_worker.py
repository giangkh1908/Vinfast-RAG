"""
app/workers/kafka_worker.py — Kafka Consumer Worker for Batch Ingestion & Alert Dispatching.

Các nhiệm vụ chính:
1. Lắng nghe topic `vinfast.telemetry`: Gom mẻ 50 logs hoặc mỗi 5 giây -> Batch Insert vào `request_metrics` (Neon DB).
2. Lắng nghe topic `vinfast.alerts`: Xử lý cảnh báo, lưu vào `system_alerts`, gửi Email khẩn cấp nếu CRITICAL.
3. Data Retention Cron: Tự động dọn dẹp log cũ hơn 30 ngày để giữ DB luôn nhẹ.
"""

import asyncio
import json
import logging
import ssl
import uuid
from typing import Any

from aiokafka import AIOKafkaConsumer

from app.config import settings
from app.core.storage.db import get_pool, run_with_db_retry
from app.core.telemetry.email_alert import record_alert_direct
from app.core.telemetry.telemetry import ensure_telemetry_schema

logger = logging.getLogger("bds.kafka_worker")


class KafkaConsumerWorker:
    def __init__(self):
        self._running = False
        self._telemetry_buffer: list[dict[str, Any]] = []
        self._buffer_lock = asyncio.Lock()
        self._flush_interval_seconds = 2
        self._batch_size = 20

    async def _flush_telemetry_batch(self) -> None:
        """Ghi batch telemetry vào bảng request_metrics trong PostgreSQL."""
        async with self._buffer_lock:
            if not self._telemetry_buffer:
                self._set_buffer_metric(0)
                return
            records_to_flush = list(self._telemetry_buffer)
            self._telemetry_buffer.clear()
        self._set_buffer_metric(len(records_to_flush))

        try:
            await ensure_telemetry_schema()
            pool = await get_pool()

            def _to_uuid(val):
                if not val:
                    return None
                try:
                    return uuid.UUID(str(val))
                except (ValueError, TypeError):
                    return None

            records_tuples = [
                (
                    r.get("request_id", ""),
                    _to_uuid(r.get("session_id")),
                    r.get("client_ip", "unknown"),
                    r.get("query_text", ""),
                    r.get("intent", "general"),
                    r.get("decision", "answer"),
                    r.get("model_used", ""),
                    r.get("prompt_version", "v1.0.0"),
                    int(r.get("prompt_tokens", 0)),
                    int(r.get("completion_tokens", 0)),
                    int(r.get("total_tokens", 0)),
                    float(r.get("cost_usd", 0.0)),
                    float(r.get("cost_vnd", 0.0)),
                    int(r.get("ttft_ms", 0)),
                    int(r.get("total_latency_ms", 0)),
                    bool(r.get("cache_hit", False)),
                    r.get("cache_type", "none"),
                    json.dumps(r.get("tools_used") or [], ensure_ascii=False),
                    int(r.get("status_code", 200)),
                    r.get("error_message"),
                )
                for r in records_to_flush
            ]

            async def _batch_insert():
                async with pool.acquire() as conn:
                    await conn.executemany(
                        """
                        INSERT INTO request_metrics (
                            request_id, session_id, client_ip, query_text, intent, decision,
                            model_used, prompt_version, prompt_tokens, completion_tokens, total_tokens,
                            cost_usd, cost_vnd, ttft_ms, total_latency_ms,
                            cache_hit, cache_type, tools_used, status_code, error_message
                        ) VALUES (
                            $1, $2, $3, $4, $5, $6,
                            $7, $8, $9, $10, $11,
                            $12, $13, $14, $15,
                            $16, $17, $18, $19, $20
                        )
                        ON CONFLICT (request_id) DO NOTHING
                        """,
                        records_tuples,
                    )

            await run_with_db_retry(_batch_insert, label="batch_insert_metrics")
            self._record_batch(ok=True)
            logger.info("Successfully flushed batch of %d telemetry records to Neon DB.", len(records_to_flush))
        except Exception as e:
            self._record_batch(ok=False)
            logger.exception("Failed to flush telemetry batch to database: %s", e)

    def _set_buffer_metric(self, depth: int) -> None:
        """Export Kafka consumer buffer depth (Prometheus gauge)."""
        try:
            from app.core.telemetry.prometheus import set_kafka_buffer

            set_kafka_buffer(depth)
        except Exception:
            pass

    def _record_batch(self, ok: bool) -> None:
        """Export Kafka batch flush result (Prometheus counter)."""
        try:
            from app.core.telemetry.prometheus import record_kafka_batch

            record_kafka_batch(ok)
        except Exception:
            pass

    async def _handle_alert_message(self, data: dict[str, Any]) -> None:
        """Xử lý gói tin cảnh báo: lưu bảng system_alerts và bắn Email nếu CRITICAL."""
        alert_type = data.get("alert_type", "UNKNOWN_ALERT")
        severity = data.get("severity", "WARNING").upper()
        title = data.get("title", f"Cảnh báo hệ thống ({severity})")
        message = data.get("message", "")
        details = data.get("details", {})

        try:
            await record_alert_direct(
                alert_type=alert_type,
                severity=severity,
                title=title,
                message=message,
                details=details,
            )
        except Exception as e:
            logger.exception("Failed to process alert message: %s", e)

    async def _periodic_flush_loop(self) -> None:
        """Định kỳ flush buffer theo thời gian nếu chưa đầy 50 records."""
        while self._running:
            try:
                await asyncio.sleep(self._flush_interval_seconds)
                if self._telemetry_buffer:
                    await self._flush_telemetry_batch()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Error in periodic telemetry flush loop: %s", e)

    async def _retention_cleanup_cron(self) -> None:
        """Tự động dọn dẹp data cũ hơn 30 ngày mỗi 24 giờ."""
        while self._running:
            try:
                await asyncio.sleep(86400)  # Mỗi 24 giờ
                retention_days = getattr(settings, "telemetry_retention_days", 30)
                pool = await get_pool()
                async with pool.acquire() as conn:
                    await conn.execute(
                        "DELETE FROM request_metrics WHERE created_at < NOW() - INTERVAL '$1 days'",
                        retention_days,
                    )
                    await conn.execute(
                        "DELETE FROM system_alerts WHERE created_at < NOW() - INTERVAL '$1 days'",
                        retention_days,
                    )
                logger.info("Completed %d-day data retention cleanup.", retention_days)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Data retention cron failed: %s", e)

    async def start(self) -> None:
        """Bắt đầu lắng nghe và tiêu thụ tin nhắn từ Aiven Kafka Cloud."""
        if not settings.kafka_enabled or not settings.kafka_bootstrap_servers:
            logger.info("Kafka is not configured. KafkaConsumerWorker will not start.")
            return

        self._running = True

        ssl_ctx = None
        if "SASL_SSL" in settings.kafka_security_protocol.upper():
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE

        consumer = AIOKafkaConsumer(
            settings.kafka_telemetry_topic,
            settings.kafka_alerts_topic,
            bootstrap_servers=settings.kafka_bootstrap_servers,
            security_protocol=settings.kafka_security_protocol,
            sasl_mechanism=settings.kafka_sasl_mechanism,
            sasl_plain_username=settings.kafka_sasl_username,
            sasl_plain_password=settings.kafka_sasl_password,
            ssl_context=ssl_ctx,
            group_id="vinfast-telemetry-workers",
            auto_offset_reset="latest",
            enable_auto_commit=True,
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        )

        try:
            await consumer.start()
            logger.info(
                "Kafka Consumer Worker started listening on topics: %s, %s",
                settings.kafka_telemetry_topic,
                settings.kafka_alerts_topic,
            )

            flush_task = asyncio.create_task(self._periodic_flush_loop())
            retention_task = asyncio.create_task(self._retention_cleanup_cron())

            try:
                async for msg in consumer:
                    if not self._running:
                        break
                    topic = msg.topic
                    data = msg.value

                    if topic == settings.kafka_telemetry_topic:
                        async with self._buffer_lock:
                            self._telemetry_buffer.append(data)
                            if len(self._telemetry_buffer) >= self._batch_size:
                                asyncio.create_task(self._flush_telemetry_batch())

                    elif topic == settings.kafka_alerts_topic:
                        asyncio.create_task(self._handle_alert_message(data))

            finally:
                flush_task.cancel()
                retention_task.cancel()
                if self._telemetry_buffer:
                    await self._flush_telemetry_batch()
                await consumer.stop()
                logger.info("Kafka Consumer Worker stopped.")

        except Exception as e:
            logger.exception("Kafka Consumer Worker encountered an error: %s", e)

    def stop(self) -> None:
        self._running = False


# Background Task Lifecycle Helper
_worker_instance: KafkaConsumerWorker | None = None
_worker_task: asyncio.Task | None = None


async def start_kafka_worker_background() -> None:
    global _worker_instance, _worker_task
    if _worker_instance is None:
        _worker_instance = KafkaConsumerWorker()
        _worker_task = asyncio.create_task(_worker_instance.start())
        logger.info("Spawned Kafka Consumer Worker background task.")


def stop_kafka_worker_background() -> None:
    global _worker_instance, _worker_task
    if _worker_instance:
        _worker_instance.stop()
    if _worker_task:
        _worker_task.cancel()
    logger.info("Requested shutdown of Kafka Consumer Worker.")
