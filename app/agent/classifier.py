import re
from dataclasses import dataclass, field


# Matches any VinFast model pattern (including multi-word like "VF 8 All New")
MODEL_RE = re.compile(
    r"(VF\s*\d+(?:\s*All\s*New)?|VF\s*MPV\s*\d+|VF\s*e34|"
    r"Herio\s*Green|Minio\s*Green|Limo\s*Green|EC\s*VAN|Nerio\s*Green)",
    re.IGNORECASE,
)

VERSION_ALIASES = {
    "eco": "Eco", "bản eco": "Eco", "ban eco": "Eco",
    "plus": "Plus", "bản plus": "Plus", "ban plus": "Plus",
    "tiêu chuẩn": "TieuChuan", "tieuchuan": "TieuChuan", "tiêu_chuẩn": "TieuChuan",
    "nâng cao": "NangCao", "nangcao": "NangCao",
    "cao cấp": "CaoCap", "caocap": "CaoCap",
    "pluscaptain": "PlusCaptain", "plus captain": "PlusCaptain",
    "the all new": "The All New", "all new": "The All New", "thenew": "The All New",
    "plus awd": "Plus AWD", "plusawd": "Plus AWD",
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
            # Normalize: "VF8 All New" → "VF 8 All New", "vf 8" → "VF 8"
            clean = re.sub(r"(VF)\s*(\d+)", r"\1 \2", raw, flags=re.IGNORECASE).strip()
            # Title-case to match DB format: "vf 8 all new" → "VF 8 All New"
            parts = clean.split()
            clean = " ".join(p.upper() if p.upper().startswith("VF") or p.isdigit() else p.capitalize() for p in parts)
            return clean, raw
        return None, None

    def classify(self, query: str, history: list[dict] = None) -> ClassifyResult:
        entities = {}

        normalized, raw = self._detect_model(query)
        if normalized:
            entities["model_code"] = normalized

        # Version detection: match known versions + multi-word patterns
        version_match = re.search(
            r"(Eco|Plus|PlusCaptain|Plus\s*AWD|"
            r"Ti[êe]u\s*[Cc]hu[ẩẩ]?n|TieuChuan|"
            r"N[ââ]ng\s*[Cc]ao|NangCao|"
            r"Cao\s*[Cc][ấấ]?p|CaoCap|"
            r"The\s*All\s*New|All\s*New)",
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
