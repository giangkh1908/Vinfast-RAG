#!/usr/bin/env python3
"""
split_cold_hot.py — Split intermediate JSONL into:
  - data/clean/<version>/vector/*.jsonl  (cold, ingest Qdrant)
  - data/clean/<version>/postgres/*.csv  (hot, COPY INTO Postgres)
  - data/clean/<version>/_manifest.json

Rules:
  * vector text MUST NOT contain money numbers.
  * prices go to postgres/price_list.csv + edition.csv
  * showroom/promotion/roadside-cost links go to _manifest.link_only only.
  * stable ids: <collection>:<model_lower>:<edition_lower>:<section_slug>:<seq>
"""

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
CLEAN_DIR = DATA_DIR / "clean"

CSV_DELIMITER = "|"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slugify(text: str, max_len: int = 40) -> str:
    s = text.lower()
    s = re.sub(r"[^a-z0-9\s]+", " ", s)
    s = re.sub(r"\s+", "_", s.strip())
    return s[:max_len].strip("_") or "section"


def stable_id(chunk: dict[str, Any], seq: int) -> str:
    collection = chunk["collection"]
    model = (chunk.get("model_id") or "general").lower()
    edition = (chunk.get("edition_id") or "all").lower()
    section = slugify(" ".join(chunk.get("section_path", [])[-2:]))
    return f"{collection}:{model}:{edition}:{section}:{seq}"


def has_money(text: str) -> bool:
    # Strict: require money unit keyword
    amount = r"\d{1,3}(?:[.,]\d{3})+(?:\d{2})?|\d{6,}"
    unit = r"(?:triệu|tr|tỷ|nghìn|đồng|VNĐ|VND|\bđ\b)"
    return bool(re.search(rf"(?:{amount})\s*{unit}|{unit}\s*(?:{amount})", text, flags=re.IGNORECASE))


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def write_csv(path: Path, headers: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers, delimiter=CSV_DELIMITER, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def split_vector_by_collection(vector_rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_collection: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seq_by_key: dict[str, int] = defaultdict(int)
    for row in vector_rows:
        col = row["collection"]
        key_base = f"{col}:{row.get('model_id') or 'general'}:{row.get('edition_id') or 'all'}"
        seq_by_key[key_base] += 1
        row["id"] = stable_id(row, seq_by_key[key_base])
        # Ensure no money in text
        if has_money(row["text"]):
            # Drop the chunk rather than leak stale prices
            print(f"  WARN: money detected in vector text, dropping id={row['id']}", file=sys.stderr)
            continue
        by_collection[col].append(row)
    return dict(by_collection)


def build_edition_rows(hot_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    rows = []
    created_at = now_iso()
    for h in hot_rows:
        key = (h["model_id"], h["edition_id"])
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "model_id": h["model_id"],
            "edition_id": h["edition_id"],
            "model_label": h["model_label"],
            "edition_label": h["edition_label"],
            "year_range": h.get("year_range", "2025-2026"),
            "is_active": "t" if h.get("is_active", True) else "f",
            "created_at": created_at,
            "updated_at": created_at,
        })
    return rows


def build_price_rows(hot_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    updated_at = now_iso()
    for h in hot_rows:
        rows.append({
            "model_id": h["model_id"],
            "edition_id": h["edition_id"],
            "price_list_vnd": h.get("price_list_vnd") or "",
            "price_promo_vnd": h.get("price_promo_vnd") or "",
            "promo_label": h.get("promo_label", ""),
            "vat_included": "t" if h.get("vat_included", True) else "f",
            "battery_included": "t" if h.get("battery_included", True) else "f",
            "valid_from": h.get("valid_from", ""),
            "valid_to": h.get("valid_to") or "",
            "updated_at": updated_at,
            "source_url": h.get("source_url", ""),
        })
    return rows


def load_link_only(version_dir: Path) -> dict[str, list[str]]:
    path = version_dir / "intermediate" / "link_only.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"brochure_urls": [], "showroom_urls": [], "promotion_urls": [], "roadside_cost_urls": []}


def build_manifest(
    version: str,
    by_collection: dict[str, list[dict[str, Any]]],
    edition_rows: list[dict[str, Any]],
    price_rows: list[dict[str, Any]],
    link_only: dict[str, list[str]],
    repo_commit: str = "",
) -> dict[str, Any]:
    vector_summary: dict[str, Any] = {}
    total_chunks = 0
    for col, rows in by_collection.items():
        vector_summary[col] = {
            "file": f"vector/{col}.jsonl",
            "chunks": len(rows),
            "added": len(rows),  # v1: all added
            "modified": 0,
            "removed": 0,
        }
        total_chunks += len(rows)

    return {
        "version": version,
        "created_at": now_iso(),
        "created_by": "scripts/clean_to_jsonl.py + scripts/split_cold_hot.py",
        "prev_version": None,
        "repo_commit": repo_commit,
        "vector": {
            "collections": vector_summary,
            "total_chunks": total_chunks,
            "total_added": total_chunks,
            "total_modified": 0,
            "total_removed": 0,
        },
        "postgres": {
            "tables": {
                "edition": {
                    "file": "postgres/edition.csv",
                    "rows": len(edition_rows),
                    "upserted": len(edition_rows),
                },
                "price_list": {
                    "file": "postgres/price_list.csv",
                    "rows": len(price_rows),
                    "upserted": len(price_rows),
                    "price_changed": sum(1 for p in price_rows if p["price_promo_vnd"]),
                },
            },
            "total_rows_upserted": len(edition_rows) + len(price_rows),
        },
        "link_only": link_only,
        "pipeline_steps": ["clean_to_jsonl", "split_cold_hot"],
        "schema_version": "1.0.0",
    }


def run(version: str = "v1", commit: str = "") -> int:
    """Split intermediate -> cold vector JSONL + hot postgres CSV + manifest.
    Trả 0 nếu OK, 1 nếu lỗi."""
    version_dir = CLEAN_DIR / version
    inter_dir = version_dir / "intermediate"
    vector_dir = version_dir / "vector"
    postgres_dir = version_dir / "postgres"

    if not inter_dir.exists():
        print(f"[split_cold_hot] intermediate dir not found: {inter_dir}", file=sys.stderr)
        return 1

    # Load intermediate
    vector_rows = [json.loads(line) for line in (inter_dir / "vector.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    hot_rows = [json.loads(line) for line in (inter_dir / "hot.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]

    # Dọn output cũ (tránh file collection không còn trong version mới — VD vivu_faq)
    for d in (vector_dir, postgres_dir):
        if d.exists():
            for f in d.iterdir():
                if f.is_file():
                    f.unlink()

    # Split vectors
    by_collection = split_vector_by_collection(vector_rows)
    for col, rows in by_collection.items():
        write_jsonl(vector_dir / f"{col}.jsonl", rows)

    # Postgres CSVs (chỉ edition + price_list — bảo dưỡng chỉ trả link, không lưu bảng)
    edition_rows = build_edition_rows(hot_rows)
    price_rows = build_price_rows(hot_rows)

    write_csv(
        postgres_dir / "edition.csv",
        ["model_id", "edition_id", "model_label", "edition_label", "year_range", "is_active", "created_at", "updated_at"],
        edition_rows,
    )
    write_csv(
        postgres_dir / "price_list.csv",
        ["model_id", "edition_id", "price_list_vnd", "price_promo_vnd", "promo_label",
         "vat_included", "battery_included", "valid_from", "valid_to", "updated_at", "source_url"],
        price_rows,
    )

    # Manifest
    link_only = load_link_only(version_dir)
    manifest = build_manifest(version, by_collection, edition_rows, price_rows, link_only, commit)
    (version_dir / "_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[split_cold_hot] version={version}")
    print(f"  vector collections: {len(by_collection)}  total chunks: {manifest['vector']['total_chunks']}")
    print(f"  postgres edition rows: {len(edition_rows)}  price rows: {len(price_rows)}")
    print(f"  output dir: {version_dir}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Split intermediate JSONL into cold vector + hot postgres CSV.")
    ap.add_argument("--version", default="v1", help="Version folder (default: v1)")
    ap.add_argument("--commit", default="", help="Repository commit hash")
    args = ap.parse_args()
    return run(args.version, args.commit)


if __name__ == "__main__":
    sys.exit(main())
