import logging
import re

from app.agent.decision import assess_evidence, validate_citations, REFUSAL_MESSAGES
from app.agent.graph_state import AgentState

logger = logging.getLogger("bds.graph.validate")

REFUSAL_PATTERNS = [
    r"chưa thể xác nhận",
    r"không có thông tin",
    r"không đủ thông tin",
    r"không được cung cấp",
    r"không tìm thấy",
    r"không có dữ liệu",
    r"không có trong danh sách",
    r"không nằm trong phạm vi",
]


def _strip_urls(text: str) -> str:
    return re.sub(r"https?://\S+", "", text)


def _strip_non_factual_numbers(text: str) -> str:
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\(\d{4}\)", "", text)
    text = re.sub(r"\bVF\s*\d+\b", "", text, flags=re.IGNORECASE)
    return text


def _extract_numbers(text: str) -> set[float]:
    nums = set()
    cleaned = re.sub(r"\d+[-–]\d+", "", text)
    for m in re.findall(r"\d[\d.,]*\d|\d+", cleaned):
        clean = m.replace(",", "").replace(".", "")
        try:
            nums.add(float(clean))
        except ValueError:
            pass
    return nums


def _check_grounding(response: str, tool_results: list[dict]) -> bool:
    if not tool_results:
        return False

    response_numbers = _extract_numbers(_strip_non_factual_numbers(response))
    if not response_numbers:
        return True

    price_numbers: set[float] = set()
    spec_numbers: set[float] = set()
    kb_numbers: set[float] = set()

    for tr in tool_results:
        if not tr.get("success"):
            continue
        result = tr["result"]
        if tr["tool"] == "get_specs":
            for s in result.get("specs", []):
                spec_numbers.update(_extract_numbers(s.get("value", "")))
        elif tr["tool"] == "get_price":
            for p in result.get("prices", []):
                for fld in ("price_vnd", "promo_price_vnd"):
                    pv = p.get(fld)
                    if pv is not None:
                        price_numbers.update(_extract_numbers(str(pv)))
        elif tr["tool"] == "search_knowledge_base":
            for r in result.get("results", []):
                kb_numbers.update(_extract_numbers(r.get("text", "")))
        elif tr["tool"] == "search_all":
            sub_specs = result.get("specs", {})
            for s in sub_specs.get("specs", []):
                spec_numbers.update(_extract_numbers(s.get("value", "")))
            sub_kb = result.get("knowledge_base", {})
            for r in sub_kb.get("results", []):
                kb_numbers.update(_extract_numbers(r.get("text", "")))

    all_ctx = price_numbers | spec_numbers | kb_numbers
    has_price = bool(price_numbers)

    PRICE_KW = re.compile(
        r"(gi[aá]|price|ni[eê]m\s+y[eế]t|[uư]u\s+[đd][ãa]i|VN[DĐ]|tri[eệ]u|t[yỷ]|l[aă]n\s+b[aá]nh|tr[aả]\s+g[oó]p)",
        re.IGNORECASE,
    )
    resp_has_price = bool(PRICE_KW.search(response))

    for num in response_numbers:
        if num < 100 and num == int(num):
            continue
        if num not in all_ctx:
            return False
        if resp_has_price and has_price and num not in price_numbers:
            if not any(abs(num - sn) / max(sn, 1) < 0.01 for sn in spec_numbers if sn > 1000):
                return False

    return True


async def validate_node(state: AgentState) -> dict:
    final_response = state.get("final_response", "")
    tool_results = state.get("tool_results", [])
    decision = state.get("decision", "answer")

    if decision != "answer":
        return {}

    assessment, valid_sources = assess_evidence(tool_results, state["query"])

    if assessment == "insufficient":
        return {
            "decision": "refuse",
            "reason_code": "insufficient_evidence",
            "response_text": REFUSAL_MESSAGES["insufficient_evidence"],
            "assessment": assessment,
            "citations": [],
            "grounding_ok": False,
        }

    citations = validate_citations(valid_sources)

    if not citations and final_response and bool(re.search(r"\d[\d.,]+", _strip_non_factual_numbers(final_response))):
        return {
            "decision": "refuse",
            "reason_code": "citation_failure",
            "response_text": REFUSAL_MESSAGES["no_citation"],
            "assessment": assessment,
            "citations": [],
            "grounding_ok": False,
        }

    grounding_ok = _check_grounding(final_response, tool_results)

    if not grounding_ok:
        return {
            "decision": "refuse",
            "reason_code": "grounding_failure",
            "response_text": REFUSAL_MESSAGES["grounding_fail"],
            "assessment": assessment,
            "citations": citations,
            "grounding_ok": False,
        }

    is_refusal = any(re.search(p, final_response, re.IGNORECASE) for p in REFUSAL_PATTERNS)
    if is_refusal:
        return {
            "decision": "refuse",
            "reason_code": "insufficient_evidence",
            "assessment": assessment,
            "citations": citations,
            "grounding_ok": True,
        }

    return {
        "decision": "answer",
        "assessment": assessment,
        "citations": citations,
        "grounding_ok": True,
    }
