"""Version helpers — build version (git), prompt hash, data snapshot id (PG/manifest).

Tách từ decision.py để models/log_builder dùng chung, tránh import vòng.
"""

import hashlib
import json
import logging
import os
import subprocess
import threading
from pathlib import Path

from app.config import settings

logger = logging.getLogger("bds.decision")

REPO_ROOT = Path(__file__).resolve().parents[3]

_cached_build_version = None
_cached_data_snapshot = None


def _get_build_version() -> str:
    global _cached_build_version
    if _cached_build_version is not None:
        return _cached_build_version
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(REPO_ROOT),
        )
        _cached_build_version = result.stdout.strip() or "unknown"
    except Exception:
        _cached_build_version = "unknown"
    return _cached_build_version


def _get_prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]


def _get_data_snapshot_id() -> str:
    """Read active data version. Ưu tiên env DATA_SNAPSHOT_ID (0ms), sau đó
    fallback PG ingest_version (chậm ~15s từ VN → Neon, nên warm up nền)."""
    global _cached_data_snapshot
    if _cached_data_snapshot is not None:
        return _cached_data_snapshot

    env_snap = os.environ.get("DATA_SNAPSHOT_ID", "").strip()
    if env_snap:
        _cached_data_snapshot = env_snap
        return _cached_data_snapshot

    try:
        import psycopg2

        pg_url = settings.postgres_url.replace("+asyncpg", "")
        conn = psycopg2.connect(pg_url, connect_timeout=5)
        cur = conn.cursor()
        cur.execute("SELECT version, created_at FROM ingest_version WHERE is_current LIMIT 1")
        row = cur.fetchone()
        conn.close()
        if row:
            ver, created_at = row
            ts = created_at.strftime("%Y-%m-%d") if created_at else ""
            _cached_data_snapshot = f"{ver}_{ts}"
            return _cached_data_snapshot
    except Exception:
        pass

    manifest = REPO_ROOT / "data" / "clean" / "v1" / "_manifest.json"
    if manifest.exists():
        try:
            m = json.loads(manifest.read_text(encoding="utf-8"))
            _cached_data_snapshot = m.get("version", "v1") + "_" + m.get("created_at", "")[:10]
            return _cached_data_snapshot
        except Exception:
            pass
    _cached_data_snapshot = "unknown"
    return _cached_data_snapshot


def _warm_snapshot_cache() -> None:
    """Warm cache nền để request đầu tiên không bị block ~15s (PG round-trip)."""
    if _cached_data_snapshot is not None:
        return
    threading.Thread(target=_get_data_snapshot_id, daemon=True).start()
