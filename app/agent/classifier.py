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
        return re.compile(r"(?!)", re.IGNORECASE)
    return re.compile("(" + "|".join(parts) + ")", re.IGNORECASE)


VERSION_ALIASES = {
    "eco": "Eco", "bản eco": "Eco", "ban eco": "Eco",
    "plus": "Plus", "bản plus": "Plus", "ban plus": "Plus",
}

ALL_MODEL_RE = re.compile(
    r"(VF\s*\d+|VF\s*e34|VF\s*MPV\s*7|Herio\s*Green|Minio\s*Green|Limo\s*Green|EC\s*VAN|Nerio\s*Green)",
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

        if settings.scope_enabled:
            if "model_code_raw" in entities and "model_code" not in entities:
                return ClassifyResult(
                    decision="out_of_scope",
                    reason=f"BDS-02A: model '{entities['model_code_raw']}' not in scope ({self._model_list_str})",
                    entities=entities,
                    specificity="unclear",
                )
            all_models = ALL_MODEL_RE.findall(query)
            for m in all_models:
                clean = re.sub(r"\s+", " ", m.strip()).lower()
                if clean not in self._scope_aliases:
                    return ClassifyResult(
                        decision="out_of_scope",
                        reason=f"BDS-02A: model '{m}' not in scope ({self._model_list_str})",
                        entities=entities,
                        specificity="unclear",
                    )

        has_model = "model_code" in entities
        has_version = "version" in entities
        specificity = "clear" if has_model else "unclear"

        # OOS: cross-model comparison (different models mentioned)
        if settings.scope_enabled:
            all_models_in_query = ALL_MODEL_RE.findall(query)
            unique_models = {re.sub(r"\s+", " ", m.strip()).lower() for m in all_models_in_query}
            if len(unique_models) > 1:
                comparison_kw = re.compile(
                    r"(so\s*sánh|hay|hay\s*là|vs|versus|khác\s*nhau|đối\s*chiếu)",
                    re.IGNORECASE,
                )
                if comparison_kw.search(query):
                    return ClassifyResult(
                        decision="out_of_scope",
                        reason="comparison: cross-model comparison not supported",
                        entities=entities,
                        specificity="unclear",
                    )

        # OOS: recommendation
        recommend_kw = re.compile(
            r"(nên\s*mua|xe\s*nào\s*tốt|gợi\s*y|recommend|phù\s*hợp\s*với|tư\s*vấn\s*mua|lựa\s*chọn)",
            re.IGNORECASE,
        )
        if recommend_kw.search(query):
            return ClassifyResult(
                decision="out_of_scope",
                reason="recommendation: purchase advice not supported",
                entities=entities,
                specificity="unclear",
            )

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
