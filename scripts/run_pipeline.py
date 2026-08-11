#!/usr/bin/env python3
"""
run_pipeline.py — End-to-end data pipeline.

Chạy đủ bước theo thứ tự cho 1 version:
  data/raw/*.txt + data/raw_pdf/*.txt
    → 1. clean (clean_to_jsonl)      → intermediate/{vector,hot}.jsonl + link_only.json
    → 2. split cold/hot (split_cold_hot) → vector/*.jsonl + postgres/*.csv + _manifest.json
    → 3. parse_pdf_specs → postgres/specs.csv (feature specs từ raw_pdf brochure)
    → 4. embed + ingest Qdrant dense (vector_ingest)
    → 5. BM25 sparse → Qdrant sparse (sparse_ingest)   [bỏ qua nếu --no-sparse]
    → 6. UPSERT PostgreSQL (postgres_ingest)

Specs chỉ lấy từ data/raw_pdf/*.txt (brochure PDF pipe-tables) qua parse_pdf_specs.

Usage:
    python scripts/run_pipeline.py --version v1 --recreate --promote
    python scripts/run_pipeline.py --version v1 --no-sparse  # bỏ BM25
"""

import argparse
import sys
import time
from pathlib import Path

# Chạy trực tiếp (`python scripts/run_pipeline.py`) → đưa repo root vào sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.config import PG_DSN, QDRANT_API_KEY, QDRANT_URL, REPO_ROOT  # noqa: E402

from scripts.clean_data import clean_to_jsonl, split_cold_hot  # noqa: E402
from scripts.clean_data import parse_pdf_specs  # noqa: E402
from scripts.ingest import vector_ingest, sparse_ingest, postgres_ingest  # noqa: E402
from lib import openrouter  # noqa: E402
from scripts import version_manager  # noqa: E402


def _bar(label: str) -> str:
    return f"\n{'=' * 72}\n{label}\n{'=' * 72}"


def preflight(version: str, want_qdrant: bool, want_pg: bool) -> int:
    """Kiểm tra đầu vào trước khi chạy. Trả 0 nếu OK, 1 nếu thiếu."""
    raw = REPO_ROOT / "data" / "raw"
    if not raw.exists() or not any(raw.iterdir()):
        print(f"[preflight] data/raw rỗng hoặc không tồn tại: {raw}", file=sys.stderr)
        return 1

    raw_pdf = REPO_ROOT / "data" / "raw_pdf"
    if not raw_pdf.exists() or not any(raw_pdf.iterdir()):
        print(f"[preflight] data/raw_pdf trống — pipeline sẽ không có spec data")

    if not openrouter.API_KEY:
        print("[preflight] OPENROUTER_API_KEY chưa set trong .env (xem .env.example)",
              file=sys.stderr)
        return 1

    if want_qdrant:
        try:
            from qdrant_client import QdrantClient
            QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY or None).get_collections()
        except Exception as e:  # noqa: BLE001
            print(f"[preflight] không kết nối được Qdrant tại {QDRANT_URL}: {e}",
                  file=sys.stderr)
            print("  hint: docker compose up -d", file=sys.stderr)
            return 1

    if want_pg:
        try:
            import psycopg2
            psycopg2.connect(PG_DSN).close()
        except Exception as e:  # noqa: BLE001
            print(f"[preflight] không kết nối được Postgres tại {PG_DSN}: {e}",
                  file=sys.stderr)
            print("  hint: docker compose up -d", file=sys.stderr)
            return 1

    print(f"[preflight] OK  raw={raw}  qdrant={QDRANT_URL}  pg=…")
    return 0


def _step(idx: str, label: str, fn, *args, **kwargs) -> int:
    print(_bar(f"Bước {idx}: {label}"))
    t0 = time.time()
    rc = fn(*args, **kwargs)
    dt = time.time() - t0
    tag = "PASS" if rc == 0 else f"FAIL (rc={rc})"
    print(f"→ {label}: {tag}  ({dt:.1f}s)")
    return rc


def run(version: str, recreate: bool, no_sparse: bool, commit: str,
       max_len: int = 800, prev: str | None = None, promote: bool = False) -> int:
    want_qdrant = True
    want_pg = True
    if preflight(version, want_qdrant, want_pg) != 0:
        return 1

    t_total = time.time()
    print(_bar(f"END-TO-END DATA PIPELINE  version={version}"))

    steps = [
        ("1/6", "clean (raw → intermediate)", clean_to_jsonl.run,
         (version,), {"max_len": max_len}),
        ("2/6", "split cold/hot → vector + postgres CSV", split_cold_hot.run,
        (version,), {"commit": commit, "prev": prev}),
        ("3/6", "parse_pdf_specs → postgres/specs.csv (feature specs từ brochure)", parse_pdf_specs.run,
         (version,), {}),
        ("4/6", "embed + ingest Qdrant dense (incremental)", vector_ingest.run,
         (version,), {"url": QDRANT_URL, "recreate": recreate}),
    ]
    if not no_sparse:
        steps.append(("5/6", "BM25 sparse → Qdrant sparse", sparse_ingest.run,
                      (version,), {"url": QDRANT_URL, "recreate": recreate}))
    steps.append(("6/6" if not no_sparse else "5/5",
                  "UPSERT PostgreSQL (versioned)", postgres_ingest.run,
                  (version,), {"dsn": PG_DSN}))

    for idx, label, fn, args, kwargs in steps:
        rc = _step(idx, label, fn, *args, **kwargs)
        if rc != 0:
            print(f"\n[run_pipeline] DỪNG ở bước {idx} ({label}). Các bước sau KHÔNG chạy.",
                  file=sys.stderr)
            return rc

    print(_bar(f"XONG ingest  version={version}  ({time.time() - t_total:.1f}s)"))
    print("Ingest xong — version CHƯA active. Activate bằng:")
    print(f"  python scripts/version_manager.py promote --version {version}")
    if promote:
        print(_bar(f"PROMOTE → active={version}"))
        rc = version_manager._activate(version, rollback=False)
        if rc != 0:
            print("[run_pipeline] promote FAIL — version đã ingest nhưng chưa active.",
                  file=sys.stderr)
            print(f"  sửa rồi chạy: version_manager.py promote --version {version}",
                  file=sys.stderr)
        return rc
    print("Verify:")
    print(f"  python scripts/version_manager.py status")
    print(f"  cat data/clean/{version}/_manifest.json")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="End-to-end data pipeline (dữ liệu hiện có).")
    ap.add_argument("--version", default="v1", help="Version folder (mặc định v1)")
    ap.add_argument("--recreate", action="store_true",
                    help="Xóa collection __version + bỏ qua cache (rebuild sạch)")
    ap.add_argument("--no-sparse", action="store_true",
                    help="Bỏ qua BM25 sparse (chỉ dense + PostgreSQL)")
    ap.add_argument("--commit", default="",
                    help="Repo commit hash ghi vào _manifest / ingest_version")
    ap.add_argument("--max-len", type=int, default=800,
                    help="Chunk max length chars (mặc định 800; dùng 400 nếu cần chunk nhỏ hơn)")
    ap.add_argument("--prev", default=None,
                    help="Version trước để diff (mặc định: auto-detect)")
    ap.add_argument("--promote", action="store_true",
                    help="Sau khi ingest xong, tự activate version (alias swap + is_current)")
    args = ap.parse_args()
    return run(args.version, args.recreate, args.no_sparse, args.commit,
               args.max_len, args.prev, args.promote)


if __name__ == "__main__":
    sys.exit(main())
