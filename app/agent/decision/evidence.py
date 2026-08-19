"""Evidence assessment — keyword maps, assess_evidence (LRU memoize), validate_citations.

Không gọi embedding network trong answer path: keyword scoring đủ cho
validation decision. Embedding chỉ dùng trong retrieval (hybrid_search).
"""

import hashlib
import json
import logging
import re
import threading
import time
import unicodedata
from collections import OrderedDict

logger = logging.getLogger("bds.decision")

# ── Keyword maps ───────────────────────────────────────────────────────────
_SPEC_QUERY_KEYWORDS = {
    "công_suất": ["power_kw", "power", "công suất", "mã lực", "hp", "công suât"],
    "mômen_xoắn": ["torque_nm", "torque", "mô-men", "mô men", "xoắn", "mo men"],
    "tốc_độ": ["top_speed", "speed", "tốc độ", "tối đa", "tốc do"],
    "pin": ["battery_kwh", "battery", "battery_heater", "pin", "dung lượng", "dung luong", "kwh", "kWh", "gia nhiệt"],
    "quãng_đường": [
        "range_km",
        "range",
        "quãng đường",
        "phạm vi",
        "di chuyển",
        "đi được",
        "bao xa",
        "bao nhiêu km",
        "sạc đầy",
        "một lần sạc",
        "autonomy",
    ],
    "sạc": [
        "charge",
        "sạc",
        "charging",
        "charger",
        "charge_management",
        "charger_map",
        "nạp pin",
        "thời gian sạc",
        "sạc nhanh",
        "sạc chậm",
        "phút",
        "10%",
        "70%",
        "quản lý sạc",
        "trạm sạc",
        "bản đồ sạc",
    ],
    "kích_thước": [
        "length_mm",
        "width_mm",
        "height_mm",
        "wheelbase_mm",
        "ground_clearance_mm",
        "length",
        "width",
        "height",
        "wheelbase",
        "ground_clearance",
        "kích thước",
        "chiều dài",
        "chiều rộng",
        "chiều cao",
        "khoảng sáng gầm",
        "dài",
        "rộng",
        "cao",
    ],
    "trọng_lượng": ["curb_weight_kg", "curb_weight", "trọng lượng", "nặng", "kg"],
    "an_toàn": [
        "airbag",
        "abs",
        "ebd",
        "esc",
        "tcs",
        "hsa",
        "aeb",
        "collision",
        "túi khí",
        "an toàn",
        "phanh",
        "camera 360",
        "surround_view",
        "rearview",
        "parking",
        "blind_spot",
        "lane_keep",
        "lane_departure",
        "forward_collision",
        "emergency",
        "brake",
        "tpms",
        "rollover_mitigation",
        "isofix",
        "ảnh suất lốp",
        "chống lật",
        "ghế trẻ em",
    ],
    "nội_thất": [
        "seat",
        "ghế",
        "leatherette",
        "speaker",
        "loa",
        "màn hình",
        "display",
        "nội thất",
        "HUD",
        "head-up",
        "khoang xe",
        "vô lăng",
        "điều hòa",
        "seats",
        "trunk_capacity",
        "trunk",
        "steering",
        "subwoofer",
        "cốp",
        "cabin_air_filter",
        "lọc không khí",
        "lọc bụi",
        "rear_ac_vents",
        "cửa gió",
        "loa trầm",
    ],
    "ngoại_thất": [
        "headlight",
        "đèn",
        "wheel",
        "la-zăng",
        "mâm",
        "mirror",
        "gương",
        "ngoại thất",
        "màu",
        "body",
        "design",
        "drl",
        "tail_light",
        "wheel_size_inch",
        "adaptive_headlights",
        "windshield",
        "kính chắn gió",
        "frunk_capacity",
        "privacy_glass",
        "kính tối màu",
        "cốp trước",
    ],
    "giá": ["price", "giá", "giá niêm yết", "ưu đãi", "giá bán"],
    "adas": [
        "adas",
        "cruise",
        "lane",
        "blind_spot",
        "parking",
        "camera",
        "adasi",
        "highway",
        "traffic_jam",
        "lane_centering",
        "auto_lane_change",
        "hỗ trợ lái",
        "tự lái",
        "cấp",
    ],
    "phiên_bản": ["edition", "version", "phiên bản", "bản", "eco", "plus"],
    "tính_năng": [
        "tính năng",
        "trang bị",
        "công nghệ",
        "thông minh",
        "tiện nghi",
        "ota",
        "navigation",
        "bluetooth",
        "carplay",
        "android",
        "gaming",
        "voice",
        "phone_app",
        "web_browser",
        "smartphone",
        "smart_key",
        "chìa khóa",
        "usb",
        "cổng sạc",
    ],
    "điều_hòa": ["ac_type", "điều hòa", "climate", "nhiệt độ", "lạnh", "máy lạnh"],
}

_TOKEN_RE = re.compile(r"[a-zà-ỹ0-9]+", re.UNICODE)

_MODEL_RE = re.compile(
    r"(VF\s*\d+|VF\s*e34|VF\s*MPV\s*7|Herio\s*Green|Minio\s*Green|Limo\s*Green|EC\s*VAN|Nerio\s*Green)",
    re.IGNORECASE,
)


def _query_tokens(query: str) -> set[str]:
    return set(_TOKEN_RE.findall(unicodedata.normalize("NFC", query).lower()))


def _query_models(query: str) -> set[str]:
    """Extract normalized model codes mentioned in the query."""
    matches = _MODEL_RE.findall(query)
    return {m.upper().replace(" ", "").replace("\u00a0", "") for m in matches}


def _spec_relevance_score(query_tokens: set[str], spec_key: str, spec_value: str) -> float:
    """Score 0.0-1.0 indicating how relevant a spec is to the query."""
    key_lower = spec_key.lower()
    value_lower = spec_value.lower()
    key_tokens = set(_TOKEN_RE.findall(key_lower + " " + value_lower))

    for group_tokens in _SPEC_QUERY_KEYWORDS.values():
        # Tokenize multi-word phrases (e.g. "công suất" → {"công", "suất"})
        group_set: set[str] = set()
        for phrase in group_tokens:
            group_set.update(_TOKEN_RE.findall(phrase.lower()))
        query_match = group_set & query_tokens
        spec_match = group_set & key_tokens
        if query_match and spec_match:
            return 0.9

    if key_tokens & query_tokens:
        return 0.7

    return 0.3


def _price_relevance_score(query_tokens: set[str]) -> float:
    price_tokens = {"giá", "price", "niêm yết", "ưu đãi", "vnđ", "triệu", "tỷ", "cost", "bao nhiêu"}
    if price_tokens & query_tokens:
        return 0.9
    return 0.5


def _score_specs_rerank(query: str, specs: list[dict], qtokens: set[str]) -> list[float]:
    """Score specs by keyword matching ONLY.

    Không gọi embedding — keyword score đủ cho answer generation.
    Embedding chỉ dùng trong background logging (make_decision_log).
    """
    return [_spec_relevance_score(qtokens, s.get("key", ""), s.get("value", "")) for s in specs]


# Cache assess_evidence: content-hash key, LRU 128 entries, TTL 2 phút.
# Key theo NỘI DUNG nên không có rủi ro stale: data đổi → tool_results đổi
# → key đổi → miss. LƯU Ý: sources trả về từ cache là object dùng chung —
# caller chỉ đọc, không mutate.
_ASSESS_CACHE_TTL = 120
_ASSESS_CACHE_MAX = 128
_assess_cache: OrderedDict = OrderedDict()
_assess_cache_lock = threading.Lock()


def _assess_cache_key(tool_results: list[dict], query: str) -> str | None:
    try:
        payload = json.dumps(tool_results, sort_keys=True, ensure_ascii=False, default=str)
    except Exception:
        return None  # Không serialize được → bỏ cache, vẫn chạy bình thường
    return hashlib.sha256((payload + "\x00" + query).encode("utf-8")).hexdigest()


def assess_evidence(tool_results: list[dict], query: str) -> tuple[str, list[dict]]:
    # Memoize theo nội dung: hàm pure nên cùng (tool_results, query) → cùng
    # kết quả. Cache khử lần tính lại trong respond/make_decision_log.
    key = _assess_cache_key(tool_results, query)
    if key is not None:
        with _assess_cache_lock:
            hit = _assess_cache.get(key)
            if hit is not None:
                ts, assessment, sources = hit
                if time.time() - ts < _ASSESS_CACHE_TTL:
                    _assess_cache.move_to_end(key)
                    return assessment, sources
                del _assess_cache[key]

    assessment, valid_sources = _assess_evidence_impl(tool_results, query)

    if key is not None:
        with _assess_cache_lock:
            _assess_cache[key] = (time.time(), assessment, valid_sources)
            while len(_assess_cache) > _ASSESS_CACHE_MAX:
                _assess_cache.popitem(last=False)  # LRU: loại entry cũ nhất
    return assessment, valid_sources


def _assess_evidence_impl(tool_results: list[dict], query: str) -> tuple[str, list[dict]]:
    if not tool_results:
        return "insufficient", []

    valid_sources = []
    has_direct = False
    has_partial = False
    qtokens = _query_tokens(query)

    for tr in tool_results:
        if not tr.get("success"):
            continue
        result = tr["result"]
        tool = tr["tool"]

        if tool == "get_specs" and result.get("specs"):
            specs = result["specs"]
            scores = _score_specs_rerank(query, specs, qtokens)
            for i, s in enumerate(specs):
                score = scores[i] if i < len(scores) else 0.0
                page = s.get("page", "")
                page_str = f" (trang {page})" if page else ""
                valid_sources.append(
                    {
                        "tool": tool,
                        "model_code": result.get("model_code", ""),
                        "text": f"{s.get('key', '')}: {s.get('value', '')} {s.get('unit', '')}{page_str}",
                        "source_url": result.get("source_url", ""),
                        "source_type": "specs",
                        "score": round(score, 4),
                        "page": page,
                    }
                )
                if score >= 0.5:
                    has_direct = True
                elif score >= 0.2:
                    has_partial = True

        elif tool == "get_price" and result.get("prices"):
            score = _price_relevance_score(qtokens)
            for p in result["prices"]:
                valid_sources.append(
                    {
                        "tool": tool,
                        "model_code": result.get("model_code", ""),
                        "text": f"{p.get('version_name', '')}: {p.get('price_vnd', '')}",
                        "source_url": result.get("source_url", ""),
                        "source_type": "pricing",
                        "score": score,
                    }
                )
            if score >= 0.7:
                has_direct = True
            else:
                has_partial = True

        elif tool == "search_knowledge_base" and result.get("results"):
            is_supplementary = tr.get("auto_injected", False)
            for r in result["results"]:
                score = r.get("score", 0)
                if score >= 0.3:
                    page = r.get("page", "")
                    page_str = f" (trang {page})" if page else ""
                    text = r.get("text", "")[:200]
                    valid_sources.append(
                        {
                            "tool": tool,
                            "text": f"{text}{page_str}",
                            "source_url": r.get("source_url", ""),
                            "source_type": r.get("source_type", ""),
                            "score": score,
                            "chunk_id": r.get("id", ""),
                            "model_id": r.get("model_id", ""),
                            "page": page,
                            "supplementary": is_supplementary,
                        }
                    )
                    if is_supplementary:
                        # Auto-injected KB: supplementary only, never direct
                        has_partial = True
                    elif score >= 0.5:
                        has_direct = True
                    else:
                        has_partial = True

        elif tool == "list_available_models" and result.get("models"):
            mentioned = _query_models(query)
            found_any = False
            for m in result["models"]:
                mc = m.get("model_code", "")
                mc_compact = mc.upper().replace(" ", "")
                vers = ", ".join(m.get("versions", []))
                if mentioned and mc_compact not in mentioned:
                    continue
                valid_sources.append(
                    {
                        "tool": tool,
                        "model_code": mc,
                        "text": f"{mc} — Phiên bản: {vers}",
                        "source_url": m.get("source_url", ""),
                        "source_type": "catalog",
                        "score": 0.9,
                    }
                )
                found_any = True
            if found_any:
                has_direct = True

        elif tool == "get_colors" and result.get("colors"):
            mc = result.get("model_code", "")
            colors = result.get("colors", [])
            interiors = result.get("interiors", [])
            text = f"{mc}: {len(colors)} màu ngoại thất, {len(interiors)} màu nội thất"
            # Ưu tiên source_url thật từ DB; fallback trang sản phẩm VinFast
            model_slug = mc.lower().replace(" ", "")
            source_url = result.get("source_url") or f"https://shop.vinfastauto.com/vn_vi/dat-coc-xe-{model_slug}.html"
            valid_sources.append(
                {
                    "tool": tool,
                    "model_code": mc,
                    "text": text,
                    "source_url": source_url,
                    "source_type": "colors",
                    "score": 0.9,
                }
            )
            has_direct = True

        # Catch-all: utility tools that return URLs (showroom, booking, loan, etc.)
        elif tool not in ("get_specs", "get_price", "search_knowledge_base", "list_available_models", "get_colors"):
            url = result.get("url", "")
            label = result.get("label", tool)
            # Handle tools that return links array
            if not url and result.get("links"):
                first = result["links"][0]
                url = first.get("url") or first.get("source_url", "")
            if url:
                valid_sources.append(
                    {
                        "tool": tool,
                        "model_code": "",
                        "text": label,
                        "source_url": url,
                        "source_type": "utility",
                        "score": 0.9,
                    }
                )
                has_direct = True

    if has_direct:
        return "direct_support", valid_sources
    if has_partial:
        return "partial_support", valid_sources

    # Special case: get_specs returned data for the model (dù không match với query)
    # → coi như có partial evidence, LLM sẽ trả lời "không có thông tin về tính năng này"
    for tr in tool_results:
        if tr.get("tool") == "get_specs" and tr.get("result", {}).get("specs"):
            return "partial_support", valid_sources

    return "insufficient", valid_sources


def validate_citations(sources: list[dict], query: str = "") -> list[dict]:
    """Filter citations: must have valid source reference AND be relevant to the query."""
    valid = []
    qtokens = _query_tokens(query) if query else set()
    for s in sources:
        url = s.get("source_url", "")
        # Accept any non-empty source reference (HTTP URL, file path, document name)
        if not url:
            continue
        # Content relevance gate: if we have query tokens, check that the
        # source text has at least some overlap with the query.
        text = s.get("text", "").lower()
        score = s.get("score", 0)
        if qtokens and text:
            text_tokens = set(_TOKEN_RE.findall(text))
            overlap = qtokens & text_tokens - {"xe", "vinfast", "vf", "của", "và", "là", "cho", "tôi", "bạn"}
            # Accept if score is high (from reranker/embedding) OR has meaningful token overlap
            if score < 0.3 and len(overlap) == 0:
                continue
        valid.append(s)
    return valid
