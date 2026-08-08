#!/usr/bin/env python3
"""
ragas_eval.py — Automated eval using RAGAS metrics.

Runs test cases through the agent, collects (question, answer, contexts, ground_truth),
then scores with RAGAS.

Usage:
    python scripts/ragas_eval.py --input eval/golden_dataset.csv --output eval/ragas_results.jsonl
    python scripts/ragas_eval.py --input eval/golden_dataset.csv --output eval/ragas_results.jsonl --api-url http://localhost:8000
"""

import argparse
import json
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests


def run_eval(input_path: str, output_path: str, api_url: str):
    input_file = Path(input_path)
    output_file = Path(output_path)

    if not input_file.exists():
        print(f"Input file not found: {input_file}", file=sys.stderr)
        return 1

    run_id = f"eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    print(f"[ragas_eval] run_id={run_id}")
    print(f"[ragas_eval] input={input_file}")
    print(f"[ragas_eval] output={output_file}")
    print()

    # Load golden dataset
    df = pd.read_csv(input_file)
    required_cols = {"test_id", "user_query", "expected_answer"}
    if not required_cols.issubset(set(df.columns)):
        print(f"CSV must have columns: {required_cols}", file=sys.stderr)
        return 1

    print(f"Found {len(df)} test cases")
    print()

    # Run each test case through agent
    questions = []
    answers = []
    contexts_list = []
    ground_truths = []
    test_ids = []
    latencies = []

    for i, row in df.iterrows():
        test_id = row["test_id"]
        query = row["user_query"]
        expected = row["expected_answer"]

        print(f"[{i+1}/{len(df)}] {test_id}: {query[:50]}...", end=" ")

        t0 = time.time()
        try:
            resp = requests.post(
                f"{api_url}/api/chat",
                json={"message": query, "history": []},
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()
            latency = (time.time() - t0) * 1000

            answer = data.get("response", "")
            dlog = data.get("decision_log", {})
            chunks = dlog.get("retrieved_chunks", [])

            # Extract contexts from retrieved chunks
            context_texts = [c.get("content", "") for c in chunks if c.get("content")]

            questions.append(query)
            answers.append(answer)
            contexts_list.append(context_texts)
            ground_truths.append(expected)
            test_ids.append(test_id)
            latencies.append(latency)

            decision = dlog.get("decision", "?")
            print(f"-> {decision} {latency:.0f}ms ({len(chunks)} chunks)")

        except Exception as e:
            latency = (time.time() - t0) * 1000
            questions.append(query)
            answers.append(f"ERROR: {e}")
            contexts_list.append([])
            ground_truths.append(expected)
            test_ids.append(test_id)
            latencies.append(latency)
            print(f"-> ERROR: {e}")

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
            for i, row in df.iterrows():
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

        print(f"[ragas_eval] Results saved to {output_file}")

        # Save summary
        summary = {
            "run_id": run_id,
            "timestamp": datetime.now().isoformat(),
            "total_cases": len(questions),
            "avg_faithfulness": round(float(scores["faithfulness"].mean()), 3),
            "avg_answer_relevancy": round(float(scores["answer_relevancy"].mean()), 3),
            "avg_context_precision": round(float(scores["context_precision"].mean()), 3),
            "avg_context_recall": round(float(scores["context_recall"].mean()), 3),
            "avg_latency_ms": round(sum(latencies) / len(latencies), 1),
        }
        summary_path = output_file.with_suffix(".summary.json")
        summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[ragas_eval] Summary saved to {summary_path}")

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
        print(f"[ragas_eval] Raw results saved to {output_file}")
        return 1

    return 0


def main():
    ap = argparse.ArgumentParser(description="RAGAS eval runner")
    ap.add_argument("--input", required=True, help="CSV with test_id,user_query,expected_answer")
    ap.add_argument("--output", default="eval/ragas_results.jsonl", help="Output JSONL")
    ap.add_argument("--api-url", default="http://localhost:8000", help="API base URL")
    args = ap.parse_args()

    return run_eval(args.input, args.output, args.api_url)


if __name__ == "__main__":
    sys.exit(main())
