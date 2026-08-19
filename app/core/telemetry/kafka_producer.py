"""
app/core/kafka_producer.py — Asynchronous Kafka Event Producer with Fail-safe Fallback.

Bắn event bất đồng bộ vào 2 Kafka Topics:
1. `vinfast.telemetry`: Ghi log chat turn, tokens, cost, latency.
2. `vinfast.alerts`: Bắn sự kiện cảnh báo sự cố hệ thống (Spam 429, AI Error 500, Cost spike).
"""

import asyncio
import json
import logging
import ssl
from typing import Any, Optional

from aiokafka import AIOKafkaProducer

from app.config import settings

logger = logging.getLogger("bds.kafka")


class KafkaProducerService:
    _instance: Optional["KafkaProducerService"] = None
    _lock = asyncio.Lock()

    def __init__(self):
        self._producer: AIOKafkaProducer | None = None
        self._started = False

    @classmethod
    async def get_instance(cls) -> "KafkaProducerService":
        if cls._instance is None:
            async with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
                    if settings.kafka_enabled:
                        await cls._instance.start()
        return cls._instance

    async def start(self) -> None:
        if self._started or not settings.kafka_enabled:
            return

        try:
            # Bỏ qua SSL verification cho Aiven Certificate
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE

            self._producer = AIOKafkaProducer(
                bootstrap_servers=settings.kafka_bootstrap_servers,
                security_protocol="SASL_SSL",
                sasl_mechanism="SCRAM-SHA-256",
                sasl_plain_username=settings.kafka_sasl_username,
                sasl_plain_password=settings.kafka_sasl_password,
                ssl_context=ssl_ctx,
                request_timeout_ms=5000,
                retry_backoff_ms=500,
            )
            await self._producer.start()
            self._started = True
            logger.info("Kafka Producer successfully connected to Aiven Kafka Cloud!")
        except Exception as e:
            logger.warning(
                "Could not connect to Kafka Cloud (%s). Falling back to direct in-process handling.",
                e,
            )
            self._producer = None
            self._started = False

    async def stop(self) -> None:
        if self._producer and self._started:
            try:
                await self._producer.stop()
            except Exception:
                pass
            self._started = False

    async def send_telemetry(self, payload: dict[str, Any]) -> bool:
        """Gửi telemetry record vào topic vinfast.telemetry."""
        if not self._started or not self._producer:
            # Fallback ghi trực tiếp DB
            from app.core.telemetry.telemetry import log_metric_background

            log_metric_background(payload)
            return False

        try:
            msg = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            await self._producer.send(settings.kafka_telemetry_topic, msg)
            return True
        except Exception as e:
            logger.error("Failed to send telemetry to Kafka: %s. Using fallback.", e)
            from app.core.telemetry.telemetry import log_metric_background

            log_metric_background(payload)
            return False

    async def send_alert(
        self,
        alert_type: str,
        severity: str,
        title: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> bool:
        """
        Gửi cảnh báo sự cố vào topic vinfast.alerts.
        severity: 'WARNING' (chỉ lưu Dashboard) | 'CRITICAL' (Lưu Dashboard + Gửi Email)
        """
        payload = {
            "alert_type": alert_type,
            "severity": severity.upper(),
            "title": title,
            "message": message,
            "details": details or {},
        }

        if not self._started or not self._producer:
            from app.core.telemetry.email_alert import record_alert_direct

            asyncio.create_task(record_alert_direct(payload))
            return False

        try:
            msg = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            await self._producer.send(settings.kafka_alerts_topic, msg)
            return True
        except Exception as e:
            logger.error("Failed to send alert to Kafka: %s. Using direct fallback.", e)
            from app.core.telemetry.email_alert import record_alert_direct

            asyncio.create_task(record_alert_direct(payload))
            return False


def produce_telemetry_bg(payload: dict[str, Any]) -> None:
    """Helper gọi background task không block coroutine hiện tại."""

    async def _task():
        try:
            producer = await KafkaProducerService.get_instance()
            await producer.send_telemetry(payload)
        except Exception as e:
            logger.warning("produce_telemetry_bg error: %s. Using direct DB fallback.", e)
            from app.core.telemetry.telemetry import log_metric_background

            log_metric_background(payload)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_task())
    except RuntimeError:
        pass


def produce_alert_bg(
    alert_type: str,
    severity: str,
    title: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> None:
    """Helper gọi background task bắn cảnh báo."""

    async def _task():
        try:
            producer = await KafkaProducerService.get_instance()
            await producer.send_alert(alert_type, severity, title, message, details)
        except Exception as e:
            logger.warning("produce_alert_bg error: %s. Using direct alert fallback.", e)
            from app.core.telemetry.email_alert import record_alert_direct

            await record_alert_direct(
                alert_type=alert_type,
                severity=severity,
                title=title,
                message=message,
                details=details,
            )

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_task())
    except RuntimeError:
        pass
