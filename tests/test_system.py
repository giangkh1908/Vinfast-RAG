"""
Full system test — covers all tools, classify logic, validate logic.
Each test traces which step fails: classify → tools → generate → validate.
"""
import sys, io, asyncio, time, json, traceback
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

PASS = 0
FAIL = 0
ERRORS = []


def report(test_id: str, passed: bool, step: str, detail: str):
    global PASS, FAIL, ERRORS
    if passed:
        PASS += 1
        print(f"  [OK] {test_id}: {step} — {detail}")
    else:
        FAIL += 1
        ERRORS.append(f"{test_id}: {step} — {detail}")
        print(f"  [FAIL] {test_id}: {step} — {detail}")


async def trace_pipeline(query: str, history: list[dict] = None) -> dict:
    """Run full pipeline and capture each step's output."""
    from app.agent.nodes.classify import classify_node
    from app.agent.nodes.messages import build_messages_node
    from app.agent.nodes.tools import execute_tools_node
    from app.agent.nodes.generate import generate_node
    from app.agent.nodes.validate import validate_node
    from app.agent.graph_state import AgentState

    history = history or []
    state: AgentState = {"query": query, "history": history, "t0": time.time()}
    result = {"steps": {}}

    # Step 1: Classify
    try:
        cr = await classify_node(state)
        state.update(cr)
        result["steps"]["classify"] = {
            "decision": cr.get("decision"),
            "reason_code": cr.get("reason_code"),
            "category": cr.get("category"),
            "entities": cr.get("entities"),
        }
    except Exception as e:
        result["steps"]["classify"] = {"error": str(e)}
        return result

    if cr.get("decision") != "answer":
        result["final_decision"] = cr.get("decision")
        result["final_response"] = cr.get("response_text", "")
        return result

    # Step 2: Build messages
    try:
        state.update(await build_messages_node(state))
        result["steps"]["messages"] = {"ok": True}
    except Exception as e:
        result["steps"]["messages"] = {"error": str(e)}
        return result

    # Step 3: Execute tools
    try:
        tr = await execute_tools_node(state)
        state.update(tr)
        tools_used = []
        for t in state.get("tool_results", []):
            tool = t.get("tool", "")
            success = t.get("success", True)
            result_data = t.get("result", {})
            error = result_data.get("error", "")
            tools_used.append({
                "tool": tool,
                "success": success,
                "error": error,
                "result_keys": list(result_data.keys())[:5],
            })
        result["steps"]["tools"] = {
            "tools_used": tools_used,
            "final_response": state.get("final_response", "")[:100],
        }
    except Exception as e:
        result["steps"]["tools"] = {"error": str(e)}
        return result

    # Step 4: Generate
    try:
        gen = await generate_node(state)
        state.update(gen)
        result["steps"]["generate"] = {
            "final_response": state.get("final_response", "")[:200],
        }
    except Exception as e:
        result["steps"]["generate"] = {"error": str(e)}
        return result

    # Step 5: Validate
    try:
        val = await validate_node(state)
        state.update(val)
        result["steps"]["validate"] = {
            "decision": val.get("decision"),
            "reason_code": val.get("reason_code"),
            "assessment": val.get("assessment"),
        }
    except Exception as e:
        result["steps"]["validate"] = {"error": str(e)}
        return result

    result["final_decision"] = state.get("decision", state.get("steps", {}).get("validate", {}).get("decision"))
    result["final_response"] = state.get("final_response", "")[:200]
    return result


# ═══════════════════════════════════════════════════════════════
# TEST CASES
# ═══════════════════════════════════════════════════════════════

async def test_tools_direct():
    """Test each tool directly (unit test)."""
    print("\n═══ 1. DIRECT TOOL TESTS ═══")

    from app.agent.tools import (
        get_specs, get_price, get_colors, search_knowledge_base,
        search_all, list_available_models, get_showroom_charging_link,
        get_booking_link, get_onroad_cost_link, get_loan_estimate_link,
        get_active_promotions, get_maintenance_link,
    )

    # get_specs
    r = await get_specs("VF 6", version="Eco")
    report("T-GETSPECS-01", len(r.get("specs", [])) > 0, "get_specs",
           f"{len(r.get('specs', []))} specs for VF 6 Eco")

    r = await get_specs("VF 8 All New")
    report("T-GETSPECS-02", len(r.get("specs", [])) > 0, "get_specs",
           f"{len(r.get('specs', []))} specs for VF 8 All New")

    r = await get_specs("VF 3", category="battery")
    report("T-GETSPECS-03", len(r.get("specs", [])) > 0, "get_specs",
           f"{len(r.get('specs', []))} battery specs for VF 3")

    # get_price
    r = await get_price("VF 8")
    report("T-GETPRICE-01", len(r.get("prices", [])) > 0, "get_price",
           f"{len(r.get('prices', []))} prices for VF 8")

    r = await get_price("VF 8 All New")
    report("T-GETPRICE-02", len(r.get("prices", [])) > 0, "get_price",
           f"{len(r.get('prices', []))} prices for VF 8 All New")

    r = await get_price("VF 3", version="Eco")
    report("T-GETPRICE-03", len(r.get("prices", [])) > 0, "get_price",
           f"{len(r.get('prices', []))} prices for VF 3 Eco")

    # get_colors
    r = await get_colors("VF 8 All New")
    report("T-GETCOLORS-01", len(r.get("colors", [])) > 0, "get_colors",
           f"{len(r.get('colors', []))} colors for VF 8 All New")

    r = await get_colors("VF 3")
    report("T-GETCOLORS-02", len(r.get("colors", [])) > 0, "get_colors",
           f"{len(r.get('colors', []))} colors for VF 3")

    r = await get_colors("VF 6", version="Plus")
    report("T-GETCOLORS-03", len(r.get("colors", [])) > 0, "get_colors",
           f"{len(r.get('colors', []))} colors for VF 6 Plus")

    # search_knowledge_base
    r = await search_knowledge_base("tính năng an toàn", model_id="VF 8")
    report("T-SEARCHKB-01", len(r.get("results", [])) > 0, "search_kb",
           f"{len(r.get('results', []))} results for VF 8 safety")

    # search_all
    r = await search_all("VF 6", "nội thất ghế")
    specs_count = len(r.get("specs", {}).get("specs", []))
    kb_count = len(r.get("knowledge_base", {}).get("results", []))
    report("T-SEARCHALL-01", specs_count > 0 or kb_count > 0, "search_all",
           f"{specs_count} specs + {kb_count} KB for VF 6 interior")

    # list_available_models
    r = await list_available_models()
    report("T-LISTMODELS-01", len(r.get("models", [])) > 0, "list_models",
           f"{len(r.get('models', []))} models")

    # Utility tools
    r = await get_showroom_charging_link()
    report("T-SHOWROOM-01", bool(r.get("url")), "showroom_link",
           r.get("url", "")[:60])

    r = await get_booking_link("test_drive")
    report("T-BOOKING-01", bool(r.get("url")), "booking_link",
           r.get("url", "")[:60])

    r = await get_onroad_cost_link()
    report("T-ONROAD-01", bool(r.get("url")), "onroad_link",
           r.get("url", "")[:60])

    r = await get_loan_estimate_link()
    report("T-LOAN-01", bool(r.get("url") or r.get("links")), "loan_link",
           str(r.get("url", r.get("links", "")))[:60])

    r = await get_active_promotions()
    report("T-PROMO-01", bool(r.get("url")), "promo_link",
           r.get("url", "")[:60])

    r = await get_maintenance_link("VF 8")
    report("T-MAINT-01", bool(r.get("links")), "maintenance_link",
           f"{len(r.get('links', []))} links")


async def test_classify():
    """Test classify_node logic."""
    print("\n═══ 2. CLASSIFY TESTS ═══")

    from app.agent.nodes.classify import classify_node
    from app.agent.graph_state import AgentState

    cases = [
        # (query, history, expected_decision, expected_reason_keyword, test_id)
        ("VF 6 Eco công suất bao nhiêu?", [], "answer", None, "T-CLS-01"),
        ("giá vf8 all new", [], "answer", None, "T-CLS-02"),
        ("vf3 có mấy màu?", [], "answer", None, "T-CLS-03"),
        ("so sánh vf6 và vf8", [], "answer", None, "T-CLS-04"),
        ("tôi muốn tìm showroom", [], "answer", "utility", "T-CLS-05"),
        ("đặt lịch bảo dưỡng", [], "answer", "utility", "T-CLS-06"),
        ("xe nào tốt nhất", [], "answer", None, "T-CLS-07"),
        ("cho tôi biết về vf6", [], "clarify", "missing_topic", "T-CLS-08"),
        # Multi-turn follow-up
        ("Bản Plus", [
            {"role": "user", "content": "VF8 đi được bao nhiêu km?"},
            {"role": "assistant", "content": "Bạn muốn hỏi phiên bản nào?"},
        ], "answer", None, "T-CLS-09"),
    ]

    for query, history, exp_decision, exp_reason_kw, tid in cases:
        state: AgentState = {"query": query, "history": history, "t0": time.time()}
        try:
            cr = await classify_node(state)
            decision = cr.get("decision")
            reason = cr.get("reason_code", "")

            decision_ok = decision == exp_decision
            reason_ok = exp_reason_kw is None or exp_reason_kw in reason

            report(tid, decision_ok and reason_ok, "classify",
                   f"decision={decision} (exp {exp_decision}), reason={reason}")
        except Exception as e:
            report(tid, False, "classify", f"ERROR: {e}")


async def test_full_pipeline():
    """Test full pipeline end-to-end."""
    print("\n═══ 3. FULL PIPELINE TESTS ═══")

    cases = [
        # (query, history, expected_decision, test_id, description)
        # --- Answer cases ---
        ("VF 6 Eco công suất bao nhiêu?", [], "answer", "T-E2E-01", "specs query"),
        ("giá vf2", [], "answer", "T-E2E-02", "price query"),
        ("vf3 có mấy màu?", [], "answer", "T-E2E-03", "colors query"),
        ("VF 8 All New có ADAS gì?", [], "answer", "T-E2E-04", "ADAS query"),
        ("VF 8 Eco đi được bao xa?", [], "answer", "T-E2E-05", "range query"),
        ("VF 6 có những phiên bản nào?", [], "answer", "T-E2E-06", "versions query"),
        ("tôi muốn tìm showroom", [], "answer", "T-E2E-07", "utility: showroom"),
        ("đặt lịch lái thử", [], "answer", "T-E2E-08", "utility: booking"),
        ("VF 8 Plus có hỗ trợ lái trên đường cao tốc không?", [], "answer", "T-E2E-09", "ADAS feature"),
        # --- Multi-turn ---
        ("VF 8", [
            {"role": "user", "content": "sạc nhanh từ 10% lên 70% mất bao lâu?"},
            {"role": "assistant", "content": "Bạn muốn hỏi về VF 6 hoặc VF 8?"},
        ], "answer", "T-E2E-10", "multi-turn: charging follow-up"),
        ("Bản Plus", [
            {"role": "user", "content": "VF8 đi được bao nhiêu km?"},
            {"role": "assistant", "content": "Bạn muốn hỏi phiên bản nào?"},
        ], "answer", "T-E2E-11", "multi-turn: version follow-up"),
    ]

    for query, history, exp_decision, tid, desc in cases:
        try:
            r = await trace_pipeline(query, history)
            final_decision = r.get("final_decision", "unknown")
            passed = final_decision == exp_decision

            if not passed:
                # Find which step failed
                steps = r.get("steps", {})
                fail_step = "unknown"
                fail_detail = ""
                if steps.get("classify", {}).get("error"):
                    fail_step = "classify"
                    fail_detail = steps["classify"]["error"]
                elif steps.get("classify", {}).get("decision") not in ("answer", None):
                    fail_step = "classify"
                    fail_detail = f"decision={steps['classify'].get('decision')}, reason={steps['classify'].get('reason_code')}"
                elif steps.get("tools", {}).get("error"):
                    fail_step = "tools"
                    fail_detail = steps["tools"]["error"]
                elif steps.get("generate", {}).get("error"):
                    fail_step = "generate"
                    fail_detail = steps["generate"]["error"]
                elif steps.get("validate", {}).get("error"):
                    fail_step = "validate"
                    fail_detail = steps["validate"]["error"]
                elif steps.get("validate", {}).get("decision") and steps["validate"]["decision"] != "answer":
                    fail_step = "validate"
                    vd = steps["validate"]
                    fail_detail = f"decision={vd.get('decision')}, reason={vd.get('reason_code')}, assessment={vd.get('assessment')}"
                else:
                    fail_step = "generate_or_validate"
                    fr = r.get("final_response", "")[:100]
                    fail_detail = f"final_response={fr}"

                report(tid, False, fail_step,
                       f"{desc}: expected={exp_decision}, got={final_decision} | {fail_detail}")
            else:
                response = r.get("final_response", "")[:80]
                report(tid, True, "pipeline",
                       f"{desc}: {final_decision} | {response}")

            # Rate limit: wait between E2E tests (5 LLM calls/min = ~25s between tests)
            await asyncio.sleep(25)
        except Exception as e:
            report(tid, False, "exception", f"{desc}: {traceback.format_exc()[-200:]}")
            await asyncio.sleep(25)


async def main():
    print("╔══════════════════════════════════════════════════╗")
    print("║         VIVU SYSTEM TEST SUITE                   ║")
    print("╚══════════════════════════════════════════════════╝")

    t0 = time.time()

    await test_tools_direct()
    await test_classify()
    await test_full_pipeline()

    elapsed = time.time() - t0
    total = PASS + FAIL

    print(f"\n{'═' * 52}")
    print(f"  RESULTS: {PASS}/{total} PASS, {FAIL} FAIL ({elapsed:.1f}s)")
    print(f"{'═' * 52}")

    if ERRORS:
        print(f"\n{FAIL} FAILURES:")
        for e in ERRORS:
            print(f"  ✗ {e}")

    return FAIL

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
