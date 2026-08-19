"""
app/core/email_alert.py — Incident Email Alerting & System Alerts Engine.

Nhiệm vụ:
1. Quản lý bảng `system_alerts` trong PostgreSQL Neon (Lưu toàn bộ Warning & Critical).
2. Gửi Email thông báo khẩn cấp (HTML Template thương hiệu VinFast) khi phát sinh sự cố CRITICAL.
3. Cơ chế Cooldown (chống spam hòm thư, tối đa 1 email mỗi 10 phút cho cùng 1 loại sự cố).
"""

import asyncio
import html
import json
import logging
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import aiosmtplib

from app.config import settings
from app.core.storage.db import get_pool, run_with_db_retry
from app.schemas import SYSTEM_ALERTS_SCHEMA_SQL

logger = logging.getLogger("bds.alerts")

_SCHEMA_SQL = SYSTEM_ALERTS_SCHEMA_SQL

_alerts_schema_ready = False
_ensure_lock = asyncio.Lock()

# Bộ nhớ đệm Cooldown: {alert_type: last_sent_timestamp}
_cooldown_tracker: dict[str, float] = {}
COOLDOWN_SECONDS = 600  # 10 phút


async def ensure_alerts_schema() -> None:
    """Khởi tạo bảng system_alerts nếu chưa có."""
    global _alerts_schema_ready
    if _alerts_schema_ready:
        return
    async with _ensure_lock:
        if _alerts_schema_ready:
            return
        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                for stmt in _SCHEMA_SQL.split(";"):
                    s = stmt.strip()
                    if s:
                        await conn.execute(s)
            _alerts_schema_ready = True
            logger.info("System alerts schema ensured.")
        except Exception as e:
            logger.warning("Could not ensure system_alerts schema: %s", e)


def _render_email_html(severity: str, title: str, message: str, details: dict[str, Any]) -> str:
    """Tạo nội dung Email HTML chuyên nghiệp phong cách VinFast."""
    badge_color = "#dc2626" if severity == "CRITICAL" else "#f59e0b"
    time_str = time.strftime("%H:%M:%S - %d/%m/%Y (Giờ VN)")

    details_rows = ""
    for k, v in details.items():
        val_str = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)
        details_rows += f"""
        <tr>
            <td style="padding: 8px 12px; font-weight: bold; color: #475569; border-bottom: 1px solid #e2e8f0; width: 35%;">{html.escape(str(k))}</td>
            <td style="padding: 8px 12px; color: #0f172a; border-bottom: 1px solid #e2e8f0; font-family: monospace;">{html.escape(val_str)}</td>
        </tr>
        """

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f1f5f9; margin: 0; padding: 24px; }}
            .container {{ max-width: 620px; margin: 0 auto; background: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.08); }}
            .header {{ background: #0f172a; padding: 24px; color: #ffffff; }}
            .logo {{ font-size: 18px; font-weight: 800; color: #38bdf8; letter-spacing: 1px; }}
            .badge {{ display: inline-block; background: {badge_color}; color: #ffffff; font-size: 11px; font-weight: 700; padding: 4px 10px; border-radius: 20px; margin-top: 12px; text-transform: uppercase; }}
            .content {{ padding: 24px; color: #1e293b; line-height: 1.6; }}
            .title {{ font-size: 20px; font-weight: 700; color: #0f172a; margin-top: 0; }}
            .msg-box {{ background: #f8fafc; border-left: 4px solid {badge_color}; padding: 14px; border-radius: 4px; margin: 16px 0; font-size: 15px; color: #334155; }}
            .table-container {{ margin-top: 20px; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; }}
            table {{ width: 100%; border-collapse: collapse; }}
            .footer {{ background: #f8fafc; padding: 16px 24px; font-size: 12px; color: #64748b; text-align: center; border-top: 1px solid #e2e8f0; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <div class="logo">⚡ VINFAST AI OBSERVABILITY</div>
                <div class="badge">🚨 {severity} INCIDENT ALERT</div>
            </div>
            <div class="content">
                <h2 class="title">{html.escape(title)}</h2>
                <div class="msg-box">
                    <strong>Chi tiết thông báo:</strong><br>
                    {html.escape(message)}
                </div>
                <p style="font-size: 13px; color: #64748b; margin-bottom: 8px;">
                    ⏱️ <strong>Thời gian ghi nhận:</strong> {time_str}
                </p>
                {f'<div class="table-container"><table>{details_rows}</table></div>' if details_rows else ""}
            </div>
            <div class="footer">
                Hệ thống giám sát tự động VinFast Chatbot • Cảnh báo này được gửi tự động qua Kafka Cloud & SMTP Dispatcher.
            </div>
        </div>
    </body>
    </html>
    """


async def send_email_alert(
    severity: str,
    title: str,
    message: str,
    details: dict[str, Any] | None = None,
    alert_type: str = "general",
) -> bool:
    """Gửi email cảnh báo khẩn cấp tới Quản trị viên (có kiểm tra Cooldown)."""
    if not settings.alert_email_enabled:
        return False

    now = time.monotonic()
    last_sent = _cooldown_tracker.get(alert_type, 0.0)
    if (now - last_sent) < COOLDOWN_SECONDS:
        logger.info(
            "Alert %s is in cooldown (%.1fs remaining). Suppressing email.",
            alert_type,
            COOLDOWN_SECONDS - (now - last_sent),
        )
        return False

    details = details or {}
    subject = f"[VinFast AI - {severity}] {title}"

    msg = MIMEMultipart("alternative")
    msg["From"] = settings.smtp_user
    msg["To"] = settings.alert_email_recipient
    msg["Subject"] = subject

    html_content = _render_email_html(severity, title, message, details)
    msg.attach(MIMEText(message, "plain", "utf-8"))
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            start_tls=True,
            username=settings.smtp_user,
            password=settings.smtp_password,
            timeout=15,
        )
        _cooldown_tracker[alert_type] = now
        logger.info("Successfully dispatched incident email alert: %s to %s", title, settings.alert_email_recipient)
        return True
    except Exception as e:
        logger.error("Failed to send incident alert email: %s", e)
        return False


async def record_alert_direct(payload: dict[str, Any]) -> None:
    """Lưu cảnh báo vào DB và gửi email nếu là CRITICAL (Dùng cho Fallback và Worker)."""
    await ensure_alerts_schema()

    alert_type = str(payload.get("alert_type", "UNKNOWN"))
    severity = str(payload.get("severity", "WARNING")).upper()
    title = str(payload.get("title", "Cảnh báo hệ thống"))
    message = str(payload.get("message", ""))
    details = payload.get("details", {})

    email_sent = False
    if severity == "CRITICAL":
        email_sent = await send_email_alert(severity, title, message, details, alert_type)

    async def _insert():
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO system_alerts (alert_type, severity, title, message, details, email_sent)
                VALUES ($1, $2, $3, $4, $5::jsonb, $6)
                """,
                alert_type,
                severity,
                title,
                message,
                json.dumps(details, ensure_ascii=False),
                email_sent,
            )

    try:
        await run_with_db_retry(_insert)
    except Exception as e:
        logger.error("Failed to record alert to database: %s", e)
