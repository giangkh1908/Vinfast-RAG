import re
from dataclasses import dataclass, field

# Matches any VinFast model pattern (including multi-word like "VF 8 All New")
# Lưu ý: cho phép "VF 8 New" / "VF 8 The New" / "vf8 the all new" — người dùng
# thường gọi thế hệ mới là "VF 8 New" thay vì "VF 8 All New" (tên DB).
MODEL_RE = re.compile(
    r"(VF\s*\d+(?:\s*(?:(?:The\s+)?(?:All\s+)?New|Th[ếế]\s*h[ệệ]\s*m[ớớ]i|The\s*he\s*moi))?|"
    r"VF\s*MPV\s*\d+|VF\s*e34|"
    r"Herio\s*Green|Minio\s*Green|Limo\s*Green|EC\s*VAN|Nerio\s*Green)",
    re.IGNORECASE,
)


def normalize_model(raw: str) -> str:
    """Chuẩn hóa tên model về dạng DB (case-insensitive).

    - 'vf8' → 'VF 8'; 'vf 8 all new' → 'VF 8 All New'
    - 'VF 8 New' / 'VF 8 The New' / 'vf 8 new' → 'VF 8 All New' (model DB là
      'VF 8 All New', nhưng người dùng hay gọi thế hệ mới là 'VF 8 New').
    - 'vf 8 thế hệ mới' / 'vf 8 the he moi' → 'VF 8 All New'.
    """
    clean = re.sub(r"(VF)\s*(\d+)", r"\1 \2", raw, flags=re.IGNORECASE).strip()
    clean = re.sub(r"(VF)\s*MPV\s*(\d+)", r"\1 MPV \2", clean, flags=re.IGNORECASE).strip()
    clean = re.sub(r"(VF)\s*(e34)", r"\1 \2", clean, flags=re.IGNORECASE).strip()
    # Model họ VF8 có hậu tố New / thế hệ mới → luôn là 'VF 8 All New'
    if re.match(r"^VF\s*\d+", clean, re.I) and re.search(r"(new|m[ớớ]i|moi)", clean, re.I):
        return "VF 8 All New"
    parts = clean.split()
    norm = []
    for p in parts:
        up = p.upper()
        # "mpv" → "MPV" (DB dùng VF MPV 7); VF/số giữ nguyên; còn lại viết hoa chữ đầu
        if up.startswith("VF") or p.isdigit() or up == "MPV":
            norm.append("MPV" if up == "MPV" else (p.upper() if up.startswith("VF") else p))
        else:
            norm.append(p.capitalize())
    return " ".join(norm)


VERSION_ALIASES = {
    "eco": "Eco",
    "bản eco": "Eco",
    "ban eco": "Eco",
    "plus": "Plus",
    "bản plus": "Plus",
    "ban plus": "Plus",
    "tiêu chuẩn": "TieuChuan",
    "tieuchuan": "TieuChuan",
    "tiêu_chuẩn": "TieuChuan",
    "nâng cao": "NangCao",
    "nangcao": "NangCao",
    "cao cấp": "CaoCap",
    "caocap": "CaoCap",
    "pluscaptain": "PlusCaptain",
    "plus captain": "PlusCaptain",
    "the all new": "The All New",
    "all new": "The All New",
    "thenew": "The All New",
    "the new": "The All New",
    "new": "The All New",
    "thế hệ mới": "The All New",
    "the he moi": "The All New",
    "plus awd": "Plus AWD",
    "plusawd": "Plus AWD",
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
            # Normalize: "VF8 All New" → "VF 8 All New", "vf 8 New" → "VF 8 All New"
            clean = normalize_model(raw)
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
            r"Th[ếế]\s*h[ệệ]\s*m[ớớ]i|The\s*he\s*moi|"
            r"The\s*All\s*New|All\s*New|The\s*New|\bNew\b)",
            query,
            re.IGNORECASE,
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
