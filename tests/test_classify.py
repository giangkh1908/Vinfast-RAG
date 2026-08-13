"""Quick runner: classify tests only (no LLM, no rate limit).

Run: python tests/test_classify.py
"""
import sys, os, io, asyncio, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

PASS = 0
FAIL = 0
ERRORS = []

def report(tid, passed, step, detail):
    global PASS, FAIL, ERRORS
    if passed:
        PASS += 1
        print(f"  [OK] {tid}: {detail}")
    else:
        FAIL += 1
        ERRORS.append(f"{tid}: {step} — {detail}")
        print(f"  [FAIL] {tid}: {step} — {detail}")

async def main():
    from app.agent.nodes.classify import classify_node
    from app.agent.graph_state import AgentState

    print("╔═══════════════════════════════════════╗")
    print("║   CLASSIFY EDGE CASE TESTS            ║")
    print("╚═══════════════════════════════════════╝\n")

    cases = [
        # Basic answer
        ("VF 6 Eco công suất bao nhiêu?", [], "answer", None, "basic: specs with version"),
        ("giá vf8 all new", [], "answer", None, "basic: price"),
        ("vf3 có mấy màu?", [], "answer", None, "basic: colors"),
        ("so sánh vf6 và vf8", [], "answer", None, "basic: comparison"),

        # Utility (no model needed)
        ("tôi muốn tìm showroom", [], "answer", "utility", "utility: showroom"),
        ("đặt lịch bảo dưỡng", [], "answer", "utility", "utility: booking"),
        ("hotline vinfast", [], "answer", "utility", "utility: hotline"),
        ("đăng ký lái thử vf8", [], "answer", None, "utility: test drive + model"),
        ("trả góp vf6", [], "answer", None, "utility: loan + model"),
        ("khuyến mãi vf3", [], "answer", None, "utility: promotions + model"),

        # Clarify: missing topic (broad)
        ("cho tôi biết về vf6", [], "clarify", "missing_topic", "clarify: broad query"),
        ("vf8 thế nào", [], "clarify", "missing_topic", "clarify: broad query 2"),
        ("thông tin về vf3", [], "clarify", "missing_topic", "clarify: broad query 3"),

        # Clarify: missing model
        ("xe nào có camera 360", [], "clarify", "missing_model", "clarify: no model"),
        ("pin bao nhiêu kWh", [], "clarify", "missing_model", "clarify: no model 2"),
        ("có mấy phiên bản", [], "clarify", "missing_model", "clarify: no model 3"),

        # Clarify: ambiguous pronoun
        ("xe này có an toàn không", [], "clarify", "ambiguous", "clarify: pronoun 'xe này'"),
        ("mẫu này đi được bao xa", [], "clarify", "ambiguous", "clarify: pronoun 'mẫu này'"),

        # Clarify: missing version (version-dependent)
        ("vf8 đi được bao xa", [], "clarify", "missing_version", "clarify: range needs version"),
        ("vf6 công suất bao nhiêu", [], "clarify", "missing_version", "clarify: power needs version"),

        # Answer: version-independent (no version needed)
        ("vf8 sạc nhanh bao lâu", [], "answer", None, "v-indep: charging"),
        ("vf6 có mấy phiên bản", [], "answer", None, "v-indep: versions"),
        ("vf3 kích thước bao nhiêu", [], "answer", None, "v-indep: dimensions"),
        ("vf8 có túi khí không", [], "answer", None, "v-indep: safety"),
        ("vf6 nội thất thế nào", [], "answer", None, "v-indep: interior"),
        ("vf8 ngoại thất ra sao", [], "answer", None, "v-indep: exterior"),

        # Answer: explicit model + version
        ("VF 8 Plus đi được bao xa", [], "answer", None, "explicit: vf8 plus range"),
        ("VF 6 Eco công suất bao nhiêu", [], "answer", None, "explicit: vf6 eco power"),
        ("vf3 eco giá bao nhiêu", [], "answer", None, "explicit: vf3 eco price"),

        # Multi-turn follow-ups
        ("Bản Plus", [
            {"role": "user", "content": "VF8 đi được bao nhiêu km?"},
            {"role": "assistant", "content": "Bạn muốn hỏi phiên bản nào?"},
        ], "answer", None, "follow-up: version after range"),
        ("VF 8", [
            {"role": "user", "content": "sạc nhanh từ 10% lên 70% mất bao lâu?"},
            {"role": "assistant", "content": "Bạn muốn hỏi về VF 6 hoặc VF 8?"},
        ], "answer", None, "follow-up: model after charging"),
        ("Kích thước xe.", [
            {"role": "user", "content": "Cho tôi biết về VF 6."},
            {"role": "assistant", "content": "Bạn muốn tìm thông tin nào về VF 6?"},
        ], "answer", None, "follow-up: topic after broad"),
        ("VF 6 Eco.", [
            {"role": "user", "content": "Xe có HUD không?"},
            {"role": "assistant", "content": "Bạn muốn hỏi về VF 6 hoặc VF 8?"},
        ], "answer", None, "follow-up: model+version after HUD"),
        ("tất cả", [
            {"role": "user", "content": "cho tôi biết về vf8 all new"},
            {"role": "assistant", "content": "Bạn muốn tìm thông tin nào về VF 8 All New?"},
        ], "answer", None, "follow-up: 'tất cả' after broad"),

        # Model name variations
        ("vf6 eco", [], "answer", None, "variant: lowercase"),
        ("VF-8 Plus", [], "answer", None, "variant: hyphen"),
        ("VF8", [], "answer", None, "variant: no space"),
        ("vf 8 all new", [], "answer", None, "variant: all new"),
        ("VinFast VF 3", [], "answer", None, "variant: with brand"),
    ]

    for query, history, exp_decision, exp_reason_kw, desc in cases:
        state = AgentState = {"query": query, "history": history, "t0": time.time()}
        try:
            cr = await classify_node(state)
            decision = cr.get("decision")
            reason = cr.get("reason_code", "")
            entities = cr.get("entities", {})
            category = cr.get("category", "")

            decision_ok = decision == exp_decision
            reason_ok = exp_reason_kw is None or exp_reason_kw in reason
            passed = decision_ok and reason_ok

            extra = ""
            if not passed:
                extra = f" | got={decision}, reason={reason}"
                if entities:
                    extra += f", entities={entities}"

            tid = f"T-{desc[:30]}"
            report(tid, passed, "classify", f"{desc}{extra}")
        except Exception as e:
            report(f"T-{desc[:30]}", False, "classify", f"{desc}: ERROR: {e}")

    total = PASS + FAIL
    print(f"\n{'═' * 50}")
    print(f"  RESULTS: {PASS}/{total} PASS, {FAIL} FAIL")
    print(f"{'═' * 50}")
    if ERRORS:
        print(f"\n{FAIL} FAILURES:")
        for e in ERRORS:
            print(f"  ✗ {e}")

asyncio.run(main())
