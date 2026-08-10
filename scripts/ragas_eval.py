#!/usr/bin/env python3
"""
ragas_eval.py — Automated eval using RAGAS metrics.

Supports two input formats:
1. golden_dataset.csv: test_id, user_query, expected_answer
2. smoke_test.csv: test_id, user_query, expected_facts (JSON array), expected_decision

Usage:
    python scripts/ragas_eval.py --input eval/smoke_test.csv --output eval/ragas_results.jsonl
    python scripts/ragas_eval.py --input eval/golden_dataset.csv --output eval/ragas_results.jsonl
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


def load_test_cases(input_path: str) -> list[dict]:
    """Load test cases from CSV. Auto-detect format."""
    cases = []
    with open(input_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            test_id = row.get("test_id", "").strip()
            query = row.get("user_query", "").strip()
            if not test_id or not query:
                continue

            # Format 1: golden_dataset.csv (has expected_answer)
            if "expected_answer" in row:
                ground_truth = row["expected_answer"].strip()
            # Format 2: smoke_test.csv (has expected_facts as JSON array)
            elif "expected_facts" in row:
                try:
                    facts = json.loads(row["expected_facts"])
                    ground_truth = ". ".join(facts) if facts else ""
                except json.JSONDecodeError:
                    ground_truth = row["expected_facts"].strip()
            else:
                ground_truth = ""

            # Skip cases without ground_truth (clarify/refuse/OOS)
            expected_decision = row.get("expected_decision", "").strip()
            if expected_decision in ("clarify", "refuse", "out_of_scope"):
                continue
            if not ground_truth:
                continue

            cases.append({
                "test_id": test_id,
                "query": query,
                "ground_truth": ground_truth,
                "expected_decision": expected_decision,
                "conversation_id": row.get("conversation_id", "").strip(),
                "turn_index": int(row.get("turn_index", 1) or 1),
            })

    return cases


def run_eval(input_path: str, output_path: str, api_url: str):
    input_file = Path(input_path)
    output_file = Path(output_path)

    if not input_file.exists():
        print(f"Input file not found: {input_file}", file=sys.stderr)
        return 1

    run_id = f"ragas_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    print(f"[ragas_eval] run_id={run_id}")
    print(f"[ragas_eval] input={input_file}")
    print(f"[ragas_eval] output={output_file}")
    print()

    cases = load_test_cases(str(input_file))
    if not cases:
        print("No evaluable test cases found (need answer-type cases with ground_truth).", file=sys.stderr)
        return 1

    print(f"Found {len(cases)} evaluable cases (answer-type with ground_truth)")
    print()

    # Group by conversation for multi-turn
    conversations = {}
    singles = []
    for case in cases:
        conv_id = case.get("conversation_id", "")
        if conv_id:
            if conv_id not in conversations:
                conversations[conv_id] = []
            conversations[conv_id].append(case)
        else:
            singles.append(case)

    # Run test cases
    questions = []
    answers = []
    contexts_list = []
    ground_truths = []
    test_ids = []
    latencies = []

    # Single-turn cases
    for case in singles:
        result = run_single_case(case, [], api_url)
        questions.append(result["query"])
        answers.append(result["answer"])
        contexts_list.append(result["contexts"])
        ground_truths.append(result["ground_truth"])
        test_ids.append(result["test_id"])
        latencies.append(result["latency_ms"])

    # Multi-turn cases
    for conv_id, turns in conversations.items():
        turns.sort(key=lambda x: x["turn_index"])
        history = []
        for case in turns:
            result = run_single_case(case, history, api_url)
            questions.append(result["query"])
            answers.append(result["answer"])
            contexts_list.append(result["contexts"])
            ground_truths.append(result["ground_truth"])
            test_ids.append(result["test_id"])
            latencies.append(result["latency_ms"])
            history.append({"role": "user", "content": case["query"]})
            history.append({"role": "assistant", "content": result["answer"]})

    print()

    # Run RAGAS evaluation
    print("[ragas_eval] Running RAGAS scoring...")

    try:
        from ragas import evaluate
        from ragas.metrics import faithfulness, answer_relevancy, context_precision, context_recall
        from datasets import Dataset

        eval_dataset = Dataset.from_dict({
            "question": questions,
            "answer": answers,
            "contexts": contexts_list,
            "ground_truth": ground_truths,
        })

        result = evaluate(
            eval_dataset,
            metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
        )

        scores = result.to_pandas()
        print()
        print("=== RAGAS Scores ===")
        print(f"  Faithfulness:      {scores['faithfulness'].mean():.3f}")
        print(f"  Answer Relevancy:  {scores['answer_relevancy'].mean():.3f}")
        print(f"  Context Precision: {scores['context_precision'].mean():.3f}")
        print(f"  Context Recall:    {scores['context_recall'].mean():.3f}")
        print()

        # Save detailed results
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with output_file.open("w", encoding="utf-8") as f:
            for i in range(len(questions)):
                record = {
                    "run_id": run_id,
                    "test_id": test_ids[i],
                    "user_query": questions[i],
                    "answer": answers[i],
                    "ground_truth": ground_truths[i],
                    "contexts": contexts_list[i],
                    "latency_ms": round(latencies[i], 1),
                    "faithfulness": float(scores.iloc[i]["faithfulness"]) if i < len(scores) else None,
                    "answer_relevancy": float(scores.iloc[i]["answer_relevancy"]) if i < len(scores) else None,
                    "context_precision": float(scores.iloc[i]["context_precision"]) if i < len(scores) else None,
                    "context_recall": float(scores.iloc[i]["context_recall"]) if i < len(scores) else None,
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

        # Save summary
        summary = {
            "run_id": run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_cases": len(questions),
            "avg_faithfulness": round(float(scores["faithfulness"].mean()), 3),
            "avg_answer_relevancy": round(float(scores["answer_relevancy"].mean()), 3),
            "avg_context_precision": round(float(scores["context_precision"].mean()), 3),
            "avg_context_recall": round(float(scores["context_recall"].mean()), 3),
            "avg_latency_ms": round(sum(latencies) / len(latencies), 1),
        }
        summary_path = output_file.with_suffix(".summary.json")
        summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[ragas_eval] Results: {output_file}")
        print(f"[ragas_eval] Summary: {summary_path}")

    except Exception as e:
        print(f"[ragas_eval] RAGAS scoring failed: {e}", file=sys.stderr)
        print("[ragas_eval] Saving raw results without RAGAS scores...")
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with output_file.open("w", encoding="utf-8") as f:
            for i in range(len(questions)):
                record = {
                    "run_id": run_id,
                    "test_id": test_ids[i],
                    "user_query": questions[i],
                    "answer": answers[i],
                    "ground_truth": ground_truths[i],
                    "contexts": contexts_list[i],
                    "latency_ms": round(latencies[i], 1),
                    "ragas_error": str(e),
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"[ragas_eval] Raw results: {output_file}")

    return 0


def run_single_case(case: dict, history: list[dict], api_url: str) -> dict:
    query = case["query"]
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
        chunks = dlog.get("retrieved_chunks", [])
        context_texts = [c.get("content", "") for c in chunks if c.get("content")]

        print(f"  {case['test_id']}: {dlog.get('decision', '?')} {latency:.0f}ms ({len(chunks)} chunks)")

        return {
            "test_id": case["test_id"],
            "query": query,
            "answer": answer,
            "contexts": context_texts,
            "ground_truth": case["ground_truth"],
            "latency_ms": latency,
        }
    except Exception as e:
        latency = (time.time() - t0) * 1000
        print(f"  {case['test_id']}: ERROR {e}")
        return {
            "test_id": case["test_id"],
            "query": query,
            "answer": f"ERROR: {e}",
            "contexts": [],
            "ground_truth": case["ground_truth"],
            "latency_ms": latency,
        }


def main():
    ap = argparse.ArgumentParser(description="RAGAS eval runner")
    ap.add_argument("--input", required=True, help="CSV test file")
    ap.add_argument("--output", default="eval/ragas_results.jsonl", help="Output JSONL")
    ap.add_argument("--api-url", default="http://localhost:8000", help="API base URL")
    args = ap.parse_args()

    return run_eval(args.input, args.output, args.api_url)


if __name__ == "__main__":
    sys.exit(main())
