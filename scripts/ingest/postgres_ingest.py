#!/usr/bin/env python3
"""
postgres_ingest.py — Ingest postgres CSV vào PostgreSQL (versioned).

Bảng hot (edition, price_list) có cột `version` trong PK → nhiều version tồn tại
song song; active = `ingest_version.is_current=true`. Consumer query qua VIEW
`edition_active` / `price_list_active` (KHÔNG query base table trực tiếp).

`ingest_version`: audit log per-version + active pointer (`is_current`, đúng 1
row, ép bằng partial unique index). `record_manifest` ghi `is_current=false`
(ingest ≠ active); `set_current(version)` flip (dùng cho promote/rollback).

Reads: data/clean/<version>/postgres/{edition,price_list}.csv
Bảo dưỡng KHÔNG lưu DB (chỉ trả link) — xem docs/DATA_SCHEMA_SPEC.md §5.4.

Usage:
    python scripts/ingest/postgres_ingest.py --version v1
"""

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import execute_values

# Chạy trực tiếp (`python scripts/ingest/postgres_ingest.py`) → repo root vào sys.path
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.config import CLEAN_DIR, PG_DSN  # noqa: E402

# DDL versioned: cột `version` trong PK + FK; VIEW active cho consumer.
DDL = """
CREATE TABLE IF NOT EXISTS edition (
    version         TEXT NOT NULL,
    model_id        TEXT NOT NULL,
    edition_id      TEXT NOT NULL,
    model_label     TEXT NOT NULL,
    edition_label   TEXT NOT NULL,
    year_range      TEXT,
    is_active       BOOLEAN DEFAULT true,
    created_at       TIMESTAMPTZ DEFAULT now(),
    updated_at       TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (version, model_id, edition_id)
);

CREATE TABLE IF NOT EXISTS price_list (
    version         TEXT NOT NULL,
    model_id        TEXT NOT NULL,
    edition_id      TEXT NOT NULL,
    price_list_vnd  BIGINT,
    price_promo_vnd BIGINT,
    promo_label     TEXT,
    vat_included    BOOLEAN DEFAULT true,
    battery_included BOOLEAN DEFAULT true,
    valid_from      DATE NOT NULL DEFAULT '1970-01-01',
    valid_to        DATE,
    updated_at      TIMESTAMPTZ DEFAULT now(),
    source_url      TEXT,
    PRIMARY KEY (version, model_id, edition_id, valid_from),
    FOREIGN KEY (version, model_id, edition_id) REFERENCES edition(version, model_id, edition_id)
);

CREATE INDEX IF NOT EXISTS idx_price_active
ON price_list(version, model_id, edition_id) WHERE valid_to IS NULL;

-- Bảo dưỡng KHÔNG lưu DB (chỉ trả link) — xem docs/DATA_SCHEMA_SPEC.md §5.4

CREATE TABLE IF NOT EXISTS ingest_version (
    version                 TEXT PRIMARY KEY,
    created_at              TIMESTAMPTZ DEFAULT now(),
    activated_at            TIMESTAMPTZ,
    prev_version            TEXT,
    repo_commit             TEXT,
    is_current              BOOLEAN DEFAULT false,
    vector_chunks_added     INT,
    vector_chunks_modified  INT,
    vector_chunks_removed   INT,
    pg_rows_upserted        INT,
    rolled_back_at          TIMESTAMPTZ,
    notes                   TEXT
);
-- Đúng 1 version active:
CREATE UNIQUE INDEX IF NOT EXISTS uniq_ingest_current
ON ingest_version(is_current) WHERE is_current;

-- VIEW active cho consumer (retriever / team khác query VIEW, không filter version):
CREATE OR REPLACE VIEW edition_active AS
SELECT * FROM edition WHERE version = (SELECT version FROM ingest_version WHERE is_current LIMIT 1);
CREATE OR REPLACE VIEW price_list_active AS
SELECT * FROM price_list WHERE version = (SELECT version FROM ingest_version WHERE is_current LIMIT 1);

-- car_specs: lookup thông số kỹ thuật (EAV), versioned qua ingest_version column.
-- Consumer nên query VIEW car_specs_active (chỉ trả version đang active).
-- Nhiều version tồn tại song song trong cùng bảng → rollback = đổi is_current.
CREATE TABLE IF NOT EXISTS car_specs (
    id             SERIAL PRIMARY KEY,
    ingest_version TEXT NOT NULL DEFAULT '',
    model_code     TEXT NOT NULL,      -- "VF 8" (MODEL_LABEL, có dấu cách)
    version_name   TEXT,               -- "Eco"|"Plus"|...|NULL (= chung mọi bản)
    version_code   TEXT,               -- NULL (raw không có mã nội bộ)
    spec_category      TEXT NOT NULL,   -- dimension|powertrain|interior|safety|exterior
    spec_category_vn   TEXT,            -- "Kích thước & trọng lượng" (VN label)
    spec_key           TEXT NOT NULL,   -- power_kw|range_km|battery_kwh|length_mm|...
    spec_key_vn        TEXT,            -- "Công suất tối đa" (VN label)
    spec_value         TEXT NOT NULL,   -- "150"|"87.7"|"5" (string)
    spec_unit          TEXT,            -- "kW"|"km"|"kWh"|"mm"|""|NULL
    source_url         TEXT,
    updated_at         TIMESTAMPTZ DEFAULT now()
);
DROP INDEX IF EXISTS uniq_car_specs;
CREATE UNIQUE INDEX IF NOT EXISTS uniq_car_specs ON car_specs
    (ingest_version, model_code, COALESCE(version_code,''), COALESCE(version_name,''), spec_category, spec_key);
CREATE INDEX IF NOT EXISTS idx_car_specs_ingest_version ON car_specs(ingest_version);

-- VIEW active: chỉ trả rows của version đang active (dùng cho consumer query)
CREATE OR REPLACE VIEW car_specs_active AS
SELECT * FROM car_specs
WHERE ingest_version = (SELECT version FROM ingest_version WHERE is_current LIMIT 1);

-- car_colors: màu ngoại thất + phí màu nâng cao (vinfast_color.csv).
-- Giá xe = price_list (giá chuẩn) + color_fee_vnd (nếu màu Nâng cao).
-- model_id dùng mã chuẩn (VF2, VF3, VF8NEW...) giống price_list/edition.
-- Versioned giống car_specs; query qua car_colors_active.
CREATE TABLE IF NOT EXISTS car_colors (
    id             SERIAL PRIMARY KEY,
    ingest_version TEXT NOT NULL DEFAULT '',
    model_id       TEXT NOT NULL,      -- "VF8NEW" (mã chuẩn, giống price_list)
    version_code   TEXT,               -- "HC11V" (mã phiên bản nội bộ)
    version_name   TEXT,               -- "The All New"|"Eco"|...
    color_code     TEXT,               -- "CE33"
    color_name     TEXT,               -- "Starburst Blue"
    color_type     TEXT,               -- "Cơ bản"|"Nâng cao"
    color_fee_vnd  BIGINT,             -- phí màu nâng cao (0 = màu cơ bản)
    interior_code  TEXT,               -- "CI11, CI13" (có thể nhiều)
    interior_name  TEXT,
    source_url     TEXT,
    updated_at     TIMESTAMPTZ DEFAULT now()
);
DROP INDEX IF EXISTS uniq_car_colors;
CREATE UNIQUE INDEX IF NOT EXISTS uniq_car_colors ON car_colors
    (ingest_version, model_id, COALESCE(version_code,''),
     COALESCE(color_code,''), COALESCE(interior_code,''));
CREATE INDEX IF NOT EXISTS idx_car_colors_ingest_version ON car_colors(ingest_version);

CREATE OR REPLACE VIEW car_colors_active AS
SELECT * FROM car_colors
WHERE ingest_version = (SELECT version FROM ingest_version WHERE is_current LIMIT 1);

-- car_options: tuỳ chọn nâng cấp (HUD, AWD, trần kính, lazang...) từ trang
-- configurator. Giá option CỘNG THÊM vào price_list (giá chuẩn) — đã quy về VND.
-- version_code/name NULL = áp dụng mọi bản của model; có giá trị = chỉ bản đó.
CREATE TABLE IF NOT EXISTS car_options (
    id              SERIAL PRIMARY KEY,
    ingest_version  TEXT NOT NULL DEFAULT '',
    model_id        TEXT NOT NULL,      -- "VF7"
    version_code    TEXT,               -- "GC12V" (NULL = mọi bản)
    version_name    TEXT,               -- "Plus"
    option_group    TEXT NOT NULL,      -- wheel|hud|driveTypes|options
    option_name     TEXT,               -- Lazang|HUD|Drive Types|Tùy Chọn
    value_id        TEXT,               -- T023|CR151|D321...
    value_name      TEXT,               -- "Hai cầu (AWD, 2 động cơ)"
    price_extra_vnd BIGINT,             -- phí cộng thêm (VND)
    source_url      TEXT,
    updated_at      TIMESTAMPTZ DEFAULT now()
);
DROP INDEX IF EXISTS uniq_car_options;
CREATE UNIQUE INDEX IF NOT EXISTS uniq_car_options ON car_options
    (ingest_version, model_id, COALESCE(version_code,''), COALESCE(option_group,''), COALESCE(value_id,''));
CREATE INDEX IF NOT EXISTS idx_car_options_ingest_version ON car_options(ingest_version);

CREATE OR REPLACE VIEW car_options_active AS
SELECT * FROM car_options
WHERE ingest_version = (SELECT version FROM ingest_version WHERE is_current LIMIT 1);

-- car_variants: đã thay bằng car_colors + price_list giá chuẩn → bỏ
DROP VIEW IF EXISTS car_variants_active;
DROP TABLE IF EXISTS car_variants;
"""

# DDL nâng cấp ingest_version từ schema cũ (cho migrate-v1 — chỉ thêm cột mới,
# không ALTER edition/price_list vì migrate drop+recreate chúng).
_MIGRATE_INGEST_VERSION_DDL = """
ALTER TABLE ingest_version ADD COLUMN IF NOT EXISTS activated_at   TIMESTAMPTZ;
ALTER TABLE ingest_version ADD COLUMN IF NOT EXISTS is_current     BOOLEAN DEFAULT false;
ALTER TABLE ingest_version ADD COLUMN IF NOT EXISTS rolled_back_at  TIMESTAMPTZ;
CREATE UNIQUE INDEX IF NOT EXISTS uniq_ingest_current
ON ingest_version(is_current) WHERE is_current;
"""

# Migration cho car_specs: bỏ page (nguồn giờ là CSV, không còn số trang PDF)
# View car_specs_active phụ thuộc cột page → drop view trước, drop column, recreate view sau.
_MIGRATE_CAR_SPECS_DDL = """
DROP VIEW IF EXISTS car_specs_active;
ALTER TABLE car_specs DROP COLUMN IF EXISTS page;
CREATE OR REPLACE VIEW car_specs_active AS
SELECT * FROM car_specs
WHERE ingest_version = (SELECT version FROM ingest_version WHERE is_current LIMIT 1);
"""

# Migration cho car_colors: model_code → model_id (đồng bộ định dạng price_list/edition)
_MIGRATE_CAR_COLORS_DDL = """
DROP VIEW IF EXISTS car_colors_active;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name='car_colors' AND column_name='model_code') THEN
        ALTER TABLE car_colors RENAME COLUMN model_code TO model_id;
    END IF;
END $$;
"""


def load_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="|")
        return [row for row in reader]


def to_bool(value: str | None) -> bool:
    return str(value).lower() in {"t", "true", "1", "yes"}


def upsert_edition(conn, version: str, rows: list[dict[str, Any]]) -> int:
    cur = conn.cursor()
    sql = """
    INSERT INTO edition (version, model_id, edition_id, model_label, edition_label,
                         year_range, is_active, created_at, updated_at)
    VALUES %s
    ON CONFLICT (version, model_id, edition_id) DO UPDATE SET
        model_label = EXCLUDED.model_label,
        edition_label = EXCLUDED.edition_label,
        year_range = EXCLUDED.year_range,
        is_active = EXCLUDED.is_active,
        updated_at = EXCLUDED.updated_at
    """
    values = [
        (version, r["model_id"], r["edition_id"], r["model_label"], r["edition_label"],
         r["year_range"], to_bool(r["is_active"]), r["created_at"], r["updated_at"])
        for r in rows
    ]
    execute_values(cur, sql, values)
    conn.commit()
    return len(rows)


def upsert_price_list(conn, version: str, rows: list[dict[str, Any]]) -> int:
    cur = conn.cursor()
    sql = """
    INSERT INTO price_list (version, model_id, edition_id, price_list_vnd, price_promo_vnd,
                            promo_label, vat_included, battery_included, valid_from, valid_to,
                            updated_at, source_url)
    VALUES %s
    ON CONFLICT (version, model_id, edition_id, valid_from) DO UPDATE SET
        price_list_vnd = EXCLUDED.price_list_vnd,
        price_promo_vnd = EXCLUDED.price_promo_vnd,
        promo_label = EXCLUDED.promo_label,
        vat_included = EXCLUDED.vat_included,
        battery_included = EXCLUDED.battery_included,
        valid_to = EXCLUDED.valid_to,
        updated_at = EXCLUDED.updated_at,
        source_url = EXCLUDED.source_url
    """
    values = []
    for r in rows:
        values.append((
            version,
            r["model_id"],
            r["edition_id"],
            int(r["price_list_vnd"]) if r["price_list_vnd"] else None,
            int(r["price_promo_vnd"]) if r["price_promo_vnd"] else None,
            r["promo_label"] or None,
            to_bool(r["vat_included"]),
            to_bool(r["battery_included"]),
            r["valid_from"] or "1970-01-01",  # NOT NULL; coerce empty → sentinel
            r["valid_to"] or None,
            r["updated_at"] or None,
            r["source_url"] or None,
        ))
    execute_values(cur, sql, values)
    conn.commit()
    return len(rows)


def upsert_colors(conn, version: str, rows: list[dict[str, Any]]) -> int:
    """Upsert car_colors cho 1 version: xoá rows cũ + insert mới."""
    if not rows:
        return 0
    cur = conn.cursor()
    cur.execute("DELETE FROM car_colors WHERE ingest_version = %s", (version,))
    sql = """
    INSERT INTO car_colors (ingest_version, model_id, version_code, version_name,
                            color_code, color_name, color_type, color_fee_vnd,
                            interior_code, interior_name, source_url)
    VALUES %s
    """
    values = [
        (version, r["model_id"], r.get("version_code") or None, r.get("version_name") or None,
         r.get("color_code") or None, r.get("color_name") or None,
         r.get("color_type") or None,
         int(r["color_fee_vnd"]) if r.get("color_fee_vnd") else 0,
         r.get("interior_code") or None, r.get("interior_name") or None,
         r.get("source_url") or None)
        for r in rows
    ]
    execute_values(cur, sql, values)
    conn.commit()
    return len(rows)


def upsert_options(conn, version: str, rows: list[dict[str, Any]]) -> int:
    """Upsert car_options cho 1 version: xoá rows cũ + insert mới (giống car_colors)."""
    if not rows:
        return 0
    cur = conn.cursor()
    cur.execute("DELETE FROM car_options WHERE ingest_version = %s", (version,))
    sql = """
    INSERT INTO car_options (ingest_version, model_id, version_code, version_name,
                             option_group, option_name, value_id, value_name,
                             price_extra_vnd, source_url, updated_at)
    VALUES %s
    """
    values = [
        (version, r["model_id"], r.get("version_code") or None, r.get("version_name") or None,
         r.get("option_group") or None, r.get("option_name") or None,
         r.get("value_id") or None, r.get("value_name") or None,
         int(r["price_extra_vnd"]) if r.get("price_extra_vnd") else 0,
         r.get("source_url") or None, r.get("updated_at") or None)
        for r in rows
    ]
    execute_values(cur, sql, values)
    conn.commit()
    return len(rows)


def upsert_specs(conn, version: str, rows: list[dict[str, Any]]) -> int:
    """Upsert car_specs cho 1 version: xoá rows cũ của version này + insert mới.

    Không dùng TRUNCATE (giữ nguyên data version khác) → hỗ trợ rollback.
    """
    if not rows:
        return 0
    cur = conn.cursor()
    cur.execute("DELETE FROM car_specs WHERE ingest_version = %s", (version,))
    sql = """
    INSERT INTO car_specs (ingest_version, model_code, version_name, version_code,
                           spec_category, spec_category_vn, spec_key, spec_key_vn,
                           spec_value, spec_unit, source_url)
    VALUES %s
    """
    values = [
        (version, r["model_code"], r["version_name"] or None, r["version_code"] or None,
         r["spec_category"], r.get("spec_category_vn", ""),
         r["spec_key"], r.get("spec_key_vn", ""),
         r["spec_value"], r["spec_unit"] or None, r["source_url"] or None)
        for r in rows
    ]
    execute_values(cur, sql, values)
    conn.commit()
    return len(rows)


def record_manifest(conn, version: str, version_dir: Path) -> None:
    """Ghi/UPSERT dòng ingest_version cho `version` (is_current=false — ingest ≠ active)."""
    manifest_path = version_dir / "_manifest.json"
    if not manifest_path.exists():
        return
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO ingest_version (version, created_at, activated_at, prev_version, repo_commit,
                                    is_current, vector_chunks_added, vector_chunks_modified,
                                    vector_chunks_removed, pg_rows_upserted, notes)
        VALUES (%s, %s, NULL, %s, %s, false, %s, %s, %s, %s, %s)
        ON CONFLICT (version) DO UPDATE SET
            created_at = EXCLUDED.created_at,
            prev_version = EXCLUDED.prev_version,
            repo_commit = EXCLUDED.repo_commit,
            vector_chunks_added = EXCLUDED.vector_chunks_added,
            vector_chunks_modified = EXCLUDED.vector_chunks_modified,
            vector_chunks_removed = EXCLUDED.vector_chunks_removed,
            pg_rows_upserted = EXCLUDED.pg_rows_upserted,
            notes = EXCLUDED.notes
        """,
        (
            m["version"],
            m["created_at"],
            m.get("prev_version"),
            m.get("repo_commit"),
            m["vector"]["total_added"],
            m["vector"]["total_modified"],
            m["vector"]["total_removed"],
            m["postgres"]["total_rows_upserted"],
            "ingested by scripts/ingest/postgres_ingest.py",
        ),
    )
    conn.commit()


def set_current(conn, version: str, rollback: bool = False) -> None:
    """Flip active version → `version` (cho promote/rollback). Đúng 1 row is_current=true."""
    cur = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    cur.execute("UPDATE ingest_version SET is_current = false")
    cur.execute(
        """UPDATE ingest_version
           SET is_current = true,
               activated_at = COALESCE(activated_at, %s),
               rolled_back_at = CASE WHEN %s THEN %s ELSE rolled_back_at END
           WHERE version = %s""",
        (now, rollback, now, version),
    )
    if cur.rowcount == 0:
        raise RuntimeError(f"version {version} chưa ingest (không có row trong ingest_version)")
    conn.commit()


def run(version: str = "v1", dsn: str = PG_DSN) -> int:
    """Upsert version-tagged edition + price_list + record ingest_version (is_current=false)."""
    version_dir = CLEAN_DIR / version
    pg_dir = version_dir / "postgres"
    if not pg_dir.exists():
        print(f"[postgres_ingest] postgres dir not found: {pg_dir}", file=sys.stderr)
        return 1

    try:
        conn = psycopg2.connect(dsn)
    except Exception as e:
        print(f"[postgres_ingest] cannot connect to Postgres at {dsn}: {e}", file=sys.stderr)
        print("  hint: docker compose up -d", file=sys.stderr)
        return 1

    cur = conn.cursor()
    cur.execute(_MIGRATE_CAR_COLORS_DDL)
    cur.execute(DDL)
    cur.execute(_MIGRATE_CAR_SPECS_DDL)
    conn.commit()

    edition_rows = load_csv(pg_dir / "edition.csv")
    price_rows = load_csv(pg_dir / "price_list.csv")
    specs_rows = load_csv(pg_dir / "specs.csv") if (pg_dir / "specs.csv").exists() else []
    colors_rows = load_csv(pg_dir / "colors.csv") if (pg_dir / "colors.csv").exists() else []
    options_rows = load_csv(pg_dir / "options.csv") if (pg_dir / "options.csv").exists() else []

    n_edition = upsert_edition(conn, version, edition_rows)
    n_price = upsert_price_list(conn, version, price_rows)
    n_specs = upsert_specs(conn, version, specs_rows)
    n_colors = upsert_colors(conn, version, colors_rows)
    n_options = upsert_options(conn, version, options_rows)
    record_manifest(conn, version, version_dir)

    print(f"[postgres_ingest] version={version}  edition={n_edition}  price_list={n_price}  "
          f"car_specs={n_specs}  car_colors={n_colors}  car_options={n_options}  (is_current=false)")
    conn.close()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Ingest postgres CSV into PostgreSQL (versioned).")
    ap.add_argument("--version", default="v1", help="Clean data version")
    ap.add_argument("--dsn", default=PG_DSN, help="PostgreSQL connection string")
    args = ap.parse_args()
    return run(args.version, args.dsn)


if __name__ == "__main__":
    sys.exit(main())
