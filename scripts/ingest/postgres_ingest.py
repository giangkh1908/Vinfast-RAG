#!/usr/bin/env python3
"""
postgres_ingest.py — Ingest postgres CSV into local PostgreSQL.

Reads:
  - data/clean/<version>/postgres/edition.csv
  - data/clean/<version>/postgres/price_list.csv
  - data/clean/<version>/postgres/maintenance_schedule.csv

Creates tables if missing and upserts data.

Usage:
    python scripts/ingest/postgres_ingest.py --version v1
"""

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import execute_values

REPO_ROOT = Path(__file__).resolve().parents[2]
POSTGRES_DIR = REPO_ROOT / "data" / "clean" / "{version}" / "postgres"

DEFAULT_DSN = "postgresql://vivu:vivu@localhost:5432/vivu"

DDL = """
CREATE TABLE IF NOT EXISTS edition (
    model_id        TEXT NOT NULL,
    edition_id      TEXT NOT NULL,
    model_label     TEXT NOT NULL,
    edition_label   TEXT NOT NULL,
    year_range      TEXT,
    is_active       BOOLEAN DEFAULT true,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (model_id, edition_id)
);

CREATE TABLE IF NOT EXISTS price_list (
    model_id            TEXT NOT NULL,
    edition_id          TEXT NOT NULL,
    price_list_vnd      BIGINT,
    price_promo_vnd     BIGINT,
    promo_label         TEXT,
    vat_included        BOOLEAN DEFAULT true,
    battery_included    BOOLEAN DEFAULT true,
    valid_from          DATE,
    valid_to            DATE,
    updated_at          TIMESTAMPTZ DEFAULT now(),
    source_url          TEXT,
    PRIMARY KEY (model_id, edition_id, valid_from),
    FOREIGN KEY (model_id, edition_id) REFERENCES edition(model_id, edition_id)
);

CREATE INDEX IF NOT EXISTS idx_price_active
ON price_list(model_id, edition_id) WHERE valid_to IS NULL;

-- Bảo dưỡng KHÔNG lưu DB (chỉ trả link) — xem docs/DATA_SCHEMA_SPEC.md §5.4

CREATE TABLE IF NOT EXISTS ingest_version (
    version                 TEXT PRIMARY KEY,
    created_at              TIMESTAMPTZ DEFAULT now(),
    prev_version            TEXT,
    repo_commit             TEXT,
    vector_chunks_added     INT,
    vector_chunks_modified  INT,
    vector_chunks_removed   INT,
    pg_rows_upserted        INT,
    notes                   TEXT
);
"""


def load_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="|")
        return [row for row in reader]


def to_bool(value: str | None) -> bool:
    return str(value).lower() in {"t", "true", "1", "yes"}


def upsert_edition(conn, rows: list[dict[str, Any]]) -> int:
    cur = conn.cursor()
    sql = """
    INSERT INTO edition (model_id, edition_id, model_label, edition_label, year_range, is_active, created_at, updated_at)
    VALUES %s
    ON CONFLICT (model_id, edition_id) DO UPDATE SET
        model_label = EXCLUDED.model_label,
        edition_label = EXCLUDED.edition_label,
        year_range = EXCLUDED.year_range,
        is_active = EXCLUDED.is_active,
        updated_at = EXCLUDED.updated_at
    """
    values = [
        (r["model_id"], r["edition_id"], r["model_label"], r["edition_label"],
         r["year_range"], to_bool(r["is_active"]), r["created_at"], r["updated_at"])
        for r in rows
    ]
    execute_values(cur, sql, values)
    conn.commit()
    return len(rows)


def upsert_price_list(conn, rows: list[dict[str, Any]]) -> int:
    cur = conn.cursor()
    sql = """
    INSERT INTO price_list (model_id, edition_id, price_list_vnd, price_promo_vnd, promo_label,
                            vat_included, battery_included, valid_from, valid_to, updated_at, source_url)
    VALUES %s
    ON CONFLICT (model_id, edition_id, valid_from) DO UPDATE SET
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
            r["model_id"],
            r["edition_id"],
            int(r["price_list_vnd"]) if r["price_list_vnd"] else None,
            int(r["price_promo_vnd"]) if r["price_promo_vnd"] else None,
            r["promo_label"] or None,
            to_bool(r["vat_included"]),
            to_bool(r["battery_included"]),
            r["valid_from"] or None,
            r["valid_to"] or None,
            r["updated_at"] or None,
            r["source_url"] or None,
        ))
    execute_values(cur, sql, values)
    conn.commit()
    return len(rows)


def upsert_maintenance(conn, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    cur = conn.cursor()
    sql = """
    INSERT INTO maintenance_schedule (model_id, year, service_type, mileage_km, items, cost_est_vnd, source_url, updated_at)
    VALUES %s
    ON CONFLICT (model_id, year, service_type) DO UPDATE SET
        mileage_km = EXCLUDED.mileage_km,
        items = EXCLUDED.items,
        cost_est_vnd = EXCLUDED.cost_est_vnd,
        source_url = EXCLUDED.source_url,
        updated_at = EXCLUDED.updated_at
    """
    values = [
        (r["model_id"], int(r["year"]), r["service_type"],
         int(r["mileage_km"]) if r["mileage_km"] else None,
         r["items"] if r["items"] else None,
         int(r["cost_est_vnd"]) if r["cost_est_vnd"] else None,
         r["source_url"] or None,
         r["updated_at"] or None)
        for r in rows
    ]
    execute_values(cur, sql, values)
    conn.commit()
    return len(rows)


def record_manifest(conn, version_dir: Path) -> None:
    manifest_path = version_dir / "_manifest.json"
    if not manifest_path.exists():
        return
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO ingest_version (version, created_at, prev_version, repo_commit,
                                     vector_chunks_added, vector_chunks_modified, vector_chunks_removed,
                                     pg_rows_upserted, notes)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
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


def run(version: str = "v1", dsn: str = DEFAULT_DSN) -> int:
    """Upsert edition + price_list + record ingest_version. Trả 0/1."""
    version_dir = REPO_ROOT / "data" / "clean" / version
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

    # Ensure schema
    cur = conn.cursor()
    cur.execute(DDL)
    conn.commit()

    edition_rows = load_csv(pg_dir / "edition.csv")
    price_rows = load_csv(pg_dir / "price_list.csv")

    n_edition = upsert_edition(conn, edition_rows)
    n_price = upsert_price_list(conn, price_rows)
    record_manifest(conn, version_dir)

    print(f"[postgres_ingest] done: edition={n_edition}, price_list={n_price}")
    conn.close()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Ingest postgres CSV into local PostgreSQL.")
    ap.add_argument("--version", default="v1", help="Clean data version")
    ap.add_argument("--dsn", default=DEFAULT_DSN, help="PostgreSQL connection string")
    args = ap.parse_args()
    return run(args.version, args.dsn)


if __name__ == "__main__":
    sys.exit(main())
