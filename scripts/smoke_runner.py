#!/usr/bin/env python3
"""
smoke_runner.py — Run smoke_test.csv against /api/chat, output DecisionLog JSONL.

Output format matches the P0 DecisionLog schema:
  request_id, timestamp, run_id, build_version, prompt_version,
  data_snapshot_id, user_query, detected_vehicle_model, detected_vehicle_version,
  detected_topic, decision, reason_code, retrieval_status, retrieved_chunks,
  displayed_answer, displayed_citations, latency_total_ms, latency_retrieval_ms,
  latency_generation_ms

Usage:
    python scripts/smoke_runner.py
    python scripts/smoke_runner.py --api-url http://localhost:8000
    python scripts/smoke_runner.py --output eval/smoke_results.jsonl
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


def run_smoke(input_path: str, output_path: str, api_url: str) -> int:
    input_file = Path(input_path)
    output_file = Path(output_path)

    if not input_file.exists():
        print(f"Input not found: {input_file}", file=sys.stderr)
        return 1

    run_id = f"smoke_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    print(f"[smoke] run_id={run_id}")
    print(f"[smoke] input={input_file}")
    print(f"[smoke] output={output_file}")
    print(f"[smoke] api={api_url}")
    print()

    cases = []
    with input_file.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            test_id = row.get("test_id", "").strip()
            query = row.get("user_query", "").strip()
            if test_id and query:
                cases.append(row)

    if not cases:
        print("No valid test cases.", file=sys.stderr)
        return 1

    conversations: dict[str, list[dict]] = {}
    single_turns: list[dict] = []
    for case in cases:
        conv_id = case.get("conversation_id", "").strip()
        if conv_id:
            conversations.setdefault(conv_id, []).append(case)
        else:
            single_turns.append(case)

    print(f"Found {len(cases)} cases: {len(conversations)} convs + {len(single_turns)} single")
    print()

    results: list[dict] = []
    total_pass = 0
    total_fail = 0

    def _process(case: dict, history: list[dict]) -> dict:
        nonlocal total_pass, total_fail
        test_id = case.get("test_id", "")
        query = case.get("user_query", "")
        expected = case.get("expected_decision", "")
        turn_idx = int(case.get("turn_index") or 1)
        label = f"T{turn_idx}" if turn_idx else ""
        print(f"  [{test_id}] {label}: {query[:60]}", end=" ... ")

        t0 = time.time()
        try:
            resp = requests.post(
                f"{api_url}/api/chat",
                json={"message": query, "history": history},
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()
            dlog = data.get("decision_log", {})

            if not dlog:
                dlog = {
                    "decision": data.get("decision", "?"),
                    "reason_code": "",
                    "displayed_answer": data.get("response", ""),
                    "displayed_citations": [],
                    "retrieved_chunks": [],
                }

            actual = dlog.get("decision", "?")
            match = actual == expected
            if match:
                total_pass += 1
            else:
                total_fail += 1

            latency = (time.time() - t0) * 1000
            status = "OK" if match else "FAIL"
            print(f"-> {actual} {latency:.0f}ms {status}")

            result = {
                "schema_version": "1.0",
                "request_id": dlog.get("request_id", f"req_{uuid.uuid4().hex[:12]}"),
                "timestamp": dlog.get("timestamp", datetime.now(timezone.utc).isoformat()),
                "run_id": dlog.get("run_id", run_id),
                "test_id": test_id,
                "build_version": dlog.get("build_version", ""),
                "prompt_version": dlog.get("prompt_version", ""),
                "data_snapshot_id": dlog.get("data_snapshot_id", ""),
                "conversation_id": case.get("conversation_id", ""),
                "turn_index": turn_idx,
                "user_query": query,
                "detected_vehicle_model": dlog.get("detected_vehicle_model", ""),
                "detected_vehicle_version": dlog.get("detected_vehicle_version", ""),
                "detected_topic": dlog.get("detected_topic", ""),
                "decision": actual,
                "expected_decision": expected,
                "decision_match": match,
                "reason_code": dlog.get("reason_code", ""),
                "retrieval_status": dlog.get("retrieval_status", ""),
                "retrieved_chunks": dlog.get("retrieved_chunks", []),
                "displayed_answer": dlog.get("displayed_answer", ""),
                "displayed_citations": dlog.get("displayed_citations", []),
                "latency_total_ms": dlog.get("latency_total_ms", round(latency, 1)),
                "latency_retrieval_ms": dlog.get("latency_retrieval_ms", 0),
                "latency_generation_ms": dlog.get("latency_generation_ms", 0),
            }

            answer = data.get("response", "")
            return result, answer

        except Exception as e:
            latency = (time.time() - t0) * 1000
            total_fail += 1
            print(f"-> ERROR: {e}")
            return {
                "schema_version": "1.0",
                "request_id": f"req_{uuid.uuid4().hex[:12]}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "run_id": run_id,
                "test_id": test_id,
                "user_query": query,
                "decision": "error",
                "expected_decision": expected,
                "decision_match": False,
                "reason_code": "system_error",
                "displayed_answer": f"ERROR: {e}",
                "displayed_citations": [],
                "retrieved_chunks": [],
                "latency_total_ms": round(latency, 1),
                "latency_retrieval_ms": 0,
                "latency_generation_ms": 0,
            }, ""

    for case in single_turns:
        result, _ = _process(case, [])
        results.append(result)

    for conv_id, turns in conversations.items():
        turns.sort(key=lambda x: int(x.get("turn_index", 1)))
        history: list[dict] = []
        for case in turns:
            result, answer = _process(case, history)
            results.append(result)
            history.append({"role": "user", "content": case["user_query"]})
            history.append({"role": "assistant", "content": answer})

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    total = total_pass + total_fail
    print()
    print("=" * 60)
    print(f"  SMOKE TEST — {run_id}")
    print("=" * 60)
    print(f"  Total:          {total}")
    print(f"  Decision PASS:  {total_pass}/{total} ({100*total_pass/total:.0f}%)" if total else "  No cases")
    print(f"  Decision FAIL:  {total_fail}/{total}")
    print()

    failures = [r for r in results if not r.get("decision_match")]
    if failures:
        print("  FAILURES:")
        for r in failures:
            print(f"    {r['test_id']}: expected={r['expected_decision']} got={r['decision']} | {r['user_query'][:50]}")
        print()

    print(f"  Results: {output_file}")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Smoke test runner")
    ap.add_argument("--input", default=str(REPO_ROOT / "eval" / "smoke_test.csv"))
    ap.add_argument("--output", default=str(REPO_ROOT / "eval" / "smoke_results.jsonl"))
    ap.add_argument("--api-url", default="http://localhost:8000")
    args = ap.parse_args()
    return run_smoke(args.input, args.output, args.api_url)


if __name__ == "__main__":
    sys.exit(main())
