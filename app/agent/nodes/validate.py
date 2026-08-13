import logging
import re
import unicodedata

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
    r"chưa có trong dữ liệu",
    r"hiện chưa có",
]

_FEATURE_RE = re.compile(
    r"(hud|head.?up|adas|aeb|acc|adaptive.?cruise|lane.?keep|lane.?depart|"
    r"blind.?spot|collision|parking|camera|túi.?khí|airbag|abs|ebd|esc|tcs|hsa|"
    r"cruise.?control|auto.?brake|emergency|surround|monitoring|"
    r"điều.?hòa|ghế|màn.?hình|loa|đèn|cửa.?sổ|gương|vô.?lăng|"
    r"pin|sạc|phạm.?vi|tốc.?độ|công.?suất|mô.?men|xoắn|quãng.?đường|"
    r"nội.?thất|ngoại.?thất|an.?toàn|tiện.?nghi|thông.?minh|"
    r"navigation|gaming|ota|browser|phone.?app|diagnosis|"
    r"leatherette|speaker|drivetrain|suspension|brake|"
    r"immobilizer|alarm|theft|massage|tự.?lái|lội.?nước|bán kính|quay.?vòng)",
    re.IGNORECASE,
)


def _strip_urls(text: str) -> str:
    return re.sub(r"https?://\S+", "", text)


def _strip_non_factual_numbers(text: str) -> str:
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\d+[-–]\d+", "", text)
    text = re.sub(r"\(\d{4}\)", "", text)
    text = re.sub(r"\bVF\s*\d+\b", "", text, flags=re.IGNORECASE)
    # Strip product names with numbers (e.g., "Camera 360", "360 độ")
    text = re.sub(r"[Cc]amera\s*\d+", "camera", text)
    text = re.sub(r"\d+\s*độ", "", text)
    # Strip percentages (e.g., "10%", "70%" from spec labels like "10%-70%")
    text = re.sub(r"\d+\s*%", "", text)
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


_SPEC_KEY_TO_VI: dict[str, set[str]] | None = None


def _get_spec_key_vi_map() -> dict[str, set[str]]:
    """Build mapping from English spec keys to Vietnamese keywords."""
    global _SPEC_KEY_TO_VI
    if _SPEC_KEY_TO_VI is not None:
        return _SPEC_KEY_TO_VI
    from app.agent.decision import _SPEC_QUERY_KEYWORDS
    _TOKEN_RE = re.compile(r"[a-zà-ỹ0-9]+", re.UNICODE)
    key_to_vi: dict[str, set[str]] = {}
    for _group, tokens in _SPEC_QUERY_KEYWORDS.items():
        en_keys = set()
        vi_words = set()
        for phrase in tokens:
            words = set(_TOKEN_RE.findall(phrase.lower()))
            # English keys contain only ascii
            ascii_words = {w for w in words if all(c in "abcdefghijklmnopqrstuvwxyz0123456789_" for c in w)}
            vi_words |= words - ascii_words
            en_keys |= ascii_words
        for ek in en_keys:
            if ek not in key_to_vi:
                key_to_vi[ek] = set()
            key_to_vi[ek] |= vi_words
    _SPEC_KEY_TO_VI = key_to_vi
    return key_to_vi


_SPEC_KEY_ALIASES = {
    "head_up_display": ["hud", "head-up"],
    "surround_view_camera": ["camera 360", "camera360"],
    "adaptive_cruise_control": ["acc"],
    "anti_lock_braking_system": ["abs"],
    "electronic_stability_control": ["esc"],
    "traction_control": ["tcs"],
    "hill_start_assist": ["hsa"],
    "autonomous_emergency_braking": ["aeb"],
}


def _enrich_features_with_vi(features: set[str], spec_key: str, spec_value: str):
    """Add Vietnamese translations + common aliases for English spec keys."""
    vi_map = _get_spec_key_vi_map()
    key_lower = spec_key.lower()
    # Check if any English keyword from vi_map matches the spec key
    for en_key, vi_words in vi_map.items():
        if en_key in key_lower or key_lower.startswith(en_key):
            features |= vi_words
            break


def _extract_context_features(tool_results: list[dict]) -> tuple[set[str], str]:
    """Extract feature terms + raw text corpus from tool results."""
    features = set()
    raw_parts = []
    for tr in tool_results:
        if not tr.get("success"):
            continue
        result = tr["result"]
        tool = tr["tool"]
        if tool == "get_specs":
            for s in result.get("specs", []):
                key = s.get("key", "")
                value = s.get("value", "")
                features.add(key.lower())
                features.update(m.group().lower() for m in _FEATURE_RE.finditer(key))
                features.update(m.group().lower() for m in _FEATURE_RE.finditer(value))
                _enrich_features_with_vi(features, key, value)
                # Add common aliases for spec keys (e.g. head_up_display → hud)
                key_aliases = _SPEC_KEY_ALIASES.get(key.lower(), [])
                for alias in key_aliases:
                    features.add(alias)
                    raw_parts.append(alias)
                raw_parts.append(key)
                raw_parts.append(value)
        elif tool == "search_knowledge_base":
            for r in result.get("results", []):
                txt = r.get("text", "")
                features.update(m.group().lower() for m in _FEATURE_RE.finditer(txt))
                raw_parts.append(txt)
        elif tool == "get_price":
            for p in result.get("prices", []):
                features.add("giá")
                features.add("price")
                # Add price text to raw_corpus for grounding
                price_str = f"{p.get('version_name', '')} {p.get('price_vnd', '')} {p.get('promo_price_vnd', '')}"
                raw_parts.append(price_str)
    return features, " ".join(raw_parts).lower()


_NEGATIVE_CLAUSE_RE = re.compile(
    r"(không\s*(có|được\s*trang\s*bị|hỗ\s*trợ|trang\s*bị)|chưa\s*(có|trang\s*bị))",
    re.IGNORECASE,
)


def _nfc(text: str) -> str:
    """Normalize Unicode to NFC + lowercase + strip separators."""
    return unicodedata.normalize("NFC", re.sub(r"[\s\-_]", "", text.lower()))


def _check_text_grounding(response: str, tool_results: list[dict], query: str = "") -> bool:
    response_features = set(m.group().lower() for m in _FEATURE_RE.finditer(response))
    if not response_features:
        return True

    context_features, raw_corpus = _extract_context_features(tool_results)
    if not context_features and not raw_corpus:
        return True

    query_features = set(m.group().lower() for m in _FEATURE_RE.finditer(query)) if query else set()
    has_negative = bool(_NEGATIVE_CLAUSE_RE.search(response))
    raw_nfc = _nfc(raw_corpus)

    unmatched = set()
    for feat in response_features:
        normalized = _nfc(feat)

        # For negative claims about query features: require raw_corpus match.
        if has_negative and feat in query_features:
            feat_in_corpus = normalized in raw_nfc or feat in raw_nfc
            if not feat_in_corpus:
                unmatched.add(feat)
            continue

        found = False
        for ctx in context_features:
            ctx_norm = _nfc(ctx)
            if normalized in ctx_norm or ctx_norm in normalized:
                found = True
                break
        if not found and raw_corpus:
            if normalized in raw_nfc or feat in raw_nfc:
                found = True
        if not found:
            unmatched.add(feat)

    if not unmatched:
        return True

    ratio = len(unmatched) / len(response_features)
    if ratio >= 0.5:
        logger.warning("Text grounding fail: unmatched features %s / total %s (%.0f%%)", unmatched, response_features, ratio * 100)
        return False

    return True


def _check_grounding(response: str, tool_results: list[dict], query: str = "") -> bool:
    if not tool_results:
        return False

    if not _check_text_grounding(response, tool_results, query):
        return False

    response_numbers = _extract_numbers(_strip_non_factual_numbers(response))
    if not response_numbers:
        return True

    # Skip strict number check for price-only queries — LLM may format
    # prices differently (e.g., "830 triệu" vs "830,000,000"). Price data
    # comes directly from DB via get_price, no hallucination risk.
    tools_used = {tr.get("tool") for tr in tool_results if tr.get("success")}
    if tools_used == {"get_price"} or tools_used == {"get_price", "list_available_models"}:
        return True

    query_numbers = _extract_numbers(query) if query else set()

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

    all_ctx = price_numbers | spec_numbers | kb_numbers
    has_price = bool(price_numbers)

    PRICE_KW = re.compile(
        r"(gi[aá]|price|ni[eê]m\s+y[eế]t|[uư]u\s+[đd][ãa]i|VN[DĐ]|tri[eệ]u|t[yỷ]|l[aă]n\s+b[aá]nh|tr[aả]\s+g[oó]p)",
        re.IGNORECASE,
    )
    resp_has_price = bool(PRICE_KW.search(response))

    for num in response_numbers:
        if 1 <= num <= 9 and num == int(num):
            continue
        if num in query_numbers:
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

    # Build context-aware query for multi-turn
    query = state.get("query", "")
    history = state.get("history", [])
    scoring_query = query
    if history:
        history_queries = [m["content"] for m in history if m.get("role") == "user"]
        if history_queries:
            scoring_query = " ".join(history_queries) + " " + query

    assessment, valid_sources = assess_evidence(tool_results, scoring_query)
    citations = validate_citations(valid_sources, scoring_query)

    logger.info("VALIDATE: query=%s assessment=%s sources=%d citations=%d tools=%s",
                query, assessment, len(valid_sources), len(citations),
                [tr.get("tool") for tr in tool_results if tr.get("success")])

    # Only block on insufficient evidence — no grounding check (deferred to guardrails)
    if assessment == "insufficient":
        logger.warning("VALIDATE: refuse — insufficient_evidence")
        return {
            "decision": "refuse",
            "reason_code": "insufficient_evidence",
            "response_text": REFUSAL_MESSAGES["insufficient_evidence"],
            "assessment": assessment,
            "citations": [],
        }

    return {
        "decision": "answer",
        "assessment": assessment,
        "citations": citations,
    }
