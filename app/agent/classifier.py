import re
from dataclasses import dataclass, field

from app.config import settings

# BDS topics in scope
TOPIC_PATTERNS = {
    "phiên_bản": r"(phi[eê]n\s+b[aả]n|b[aả]n\s+n[aà]o|c[oó]\s+m[aấ]y\s+b[aả]n|version|edition)",
    "thông_số_kỹ_thuật": r"(th[oô]ng\s+s[oố]|k[yỹ]\s+thu[aậ]t|specs?|c[oô]ng\s+su[aấ]t|Nm|m[oô]\s+men|t[oố]c\s+[đd][ộo]\s+t[oố]i\s+[đd]a|t[aă]ng\s+t[oố]c|0[-–]?100|tr[oọ]ng\s+l[uư][ợo]ng|t[aả]i\s+tr[oọ]ng|bán kính quay vòng)",
    "tính_năng_nổi_bật": r"(t[ií]nh\s+n[aă]ng|c[oô]ng\s+ngh[eệ]|n[oổ]i\s+b[aậ]t|[đd][aặ]c\s+[đd]i[eể]m|ADAS|cruise\s*control|phanh\s+kh[aẩ]n\s+c[aấ]p|camera|c[aả]m\s+bi[eế]n|l[aá]i\s+.*cao\s+t[oố]c|[uù]n\s+t[aắ]c|t[uự]\s+l[aá]i|ch[eế]\s+[đd][ộộ]\s+t[uự]\s+l[aá]i)",
    "kích_thước": r"(k[ií]ch\s+th[uư][ớơo]c|chi[eề]u\s+d[aà]i|chi[eề]u\s+r[oộ]ng|chi[eề]u\s+cao|kho[aả]ng\s+s[aá]ng|c[aơ]\s+s[oở]|bán kính quay vòng)",
    "pin_và_sạc": r"(\bpin\b|dung\s+l[uư][ợo]ng\s+pin|kWh|s[aạ]c\s+nhanh|s[aạ]c\s+ch[aậ]m|tr[aạm]m?\s+s[aạ]c|lo[aạ]i\s+pin|th[oờ]i\s+gian\s+s[aạ]c|d[aạ]c\s+pin|n[aạp]\s+pin|s[aạ]c\s+t[uừ])",
    "phạm_vi_di_chuyển": r"(ph[aạm]m\s+vi|qu[aã]ng\s+[đd][ưu][ờơ]ng|[đd]i\s+[đd][ưu][ợơ]c\s+bao\s+xa|t[aầ]m\s+[đd]i|[đd][ộộ]\s+di\s+chuy[eển]n|\brange\b|NEDC|WLTP)",
    "an_toàn": r"(an\s+to[aà]n|t[uú]i\s+kh[ií]|phanh|c[aả]m\s+bi[eế]n|c[aản]nh?\s+b[aá]o|camera\s*360|camera\s+l[uù]i)",
    "nội_thất": r"(n[ộộo]i?\s*th[ấấa]t|gh[eế]|m[aà]n\s+h[ìi]nh|b[aả]ng\s+[đd]i[eề]u\s+khi[eể]n|[đd]i[eề]u\s+ho[aà]|khoang\s+h[aà]nh\s+kh[aá]ch|c[oổ]ng\s+s[aạ]c\s+kh[oô]ng\s+d[aây]|HUD|massage)",
    "ngoại_thất": r"(ngo[aạ]i?\s*th[ấấa]t|\bm[aà]u\b|m[aà]u\s+s[aắ]c?|[đd][èe]n|m[aâ]m|thi[eế]k[eế]|d[aá]ng|body|[đd][ầâu]\s+xe|[đd]u[oô]i\s+xe|g[uư][ơơn]ng|la-z[aă]ng|inch)",
}

# Out-of-scope patterns — only enforced when scope_enabled
OOS_PATTERNS = {
    "comparison": r"(so\s+s[aá]nh|compare|\bvs\b|kh[aá]c\s+g[ìi]|hon\s+nhau|h[aơn]+\s+nhau)",
    "recommendation": r"(n[êê]n\s+mua|mu[aố]n\s+mua|ph[ùù]?\s*h[ợợ]p\s+v[ớới]|g[ợợi]\s+[ýy]|t[ưu]\s+v[ấấn]|ng[âân]\s+s[aá]ch.*mua)",
    "pricing": r"(gi[aá]\s|bao\s+nhi[êe]u\s+ti[ềề]n|ni[êe]m\s+y[ếe]t|[uư]u\s+[đd][ãa]i|khuy[ếe]n\s+m[aã]i|gi[aả]m\s+gi[aá]|voucher|[đd][ặặ]t\s+c[ọọc]|l[aă]n\s+b[aá]nh|tr[aả]\s+g[oó]p|vay|l[aã]i\s+su[aấ]t|khuy[aã]n\s+m[aại])",
    "warranty_maintenance": r"(b[aảo]+\s+d[uư][oõ]ng|b[aảo]+\s+h[aà]nh|thay\s+d[aầu]+|l[oọc]\s+gi[oó]|b[aảo]+\s+tr[iì]|h[uớo]ng\s+d[aẫn]+|manual|l[aị]ch\s+s[uử]\s+b[aảo]+\s+d[uư][oõ]ng|VIN)",
    "diagnostics": r"(\bl[oỗ]i\b|\bc[aản]nh?\s+b[aá]o\b|\bs[uự]\s+c[oố]|\bh[oỏ]ng\b|\bs[uửa]\s+ch[uữ]a|\bx[uử]\s+l[yý]|\bch[aẩn]\s+[đd][oá]n|\bb[aáo]\s+l[oỗ]i\b)",
    "hotline_showroom": r"(hotline|showroom|tr[aạm]\s+s[aạc]|[đd][aạ]i\s+l[yý]|l[aá]i\s+th[uử]|test\s*drive|[đd][aặ]t\s+l[iị]ch|li[êên]\s+h[ệệ]|[đd][aă]ng\s+k[yý])",
    "external_source": r"(internet|di[aễn]\s+[đd][aà]n|review|[đd][aá]nh\s+gi[aá]|google|facebook|youtube)",
    "personal_data": r"(VIN|l[aị]ch\s+s[uử]\s+d[aị]ch\s+v[uụ]|t[aà]i\s+kh[oỏ]n|d[aữữ]\s+li[eệ]u\s+c[aá]\s+nh[ââ]n)",
}


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
    intents: list[str] = field(default_factory=list)
    topic: str | None = None
    decision: str = "answer"
    reason: str = ""
    entities: dict = field(default_factory=dict)
    missing_fields: list[str] = field(default_factory=list)
    source: str = "regex"


def _normalize_version(raw: str) -> str | None:
    clean = raw.strip().lower()
    return VERSION_ALIASES.get(clean)


def _detect_topic(query: str) -> tuple[str | None, list[str]]:
    matched = [
        topic for topic, pattern in TOPIC_PATTERNS.items()
        if re.search(pattern, query, re.IGNORECASE)
    ]
    topic = matched[0] if len(matched) == 1 else None
    return topic, matched


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

        # 1. Detect model
        normalized, raw = self._detect_model(query)
        if normalized:
            entities["model_code"] = normalized
        elif raw:
            entities["model_code_raw"] = raw

        # 2. Detect version
        version_match = re.search(
            r"(Eco|Plus|Ti[êe]u chu[ẩẩ]n|N[ââ]ng cao|Cao c[ấấ]p)",
            query, re.IGNORECASE,
        )
        if version_match:
            nv = _normalize_version(version_match.group(1))
            if nv:
                entities["version"] = nv

        # 3. Detect topic
        topic, matched_topics = _detect_topic(query)

        # 4. OOS check — only when scope_enabled
        if settings.scope_enabled:
            if re.search(OOS_PATTERNS["personal_data"], query, re.IGNORECASE):
                return ClassifyResult(
                    intents=["personal_data"], topic=None,
                    decision="out_of_scope", reason="BDS: personal data/transaction",
                    entities=entities, source="regex",
                )
            for oos_type, pattern in OOS_PATTERNS.items():
                if oos_type == "personal_data":
                    continue
                if re.search(pattern, query, re.IGNORECASE):
                    return ClassifyResult(
                        intents=[oos_type], topic=None,
                        decision="out_of_scope", reason=f"BDS: out-of-scope '{oos_type}'",
                        entities=entities, source="regex",
                    )
            if "model_code_raw" in entities and "model_code" not in entities:
                return ClassifyResult(
                    intents=["model_oos"], topic=None,
                    decision="out_of_scope",
                    reason=f"BDS-02A: model '{entities['model_code_raw']}' not in scope ({self._model_list_str})",
                    entities=entities, source="regex",
                )
            all_models = ALL_MODEL_RE.findall(query)
            for m in all_models:
                clean = re.sub(r"\s+", " ", m.strip()).lower()
                if clean not in self._scope_aliases:
                    return ClassifyResult(
                        intents=["model_oos"], topic=None,
                        decision="out_of_scope",
                        reason=f"BDS-02A: model '{m}' not in scope ({self._model_list_str})",
                        entities=entities, source="regex",
                    )

        # 5. All clear → answer (LLM will call ask_clarification if needed)
        return ClassifyResult(
            intents=matched_topics or ["general"],
            topic=topic,
            decision="answer",
            reason="context sufficient, proceed to retrieval",
            entities=entities,
            source="regex",
        )


_classifier = None


def get_classifier() -> QueryClassifier:
    global _classifier
    if _classifier is None:
        _classifier = QueryClassifier()
    return _classifier
