import re
from dataclasses import dataclass, field


# Matches any VinFast model pattern
MODEL_RE = re.compile(
    r"(VF\s*\d+|VF\s*e34|VF\s*MPV\s*7|Herio\s*Green|Minio\s*Green|Limo\s*Green|EC\s*VAN|Nerio\s*Green)",
    re.IGNORECASE,
)

VERSION_ALIASES = {
    "eco": "Eco", "bản eco": "Eco", "ban eco": "Eco",
    "plus": "Plus", "bản plus": "Plus", "ban plus": "Plus",
    "tiêu chuẩn": "Tiêu chuẩn", "tieuchuan": "Tiêu chuẩn",
    "nâng cao": "Nâng cao", "nangcao": "Nâng cao",
    "cao cấp": "Cao cấp", "caocap": "Cao cấp",
}


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
    """Detect model + version from query. No OOS gating — all models supported."""

    def _detect_model(self, query: str) -> tuple[str | None, str | None]:
        m = MODEL_RE.search(query)
        if m:
            raw = m.group(1).strip()
            # Normalize: "VF6" → "VF 6", "VF 8" stays "VF 8"
            clean = re.sub(r"(VF)\s*(\d+)", r"\1 \2", raw, flags=re.IGNORECASE).strip()
            return clean, raw
        return None, None

    def classify(self, query: str, history: list[dict] = None) -> ClassifyResult:
        entities = {}

        normalized, raw = self._detect_model(query)
        if normalized:
            entities["model_code"] = normalized

        version_match = re.search(
            r"(Eco|Plus|Ti[êe]u\s*chu[ẩẩ]n|N[ââ]ng\s*cao|Cao\s*c[ấấ]p)",
            query, re.IGNORECASE,
        )
        if version_match:
            nv = _normalize_version(version_match.group(1))
            if nv:
                entities["version"] = nv

        has_model = "model_code" in entities
        specificity = "clear" if has_model else "unclear"

        return ClassifyResult(
            decision="answer",
            reason="proceed to retrieval",
            entities=entities,
            specificity=specificity,
        )


_classifier = None


def get_classifier() -> QueryClassifier:
    global _classifier
    if _classifier is None:
        _classifier = QueryClassifier()
    return _classifier
