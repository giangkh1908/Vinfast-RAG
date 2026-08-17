#!/usr/bin/env python3
"""Benchmark runner — đánh giá hệ thống theo `eval/benchmark/*.json`.

Benchmark là bộ câu hỏi + ground-truth độc lập (viết từ dữ liệu nguồn), không
phải từ hành vi code. File này tính metric:
  - decision_accuracy : đúng expected_decision (+ reason nếu clarify)
  - fact_recall        : tỷ lệ expected_facts xuất hiện trong data/answer
  - grounded_model     : data lấy về đúng model kỳ vọng (chống trộn model)
  - no_data            : case "không có dữ liệu" (VD số chỗ VF6) KHÔNG được trả số
  - negative_violations: must_not xuất hiện (chỉ đo ở live/answer mode)

Hai mode:
  1) OFFLINE (mặc định) — classify + tool plan + get_specs, KHÔNG cần LLM:
     kiểm tra decision/model/version + đúng dữ liệu model + không lọt dữ liệu giả.
  2) LIVE (--api-url http://localhost:8000) — chạy pipeline thật, kiểm tra câu
     trả lời chứa expected_facts và KHÔNG chứa must_not (đo LLM/ảo giác).

Usage:
    python eval/benchmark/run_benchmark.py --set eval/benchmark/benchmark_v1.json
    python eval/benchmark/run_benchmark.py --set ... --api-url http://localhost:8000
"""
import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


# ═════════════── OFFLINE HELPERS ════════════════
async def _no_llm(query, history):
    return None


def _norm_model(name):
    from app.agent.classifier import normalize_model
    return normalize_model(name) if name else None


async def _classify_offline(query, history):
    import app.agent.nodes.classify as cf
    cf.llm_classify_fallback = _no_llm
    from app.agent.nodes.classify import classify_node
    return await classify_node({"query": query, "history": history})


async def _fetch_specs(st):
    """Execute tool plan (offline) → (spec_model, spec_text)."""
    from app.agent.direct_plan import build_tool_plan
    from app.agent.tools import get_specs
    plan = build_tool_plan(st)
    if not plan:
        return None, ""
    spec_texts, spec_model = [], None
    for tool, args in plan:
        if tool == "get_specs":
            r = await get_specs(**args)
            spec_model = r.get("model_code") or spec_model
            for s in r.get("specs", []):
                if s.get("value") and s["value"] != "Không":
                    spec_texts.append(f"{s.get('key')}: {s['value']}")
        elif tool == "get_price":
            spec_model = spec_model or (args.get("model_code"))
    return spec_model, " | ".join(spec_texts)


# ═══════════════ CHECK FUNCTIONS ════════════════
def _check_routing(st, exp) -> dict:
    got_decision = st.get("decision")
    got_reason = st.get("reason_code") or ""
    got_model = st.get("entities", {}).get("model_code")
    got_version = st.get("entities", {}).get("version")

    checks = {}
    checks["decision"] = (got_decision == exp.get("decision"))
    checks["reason"] = (not exp.get("reason_code")) or (exp["reason_code"] in got_reason)
    checks["model"] = True
    e_model = exp.get("model")
    if e_model:
        checks["model"] = (_norm_model(got_model) == _norm_model(e_model))
    if exp.get("version"):
        checks["version"] = (got_version == exp["version"])
    return checks, got_decision, got_reason, got_model, got_version


def _check_offline_content(st, exp, spec_model, spec_text) -> dict:
    checks = {}
    # data lấy về đúng model kỳ vọng (chống trộn model)
    checks["grounded_model"] = True
    if exp.get("model") and (st.get("decision") == "answer") and spec_model:
        checks["grounded_model"] = (_norm_model(spec_model) == _norm_model(exp["model"]))

    # expected_facts phải có trong data trả về
    facts = exp.get("facts") or []
    checks["facts_present"] = (
        all(f.lower() in spec_text.lower() for f in facts) if facts else True
    )

    # anti-hallucination: các spec_key không-có-dữ-liệu phải ABSENT (không số giả)
    absent_keys = exp.get("absent_spec_keys") or []
    checks["no_data"] = True
    if absent_keys:
        for k in absent_keys:
            if re.search(rf"\b{re.escape(k)}\s*:\s*\S+", spec_text):
                checks["no_data"] = False
                break
    return checks


def _check_live_answer(answer, exp) -> dict:
    a = (answer or "").lower()
    checks = {}
    facts = exp.get("facts") or []
    checks["facts_present"] = all(f.lower() in a for f in facts) if facts else True
    neg = exp.get("must_not") or []
    checks["negatives_absent"] = not any(n.lower() in a for n in neg) if neg else True
    return checks


async def _run_case_offline(case) -> dict:
    query = case["query"]
    exp = case["expected"]
    st = await _classify_offline(query, case.get("history", []))
    r_checks, dec, reason, model, version = _check_routing(st, exp)

    spec_model, spec_text = None, ""
    if st.get("decision") == "answer":
        spec_model, spec_text = await _fetch_specs(st)
    c_checks = _check_offline_content(st, exp, spec_model, spec_text)
    checks = {**r_checks, **c_checks}

    return {
        "case": case.get("id", "?"), "query": query,
        "decision": dec, "reason": reason, "model": model, "version": version,
        "spec_model": spec_model, "checks": checks,
        "pass": all(checks.values()),
    }


async def _run_case_live(case, api_url) -> dict:
    import requests
    query = case["query"]
    exp = case["expected"]
    payload = {"message": query, "history": case.get("history", [])}
    try:
        r = requests.post(f"{api_url}/api/chat", json=payload, timeout=120)
        r.raise_for_status()
        data = r.json()
        answer = data.get("response", "")
        dlog = data.get("decision_log", {})
        got_decision = dlog.get("decision", data.get("decision", "?"))
        got_reason = dlog.get("reason_code", "")
    except Exception as e:  # noqa: BLE001
        return {"case": case.get("id", "?"), "query": query, "error": str(e), "pass": False}

    checks = {
        "decision": (got_decision == exp.get("decision")),
        "reason": (not exp.get("reason_code")) or (exp["reason_code"] in got_reason),
        **_check_live_answer(answer, exp),
    }
    return {
        "case": case["id"], "query": query, "answer": answer[:120],
        "decision": got_decision, "reason": got_reason, "checks": checks,
        "pass": all(checks.values()),
    }


async def run_benchmark(path: Path, api_url: str | None) -> int:
    bench = json.loads(path.read_text(encoding="utf-8"))
    cases = bench.get("cases", [])
    conversations = bench.get("conversations", [])
    print(f"\n▸ Benchmark: {bench['meta']['name']}")
    print(f"▸ Ground truth: {bench['meta']['ground_truth_source']}")
    print(f"▸ Mode: {'LIVE (' + api_url + ')' if api_url else 'OFFLINE'}")

    results = []
    # single-turn
    for c in cases:
        res = await (_run_case_live(c, api_url) if api_url else _run_case_offline(c))
        results.append(res)

    # multi-turn
    for conv in conversations:
        history = []
        turn_ok = True
        for t in conv["turns"]:
            t["history"] = history
            res = await (_run_case_live(t, api_url) if api_url else _run_case_offline(t))
            res["case"] = f"{conv['id']}-{conv['turns'].index(t)+1}"
            results.append(res)
            if not res["pass"]:
                turn_ok = False
            history.append({"role": "user", "content": t["query"]})
            history.append({"role": "assistant", "content": "(assistant)"})
        results.append({"case": f"{conv['id']}", "query": conv["name"], "group": True,
                        "pass": turn_ok, "checks": {},
                        "turns_ok": sum(1 for _ in conv['turns'])})

    # ── Metrics ──
    unit = [r for r in results if not r.get("group")]
    n_pass = sum(1 for r in unit if r.get("pass"))
    decision_ok = sum(1 for r in unit if r["checks"].get("decision"))
    fact_ok = sum(1 for r in unit if r["checks"].get("facts_present", True))
    neg_total = sum(1 for r in unit if r["checks"].get("negatives_absent") is not None)
    neg_ok = sum(1 for r in unit if r["checks"].get("negatives_absent"))

    print("\n" + "=" * 66)
    for r in unit:
        if r.get("error"):
            print(f"  [ERR] {r['case']}: {r['error']}")
            continue
        flag = "OK " if r["pass"] else "FAIL"
        fails = [k for k, v in r["checks"].items() if not v]
        extra = f"  ✗{fails}" if fails else ""
        print(f"  [{flag}] {r['case']:12} {r['query'][:44]:46} dec={r.get('decision')} model={r.get('model')}{extra}")
    groups = [r for r in results if r.get("group")]
    for g in groups:
        print(f"  [{'OK ' if g['pass'] else 'FAIL'}] {g['case']} (multi-turn) {'✓' if g['pass'] else '✗'}")

    print("=" * 66)
    tot = len(unit)
    print(f"\n  Case pass          : {n_pass}/{tot} ({100*n_pass/tot:.0f}%)")
    print(f"  Decision accuracy  : {decision_ok}/{tot} ({100*decision_ok/tot:.0f}%)")
    print(f"  Fact present (recall): {fact_ok}/{tot} ({100*fact_ok/tot:.0f}%)")
    if neg_total:
        print(f"  Negative constraint: {neg_ok}/{neg_total}")
    if groups:
        print(f"  Multi-turn convs   : {sum(1 for g in groups if g['pass'])}/{len(groups)}")
    return 0 if n_pass == tot else 1


def main():
    ap = argparse.ArgumentParser(description="Run VinFast benchmark")
    ap.add_argument("--set", default=str(REPO_ROOT / "eval/benchmark/benchmark_v1.json"))
    ap.add_argument("--api-url", default=None, help="Live API URL để đánh giá answer (mặc định offline)")
    args = ap.parse_args()
    return asyncio.run(run_benchmark(Path(args.set), args.api_url))


if __name__ == "__main__":
    sys.exit(main())
