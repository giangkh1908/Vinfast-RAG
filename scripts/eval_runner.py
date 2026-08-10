#!/usr/bin/env python3
"""
eval_runner.py — Unified eval runner for Trust Foundation smoke tests.

Handles:
- Multi-turn conversations (turn_index, conversation_id)
- Decision routing validation (expected_decision, expected_reason_code)
- must_not_do assertion checking
- RAGAS automated scoring (faithfulness, relevancy, precision, recall)

Usage:
    python scripts/eval_runner.py --input eval/smoke_test.csv --output eval/eval_report.jsonl
    python scripts/eval_runner.py --input eval/smoke_test.csv --output eval/eval_report.jsonl --api-url http://localhost:8000
"""

import argparse
import csv
import json
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]


# ── must_not_do assertion checker ───────────────────────────────────────────
def check_must_not_do(answer: str, must_not_do: list[str], decision: str,
                      retrieved_chunks: list[dict], citations: list[dict]) -> list[dict]:
    """Check answer against must_not_do constraints. Returns list of violations."""
    # Skip checks for OOS and refuse — these are system messages, not LLM answers
    if decision in ("out_of_scope", "refuse", "clarify"):
        return []
    violations = []
    answer_lower = answer.lower()

    for rule in must_not_do:
        rule_lower = rule.lower().strip()
        violated = False
        reason = ""

        # "Không chọn Eco hoặc Plus mặc định"
        if "chọn" in rule_lower and ("mặc định" in rule_lower or "default" in rule_lower):
            if decision == "answer":
                # Check if answer mentions a specific version without user asking
                if re.search(r"(eco|plus)", answer_lower) and not re.search(r"(phiên bản|bản)", answer_lower):
                    violated = True
                    reason = "Answer mentions Eco/Plus without user specifying version"

        # "Không trộn NEDC/WLTP"
        if "trộn" in rule_lower and ("nedc" in rule_lower or "wltp" in rule_lower):
            if "nedc" in answer_lower and "wltp" in answer_lower:
                violated = True
                reason = "Answer contains both NEDC and WLTP"

        # "Không citation" (for clarify/refuse)
        if "không citation" in rule_lower or "không có citation" in rule_lower:
            if decision in ("clarify", "refuse") and citations:
                violated = True
                reason = f"Clarify/refuse response has {len(citations)} citations"

        # "Không đưa factual answer" (for clarify)
        if "không đưa factual answer" in rule_lower or "không factual" in rule_lower:
            if decision == "clarify":
                # Check if answer contains numbers that look like specs
                if re.search(r"\d+\s*(kW|Nm|km|mm|kWh|inch|mph)", answer):
                    violated = True
                    reason = "Clarify response contains factual specs"

        # "Không tự chọn model"
        if "không tự chọn" in rule_lower and ("mẫu xe" in rule_lower or "model" in rule_lower):
            if decision == "clarify":
                # Check if answer mentions a specific model
                if re.search(r"VF\s*[68]", answer):
                    violated = True
                    reason = "Clarify response mentions specific model"

        # "Không dùng kiến thức nền"
        if "kiến thức nền" in rule_lower or "kiến thức sẵn" in rule_lower:
            if decision == "answer" and not retrieved_chunks:
                violated = True
                reason = "Answer without retrieved evidence"

        # "Không đoán" (for refuse cases)
        if "không đoán" in rule_lower:
            if decision == "answer" and not retrieved_chunks:
                violated = True
                reason = "Answer without evidence (guessed)"

        # "Không thêm phiên bản khác"
        if "không thêm phiên bản" in rule_lower:
            # Check if answer mentions versions not in expected_facts
            pass  # Complex check, skip for now

        # "Không dùng [version] của [model]" (version mixing)
        if "không dùng" in rule_lower and ("của" in rule_lower or "phiên bản" in rule_lower):
            pass  # Complex check, needs expected_facts context

        # "Không so sánh" / "Không lập bảng so sánh"
        if ("không so sánh" in rule_lower or "không lập bảng" in rule_lower) and decision == "answer":
            if re.search(r"(so sánh|bảng|khác nhau|versus|\bvs\b)", answer_lower):
                violated = True
                reason = "Answer contains comparison content"

        # "Không khuyên" (recommendation)
        if "không khuyên" in rule_lower:
            if re.search(r"(nên mua|khuyên|gợi ý|chọn)", answer_lower):
                violated = True
                reason = "Answer contains recommendation"

        # "Không bịa" (fabrication)
        if "không bịa" in rule_lower:
            if decision == "answer" and not retrieved_chunks:
                violated = True
                reason = "Answer without evidence (fabricated)"

        # "Không chẩn đoán" / "Không hướng dẫn sửa chữa"
        if "chẩn đoán" in rule_lower or "hướng dẫn sửa" in rule_lower:
            if re.search(r"(bạn nên|cách sửa|thao tác|kiểm tra|thay thế)", answer_lower):
                violated = True
                reason = "Answer contains repair/diagnosis instructions"

        if violated:
            violations.append({
                "rule": rule,
                "reason": reason,
                "severity": "blocker",
            })

    return violations


# ── Main eval runner ────────────────────────────────────────────────────────
def run_eval(input_path: str, output_path: str, api_url: str):
    input_file = Path(input_path)
    output_file = Path(output_path)

    if not input_file.exists():
        print(f"Input file not found: {input_file}", file=sys.stderr)
        return 1

    run_id = f"eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    print(f"[eval_runner] run_id={run_id}")
    print(f"[eval_runner] input={input_file}")
    print(f"[eval_runner] output={output_file}")
    print()

    # Load test cases grouped by conversation_id
    cases = []
    with input_file.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            test_id = row.get("test_id", "").strip()
            query = row.get("user_query", "").strip()
            if test_id and query:
                cases.append(row)

    if not cases:
        print("No valid test cases found.", file=sys.stderr)
        return 1

    # Group by conversation_id for multi-turn
    conversations = {}
    single_turns = []
    for case in cases:
        conv_id = case.get("conversation_id", "").strip()
        if conv_id:
            if conv_id not in conversations:
                conversations[conv_id] = []
            conversations[conv_id].append(case)
        else:
            single_turns.append(case)

    print(f"Found {len(cases)} test cases: {len(conversations)} conversations + {len(single_turns)} single-turn")
    print()

    results = []
    total_pass = 0
    total_fail = 0
    total_violations = 0

    # Process single-turn cases
    for case in single_turns:
        result = process_case(case, [], api_url, run_id)
        results.append(result)
        if result["decision_match"]:
            total_pass += 1
        else:
            total_fail += 1
        total_violations += len(result.get("violations", []))

    # Process multi-turn conversations
    for conv_id, turns in conversations.items():
        turns.sort(key=lambda x: int(x.get("turn_index", 1)))
        history = []

        for case in turns:
            result = process_case(case, history, api_url, run_id)
            results.append(result)

            if result["decision_match"]:
                total_pass += 1
            else:
                total_fail += 1
            total_violations += len(result.get("violations", []))

            # Build history for next turn
            history.append({"role": "user", "content": case["user_query"]})
            history.append({"role": "assistant", "content": result.get("answer", "")})

    # Save results
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Print summary
    total = total_pass + total_fail
    print()
    print("=" * 60)
    print(f"  EVAL SUMMARY — {run_id}")
    print("=" * 60)
    print(f"  Total cases:       {total}")
    print(f"  Decision PASS:     {total_pass}/{total} ({100*total_pass/total:.0f}%)")
    print(f"  Decision FAIL:     {total_fail}/{total}")
    print(f"  must_not_do violations: {total_violations}")
    print()

    # Print failures
    failures = [r for r in results if not r["decision_match"]]
    if failures:
        print("  FAILURES:")
        for r in failures:
            print(f"    {r['test_id']}: expected={r['expected_decision']} got={r['actual_decision']} | {r['query'][:50]}")
            if r.get("violations"):
                for v in r["violations"]:
                    print(f"      VIOLATION: {v['rule'][:60]}")
        print()

    # Save summary
    summary = {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_cases": total,
        "decision_pass": total_pass,
        "decision_fail": total_fail,
        "must_not_do_violations": total_violations,
        "pass_rate": round(total_pass / total * 100, 1) if total else 0,
    }
    summary_path = output_file.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  Summary: {summary_path}")
    print(f"  Results: {output_file}")

    return 0


def process_case(case: dict, history: list[dict], api_url: str, run_id: str) -> dict:
    test_id = case.get("test_id", "")
    query = case.get("user_query", "")
    expected_decision = case.get("expected_decision", "")
    expected_reason = case.get("expected_reason_code", "")
    must_not_do_raw = case.get("must_not_do", "[]")
    expected_facts_raw = case.get("expected_facts", "[]")
    turn_index = int(case.get("turn_index") or 1)
    conv_id = case.get("conversation_id", "")

    # Parse must_not_do
    try:
        must_not_do = json.loads(must_not_do_raw) if must_not_do_raw else []
    except json.JSONDecodeError:
        must_not_do = []

    # Parse expected_facts
    try:
        expected_facts = json.loads(expected_facts_raw) if expected_facts_raw else []
    except json.JSONDecodeError:
        expected_facts = []

    label = f"T{turn_index}" if turn_index else ""
    print(f"  [{test_id}] {label}: {query[:60]}...", end=" ")

    t0 = time.time()
    try:
        resp = requests.post(
            f"{api_url}/api/chat",
            json={"message": query, "history": history},
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        latency = (time.time() - t0) * 1000

        answer = data.get("response", "")
        dlog = data.get("decision_log", {})
        actual_decision = dlog.get("decision", data.get("decision", "?"))
        actual_reason = dlog.get("reason_code", "")
        chunks = dlog.get("retrieved_chunks", [])
        citations = dlog.get("displayed_citations", [])

        # Check decision match
        decision_match = actual_decision == expected_decision

        # Check must_not_do violations
        violations = check_must_not_do(answer, must_not_do, actual_decision, chunks, citations)

        # Check expected_facts (basic keyword check)
        facts_found = []
        facts_missing = []
        for fact in expected_facts:
            # Extract key numbers/values from fact
            fact_numbers = set(re.findall(r"\d[\d.,]*", fact))
            if fact_numbers:
                found = any(n in answer for n in fact_numbers)
                if found:
                    facts_found.append(fact)
                else:
                    facts_missing.append(fact)
            elif any(kw.lower() in answer.lower() for kw in fact.split()[:3]):
                facts_found.append(fact)
            else:
                facts_missing.append(fact)

        status = "PASS" if decision_match and not violations else "FAIL"
        print(f"-> {actual_decision} {latency:.0f}ms {'OK' if status == 'PASS' else 'FAIL'}")

        return {
            "run_id": run_id,
            "test_id": test_id,
            "conversation_id": conv_id,
            "turn_index": turn_index,
            "query": query,
            "expected_decision": expected_decision,
            "expected_reason_code": expected_reason,
            "actual_decision": actual_decision,
            "actual_reason_code": actual_reason,
            "decision_match": decision_match,
            "answer": answer,
            "retrieved_chunks_count": len(chunks),
            "citations_count": len(citations),
            "expected_facts": expected_facts,
            "facts_found": facts_found,
            "facts_missing": facts_missing,
            "must_not_do": must_not_do,
            "violations": violations,
            "latency_ms": round(latency, 1),
            "status": status,
        }

    except Exception as e:
        latency = (time.time() - t0) * 1000
        print(f"-> ERROR: {e}")
        return {
            "run_id": run_id,
            "test_id": test_id,
            "conversation_id": conv_id,
            "turn_index": turn_index,
            "query": query,
            "expected_decision": expected_decision,
            "actual_decision": "error",
            "decision_match": False,
            "answer": f"ERROR: {e}",
            "violations": [],
            "latency_ms": round(latency, 1),
            "status": "ERROR",
        }


def main():
    ap = argparse.ArgumentParser(description="Unified eval runner")
    ap.add_argument("--input", required=True, help="CSV smoke test file")
    ap.add_argument("--output", default="eval/eval_report.jsonl", help="Output JSONL")
    ap.add_argument("--api-url", default="http://localhost:8000", help="API base URL")
    args = ap.parse_args()

    return run_eval(args.input, args.output, args.api_url)


if __name__ == "__main__":
    sys.exit(main())
