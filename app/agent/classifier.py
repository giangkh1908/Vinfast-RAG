import re
from dataclasses import dataclass, field

from app.config import settings


def _build_model_aliases() -> dict[str, str]:
    aliases = {}
    for model in settings.scope_models:
        clean = model.strip()
        compact = clean.replace(" ", "")
        lower = clean.lower()
        compact_lower = compact.lower()
        for variant in {clean, compact, lower, compact_lower,
                        clean.replace(" ", "-"), compact_lower + "-"}:
            aliases[variant] = clean
    return aliases


def _build_model_regex() -> re.Pattern:
    parts = []
    for model in settings.scope_models:
        escaped = re.escape(model.strip())
        parts.append(escaped)
        compact = model.strip().replace(" ", r"\s*")
        if compact != escaped:
            parts.append(compact)
    if not parts:
        # Fallback: match any VF + number pattern
        return re.compile(r"(VF\s*\d+)", re.IGNORECASE)
    return re.compile("(" + "|".join(parts) + ")", re.IGNORECASE)


VERSION_ALIASES = {
    "eco": "Eco", "bản eco": "Eco", "ban eco": "Eco",
    "plus": "Plus", "bản plus": "Plus", "ban plus": "Plus",
}

ALL_MODEL_RE = re.compile(
    r"(VF\s*\d+|VF\s*e34|VF\s*MPV\s*7|Herio\s*Green|Minio\s*Green|Limo\s*Green|EC\s*VAN|Nerio\s*Green)",
    re.IGNORECASE,
)

# ── OOS Patterns (BDS-11..17) ──────────────────────────────────────────────

_COMPARISON_RE = re.compile(
    r"(so\s*sánh|khác\s*nhau\s*thế\s*nào|xe\s*nào\s*hơn|đối\s*chiếu|"
    r"vs\.?|versus|tốt\s*hơn|nhanh\s*hơn|xịn\s*hơn|"
    r"VF\s*\d+.*(?:hay|hoặc|vs).*VF\s*\d+)",
    re.IGNORECASE,
)

_RECOMMENDATION_RE = re.compile(
    r"(nên\s*mua|xe\s*nào\s*tốt|gợi\s*y|recommend|phù\s*hợp\s*với|"
    r"tư\s*vấn\s*mua|lựa\s*chọn|ngân\s*sách|nhu\s*cầu|"
    r"tôi\s*nên|có\s*nên|đáng\s*mua|ưu\s*điểm\s*nhược)",
    re.IGNORECASE,
)

_PRICING_RE = re.compile(
    r"(giá\s*(bán|niêm\s*yết|ưu\s*đãi|khuyến\s*mãi)|bao\s*nhiêu\s*tiền|"
    r"chi\s*phí|trả\s*góp|lăn\s*bánh|đặt\s*cọc|"
    r"khuyến\s*mãi|ưu\s*đãi|voucher|chính\s*sách\s*giá|"
    r"giá\s*(VF|xe)|VNĐ|triệu\s*đồng)",
    re.IGNORECASE,
)

_WARRANTY_RE = re.compile(
    r"(bảo\s*hành|bảo\s*dưỡng|manual|hướng\s*dẫn\s*sử\s*dụng|"
    r"thay\s*dầu|kiểm\s*tra|định\s*kỳ|lịch\s*bảo\s*dưỡng|"
    r"phụ\s*tùng|sửa\s*chữa\s*định|service)",
    re.IGNORECASE,
)

_DIAGNOSTICS_RE = re.compile(
    r"(cảnh\s*báo\s*lỗi|xe\s*hỏng|sự\s*cố\s*kỹ\s*thuật|"
    r"xử\s*lý\s*sự\s*cố|chẩn\s*đoán|sửa\s*chữa|"
    r"lỗi|mã\s*lỗi|check\s*engine|khởi\s*động\s*lại|"
    r"pin\s*chai|pin\s*chết|sạc\s*không\s*vào|"
    r"phanh\s*không\s*ăn|vô\s*lăng\s*run)",
    re.IGNORECASE,
)

_HOTLINE_RE = re.compile(
    r"(hotline|showroom|lái\s*thử|test\s*drive|đăng\s*ký\s*lái|"
    r"gặp\s*(sales|nhân\s*viên)|liên\s*hệ|số\s*điện\s*thoại|"
    r"đại\s*lý|cửa\s*hàng|chi\s*nhánh)",
    re.IGNORECASE,
)

_EXTERNAL_SOURCE_RE = re.compile(
    r"(internet|diễn\s*đàn|review|forum|facebook|youtube|"
    r"google|tìm\s*kiếm|nguồn\s*khác|website\s*khác|"
    r"so\s*sánh\s*với\s*xe\s*khác\s*hãng)",
    re.IGNORECASE,
)

_PERSONAL_DATA_RE = re.compile(
    r"(VIN\b|số\s*VIN|mã\s*VIN|"
    r"lịch\s*sử\s*(dịch\s*vụ|bảo\s*dưỡng)\s*theo|"
    r"tài\s*khoản|đăng\s*nhập|"
    r"dữ\s*liệu\s*cá\s*nhân|thông\s*tin\s*cá\s*nhân|"
    r"kiểm\s*tra\s*lịch\s*sử|tra\s*cứu\s*VIN)",
    re.IGNORECASE,
)


@dataclass
class ClassifyResult:
    decision: str = "answer"
    reason: str = ""
    entities: dict = field(default_factory=dict)
    specificity: str = "unclear"


def _normalize_version(raw: str) -> str | None:
    clean = raw.strip().lower()
    return VERSION_ALIASES.get(clean)


class QueryClassifier:
    def __init__(self):
        self._scope_aliases = _build_model_aliases()
        self._scope_regex = _build_model_regex()
        self._model_list_str = " hoặc ".join(settings.scope_models)

    def _detect_model(self, query: str) -> tuple[str | None, str | None]:
        m = self._scope_regex.search(query)
        if m:
            raw = m.group(1).strip()
            clean = re.sub(r"\s+", " ", raw).lower()
            normalized = self._scope_aliases.get(clean)
            if normalized:
                return normalized, raw
            return None, raw
        if not settings.scope_enabled:
            m2 = ALL_MODEL_RE.search(query)
            if m2:
                return m2.group(1).strip(), m2.group(1).strip()
        return None, None

    def _detect_oos(self, query: str, entities: dict) -> ClassifyResult | None:
        """Check all OOS patterns (BDS-11..17). Returns ClassifyResult if OOS, None otherwise."""
        has_model = "model_code" in entities

        # BDS-17: External source request (check first — highest priority)
        if _EXTERNAL_SOURCE_RE.search(query):
            return ClassifyResult(
                decision="out_of_scope",
                reason="external_source: external data sources not allowed",
                entities=entities, specificity="unclear",
            )

        # BDS-15: Safety diagnostics
        if _DIAGNOSTICS_RE.search(query):
            return ClassifyResult(
                decision="out_of_scope",
                reason="diagnostics: safety diagnosis not supported",
                entities=entities, specificity="unclear",
            )

        # Personal data / transaction (VIN, account, service history lookup)
        if _PERSONAL_DATA_RE.search(query):
            return ClassifyResult(
                decision="out_of_scope",
                reason="personal_data: personal data or transaction not supported",
                entities=entities, specificity="unclear",
            )

        # BDS-16: Hotline/showroom/test drive
        if _HOTLINE_RE.search(query):
            return ClassifyResult(
                decision="out_of_scope",
                reason="hotline_showroom: contact workflow not supported",
                entities=entities, specificity="unclear",
            )

        # BDS-14: Warranty/maintenance/manual
        if _WARRANTY_RE.search(query):
            return ClassifyResult(
                decision="out_of_scope",
                reason="warranty_maintenance: after-sales not supported",
                entities=entities, specificity="unclear",
            )

        # BDS-13: Pricing/promotions
        if _PRICING_RE.search(query):
            return ClassifyResult(
                decision="out_of_scope",
                reason="pricing: pricing not supported in this slice",
                entities=entities, specificity="unclear",
            )

        # BDS-12: Recommendation
        if _RECOMMENDATION_RE.search(query):
            return ClassifyResult(
                decision="out_of_scope",
                reason="recommendation: purchase advice not supported",
                entities=entities, specificity="unclear",
            )

        # BDS-11: Comparison — ALL comparisons are OOS (same-model too)
        if _COMPARISON_RE.search(query):
            return ClassifyResult(
                decision="out_of_scope",
                reason="comparison: comparison not supported in this slice",
                entities=entities, specificity="unclear",
            )

        # BDS-10: Multi-model, unclear intent
        if settings.scope_enabled and not has_model:
            all_models = ALL_MODEL_RE.findall(query)
            unique = {re.sub(r"\s+", " ", m.strip()).lower() for m in all_models}
            if len(unique) > 1:
                comparison_hint = _COMPARISON_RE.search(query)
                if not comparison_hint:
                    return ClassifyResult(
                        decision="clarify",
                        reason="BDS-10: multiple models, unclear intent",
                        entities=entities, specificity="unclear",
                    )

        return None

    def classify(self, query: str, history: list[dict] = None) -> ClassifyResult:
        entities = {}

        normalized, raw = self._detect_model(query)
        if normalized:
            entities["model_code"] = normalized
        elif raw:
            entities["model_code_raw"] = raw

        version_match = re.search(
            r"(Eco|Plus|Ti[êe]u chu[ẩẩ]n|N[ââ]ng cao|Cao c[ấấ]p)",
            query, re.IGNORECASE,
        )
        if version_match:
            nv = _normalize_version(version_match.group(1))
            if nv:
                entities["version"] = nv

        # Model scope OOS (BDS-02A)
        if settings.scope_enabled:
            if "model_code_raw" in entities and "model_code" not in entities:
                return ClassifyResult(
                    decision="out_of_scope",
                    reason=f"BDS-02A: model '{entities['model_code_raw']}' not in scope ({self._model_list_str})",
                    entities=entities, specificity="unclear",
                )
            all_models = ALL_MODEL_RE.findall(query)
            for m in all_models:
                clean = re.sub(r"\s+", " ", m.strip()).lower()
                if clean not in self._scope_aliases:
                    return ClassifyResult(
                        decision="out_of_scope",
                        reason=f"BDS-02A: model '{m}' not in scope ({self._model_list_str})",
                        entities=entities, specificity="unclear",
                    )

        # OOS patterns (BDS-10..17) — after model detection
        oos_result = self._detect_oos(query, entities)
        if oos_result:
            return oos_result

        has_model = "model_code" in entities
        specificity = "clear" if has_model else "unclear"

        return ClassifyResult(
            decision="answer",
            reason="context sufficient, proceed to retrieval",
            entities=entities,
            specificity=specificity,
        )


_classifier = None


def get_classifier() -> QueryClassifier:
    global _classifier
    if _classifier is None:
        _classifier = QueryClassifier()
    return _classifier
