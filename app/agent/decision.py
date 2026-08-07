import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.config import settings

logger = logging.getLogger("bds.decision")


@dataclass
class DecisionLog:
    user_query: str = ""
    detected_vehicle_model: str = "unknown"
    detected_vehicle_version: str = "unknown"
    detected_topic: str = "unknown"
    decision: str = ""
    reason: str = ""
    retrieved_sources: list[dict] = field(default_factory=list)
    evidence_assessment: str = ""
    displayed_answer: str = ""
    displayed_citations: list[dict] = field(default_factory=list)
    error: str = ""
    timestamp: str = ""

    def to_dict(self) -> dict:
        return {
            "user_query": self.user_query,
            "detected_vehicle_model": self.detected_vehicle_model,
            "detected_vehicle_version": self.detected_vehicle_version,
            "detected_topic": self.detected_topic,
            "decision": self.decision,
            "reason": self.reason,
            "retrieved_sources": self.retrieved_sources,
            "evidence_assessment": self.evidence_assessment,
            "displayed_answer": self.displayed_answer,
            "displayed_citations": self.displayed_citations,
            "error": self.error,
            "timestamp": self.timestamp or datetime.now(timezone.utc).isoformat(),
        }


def _scope_model_list() -> str:
    return " hoặc ".join(settings.scope_models)


REFUSAL_MESSAGES = {
    "no_evidence": "Mình chưa thể xác nhận thông tin này từ nguồn đã được phê duyệt hiện có.",
    "insufficient_evidence": "Mình chưa thể xác nhận thông tin chính từ nguồn hiện có.",
    "no_citation": "M mình chưa thể xác nhận vì chưa có nguồn kiểm chứng hợp lệ.",
    "conflict": "Nguồn hiện có chưa đủ nhất quán để xác nhận thông tin này.",
    "invalid_source": "Mình chưa thể xác nhận từ nguồn hợp lệ hiện có.",
    "system_error": "Mình chưa thể hoàn tất câu trả lời lúc này. Vui lòng thử lại.",
    "grounding_fail": "Mình chưa thể xác nhận thông tin này từ nguồn đã được phê duyệt hiện có.",
}


def get_oos_messages() -> dict[str, str]:
    ml = _scope_model_list()
    return {
        "comparison": f"Hiện tại mình chưa hỗ trợ so sánh xe trong lát cắt này. Bạn có thể hỏi thông tin sản phẩm cụ thể của {ml}.",
        "recommendation": f"Gợi ý xe theo nhu cầu chưa được hỗ trợ trong lát cắt này. Bạn có thể hỏi thông tin sản phẩm cụ thể của {ml}.",
        "pricing": f"Nội dung giá/ưu đãi/chính sách chưa thuộc phạm vi hỗ trợ hiện tại. Bạn có thể hỏi thông tin sản phẩm của {ml}.",
        "warranty_maintenance": f"Nhóm hỗ trợ sau mua chưa thuộc lát cắt này. Bạn có thể hỏi thông tin sản phẩm của {ml}.",
        "diagnostics": "Nội dung chẩn đoán hoặc xử lý sự cố không thuộc phạm vi hiện tại.",
        "hotline_showroom": "Workflow liên hệ/lái thử chưa được hỗ trợ trong lát cắt này.",
        "external_source": "Mình chỉ dùng approved data sources trong lát cắt này.",
        "model_oos": f"Lát cắt hiện tại chỉ phục vụ {ml}, chưa hỗ trợ các mẫu xe khác.",
    }


def get_clarify_messages() -> dict[str, str]:
    ml = _scope_model_list()
    return {
        "model_code": f"Bạn muốn hỏi về {ml}?",
        "topic": "Bạn muốn tìm thông tin nào về {model}: phiên bản, thông số kỹ thuật, tính năng, kích thước, pin/sạc, phạm vi di chuyển, an toàn, nội thất hay ngoại thất?",
        "version": "Bạn muốn hỏi về phiên bản Eco hay Plus?",
    }


def assess_evidence(tool_results: list[dict], query: str) -> tuple[str, list[dict]]:
    """Assess evidence quality. Returns (assessment_type, valid_sources)."""
    if not tool_results:
        return "insufficient", []

    valid_sources = []
    has_direct = False
    has_partial = False

    for tr in tool_results:
        if not tr.get("success"):
            continue
        result = tr["result"]
        tool = tr["tool"]

        if tool == "get_specs" and result.get("specs"):
            for s in result["specs"]:
                src_url = result.get("source_url", "")
                valid_sources.append({
                    "tool": tool,
                    "model_code": result.get("model_code", ""),
                    "text": f"{s.get('key', '')}: {s.get('value', '')} {s.get('unit', '')}",
                    "source_url": src_url,
                    "source_type": "specs",
                })
            has_direct = True

        elif tool == "get_price" and result.get("prices"):
            for p in result["prices"]:
                valid_sources.append({
                    "tool": tool,
                    "model_code": result.get("model_code", ""),
                    "text": f"{p.get('version_name', '')}: {p.get('price_vnd', '')}",
                    "source_url": result.get("source_url", ""),
                    "source_type": "pricing",
                })
            has_direct = True

        elif tool == "search_knowledge_base" and result.get("results"):
            for r in result["results"]:
                score = r.get("score", 0)
                if score >= 0.3:
                    valid_sources.append({
                        "tool": tool,
                        "text": r.get("text", "")[:200],
                        "source_url": r.get("source_url", ""),
                        "source_type": r.get("source_type", ""),
                        "score": score,
                    })
                    if score >= 0.5:
                        has_direct = True
                    else:
                        has_partial = True

        elif tool == "list_available_models" and result.get("models"):
            valid_sources.append({
                "tool": tool,
                "text": f"{len(result['models'])} models available",
                "source_type": "system",
            })
            has_direct = True

    if has_direct:
        return "direct_support", valid_sources
    if has_partial:
        return "partial_support", valid_sources
    return "insufficient", valid_sources


def validate_citations(sources: list[dict]) -> list[dict]:
    """Filter sources to valid citations. Accept any URL with actual content."""
    valid = []
    for s in sources:
        url = s.get("source_url", "")
        if not url:
            continue
        if not url.startswith("http"):
            continue
        valid.append(s)
    return valid


def make_decision_log(
    query: str,
    classify_result,
    tool_results: list[dict],
    response: str,
    citations: list[dict],
) -> DecisionLog:
    """Build a structured decision log entry."""
    model = classify_result.entities.get("model_code", "unknown")
    version = classify_result.entities.get("version", "all_versions")
    topic = classify_result.topic or "unknown"

    assessment, _ = assess_evidence(tool_results, query) if tool_results else ("none", [])

    return DecisionLog(
        user_query=query,
        detected_vehicle_model=model,
        detected_vehicle_version=version,
        detected_topic=topic,
        decision=classify_result.decision,
        reason=classify_result.reason,
        evidence_assessment=assessment,
        displayed_answer=response[:500],
        displayed_citations=citations,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
