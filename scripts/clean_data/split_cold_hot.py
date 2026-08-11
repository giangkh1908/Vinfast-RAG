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

# Chạy trực tiếp (`python scripts/clean_data/split_cold_hot.py`) → repo root vào sys.path
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.config import CLEAN_DIR  # noqa: E402
from scripts.schemas import Chunk, validate_chunk  # noqa: E402

CSV_DELIMITER = "|"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _content_hash(text: str, structured: Any) -> str:
    """Hash nội dung chunk (text + structured), model-agnostic — dùng cho diff."""
    body = json.dumps(structured or {}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(f"{text}\x1f{body}".encode("utf-8")).hexdigest()


def detect_prev_version(version: str) -> str | None:
    """Version trước đó = folder có _manifest.json, created_at max < version hiện tại.

    Bỏ qua chính `version` và folder không có manifest. Trả None nếu không có.
    """
    candidates: list[tuple[str, str]] = []  # (version, created_at)
    for d in CLEAN_DIR.iterdir():
        if not d.is_dir() or d.name == version:
            continue
        mf = d / "_manifest.json"
        if not mf.exists():
            continue
        try:
            m = json.loads(mf.read_text(encoding="utf-8"))
            candidates.append((d.name, m.get("created_at") or ""))
        except (json.JSONDecodeError, OSError):
            continue
    if not candidates:
        return None
    # created_at ISO → sắp giảm dần (lexicographic OK cho ISO UTC)
    candidates.sort(key=lambda c: c[1], reverse=True)
    return candidates[0][0]


def _load_prev_hashes(prev_version: str) -> dict[str, dict[str, str]]:
    """Trả {collection: {chunk_id: content_hash}} cho version trước."""
    prev_dir = CLEAN_DIR / prev_version / "vector"
    if not prev_dir.exists():
        return {}
    out: dict[str, dict[str, str]] = {}
    for f in sorted(prev_dir.glob("*.jsonl")):
        col = f.stem
        m: dict[str, str] = {}
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            c = json.loads(line)
            m[c["id"]] = _content_hash(c["text"], c.get("structured"))
        out[col] = m
    return out


def diff_chunks(
    by_collection: dict[str, list[dict[str, Any]]],
    prev_version: str | None,
) -> dict[str, dict[str, int]]:
    """Tính added/modified/removed mỗi collection so với prev_version.

    - added   = chunk_id có ở curr, KHÔNG có ở prev
    - removed = chunk_id có ở prev, KHÔNG có ở curr  (cả collection bị bỏ cũng tính)
    - modified = có ở cả 2, hash khác
    Trả {collection: {chunks, added, modified, removed}} (chỉ số, không ghi file).
    """
    prev_hashes = _load_prev_hashes(prev_version) if prev_version else {}
    diff: dict[str, dict[str, int]] = {}
    all_cols = set(by_collection) | set(prev_hashes)
    for col in all_cols:
        curr_rows = by_collection.get(col, [])
        curr_map = {r["id"]: _content_hash(r["text"], r.get("structured")) for r in curr_rows}
        prev_map = prev_hashes.get(col, {})
        curr_ids = set(curr_map)
        prev_ids = set(prev_map)
        added = len(curr_ids - prev_ids)
        removed = len(prev_ids - curr_ids)
        modified = sum(1 for cid in curr_ids & prev_ids if curr_map[cid] != prev_map[cid])
        diff[col] = {"chunks": len(curr_rows), "added": added,
                     "modified": modified, "removed": removed}
    return diff


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
    validation_errors = []
    for row in vector_rows:
        col = row["collection"]
        key_base = f"{col}:{row.get('model_id') or 'general'}:{row.get('edition_id') or 'all'}"
        seq_by_key[key_base] += 1
        row["id"] = stable_id(row, seq_by_key[key_base])
        # Validate chunk schema
        try:
            validate_chunk(row, context=f"split_vector_by_collection")
        except ValueError as e:
            validation_errors.append(str(e))
            continue  # Skip invalid chunk
        # Ensure no money in text
        if has_money(row["text"]):
            # Drop the chunk rather than leak stale prices
            print(f"  WARN: money detected in vector text, dropping id={row['id']}", file=sys.stderr)
            continue
        by_collection[col].append(row)
    if validation_errors:
        print(f"  VALIDATION ERRORS ({len(validation_errors)} chunks skipped):", file=sys.stderr)
        for err in validation_errors[:5]:  # Show first 5 errors
            print(f"    {err}", file=sys.stderr)
        if len(validation_errors) > 5:
            print(f"    ... and {len(validation_errors) - 5} more", file=sys.stderr)
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
    prev_version: str | None = None,
    diff: dict[str, dict[str, int]] | None = None,
) -> dict[str, Any]:
    diff = diff or {}
    vector_summary: dict[str, Any] = {}
    total_chunks = 0
    total_added = 0
    total_modified = 0
    total_removed = 0
    for col, rows in by_collection.items():
        d = diff.get(col, {})
        added = d.get("added", len(rows)) if diff else len(rows)
        modified = d.get("modified", 0) if diff else 0
        removed = d.get("removed", 0) if diff else 0
        vector_summary[col] = {
            "file": f"vector/{col}.jsonl",
            "chunks": len(rows),
            "added": added,
            "modified": modified,
            "removed": removed,
        }
        total_chunks += len(rows)
        total_added += added
        total_modified += modified
        total_removed += removed
    # collection bị bỏ hẳn ở version này (chỉ có ở prev) cũng tính vào removed
    for col, d in diff.items():
        if col not in by_collection:
            total_removed += d.get("removed", 0)

    return {
        "version": version,
        "created_at": now_iso(),
        "created_by": "scripts/clean_to_jsonl.py + scripts/split_cold_hot.py",
        "prev_version": prev_version,
        "repo_commit": repo_commit,
        "vector": {
            "collections": vector_summary,
            "total_chunks": total_chunks,
            "total_added": total_added,
            "total_modified": total_modified,
            "total_removed": total_removed,
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


def run(version: str = "v1", commit: str = "", prev: str | None = None) -> int:
    """Split intermediate -> cold vector JSONL + hot postgres CSV + manifest.
    Trả 0 nếu OK, 1 nếu lỗi. `prev` = version trước để diff (None → auto-detect)."""
    version_dir = CLEAN_DIR / version
    inter_dir = version_dir / "intermediate"
    vector_dir = version_dir / "vector"
    postgres_dir = version_dir / "postgres"
    prev_version = prev

    if not inter_dir.exists():
        print(f"[split_cold_hot] intermediate dir not found: {inter_dir}", file=sys.stderr)
        return 1

    # Load intermediate
    vector_rows = [json.loads(line) for line in (inter_dir / "vector.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    hot_rows = [json.loads(line) for line in (inter_dir / "hot.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]

    # Dọn output cũ — CHỈ file split sở hữu:
    #   vector/*.jsonl              (split viết hết → bỏ collection cũ như vivu_faq)
    #   postgres/edition.csv, price_list.csv
    # KHÔNG xóa postgres/specs.csv (do parse_pdf_specs.py viết — bước kế tiếp trong pipeline).
    if vector_dir.exists():
        for f in vector_dir.iterdir():
            if f.is_file():
                f.unlink()
    postgres_dir.mkdir(parents=True, exist_ok=True)
    for fname in ("edition.csv", "price_list.csv"):
        p = postgres_dir / fname
        if p.exists():
            p.unlink()

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

    # Manifest (+ chunk diff so với prev_version)
    link_only = load_link_only(version_dir)
    if prev_version is None:
        prev_version = detect_prev_version(version)
    diff = diff_chunks(by_collection, prev_version)
    manifest = build_manifest(version, by_collection, edition_rows, price_rows,
                               link_only, commit, prev_version, diff)
    (version_dir / "_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[split_cold_hot] version={version}  prev={prev_version}")
    print(f"  vector collections: {len(by_collection)}  total chunks: {manifest['vector']['total_chunks']}")
    print(f"  diff: added={manifest['vector']['total_added']}  "
          f"modified={manifest['vector']['total_modified']}  "
          f"removed={manifest['vector']['total_removed']}")
    print(f"  postgres edition rows: {len(edition_rows)}  price rows: {len(price_rows)}")
    print(f"  output dir: {version_dir}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Split intermediate JSONL into cold vector + hot postgres CSV.")
    ap.add_argument("--version", default="v1", help="Version folder (default: v1)")
    ap.add_argument("--commit", default="", help="Repository commit hash")
    ap.add_argument("--prev", default=None,
                    help="Version trước để diff (mặc định: auto-detect từ manifest)")
    args = ap.parse_args()
    return run(args.version, args.commit, args.prev)


if __name__ == "__main__":
    sys.exit(main())
