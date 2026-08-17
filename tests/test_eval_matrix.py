"""Eval-matrix + regression tests, rút từ scripts/eval và eval/*.csv.

Chạy OFFLINE (không cần LLM/network cho phần routing):
- Stub `llm_classify_fallback` → classify_node chạy thuần rules (deterministic).
- Kiểm tra golden matrix (eval/smoke_test.csv): expected_decision + reason_code
  + model resolution theo từng turn (multi-turn).
- Regression tests cho các bug đã sửa trong session:
    * VF 8 All New (aliases: "vf8 new", "vf 8 thế hệ mới", "vf8 the new")
    * VF MPV 7 capitalization ("vf mpv 7" → "VF MPV 7")
    * Số chỗ ngồi → interior (KHÔNG phải dimension)
    * Memory recency (follow-up "pin xe bao nhiêu" sau "vf8 thì sao" → VF 8)
    * Shortlink "Xem thêm" (source_link_md → [VF 6](url))
- Data correctness (get_specs) cho một vài case — cần DB reachable, nếu không
  sẽ SKIP (không tính fail).

Run: python tests/test_eval_matrix.py
"""
import sys, os, io, asyncio, time, csv, json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PASS = 0
FAIL = 0
SKIP = 0
ERRORS = []


def report(tid, passed, step, detail):
    global PASS, FAIL, ERRORS
    if passed:
        PASS += 1
        print(f"  [OK]   {tid}: {detail}")
    else:
        FAIL += 1
        ERRORS.append(f"{tid}: {step} — {detail}")
        print(f"  [FAIL] {tid}: {step} — {detail}")


def report_skip(tid, step, detail):
    global SKIP
    SKIP += 1
    print(f"  [SKIP] {tid}: {step} — {detail}")


# ═══════════════════════════════════════════════════════════════
# 1) OFFLOAD: stub LLM fallback để classify_node chạy thuần rules
# ═══════════════════════════════════════════════════════════════
async def _no_llm(query, history):
    return None


def _install_offline_stub():
    import app.agent.nodes.classify as cf
    cf.llm_classify_fallback = _no_llm


# State deterministic (không LLM) cho regression unit tests
def build_deterministic_state(query: str, history: list[dict] = None) -> dict:
    from app.agent.classifier import get_classifier
    from app.agent.nodes.classify import _classify_topic, _extract_history_context
    from app.agent.intent import classify_intent, extract_spec_category

    history = history or []
    cr = get_classifier().classify(query, history)
    entities = dict(cr.entities)
    topic = _classify_topic(query)
    intent = classify_intent(query, topic)
    if intent == "general" and extract_spec_category(query):
        intent = "spec_query"
    # kế thừa model/version từ history (same logic như classify_node)
    if not entities.get("model_code") or not entities.get("version"):
        hc = _extract_history_context(history)
        entities.setdefault("model_code", hc.get("model_code"))
        entities.setdefault("version", hc.get("version"))
    return {"query": query, "history": history, "intent": intent,
            "category": topic, "entities": entities}


# ═══════════════════════════════════════════════════════════════
# 2) GOLDEN MATRIX (eval/smoke_test.csv)
# ═══════════════════════════════════════════════════════════════
# Drift CHỦ ĐỊNH so với golden: code hiện tại (rule 14) tự trả lời bản mặc định
# thay vì hỏi lại version. Golden cũ kỳ vọng clarify/missing_version.
KNOWN_DRIFT = {
    "TF-CL-02-T1": {
        "expected_decision": "answer",
        "expected_reason_code": "sufficient_direct_evidence",
        "note": "Rule 14 default-version: không hỏi lại version khi user không nêu",
    },
}


def _load_smoke_csv() -> list[dict]:
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "eval", "smoke_test.csv")
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


async def test_golden_matrix():
    from app.agent.nodes.classify import classify_node
    from app.agent.classifier import normalize_model

    print("\n═══ 1. GOLDEN MATRIX (eval/smoke_test.csv) ═══")
    rows = _load_smoke_csv()
    if not rows:
        report("EVM-CSV", False, "load", "eval/smoke_test.csv rỗng/không đọc được")
        return

    # Group theo conversation_id để chạy multi-turn đúng thứ tự
    convs, singles = {}, []
    for r in rows:
        cid = (r.get("conversation_id") or "").strip()
        (convs.setdefault(cid, []) if cid else singles).append(r)

    async def run_case(case, history):
        tid = case.get("test_id", "")
        query = case.get("user_query", "")
        exp_decision = (case.get("expected_decision") or "").strip()
        exp_reason = (case.get("expected_reason_code") or "").strip()
        exp_model = (case.get("vehicle_model") or "").strip()

        st = await classify_node({"query": query, "history": history})
        got_decision = st.get("decision")
        got_reason = st.get("reason_code") or ""
        got_model = st.get("entities", {}).get("model_code")

        # Áp drift chủ định
        eff_exp = exp_decision
        eff_reason = exp_reason
        note = ""
        if tid in KNOWN_DRIFT:
            d = KNOWN_DRIFT[tid]
            eff_exp = d["expected_decision"]
            eff_reason = d["expected_reason_code"]
            note = f" [drift: {d['note']}]"

        decision_ok = got_decision == eff_exp
        reason_ok = (not eff_reason) or (eff_reason in (got_reason or ""))
        model_ok = True
        if exp_model and exp_model.lower() not in ("unknown", "multiple"):
            model_ok = normalize_model(got_model) == normalize_model(exp_model)

        passed = decision_ok and reason_ok and model_ok
        model_shown = got_model if exp_model and exp_model.lower() in ("unknown", "multiple") else f"{got_model} (exp {exp_model})"
        report(f"{tid}", passed, "evaluate",
               f"exp={eff_exp}/{eff_reason} got={got_decision}/{got_reason} "
               f"model={model_shown}" + (note or ""))
        return st

    # Single-turn
    for case in singles:
        await run_case(case, [])

    # Multi-turn
    for cid, turns in convs.items():
        turns.sort(key=lambda x: int(x.get("turn_index") or 1))
        history = []
        for case in turns:
            await run_case(case, history)
            history.append({"role": "user", "content": case.get("user_query", "")})
            history.append({"role": "assistant", "content": "(assistant)"})


# ═══════════════════════════════════════════════════════════════
# 3) REGRESSION — model naming / category / memory / shortlink
# ═══════════════════════════════════════════════════════════════
def test_model_naming():
    from app.agent.classifier import get_classifier, normalize_model

    print("\n═══ 2. REGRESSION: MODEL NAMING / ROUTING ═══")
    cases = [
        # (query, expected_model)
        ("thông số vf8 new", "VF 8 All New"),
        ("vf 8 thế hệ mới", "VF 8 All New"),
        ("vf8 the new", "VF 8 All New"),
        ("vf8 all new", "VF 8 All New"),
        ("thông số vf8", "VF 8"),
        ("vf mpv 7", "VF MPV 7"),
        ("VF MPV 7", "VF MPV 7"),
        ("vf8 eco", "VF 8"),
        ("giá vf9 plus", "VF 9"),
    ]
    for q, exp in cases:
        got = get_classifier().classify(q).entities.get("model_code")
        report(f"NM-{exp.replace(' ', '')}-{q[:12]}", normalize_model(got) == normalize_model(exp),
               "classify", f"{q!r} → {got!r} (exp {exp!r})")


def test_seats_category():
    from app.agent.intent import extract_spec_category
    from app.agent.nodes.classify import _classify_topic
    from app.agent.direct_plan import build_tool_plan

    print("\n═══ 3. REGRESSION: SỐ CHỖ NGỒI → INTERIOR ═══")
    for q in ["VF 6 có mấy chỗ ngồi", "VF 9 mấy chỗ", "VF 8 có mấy chỗ ngồi"]:
        cat = extract_spec_category(q)
        topic = _classify_topic(q)
        report(f"SE-{q[:16]}", cat == "interior" and topic == "nội_thất",
               "route", f"spec_category={cat}, topic={topic} (exp interior/nội_thất)")

    # Plan cho "VF 6 có mấy chỗ ngồi" → get_specs(model VF 6, category interior)
    st = build_deterministic_state("VF 6 có mấy chỗ ngồi")
    plan = build_tool_plan(st)
    ok = (plan and plan[0][0] == "get_specs"
          and plan[0][1].get("model_code") == "VF 6"
          and plan[0][1].get("category") == "interior")
    report("SE-PLAN", ok, "plan", f"plan={plan} (exp get_specs(VF 6, interior))")


def test_memory_recency():
    from app.agent.nodes.classify import _extract_history_context

    print("\n═══ 4. REGRESSION: MEMORY RECENCY (short-term ưu tiên) ═══")
    history = [
        {"role": "user", "content": "vf6 có mấy chỗ ngồi"},
        {"role": "assistant", "content": "VF 6 chưa có dữ liệu chỗ ngồi"},
        {"role": "user", "content": "xe này thông số ra sao"},
        {"role": "assistant", "content": "VF 6 thông số..."},
        {"role": "user", "content": "vf8 thì sao"},
        {"role": "assistant", "content": "VF 8 thông số..."},
    ]
    ctx = _extract_history_context(history)
    # follow-up "pin xe bao nhiêu" không nhắc model → phải kế thừa VF 8 (mới nhất)
    report("MEM-01", ctx.get("model_code") == "VF 8",
           "history", f"model={ctx.get('model_code')} (exp VF 8 — mới nhất, không phải VF 6)")

    # Trường hợp chưa đổi model → vẫn VF 6
    hist2 = history[:4]
    ctx2 = _extract_history_context(hist2)
    report("MEM-02", ctx2.get("model_code") == "VF 6",
           "history", f"model={ctx2.get('model_code')} (exp VF 6)")


def test_source_link():
    from app.agent.nodes.respond import source_link_md, _source_link_label

    print("\n═══ 5. REGRESSION: SHORTLINK 'XEM THÊM' ═══")
    urls = [
        ("https://storage.googleapis.com/vinfast-data-01/brochure/14052026/VF%206_Brochure_Final_130526%20(12AM)_compressed.pdf", "VF 6"),
        (".../VF8_Brochure_03022026.pdf", None),  # không parse hostname vì URL fake → chỉ check không crash
        ("https://static-cms-prod.vinfastauto.com/brochure/26052026/VF%208%20The%20he%20moi_Brochure_final%2020.05.pdf", "VF 8 All New"),
        ("https://storage.googleapis.com/vinfast-data-01/brochure/VF_MPV%207_Brochure_2026.02.03.pdf", "VF MPV 7"),
    ]
    for url, exp in urls:
        label = _source_link_label(url)
        ok = (exp is None) or (label == exp)
        report(f"LINK-{exp or 'noop'}", ok, "label", f"{label!r} (exp {exp!r})")
        md = source_link_md(url)
        report(f"MD-{exp or 'noop'}", exp is None or f"[{exp}](" in md,
               "markdown", f"{md[:60]}...")


# ═══════════════════════════════════════════════════════════════
# 4) DATA CORRECTNESS (get_specs) — cần DB, SKIP nếu không reachable
# ═══════════════════════════════════════════════════════════════
def _db_reachable() -> bool:
    try:
        import os
        from pathlib import Path
        for line in Path(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")).read_text(encoding="utf-8").splitlines():
            if line.startswith("PG_DSN="):
                os.environ["PG_DSN"] = line.split("=", 1)[1].strip()
        import psycopg2
        conn = psycopg2.connect(os.environ["PG_DSN"])
        conn.close()
        return True
    except Exception:
        return False


async def test_data_correctness():
    print("\n═══ 6. DATA CORRECTNESS (get_specs, DB) ═══")
    if not _db_reachable():
        report_skip("DATA", "db", "DB không reachable — skip phần data correctness")
        return

    from app.agent.tools import get_specs

    # VF 6: sau khi lọc sentinel 'Không', KHÔNG còn 'Không' và không có seats giả
    r = await get_specs("VF 6", category="interior", keys=["seats", "driver_seat_type", "leatherette_seats"])
    khong = [x for x in r["specs"] if x["value"] == "Không"]
    fake_seats = [x for x in r["specs"] if x["key"] == "seats"]
    report("DATA-VF6", len(khong) == 0 and len(fake_seats) == 0,
           "specs", f"VF 6 interior: {len(r['specs'])} rows, 'Không'={len(khong)}, seats={fake_seats}")

    # VF 8: có seat thật cho cả 2 bản
    r = await get_specs("VF 8", category="interior", keys=["seats"])
    seats = {x["version_name"]: x["value"] for x in r["specs"] if x["key"] == "seats"}
    report("DATA-VF8", seats.get("Eco") == "5" and seats.get("Plus") == "5",
           "specs", f"VF 8 seats={seats}")

    # VF 9: Eco 7, Plus 7 hoặc 6
    r = await get_specs("VF 9", category="interior", keys=["seats"])
    seats9 = {x["version_name"]: x["value"] for x in r["specs"] if x["key"] == "seats"}
    report("DATA-VF9", seats9.get("Eco") == "7",
           "specs", f"VF 9 seats={seats9}")

    # VF MPV 7: 7 chỗ (fix viết hoa MPV)
    r = await get_specs("VF MPV 7", category="interior", keys=["seats"])
    seats7 = [x["value"] for x in r["specs"] if x["key"] == "seats"]
    report("DATA-VFMPV7", seats7 == ["7"],
           "specs", f"VF MPV 7 seats={seats7}")

    # VF 8 All New có dữ liệu (không mất)
    r = await get_specs("VF 8 All New")
    report("DATA-ALLNEW", len(r.get("specs", [])) > 0,
           "specs", f"VF 8 All New: {len(r.get('specs', []))} rows")


async def main():
    print("╔═══════════════════════════════════════════════╗")
    print("║   VIVU EVAL-MATRIX + REGRESSION TEST SUITE    ║")
    print("╚═══════════════════════════════════════════════╝\n")

    t0 = time.time()
    _install_offline_stub()

    await test_golden_matrix()
    test_model_naming()
    test_seats_category()
    test_memory_recency()
    test_source_link()
    await test_data_correctness()

    elapsed = time.time() - t0
    total = PASS + FAIL
    print(f"\n{'═' * 54}")
    print(f"  RESULTS: {PASS}/{total} PASS, {FAIL} FAIL, {SKIP} SKIP ({elapsed:.1f}s)")
    print(f"{'═' * 54}")

    if ERRORS:
        print(f"\n{FAIL} FAILURES:")
        for e in ERRORS:
            print(f"  ✗ {e}")

    return FAIL


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
