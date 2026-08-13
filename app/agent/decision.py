import hashlib
import json
import logging
import re
import subprocess
import time
import unicodedata
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from app.config import settings

logger = logging.getLogger("bds.decision")

REPO_ROOT = Path(__file__).resolve().parents[2]
_cached_data_snapshot = None


# ── Reason Code Enum (contract §5) ─────────────────────────────────────────
class ReasonCode(str, Enum):
    # answer
    SUFFICIENT_DIRECT_EVIDENCE = "sufficient_direct_evidence"
    PARTIAL_DIRECT_EVIDENCE = "partial_direct_evidence"
    # clarify
    MISSING_MODEL = "missing_model"
    MISSING_VERSION = "missing_version"
    MISSING_TOPIC = "missing_topic"
    AMBIGUOUS_CONTEXT = "ambiguous_context"
    # refuse
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    INDIRECT_EVIDENCE = "indirect_evidence"
    INVALID_SOURCE = "invalid_source"
    SOURCE_CONFLICT = "source_conflict"
    CITATION_FAILURE = "citation_failure"
    SYSTEM_ERROR = "system_error"
    GROUNDING_FAILURE = "grounding_failure"
    # out_of_scope
    UNSUPPORTED_MODEL = "unsupported_model"
    UNSUPPORTED_COMPARISON = "unsupported_comparison"
    UNSUPPORTED_RECOMMENDATION = "unsupported_recommendation"
    UNSUPPORTED_PRICING_POLICY = "unsupported_pricing_policy"
    UNSUPPORTED_AFTER_SALES = "unsupported_after_sales"
    UNSUPPORTED_SAFETY_DIAGNOSIS = "unsupported_safety_diagnosis"
    UNSUPPORTED_CONTACT_WORKFLOW = "unsupported_contact_workflow"
    EXTERNAL_SOURCE_REQUESTED = "external_source_requested"
    PERSONAL_DATA_OR_TRANSACTION = "personal_data_or_transaction"


# Map classifier reason strings → ReasonCode
_REASON_MAP = {
    "BDS-01": ReasonCode.SUFFICIENT_DIRECT_EVIDENCE,
    "BDS-02": ReasonCode.MISSING_MODEL,
    "BDS-02A": ReasonCode.UNSUPPORTED_MODEL,
    "BDS-03": ReasonCode.MISSING_VERSION,
    "BDS-04": ReasonCode.SUFFICIENT_DIRECT_EVIDENCE,
    "BDS-05": ReasonCode.MISSING_TOPIC,
    "BDS-06": ReasonCode.INSUFFICIENT_EVIDENCE,
    "BDS-07A": ReasonCode.INDIRECT_EVIDENCE,
    "BDS-07B": ReasonCode.PARTIAL_DIRECT_EVIDENCE,
    "BDS-08": ReasonCode.INVALID_SOURCE,
    "BDS-09": ReasonCode.SOURCE_CONFLICT,
    "BDS-10": ReasonCode.AMBIGUOUS_CONTEXT,
    "BDS-11": ReasonCode.UNSUPPORTED_COMPARISON,
    "BDS-12": ReasonCode.UNSUPPORTED_RECOMMENDATION,
    "BDS-13": ReasonCode.UNSUPPORTED_PRICING_POLICY,
    "BDS-14": ReasonCode.UNSUPPORTED_AFTER_SALES,
    "BDS-15": ReasonCode.UNSUPPORTED_SAFETY_DIAGNOSIS,
    "BDS-16": ReasonCode.UNSUPPORTED_CONTACT_WORKFLOW,
    "BDS-17": ReasonCode.EXTERNAL_SOURCE_REQUESTED,
    "BDS-18": ReasonCode.CITATION_FAILURE,
    "BDS-19": ReasonCode.SYSTEM_ERROR,
    "insufficient_evidence": ReasonCode.INSUFFICIENT_EVIDENCE,
    "no_citation": ReasonCode.CITATION_FAILURE,
    "grounding_fail": ReasonCode.GROUNDING_FAILURE,
    "system_error": ReasonCode.SYSTEM_ERROR,
    "comparison": ReasonCode.UNSUPPORTED_COMPARISON,
    "recommendation": ReasonCode.UNSUPPORTED_RECOMMENDATION,
    "pricing": ReasonCode.UNSUPPORTED_PRICING_POLICY,
    "warranty_maintenance": ReasonCode.UNSUPPORTED_AFTER_SALES,
    "diagnostics": ReasonCode.UNSUPPORTED_SAFETY_DIAGNOSIS,
    "hotline_showroom": ReasonCode.UNSUPPORTED_CONTACT_WORKFLOW,
    "external_source": ReasonCode.EXTERNAL_SOURCE_REQUESTED,
    "personal_data": ReasonCode.PERSONAL_DATA_OR_TRANSACTION,
    "model_oos": ReasonCode.UNSUPPORTED_MODEL,
    "ambiguous_context": ReasonCode.AMBIGUOUS_CONTEXT,
    "missing_model": ReasonCode.MISSING_MODEL,
    "missing_version": ReasonCode.MISSING_VERSION,
    "missing_topic": ReasonCode.MISSING_TOPIC,
    "missing_context": ReasonCode.AMBIGUOUS_CONTEXT,
    "sufficient_direct": ReasonCode.SUFFICIENT_DIRECT_EVIDENCE,
}


def resolve_reason_code(reason: str) -> str:
    """Map classifier reason string → ReasonCode enum value."""
    for prefix, code in sorted(_REASON_MAP.items(), key=lambda x: -len(x[0])):
        if prefix in reason:
            return code.value
    logger.warning("Unmapped classifier reason: %r — defaulting to system_error for safety", reason)
    return ReasonCode.SYSTEM_ERROR.value


# ── Version helpers ────────────────────────────────────────────────────────
_cached_build_version = None


def _get_build_version() -> str:
    global _cached_build_version
    if _cached_build_version is not None:
        return _cached_build_version
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
            cwd=str(REPO_ROOT),
        )
        _cached_build_version = result.stdout.strip() or "unknown"
    except Exception:
        _cached_build_version = "unknown"
    return _cached_build_version


def _get_prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]


def _get_data_snapshot_id() -> str:
    """Read active data version from PG ingest_version table (is_current=True)."""
    global _cached_data_snapshot
    if _cached_data_snapshot is not None:
        return _cached_data_snapshot
    try:
        import psycopg2
        pg_url = settings.postgres_url.replace("+asyncpg", "")
        conn = psycopg2.connect(pg_url)
        cur = conn.cursor()
        cur.execute(
            "SELECT version, created_at FROM ingest_version WHERE is_current LIMIT 1"
        )
        row = cur.fetchone()
        conn.close()
        if row:
            ver, created_at = row
            ts = created_at.strftime("%Y-%m-%d") if created_at else ""
            _cached_data_snapshot = f"{ver}_{ts}"
            return _cached_data_snapshot
    except Exception:
        pass

    manifest = REPO_ROOT / "data" / "clean" / "v1" / "_manifest.json"
    if manifest.exists():
        try:
            m = json.loads(manifest.read_text(encoding="utf-8"))
            _cached_data_snapshot = m.get("version", "v1") + "_" + m.get("created_at", "")[:10]
            return _cached_data_snapshot
        except Exception:
            pass
    _cached_data_snapshot = "unknown"
    return _cached_data_snapshot


# ── P0 Decision Log ────────────────────────────────────────────────────────
@dataclass
class RetrievedChunk:
    rank: int = 0
    chunk_id: str = ""
    source_id: str = ""
    source_title: str = ""
    source_url: str = ""
    content: str = ""
    vehicle_model: str = ""
    vehicle_version: str = ""
    topic: str = ""
    approval_status: str = "approved"
    retrieval_score: float = 0.0
    page: str = ""


@dataclass
class DisplayedCitation:
    display_text: str = ""
    source_id: str = ""
    chunk_ids: list[str] = field(default_factory=list)
    source_url: str = ""
    section: str = ""


@dataclass
class DecisionLog:
    # §4.1 Request & version identity
    schema_version: str = "1.0"
    request_id: str = ""
    timestamp: str = ""
    run_id: str = ""
    test_id: str = ""
    build_version: str = ""
    prompt_version: str = ""
    data_snapshot_id: str = ""
    conversation_id: str = ""
    turn_index: int = 0
    previous_request_id: str = ""

    # §4.2 Input & detected context
    user_query: str = ""
    detected_vehicle_model: str = "unknown"
    detected_vehicle_version: str = "unknown"
    detected_topic: str = "unknown"
    decision: str = ""
    reason_code: str = ""

    # §4.3 Retrieval & evidence
    retrieval_status: str = "not_run"
    retrieved_chunks: list[dict] = field(default_factory=list)
    retrieval_query: str = ""
    requested_top_k: int = 5
    evidence_assessment: str = ""

    # §4.4 Answer & citation
    displayed_answer: str = ""
    displayed_citations: list[dict] = field(default_factory=list)

    # §4.5 Latency & error
    error_stage: str = ""
    error_type: str = ""
    error_message: str = ""
    latency_total_ms: float = 0.0
    latency_retrieval_ms: float = 0.0
    latency_generation_ms: float = 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("retrieval_query", None)
        d.pop("requested_top_k", None)
        return d


# ── Log Store (in-memory, exportable) ──────────────────────────────────────
class LogStore:
    """In-memory store for decision logs. Export to JSONL."""

    def __init__(self):
        self._logs: list[dict] = []
        self._run_id = ""
        self._run_timestamp = ""

    def start_run(self) -> str:
        self._run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        self._run_timestamp = datetime.now(timezone.utc).isoformat()
        return self._run_id

    def add(self, log: DecisionLog) -> None:
        if not self._run_id:
            self.start_run()
        log.run_id = self._run_id
        if not log.build_version:
            log.build_version = _get_build_version()
        if not log.data_snapshot_id:
            log.data_snapshot_id = _get_data_snapshot_id()
        self._logs.append(log.to_dict())

    def get_all(self) -> list[dict]:
        return list(self._logs)

    def get_by_run(self, run_id: str) -> list[dict]:
        return [l for l in self._logs if l.get("run_id") == run_id]

    def export_jsonl(self, path: str | Path) -> int:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            for log in self._logs:
                f.write(json.dumps(log, ensure_ascii=False) + "\n")
        return len(self._logs)

    def clear(self):
        self._logs.clear()


log_store = LogStore()


# ── Response Messages ──────────────────────────────────────────────────────

REFUSAL_MESSAGES = {
    "insufficient_evidence": "Mình chưa thể xác nhận thông tin chính từ nguồn hiện có.",
    "no_citation": "Mình chưa thể xác nhận vì chưa có nguồn kiểm chứng hợp lệ.",
    "grounding_fail": "Mình chưa thể xác nhận thông tin này từ nguồn đã được phê duyệt hiện có.",
    "system_error": "Mình chưa thể hoàn tất câu trả lời lúc này. Vui lòng thử lại.",
}


def get_clarify_messages() -> dict[str, str]:
    return {
        "model_code": "Bạn muốn hỏi về xe VinFast nào?",
        "topic": "Bạn muốn tìm thông tin nào về {model}?",
    }


# ── Evidence Assessment ────────────────────────────────────────────────────
_SPEC_QUERY_KEYWORDS = {
    "công_suất": ["power_kw", "power", "công suất", "mã lực", "hp", "công suât"],
    "mômen_xoắn": ["torque_nm", "torque", "mô-men", "mô men", "xoắn", "mo men"],
    "tốc_độ": ["top_speed", "speed", "tốc độ", "tối đa", "tốc do"],
    "pin": ["battery_kwh", "battery", "battery_heater", "pin", "dung lượng", "dung luong", "kwh", "kWh", "gia nhiệt"],
    "quãng_đường": ["range_km", "range", "quãng đường", "quãng đường", "phạm vi", "di chuyển",
                     "đi được", "bao xa", "bao nhiêu km", "sạc đầy", "một lần sạc", "autonomy"],
    "sạc": ["charge", "sạc", "charging", "charger", "charge_management", "charger_map",
            "nạp pin", "thời gian sạc", "sạc nhanh", "sạc chậm", "phút", "10%", "70%",
            "quản lý sạc", "trạm sạc", "bản đồ sạc"],
    "kích_thước": ["length_mm", "width_mm", "height_mm", "wheelbase_mm", "ground_clearance_mm",
                   "length", "width", "height", "wheelbase", "ground_clearance",
                   "kích thước", "chiều dài", "chiều rộng", "chiều cao",
                   "khoảng sáng gầm", "dài", "rộng", "cao"],
    "trọng_lượng": ["curb_weight_kg", "curb_weight", "trọng lượng", "nặng", "kg"],
    "an_toàn": ["airbag", "abs", "ebd", "esc", "tcs", "hsa", "aeb", "collision",
                "túi khí", "an toàn", "phanh", "camera 360", "surround_view",
                "rearview", "parking", "blind_spot", "lane_keep", "lane_departure",
                "forward_collision", "emergency", "brake", "tpms", "rollover_mitigation",
                "isofix", "ảnh suất lốp", "chống lật", "ghế trẻ em"],
    "nội_thất": ["seat", "ghế", "leatherette", "speaker", "loa", "màn hình", "display",
                 "nội thất", "HUD", "head-up", "khoang xe", "vô lăng", "điều hòa",
                 "seats", "trunk_capacity", "trunk", "steering", "subwoofer", "cốp",
                 "cabin_air_filter", "lọc không khí", "lọc bụi", "rear_ac_vents",
                 "cửa gió", "loa trầm"],
    "ngoại_thất": ["headlight", "đèn", "wheel", "la-zăng", "mâm", "mirror", "gương",
                   "ngoại thất", "màu", "body", "design", "drl", "tail_light",
                   "wheel_size_inch", "adaptive_headlights", "windshield", "kính chắn gió",
                   "frunk_capacity", "privacy_glass", "kính tối màu", "cốp trước"],
    "giá": ["price", "giá", "giá niêm yết", "ưu đãi", "giá bán"],
    "adas": ["adas", "cruise", "lane", "blind_spot", "parking", "camera", "adasi",
             "highway", "traffic_jam", "lane_centering", "auto_lane_change",
             "hỗ trợ lái", "tự lái", "cấp"],
    "phiên_bản": ["edition", "version", "phiên bản", "bản", "eco", "plus"],
    "tính_năng": ["tính năng", "trang bị", "công nghệ", "thông minh", "tiện nghi",
                  "ota", "navigation", "bluetooth", "carplay", "android", "gaming",
                  "voice", "phone_app", "web_browser", "smartphone",
                  "smart_key", "chìa khóa", "usb", "cổng sạc"],
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


def _rerank_texts(query: str, texts: list[str]) -> list[float] | None:
    """Score texts against query using embedding cosine similarity.

    Uses the same embedding model as retrieval (OpenRouter text-embedding-3-small).
    Returns list of floats (0.0-1.0) or None if embedding unavailable.
    """
    if not texts:
        return None
    try:
        from app.core.retrieval import _openrouter_embed
        all_texts = [query] + texts
        embeddings = _openrouter_embed(all_texts)
        if len(embeddings) < len(all_texts):
            return None
        query_emb = embeddings[0]
        import numpy as np
        query_arr = np.array(query_emb)
        query_norm = np.linalg.norm(query_arr)
        if query_norm == 0:
            return None
        scores = []
        for i in range(1, len(embeddings)):
            doc_arr = np.array(embeddings[i])
            doc_norm = np.linalg.norm(doc_arr)
            if doc_norm == 0:
                scores.append(0.0)
            else:
                sim = float(np.dot(query_arr, doc_arr) / (query_norm * doc_norm))
                scores.append(max(0.0, min(1.0, sim)))
        return scores
    except Exception as e:
        logger.warning("Embedding score failed: %s", e)
        return None


def _score_specs_rerank(query: str, specs: list[dict], qtokens: set[str]) -> list[float]:
    """Score specs using keyword matching first, embedding only for ambiguous specs.

    Keyword matching is instant (no API call). Embedding is only used for specs
    where keyword score is ambiguous (0.3-0.5). This avoids 200+ embedding calls
    when most specs are clearly relevant or irrelevant.
    """
    keyword_scores = [
        _spec_relevance_score(qtokens, s.get("key", ""), s.get("value", ""))
        for s in specs
    ]

    # Find indices where keyword score is ambiguous (needs embedding)
    ambiguous = [i for i, s in enumerate(keyword_scores) if 0.25 <= s < 0.5]

    if not ambiguous:
        return keyword_scores  # All clear, no embedding needed

    # Only embed ambiguous specs
    ambiguous_specs = [specs[i] for i in ambiguous]
    spec_texts = [
        f"{s.get('key', '')}: {s.get('value', '')} {s.get('unit', '')}"
        for s in ambiguous_specs
    ]
    embed_scores = _rerank_texts(query, spec_texts)

    if embed_scores and len(embed_scores) == len(ambiguous):
        result = list(keyword_scores)
        for j, idx in enumerate(ambiguous):
            result[idx] = max(embed_scores[j], keyword_scores[idx])
        return result

    return keyword_scores


def assess_evidence(tool_results: list[dict], query: str) -> tuple[str, list[dict]]:
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
                valid_sources.append({
                    "tool": tool,
                    "model_code": result.get("model_code", ""),
                    "text": f"{s.get('key', '')}: {s.get('value', '')} {s.get('unit', '')}{page_str}",
                    "source_url": result.get("source_url", ""),
                    "source_type": "specs",
                    "score": round(score, 4),
                    "page": page,
                })
                if score >= 0.5:
                    has_direct = True
                elif score >= 0.2:
                    has_partial = True

        elif tool == "get_price" and result.get("prices"):
            score = _price_relevance_score(qtokens)
            for p in result["prices"]:
                valid_sources.append({
                    "tool": tool,
                    "model_code": result.get("model_code", ""),
                    "text": f"{p.get('version_name', '')}: {p.get('price_vnd', '')}",
                    "source_url": result.get("source_url", ""),
                    "source_type": "pricing",
                    "score": score,
                })
            if score >= 0.7:
                has_direct = True
            else:
                has_partial = True

        elif tool == "search_knowledge_base" and result.get("results"):
            for r in result["results"]:
                score = r.get("score", 0)
                if score >= 0.3:
                    page = r.get("page", "")
                    page_str = f" (trang {page})" if page else ""
                    text = r.get("text", "")[:200]
                    valid_sources.append({
                        "tool": tool,
                        "text": f"{text}{page_str}",
                        "source_url": r.get("source_url", ""),
                        "source_type": r.get("source_type", ""),
                        "score": score,
                        "chunk_id": r.get("id", ""),
                        "model_id": r.get("model_id", ""),
                        "page": page,
                    })
                    if score >= 0.5:
                        has_direct = True
                    else:
                        has_partial = True

        elif tool == "search_all":
            sub_specs = result.get("specs", {})
            if sub_specs.get("specs"):
                specs = sub_specs["specs"]
                scores = _score_specs_rerank(query, specs, qtokens)
                for i, s in enumerate(specs):
                    score = scores[i] if i < len(scores) else 0.0
                    page = s.get("page", "")
                    page_str = f" (trang {page})" if page else ""
                    valid_sources.append({
                        "tool": "get_specs",
                        "model_code": sub_specs.get("model_code", ""),
                        "text": f"{s.get('key', '')}: {s.get('value', '')} {s.get('unit', '')}{page_str}",
                        "source_url": sub_specs.get("source_url", ""),
                        "source_type": "specs",
                        "score": round(score, 4),
                        "page": page,
                    })
                    if score >= 0.5:
                        has_direct = True
                    elif score >= 0.2:
                        has_partial = True
            sub_kb = result.get("knowledge_base", {})
            if sub_kb.get("results"):
                for r in sub_kb["results"]:
                    score = r.get("score", 0)
                    if score >= 0.3:
                        page = r.get("page", "")
                        page_str = f" (trang {page})" if page else ""
                        text = r.get("text", "")[:200]
                        valid_sources.append({
                            "tool": "search_knowledge_base",
                            "text": f"{text}{page_str}",
                            "source_url": r.get("source_url", ""),
                            "source_type": r.get("source_type", ""),
                            "score": score,
                            "chunk_id": r.get("id", ""),
                            "model_id": r.get("model_id", ""),
                            "page": page,
                        })
                        if score >= 0.5:
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
                valid_sources.append({
                    "tool": tool,
                    "model_code": mc,
                    "text": f"{mc} — Phiên bản: {vers}",
                    "source_url": m.get("source_url", ""),
                    "source_type": "catalog",
                    "score": 0.9,
                })
                found_any = True
            if found_any:
                has_direct = True

        elif tool == "get_colors" and result.get("colors"):
            mc = result.get("model_code", "")
            colors = result.get("colors", [])
            interiors = result.get("interiors", [])
            text = f"{mc}: {len(colors)} màu ngoại thất, {len(interiors)} màu nội thất"
            # Use VinFast product page as source
            model_slug = mc.lower().replace(" ", "")
            source_url = f"https://shop.vinfastauto.com/vn_vi/dat-coc-xe-{model_slug}.html"
            valid_sources.append({
                "tool": tool,
                "model_code": mc,
                "text": text,
                "source_url": source_url,
                "source_type": "colors",
                "score": 0.9,
            })
            has_direct = True

        # Catch-all: utility tools that return URLs (showroom, booking, loan, etc.)
        elif tool not in ("get_specs", "get_price", "search_knowledge_base",
                          "search_all", "list_available_models", "get_colors"):
            url = result.get("url", "")
            label = result.get("label", tool)
            # Handle tools that return links array
            if not url and result.get("links"):
                first = result["links"][0]
                url = first.get("url") or first.get("source_url", "")
            if url:
                valid_sources.append({
                    "tool": tool,
                    "model_code": "",
                    "text": label,
                    "source_url": url,
                    "source_type": "utility",
                    "score": 0.9,
                })
                has_direct = True

    if has_direct:
        return "direct_support", valid_sources
    if has_partial:
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


def build_retrieved_chunks(tool_results: list[dict], query: str = "") -> list[dict]:
    """Convert tool_results → P0 retrieved_chunks schema."""
    chunks = []
    rank = 0
    qtokens = _query_tokens(query) if query else set()

    for tr in tool_results:
        if not tr.get("success"):
            continue
        result = tr["result"]
        tool = tr["tool"]

        if tool == "search_knowledge_base" and result.get("results"):
            for r in result["results"]:
                rank += 1
                page = r.get("page", "")
                page_str = f" (trang {page})" if page else ""
                chunks.append(RetrievedChunk(
                    rank=rank,
                    chunk_id=r.get("id", f"kb_{rank}"),
                    source_id=r.get("source_type", ""),
                    source_title=r.get("source_type", ""),
                    source_url=r.get("source_url", ""),
                    content=f"{r.get('text', '')[:500]}{page_str}",
                    vehicle_model=r.get("model_id", "") or "",
                    vehicle_version="all_versions",
                    topic="",
                    approval_status="approved",
                    retrieval_score=r.get("score", 0.0),
                    page=page,
                ).__dict__)

        elif tool == "get_specs" and result.get("specs"):
            for s in result["specs"]:
                rank += 1
                score = _spec_relevance_score(qtokens, s.get("key", ""), s.get("value", "")) if qtokens else 0.5
                page = s.get("page", "")
                page_str = f" (trang {page})" if page else ""
                chunks.append(RetrievedChunk(
                    rank=rank,
                    chunk_id=f"spec_{result.get('model_code', '')}_{s.get('key', '')}",
                    source_id="car_specs",
                    source_title=f"Specs {result.get('model_code', '')}",
                    source_url=result.get("source_url", ""),
                    content=f"{s.get('key', '')}: {s.get('value', '')} {s.get('unit', '')}{page_str}",
                    vehicle_model=result.get("model_code", ""),
                    vehicle_version=s.get("version_name", "all_versions"),
                    topic="thông_số_kỹ_thuật",
                    approval_status="approved",
                    retrieval_score=score,
                    page=page,
                ).__dict__)

        elif tool == "get_price" and result.get("prices"):
            price_score = _price_relevance_score(qtokens) if qtokens else 0.5
            for p in result["prices"]:
                rank += 1
                chunks.append(RetrievedChunk(
                    rank=rank,
                    chunk_id=f"price_{result.get('model_code', '')}_{p.get('version_name', '')}",
                    source_id="price_list",
                    source_title=f"Giá {result.get('model_code', '')}",
                    source_url=result.get("source_url", ""),
                    content=f"{p.get('version_name', '')}: {p.get('price_vnd', '')}",
                    vehicle_model=result.get("model_code", ""),
                    vehicle_version=p.get("version_name", "all_versions"),
                    topic="pricing",
                    approval_status="approved",
                    retrieval_score=price_score,
                ).__dict__)

        elif tool == "search_all":
            sub_specs = result.get("specs", {})
            if sub_specs.get("specs"):
                for s in sub_specs["specs"]:
                    rank += 1
                    score = _spec_relevance_score(qtokens, s.get("key", ""), s.get("value", "")) if qtokens else 0.5
                    page = s.get("page", "")
                    page_str = f" (trang {page})" if page else ""
                    chunks.append(RetrievedChunk(
                        rank=rank,
                        chunk_id=f"spec_{sub_specs.get('model_code', '')}_{s.get('key', '')}",
                        source_id="car_specs",
                        source_title=f"Specs {sub_specs.get('model_code', '')}",
                        source_url=sub_specs.get("source_url", ""),
                        content=f"{s.get('key', '')}: {s.get('value', '')} {s.get('unit', '')}{page_str}",
                        vehicle_model=sub_specs.get("model_code", ""),
                        vehicle_version=s.get("version_name", "all_versions"),
                        topic="thông_số_kỹ_thuật",
                        approval_status="approved",
                        retrieval_score=score,
                        page=page,
                    ).__dict__)
            sub_kb = result.get("knowledge_base", {})
            if sub_kb.get("results"):
                for r in sub_kb["results"]:
                    rank += 1
                    page = r.get("page", "")
                    page_str = f" (trang {page})" if page else ""
                    chunks.append(RetrievedChunk(
                        rank=rank,
                        chunk_id=r.get("id", f"kb_{rank}"),
                        source_id=r.get("source_type", ""),
                        source_title=r.get("source_type", ""),
                        source_url=r.get("source_url", ""),
                        content=f"{r.get('text', '')[:500]}{page_str}",
                        vehicle_model=r.get("model_id", "") or "",
                        vehicle_version="all_versions",
                        topic="",
                        approval_status="approved",
                        retrieval_score=r.get("score", 0.0),
                        page=page,
                    ).__dict__)

    return chunks


def build_displayed_citations(citations: list[dict], retrieved_chunks: list[dict] | None = None) -> list[dict]:
    """Convert citations → P0 displayed_citations schema."""
    chunk_ids_by_url: dict[str, list[str]] = {}
    pages_by_url: dict[str, set[str]] = {}
    if retrieved_chunks:
        for rc in retrieved_chunks:
            url = rc.get("source_url", "")
            cid = rc.get("chunk_id", "")
            page = rc.get("page", "")
            if url and cid:
                chunk_ids_by_url.setdefault(url, [])
                if cid not in chunk_ids_by_url[url]:
                    chunk_ids_by_url[url].append(cid)
            if url and page:
                pages_by_url.setdefault(url, set()).add(str(page))

    seen = set()
    result = []
    for c in citations:
        url = c.get("source_url", "")
        if not url or url in seen:
            continue
        seen.add(url)
        model = c.get("model_code", "")
        label = c.get("source_type", "")
        text = f"{model} — {label}" if model and label else (label or url)
        pages = sorted(pages_by_url.get(url, set()), key=lambda x: int(x) if x.isdigit() else 0)
        if pages:
            page_str = ", ".join(pages)
            text += f" (trang {page_str})"
        cids = chunk_ids_by_url.get(url, [])
        if not cids and c.get("chunk_id"):
            cids = [c["chunk_id"]]
        result.append(DisplayedCitation(
            display_text=text,
            source_id=label,
            chunk_ids=cids,
            source_url=url,
            section="",
        ).__dict__)
    return result


def make_decision_log(
    query: str,
    classify_result,
    tool_results: list[dict],
    response: str,
    citations: list[dict],
    *,
    conversation_id: str = "",
    turn_index: int = 0,
    previous_request_id: str = "",
    latency_ms: float = 0.0,
    latency_retrieval_ms: float = 0.0,
    latency_generation_ms: float = 0.0,
    prompt_hash: str = "",
    error_stage: str = "",
    error_type: str = "",
    error_message: str = "",
    topic: str = "",
) -> DecisionLog:
    model = classify_result.entities.get("model_code", "unknown")
    version = classify_result.entities.get("version", "all_versions")
    detected_topic = topic or getattr(classify_result, "specificity", "unknown")

    assessment, _ = assess_evidence(tool_results, query) if tool_results else ("not_run", [])

    reason_code = resolve_reason_code(classify_result.reason)
    retrieval_status = "success" if tool_results else ("not_run" if classify_result.decision in ("clarify", "out_of_scope") else "no_result")

    retrieved_chunks = build_retrieved_chunks(tool_results, query)

    return DecisionLog(
        request_id=f"req_{uuid.uuid4().hex[:12]}",
        timestamp=datetime.now(timezone.utc).isoformat(),
        build_version=_get_build_version(),
        prompt_version=prompt_hash or _get_prompt_hash(""),
        data_snapshot_id=_get_data_snapshot_id(),
        conversation_id=conversation_id or uuid.uuid4().hex[:12],
        turn_index=turn_index,
        previous_request_id=previous_request_id,
        user_query=query,
        detected_vehicle_model=model,
        detected_vehicle_version=version,
        detected_topic=detected_topic,
        decision=classify_result.decision,
        reason_code=reason_code,
        retrieval_status=retrieval_status,
        retrieved_chunks=retrieved_chunks,
        evidence_assessment=assessment,
        displayed_answer=response[:2000],
        displayed_citations=build_displayed_citations(citations, retrieved_chunks),
        error_stage=error_stage,
        error_type=error_type,
        error_message=error_message,
        latency_total_ms=round(latency_ms, 1),
        latency_retrieval_ms=round(latency_retrieval_ms, 1),
        latency_generation_ms=round(latency_generation_ms, 1),
    )
