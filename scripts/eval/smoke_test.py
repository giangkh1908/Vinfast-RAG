#!/usr/bin/env python3
"""
Smoke test — đánh giá quality retrieval sau mỗi ingest.

Query golden set → check top-K có chứa chunk mong muốn không.
Metrics: hit@K (có match ít nhất 1), precision@K (tỷ lệ match trong K).

Usage:
    python scripts/eval/smoke_test.py --version v2 --top-k 5
"""
import argparse
import json
import sys
from pathlib import Path

# Set UTF-8 encoding for Windows console
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from qdrant_client import QdrantClient
from scripts.config import QDRANT_URL, QDRANT_API_KEY, QDRANT_TIMEOUT
from lib.openrouter import embed_texts

GOLDEN_SET_PATH = Path(__file__).parent / "golden_set.json"
DENSE_COLLECTIONS = ["vivu_product_info", "vivu_policy", "vivu_maintenance"]


def load_golden_set() -> list[dict]:
    """Đọc golden set JSON."""
    if not GOLDEN_SET_PATH.exists():
        print(f"[smoke_test] golden set not found: {GOLDEN_SET_PATH}", file=sys.stderr)
        sys.exit(1)
    with open(GOLDEN_SET_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def check_match(payload: dict, expected: dict) -> bool:
    """Check nếu payload match expected criteria."""
    # Check collection
    if expected.get("collection"):
        if payload.get("collection") != expected["collection"]:
            return False
    
    # Check model_id
    if expected.get("model_id"):
        if payload.get("model_id") != expected["model_id"]:
            return False
    
    # Check edition_id
    if expected.get("edition_id"):
        if payload.get("edition_id") != expected["edition_id"]:
            return False
    
    # Check keywords (tất cả phải có)
    keywords = expected.get("keywords", [])
    if keywords:
        text = payload.get("text", "").lower()
        for kw in keywords:
            if kw.lower() not in text:
                return False
    
    return True


def run_smoke_test(version: str, top_k: int = 5) -> int:
    """Chạy smoke test, trả về exit code (0 = pass, 1 = fail)."""
    client = QdrantClient(
        url=QDRANT_URL,
        api_key=QDRANT_API_KEY or None,
        timeout=QDRANT_TIMEOUT
    )
    
    # Verify collections exist
    for col in DENSE_COLLECTIONS:
        if not client.collection_exists(col):
            print(f"[smoke_test] collection {col} not found", file=sys.stderr)
            return 1
    
    golden_set = load_golden_set()
    print(f"[smoke_test] version={version}  top_k={top_k}  queries={len(golden_set)}")
    
    results = []
    
    for i, item in enumerate(golden_set, 1):
        query = item["query"]
        expected = item["expected"]
        
        # Embed query
        vectors = embed_texts([query])
        if not vectors:
            print(f"  [{i}/{len(golden_set)}] ✗ embed failed: {query[:50]}")
            results.append(0)
            continue
        
        # Search on all dense collections
        all_hits = []
        for col in DENSE_COLLECTIONS:
            hits = client.query_points(
                collection_name=col,
                query=vectors[0],
                limit=top_k,
                with_payload=True
            )
            points = hits.points if hasattr(hits, 'points') else hits
            all_hits.extend(points)
        
        # Sort by score and take top_k
        all_hits.sort(key=lambda x: x.score if hasattr(x, 'score') else 0, reverse=True)
        all_hits = all_hits[:top_k]
        
        # Check matches
        matches = [check_match(h.payload, expected) for h in all_hits]
        hit_any = any(matches)
        precision = sum(matches) / len(matches) if matches else 0
        
        status = "✓" if hit_any else "✗"
        print(f"  [{i}/{len(golden_set)}] {status} {query[:50]}  hit@{top_k}={hit_any}  prec@{top_k}={precision:.2f}")
        
        results.append(1 if hit_any else 0)
    
    # Summary
    hit_rate = sum(results) / len(results) if results else 0
    print(f"\n[smoke_test] hit@{top_k}={hit_rate:.2%}  ({sum(results)}/{len(results)})")
    
    if hit_rate < 0.8:
        print(f"[smoke_test] FAIL: hit rate < 80%", file=sys.stderr)
        return 1
    
    print(f"[smoke_test] PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test retrieval quality")
    parser.add_argument("--version", default="v2", help="Version label (chỉ để log)")
    parser.add_argument("--top-k", type=int, default=5, help="Số results để check (default: 5)")
    args = parser.parse_args()
    
    return run_smoke_test(args.version, args.top_k)


if __name__ == "__main__":
    sys.exit(main())
