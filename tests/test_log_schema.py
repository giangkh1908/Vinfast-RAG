"""
Test decision log schema against sample-smoke-log.json format.

Run: python tests/test_log_schema.py
"""
import sys
import os
import io
import asyncio
import json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

PASS = 0
FAIL = 0
ERRORS = []


def report(tid, passed, detail):
    global PASS, FAIL, ERRORS
    if passed:
        PASS += 1
        print(f"  [OK] {tid}: {detail}")
    else:
        FAIL += 1
        ERRORS.append(f"{tid}: {detail}")
        print(f"  [FAIL] {tid}: {detail}")


def check_schema(log: dict, required_fields: list[str], tid_prefix: str):
    """Check all required fields exist in log dict."""
    for field in required_fields:
        report(f"{tid_prefix}-{field}", field in log, f"field '{field}' {'present' if field in log else 'MISSING'}")


def check_type(log: dict, field: str, expected_type, tid: str):
    """Check field type."""
    val = log.get(field)
    if val is None:
        report(tid, expected_type == "null", f"{field}={val} type={type(val).__name__} (expected null)")
    elif isinstance(val, expected_type):
        report(tid, True, f"{field} type={expected_type.__name__} OK")
    else:
        report(tid, False, f"{field}={val} type={type(val).__name__} (expected {expected_type.__name__})")


async def test_decision_log_schema():
    """Test full DecisionLog schema matches sample-smoke-log.json."""
    print("\n═══ 1. DECISION LOG SCHEMA TESTS ═══")

    from app.agent.agent_loop import AgentLoop
    from app.agent.decision import make_decision_log, log_store

    agent = AgentLoop()
    log_store.clear()
    log_store.start_run()

    # Run a query to generate a real log
    result = await agent.run("VF 6 Eco công suất bao nhiêu?", [])
    if result.decision_log and len(log_store.get_all()) == 0:
        log_store.append(result.decision_log)

    from app.agent.classifier import get_classifier

    if len(log_store.get_all()) == 0:
        cr = get_classifier().classify("VF 6 Eco công suất bao nhiêu?", [])
        test_log = make_decision_log(
            query="VF 6 Eco công suất bao nhiêu?",
            classify_result=cr,
            tool_results=[{
                "tool": "get_specs",
                "args": {"model_code": "VF 6", "version": "Eco"},
                "success": True,
                "result": {"model_code": "VF 6", "specs": []},
            }],
            response="VF 6 Eco có công suất 130 kW.",
            citations=[],
        )
        log_store.add(test_log)

    logs = log_store.get_all()
    report("LOG-EXISTS", len(logs) > 0, f"generated {len(logs)} log(s)")



    if not logs:
        return

    log = logs[0]

    # ── Top-level fields ──
    top_fields = [
        "schema_version", "request_id", "timestamp", "run_id",
        "build_version", "prompt_version", "data_snapshot_id",
        "environment", "user_query",
        "detected_vehicle_model", "detected_vehicle_version", "detected_topic",
        "decision", "reason_code",
        "retrieval_status", "retrieval_query", "requested_top_k",
        "evidence_assessment",
        "displayed_answer",
        "latency_total_ms", "latency_retrieval_ms", "latency_generation_ms",
    ]
    check_schema(log, top_fields, "TOP")

    # Nullable fields (should be null or string)
    nullable_fields = [
        "conversation_id", "turn_index", "previous_request_id",
        "test_id", "retrieval_config_version",
        "error_stage", "error_type", "error_message",
    ]
    check_schema(log, nullable_fields, "NULL")

    # ── retrieved_chunks schema ──
    report("CHUNKS-EXISTS", "retrieved_chunks" in log, "retrieved_chunks field present")
    chunks = log.get("retrieved_chunks", [])
    if chunks:
        chunk_fields = [
            "rank", "chunk_id", "source_id", "source_title", "source_url",
            "document_name", "page", "section", "content",
            "vehicle_model", "vehicle_version", "topic",
            "approval_status", "market", "language", "retrieval_score",
        ]
        check_schema(chunks[0], chunk_fields, "CHK")
        check_type(chunks[0], "rank", int, "CHK-rank-type")
        check_type(chunks[0], "retrieval_score", float, "CHK-score-type")
        report("CHK-market-default", chunks[0].get("market") == "Vietnam", f"market={chunks[0].get('market')}")
        report("CHK-language-default", chunks[0].get("language") == "vi", f"language={chunks[0].get('language')}")

    # ── displayed_citations schema ──
    report("CITES-EXISTS", "displayed_citations" in log, "displayed_citations field present")
    cites = log.get("displayed_citations", [])
    if cites:
        cite_fields = [
            "citation_id", "display_text", "source_id", "chunk_ids",
            "source_url", "document_name", "page", "section",
        ]
        check_schema(cites[0], cite_fields, "CITE")
        report("CITE-ID-FORMAT", cites[0].get("citation_id", "").startswith("cit_"),
               f"citation_id={cites[0].get('citation_id')}")

    # ── Value checks ──
    report("VAL-schema_version", log.get("schema_version") == "1.0", f"schema_version={log.get('schema_version')}")
    report("VAL-decision", log.get("decision") in ("answer", "clarify", "refuse", "out_of_scope"),
           f"decision={log.get('decision')}")
    report("VAL-model", log.get("detected_vehicle_model") != "", f"model={log.get('detected_vehicle_model')}")
    report("VAL-retrieval_query", log.get("retrieval_query") is not None, f"retrieval_query={log.get('retrieval_query')}")
    report("VAL-requested_top_k", log.get("requested_top_k") is not None, f"requested_top_k={log.get('requested_top_k')}")


async def test_log_store_export():
    """Test LogStore export to JSONL."""
    print("\n═══ 2. LOG STORE EXPORT TESTS ═══")

    from app.agent.decision import log_store

    # Export to temp file
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        path = f.name

    count = log_store.export_jsonl(path)
    report("EXPORT-count", count > 0, f"exported {count} logs")

    # Verify JSONL is valid
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    report("EXPORT-lines", len(lines) == count, f"{len(lines)} lines == {count} logs")

    # Verify each line is valid JSON
    for i, line in enumerate(lines[:3]):
        try:
            json.loads(line)
            report(f"EXPORT-json-{i}", True, "valid JSON")
        except json.JSONDecodeError:
            report(f"EXPORT-json-{i}", False, "invalid JSON")


    os.unlink(path)


async def test_null_vs_empty():
    """Test nullable fields are null, not empty string."""
    print("\n═══ 3. NULL VS EMPTY TESTS ═══")

    from app.agent.decision import DecisionLog

    # Fresh log (no errors)
    log = DecisionLog()
    d = log.to_dict()

    nullable = ["error_stage", "error_type", "error_message", "previous_request_id", "test_id"]
    for field in nullable:
        val = d.get(field)
        report(f"NULL-{field}", val is None, f"{field}={val!r}")

    # Log with errors
    log2 = DecisionLog(error_stage="tools", error_type="429", error_message="rate limit")
    d2 = log2.to_dict()
    report("NULL-with-error-stage", d2.get("error_stage") == "tools", f"error_stage={d2.get('error_stage')}")
    report("NULL-with-error-type", d2.get("error_type") == "429", f"error_type={d2.get('error_type')}")


async def main():
    print("╔═══════════════════════════════════════╗")
    print("║   DECISION LOG SCHEMA TESTS           ║")
    print("╚═══════════════════════════════════════╝")

    await test_decision_log_schema()
    await test_log_store_export()
    await test_null_vs_empty()

    total = PASS + FAIL
    print(f"\n{'═' * 50}")
    print(f"  RESULTS: {PASS}/{total} PASS, {FAIL} FAIL")
    print(f"{'═' * 50}")
    if ERRORS:
        print(f"\n{FAIL} FAILURES:")
        for e in ERRORS:
            print(f"  ✗ {e}")


asyncio.run(main())
