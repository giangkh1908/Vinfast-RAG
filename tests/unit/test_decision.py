"""Unit tests for app.agent.decision module."""

import json
from pathlib import Path

import pytest

from app.agent.classifier import ClassifyResult
from app.agent.decision import (
    DecisionLog,
    LogStore,
    ReasonCode,
    _get_prompt_hash,
    _price_relevance_score,
    _query_models,
    _query_tokens,
    _spec_relevance_score,
    assess_evidence,
    build_displayed_citations,
    build_retrieved_chunks,
    make_decision_log,
    resolve_reason_code,
    validate_citations,
)


class TestReasonCodes:
    """Test ReasonCode enum and mapper."""

    @pytest.mark.parametrize(
        ("reason_str", "expected_code"),
        [
            ("BDS-01: sufficient evidence", ReasonCode.SUFFICIENT_DIRECT_EVIDENCE.value),
            ("BDS-02: missing model", ReasonCode.MISSING_MODEL.value),
            ("BDS-02A: unsupported model", ReasonCode.UNSUPPORTED_MODEL.value),
            ("BDS-03: missing version", ReasonCode.MISSING_VERSION.value),
            ("BDS-05: missing topic", ReasonCode.MISSING_TOPIC.value),
            ("BDS-06: insufficient evidence", ReasonCode.INSUFFICIENT_EVIDENCE.value),
            ("BDS-08: invalid source", ReasonCode.INVALID_SOURCE.value),
            ("BDS-09: source conflict", ReasonCode.SOURCE_CONFLICT.value),
            ("BDS-10: ambiguous context", ReasonCode.AMBIGUOUS_CONTEXT.value),
            ("BDS-11: comparison", ReasonCode.UNSUPPORTED_COMPARISON.value),
            ("BDS-18: citation failure", ReasonCode.CITATION_FAILURE.value),
            ("BDS-19: system error", ReasonCode.SYSTEM_ERROR.value),
            ("grounding_fail", ReasonCode.GROUNDING_FAILURE.value),
            ("pricing", ReasonCode.UNSUPPORTED_PRICING_POLICY.value),
            ("completely_unknown_string", ReasonCode.SYSTEM_ERROR.value),
        ],
    )
    def test_resolve_reason_code(self, reason_str: str, expected_code: str):
        assert resolve_reason_code(reason_str) == expected_code


class TestHelpers:
    """Test version, hashing, and token helpers."""

    def test_get_prompt_hash(self):
        h1 = _get_prompt_hash("System prompt text v1")
        h2 = _get_prompt_hash("System prompt text v1")
        h3 = _get_prompt_hash("System prompt text v2")
        assert len(h1) == 12
        assert h1 == h2
        assert h1 != h3

    def test_query_tokens(self):
        tokens = _query_tokens("VF 8 Giá bao nhiêu?")
        assert "vf" in tokens
        assert "8" in tokens
        assert "giá" in tokens

    def test_query_models(self):
        models = _query_models("So sánh VF 8 và VF 9")
        assert "VF8" in models
        assert "VF9" in models

    def test_spec_relevance_score(self):
        tokens = _query_tokens("công suất động cơ VF 8")
        score = _spec_relevance_score(tokens, "power_kw", "300")
        assert score >= 0.7

    def test_price_relevance_score(self):
        tokens = _query_tokens("giá xe niêm yết")
        assert _price_relevance_score(tokens) == 0.9
        non_price_tokens = _query_tokens("màu xe")
        assert _price_relevance_score(non_price_tokens) == 0.5


class TestAssessEvidence:
    """Test evidence assessment and LRU memoization."""

    def test_empty_tool_results_insufficient(self):
        assessment, sources = assess_evidence([], "VF 8 giá bao nhiêu?")
        assert assessment == "insufficient"
        assert sources == []

    def test_get_price_direct_support(self):
        tool_results = [
            {
                "tool": "get_price",
                "success": True,
                "result": {
                    "model_code": "VF 8",
                    "source_url": "https://shop.vinfastauto.com/vn_vi/dat-coc-xe-vf8.html",
                    "prices": [{"version_name": "Eco", "price_vnd": "1.090.000.000 VNĐ"}],
                },
            }
        ]
        assessment, sources = assess_evidence(tool_results, "VF 8 giá bao nhiêu?")
        assert assessment == "direct_support"
        assert len(sources) > 0
        assert sources[0]["source_type"] == "pricing"

    def test_get_specs_direct_support(self):
        tool_results = [
            {
                "tool": "get_specs",
                "success": True,
                "result": {
                    "model_code": "VF 8",
                    "source_url": "https://vinfastauto.com/thong-so-vf8",
                    "specs": [{"key": "battery_kwh", "value": "87.7", "unit": "kWh", "page": "1"}],
                },
            }
        ]
        assessment, sources = assess_evidence(tool_results, "dung lượng pin VF 8")
        assert assessment == "direct_support"
        assert len(sources) == 1

    def test_utility_tools_direct_support(self):
        tool_results = [
            {
                "tool": "get_showroom_charging_link",
                "success": True,
                "result": {
                    "url": "https://vinfastauto.com/vn_vi/tim-kiem-showroom-tram-sac",
                    "label": "Tìm Showroom & Trạm sạc",
                },
            }
        ]
        assessment, sources = assess_evidence(tool_results, "tìm showroom")
        assert assessment == "direct_support"
        assert len(sources) == 1
        assert sources[0]["source_url"] == "https://vinfastauto.com/vn_vi/tim-kiem-showroom-tram-sac"


class TestValidateCitations:
    """Test citation filtering and validation."""

    def test_filters_empty_urls(self):
        sources = [
            {"source_url": "", "text": "invalid"},
            {"source_url": "https://vinfastauto.com", "text": "Pin 87.7 kWh VF 8", "score": 0.8},
        ]
        valid = validate_citations(sources, query="pin VF 8")
        assert len(valid) == 1
        assert valid[0]["source_url"] == "https://vinfastauto.com"


class TestBuildRetrievedChunksAndCitations:
    """Test conversion of tool results into P0 schema objects."""

    def test_build_retrieved_chunks(self):
        tool_results = [
            {
                "tool": "get_specs",
                "success": True,
                "result": {
                    "model_code": "VF 8",
                    "source_url": "https://vinfastauto.com/thong-so",
                    "document_name": "Brochure VF8",
                    "specs": [{"key": "power_kw", "value": "300", "unit": "kW", "category": "powertrain", "page": "2"}],
                },
            }
        ]
        chunks = build_retrieved_chunks(tool_results, query="công suất VF 8", topic="powertrain")
        assert len(chunks) == 1
        assert chunks[0]["vehicle_model"] == "VF 8"
        assert chunks[0]["rank"] == 1

    def test_build_displayed_citations(self):
        citations = [
            {
                "source_url": "https://vinfastauto.com/thong-so",
                "model_code": "VF 8",
                "source_type": "car_specs",
                "document_name": "Brochure VF8",
            }
        ]
        displayed = build_displayed_citations(citations)
        assert len(displayed) == 1
        assert displayed[0]["citation_id"] == "cit_001"
        assert "VF 8" in displayed[0]["display_text"]


class TestDecisionLogAndStore:
    """Test DecisionLog creation and LogStore export/management."""

    def test_make_decision_log(self):
        cr = ClassifyResult(decision="answer", reason="BDS-01", entities={"model_code": "VF 8", "version": "Plus"})
        tool_results = [
            {
                "tool": "get_price",
                "success": True,
                "result": {
                    "model_code": "VF 8",
                    "source_url": "https://shop.vinfastauto.com",
                    "prices": [{"version_name": "Plus", "price_vnd": "1.270.000.000 VNĐ"}],
                },
            }
        ]
        log = make_decision_log(
            query="VF 8 Plus giá bao nhiêu?",
            classify_result=cr,
            tool_results=tool_results,
            response="VF 8 Plus có giá niêm yết là 1.270.000.000 VNĐ.",
            citations=[{"source_url": "https://shop.vinfastauto.com", "source_type": "pricing", "model_code": "VF 8"}],
        )
        assert isinstance(log, DecisionLog)
        assert log.decision == "answer"
        assert log.detected_vehicle_model == "VF 8"
        assert log.detected_vehicle_version == "Plus"
        assert log.evidence_assessment == "direct_support"
        assert len(log.displayed_citations) == 1

    def test_log_store_lifecycle(self, tmp_path: Path):
        store = LogStore()
        store.clear()
        assert len(store.get_all()) == 0

        cr = ClassifyResult(decision="answer", reason="BDS-01", entities={"model_code": "VF 3"})
        log = make_decision_log("VF 3 giá bao nhiêu?", cr, [], "response", [])
        store.add(log)

        all_logs = store.get_all()
        assert len(all_logs) == 1
        run_id = all_logs[0]["run_id"]
        assert len(store.get_by_run(run_id)) == 1

        export_file = tmp_path / "test_logs.jsonl"
        count = store.export_jsonl(export_file)
        assert count == 1
        assert export_file.exists()

        lines = export_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        saved_dict = json.loads(lines[0])
        assert saved_dict["user_query"] == "VF 3 giá bao nhiêu?"
