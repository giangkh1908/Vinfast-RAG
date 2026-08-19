"""
app/schemas/db_schemas.py — Centralized Database DDL Schemas for PostgreSQL.

Tập trung toàn bộ định nghĩa bảng, chỉ mục (indexes) và migration DDL:
1. `chat_sessions`: Quản lý phiên chat & lịch sử hội thoại.
2. `request_metrics`: Bảng lưu trữ Telemetry, Tokens, Cost, Latency, Cache Hit.
3. `system_alerts`: Bảng lưu trữ Sự cố & Cảnh báo hệ thống (Warning & Critical).
4. `prompt_registry`: Bảng quản lý phiên bản System Prompt động.
"""

CHAT_SESSIONS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id      UUID PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    turn_count      INT NOT NULL DEFAULT 0,
    summary         TEXT,
    summary_tokens  INT NOT NULL DEFAULT 0,
    last_message    TEXT,
    meta            JSONB
);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_updated ON chat_sessions(updated_at);
"""

REQUEST_METRICS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS request_metrics (
    id                  BIGSERIAL PRIMARY KEY,
    request_id          TEXT NOT NULL,
    session_id          UUID,
    client_ip           TEXT DEFAULT 'unknown',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    query_text          TEXT,
    intent              TEXT,
    decision            TEXT,
    model_used          TEXT,
    prompt_version      TEXT DEFAULT 'v1.0.0',
    prompt_tokens       INT DEFAULT 0,
    completion_tokens   INT DEFAULT 0,
    total_tokens        INT DEFAULT 0,
    cost_usd            NUMERIC(10, 6) DEFAULT 0.0,
    cost_vnd            NUMERIC(12, 2) DEFAULT 0.0,
    ttft_ms             INT DEFAULT 0,
    total_latency_ms    INT DEFAULT 0,
    cache_hit           BOOLEAN DEFAULT false,
    cache_type          TEXT DEFAULT 'none',
    tools_used          JSONB DEFAULT '[]'::jsonb,
    status_code         INT DEFAULT 200,
    error_message       TEXT
);

ALTER TABLE request_metrics ADD COLUMN IF NOT EXISTS prompt_version TEXT DEFAULT 'v1.0.0';
ALTER TABLE request_metrics ADD COLUMN IF NOT EXISTS client_ip TEXT DEFAULT 'unknown';

CREATE INDEX IF NOT EXISTS idx_req_metrics_created ON request_metrics(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_req_metrics_intent ON request_metrics(intent);
CREATE INDEX IF NOT EXISTS idx_req_metrics_cache ON request_metrics(cache_hit);
CREATE INDEX IF NOT EXISTS idx_req_metrics_session ON request_metrics(session_id);
CREATE INDEX IF NOT EXISTS idx_req_metrics_ip ON request_metrics(client_ip);
CREATE UNIQUE INDEX IF NOT EXISTS idx_req_metrics_req_id ON request_metrics(request_id);
"""

SYSTEM_ALERTS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS system_alerts (
    id              BIGSERIAL PRIMARY KEY,
    alert_type      TEXT NOT NULL,
    severity        TEXT NOT NULL DEFAULT 'WARNING',
    title           TEXT NOT NULL,
    message         TEXT NOT NULL,
    details         JSONB DEFAULT '{}'::jsonb,
    email_sent      BOOLEAN DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_alerts_created ON system_alerts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_severity ON system_alerts(severity);
CREATE INDEX IF NOT EXISTS idx_alerts_type ON system_alerts(alert_type);
"""

PROMPT_REGISTRY_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS prompt_registry (
    id              SERIAL PRIMARY KEY,
    prompt_type     VARCHAR(64) NOT NULL,
    version         VARCHAR(32) NOT NULL,
    template        TEXT NOT NULL,
    description     TEXT DEFAULT '',
    author          VARCHAR(128) DEFAULT 'system',
    is_active       BOOLEAN DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (prompt_type, version)
);

CREATE INDEX IF NOT EXISTS idx_prompt_registry_type ON prompt_registry(prompt_type);
CREATE UNIQUE INDEX IF NOT EXISTS idx_prompt_active_unique ON prompt_registry(prompt_type) WHERE is_active = true;
"""

ALL_DATABASE_SCHEMAS = [
    CHAT_SESSIONS_SCHEMA_SQL,
    REQUEST_METRICS_SCHEMA_SQL,
    SYSTEM_ALERTS_SCHEMA_SQL,
    PROMPT_REGISTRY_SCHEMA_SQL,
]
