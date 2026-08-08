#!/usr/bin/env python3
"""
batch_runner.py — Run eval test cases via API and export JSONL logs.

Input:  CSV file with columns test_id,user_query
Output: JSONL file with P0 schema per request

Usage:
    python scripts/batch_runner.py --input eval_cases.csv --output eval_results.jsonl
    python scripts/batch_runner.py --input eval_cases.csv --output eval_results.jsonl --api-url http://localhost:8000
"""

import argparse
import csv
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]


def run_batch(input_path: str, output_path: str, api_url: str, history_turns: int = 0):
    input_file = Path(input_path)
    output_file = Path(output_path)

    if not input_file.exists():
        print(f"Input file not found: {input_file}", file=sys.stderr)
        return 1

    run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    run_timestamp = datetime.now(timezone.utc).isoformat()

    print(f"[batch_runner] run_id={run_id}")
    print(f"[batch_runner] input={input_file}")
    print(f"[batch_runner] output={output_file}")
    print(f"[batch_runner] api_url={api_url}")
    print()

    cases = []
    with input_file.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            test_id = row.get("test_id", "").strip()
            user_query = row.get("user_query", "").strip()
            if test_id and user_query:
                cases.append({"test_id": test_id, "user_query": user_query})

    if not cases:
        print("No valid test cases found.", file=sys.stderr)
        return 1

    print(f"Found {len(cases)} test cases")
    print()

    output_file.parent.mkdir(parents=True, exist_ok=True)
    results = []

    for i, case in enumerate(cases, 1):
        test_id = case["test_id"]
        user_query = case["user_query"]

        print(f"[{i}/{len(cases)}] {test_id}: {user_query[:60]}...", end=" ")

        t0 = time.time()
        try:
            resp = requests.post(
                f"{api_url}/api/chat",
                json={"message": user_query, "history": []},
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()
            latency_ms = (time.time() - t0) * 1000

            dlog = data.get("decision_log", {})
            dlog["run_id"] = run_id
            dlog["test_id"] = test_id
            dlog["build_version"] = dlog.get("build_version", "")
            dlog["latency_total_ms"] = round(latency_ms, 1)

            results.append(dlog)

            decision = dlog.get("decision", "?")
            reason = dlog.get("reason_code", "?")
            print(f"-> {decision} ({reason}) {latency_ms:.0f}ms")

        except Exception as e:
            latency_ms = (time.time() - t0) * 1000
            error_log = {
                "schema_version": "1.0",
                "request_id": f"req_{uuid.uuid4().hex[:12]}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "run_id": run_id,
                "test_id": test_id,
                "user_query": user_query,
                "decision": "refuse",
                "reason_code": "system_error",
                "error_stage": "unknown",
                "error_type": type(e).__name__,
                "error_message": str(e)[:200],
                "latency_total_ms": round(latency_ms, 1),
            }
            results.append(error_log)
            print(f"-> ERROR: {e}")

    with output_file.open("w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print()
    print(f"[batch_runner] done. {len(results)} results -> {output_file}")

    decisions = {}
    for r in results:
        d = r.get("decision", "unknown")
        decisions[d] = decisions.get(d, 0) + 1
    print(f"[batch_runner] decisions: {decisions}")

    return 0


def main():
    ap = argparse.ArgumentParser(description="Batch eval runner")
    ap.add_argument("--input", required=True, help="CSV file with test_id,user_query")
    ap.add_argument("--output", default="eval_results.jsonl", help="Output JSONL file")
    ap.add_argument("--api-url", default="http://localhost:8000", help="API base URL")
    args = ap.parse_args()

    return run_batch(args.input, args.output, args.api_url)


if __name__ == "__main__":
    sys.exit(main())
