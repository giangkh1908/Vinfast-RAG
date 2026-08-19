"""Global pytest fixtures for Vivu VinFast AI Assistant tests.

Provides 100% offline mocks for:
- Redis (via fakeredis)
- PostgreSQL asyncpg Pool & Connection
- OpenAI LLM Client
- FastAPI httpx AsyncClient
"""

from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.core.storage.cache import cache
from app.main import app


# ── Disable rate limiting and background telemetry in tests ─────────────────
@pytest.fixture(autouse=True)
def disable_rate_limiting_and_bg_workers(monkeypatch):
    """Disable rate limiting and background worker network calls during testing."""
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    monkeypatch.setattr("app.core.telemetry.kafka_producer.produce_telemetry_bg", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.core.telemetry.kafka_producer.produce_alert_bg", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.core.telemetry.telemetry.log_metric_background", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.core.storage.session_store.ensure_schema", AsyncMock())


# ── Mock Redis Fixture ───────────────────────────────────────────────────────
@pytest.fixture
def mock_redis(monkeypatch):
    """In-memory fakeredis client bound to the global cache singleton."""
    fake_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    fake_sync_client = fakeredis.FakeRedis(decode_responses=True)

    monkeypatch.setattr(cache, "_client", fake_client)
    monkeypatch.setattr(cache, "_sync_client", fake_sync_client)
    monkeypatch.setattr(cache, "_enabled", True)
    monkeypatch.setattr(cache, "_down_until", 0.0)
    monkeypatch.setattr(cache, "_errors", 0)

    yield fake_client

    fake_sync_client.flushall()


# ── Mock DB Connection & Pool ────────────────────────────────────────────────
class MockAcquireContext:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return None


@pytest.fixture
def mock_db_conn():
    """Mock asyncpg connection with customizable returns for fetch/fetchrow/execute."""
    conn = AsyncMock()

    # Default data for queries
    async def fake_fetch(query: str, *args):
        q = query.lower()
        if "car_specs" in q:
            if "distinct model_code" in q:
                return [{"model_code": "VF 9"}, {"model_code": "VF 6"}]
            return [
                {
                    "version_name": "Eco",
                    "version_code": "VF8_ECO",
                    "spec_category": "battery",
                    "spec_key": "battery_kwh",
                    "spec_value": "87.7",
                    "spec_unit": "kWh",
                    "source_url": "https://vinfastauto.com/vn_vi/thong-so-vf8",
                    "page": "1",
                },
                {
                    "version_name": "Plus",
                    "version_code": "VF8_PLUS",
                    "spec_category": "powertrain",
                    "spec_key": "power_kw",
                    "spec_value": "300",
                    "spec_unit": "kW",
                    "source_url": "https://vinfastauto.com/vn_vi/thong-so-vf8",
                    "page": "2",
                },
                {
                    "version_name": "Plus",
                    "version_code": "VF8_PLUS",
                    "spec_category": "interior",
                    "spec_key": "sunroof_type",
                    "spec_value": "Cửa sổ trời toàn cảnh",
                    "spec_unit": "",
                    "source_url": "https://vinfastauto.com/vn_vi/thong-so-vf8",
                    "page": "3",
                },
            ]
        if "price_list_active" in q:
            if "model_id != $1" in q:
                return [
                    {
                        "model_id": "VF9",
                        "edition_id": "Plus",
                        "price_list_vnd": "1999000000",
                        "price_promo_vnd": "1900000000",
                    },
                    {
                        "model_id": "VF6",
                        "edition_id": "Eco",
                        "price_list_vnd": "675000000",
                        "price_promo_vnd": "650000000",
                    },
                ]
            return [
                {
                    "edition_id": "Eco",
                    "price_list_vnd": "1099000000",
                    "price_promo_vnd": "1050000000",
                    "promo_label": "Ưu đãi 50 triệu",
                    "source_url": "https://shop.vinfastauto.com/vn_vi/dat-coc-xe-vf8.html",
                },
                {
                    "edition_id": "Plus",
                    "price_list_vnd": "1270000000",
                    "price_promo_vnd": "1220000000",
                    "promo_label": "Ưu đãi 50 triệu",
                    "source_url": "https://shop.vinfastauto.com/vn_vi/dat-coc-xe-vf8.html",
                },
            ]
        if "car_colors" in q:
            return [
                {
                    "version_name": "Eco",
                    "color_name": "Trắng",
                    "color_type": "Metallic",
                    "color_fee_vnd": 0,
                    "interior_name": "Đen",
                    "source_url": "https://shop.vinfastauto.com/vn_vi/dat-coc-xe-vf8.html",
                },
                {
                    "version_name": "Plus",
                    "color_name": "Đỏ",
                    "color_type": "Metallic",
                    "color_fee_vnd": 10000000,
                    "interior_name": "Nâu",
                    "source_url": "https://shop.vinfastauto.com/vn_vi/dat-coc-xe-vf8.html",
                },
            ]
        if "edition_active" in q:
            return [
                {
                    "model_id": "VF3",
                    "model_label": "VF 3",
                    "edition_id": "Eco",
                    "edition_label": "Eco",
                    "year_range": "2024-2026",
                },
                {
                    "model_id": "VF8",
                    "model_label": "VF 8",
                    "edition_id": "Eco",
                    "edition_label": "Eco",
                    "year_range": "2023-2026",
                },
                {
                    "model_id": "VF8",
                    "model_label": "VF 8",
                    "edition_id": "Plus",
                    "edition_label": "Plus",
                    "year_range": "2023-2026",
                },
            ]
        if "ingest_version" in q:
            return [{"version": "v1.0", "created_at": None}]
        return []

    async def fake_fetchrow(query: str, *args):
        q = query.lower()
        if "ingest_version" in q:
            return {"version": "v1.0"}
        if "session" in q:
            return {"session_id": args[0] if args else "session-1", "summary": "Tóm tắt mẫu", "turn_count": 2}
        return None

    conn.fetch.side_effect = fake_fetch
    conn.fetchrow.side_effect = fake_fetchrow
    conn.execute.return_value = "OK"
    return conn


@pytest.fixture
def mock_db_pool(mock_db_conn, monkeypatch):
    """Mock asyncpg pool that returns mock_db_conn on acquire and delegates queries."""
    pool = MagicMock()
    pool.acquire = MagicMock(side_effect=lambda: MockAcquireContext(mock_db_conn))
    pool.fetch = AsyncMock(side_effect=mock_db_conn.fetch)
    pool.fetchrow = AsyncMock(side_effect=mock_db_conn.fetchrow)
    pool.execute = AsyncMock(side_effect=mock_db_conn.execute)
    pool.get_size.return_value = 5
    pool.get_idle_size.return_value = 5
    pool.get_min_size.return_value = 5
    pool.get_max_size.return_value = 30

    import app.core.storage.db as db_mod

    monkeypatch.setattr(db_mod, "_pool", pool)
    monkeypatch.setattr("app.core.storage.db.get_pool", AsyncMock(return_value=pool))
    monkeypatch.setattr("app.core.storage.session_store.ensure_schema", AsyncMock())
    monkeypatch.setattr(
        "app.core.storage.session_store.get_session", AsyncMock(return_value={"summary": None, "turn_count": 0})
    )
    monkeypatch.setattr("app.core.storage.session_store.touch_session", AsyncMock())
    monkeypatch.setattr("app.core.storage.session_store.update_summary", AsyncMock())
    return pool


# ── Mock LLM Client ─────────────────────────────────────────────────────────
@pytest.fixture
def mock_llm_client(monkeypatch):
    """Mock OpenAI API client for deterministic LLM unit tests."""
    client = MagicMock()
    completions = AsyncMock()

    mock_choice = MagicMock()
    mock_choice.message.content = '{"intent": "price", "model_code": "VF 8", "version": "Plus", "spec_category": null, "reason": "user asks price"}'
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    completions.create.return_value = mock_response
    client.chat.completions = completions

    monkeypatch.setattr("app.agent.llm.get_llm", lambda: client)
    return client


# ── FastAPI AsyncClient Fixture ──────────────────────────────────────────────
@pytest.fixture
async def async_client(mock_redis, mock_db_pool):
    """AsyncClient bound to FastAPI ASGI app for integration testing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
