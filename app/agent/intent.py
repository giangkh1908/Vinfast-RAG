"""Hybrid intent classification + deterministic tool planning.

Triết lý: LLM KHÔNG bao giờ chọn tool / đoán tham số tool (category, version...).
- Lớp 1 (rule): regex/keyword → intent + spec_category — nhanh, free, deterministic.
- Lớp 2 (LLM fallback): intent vẫn "general" mà query rõ ràng là câu hỏi thật →
  1 LLM call strict-JSON (enum intent + entities), kết quả được VALIDATE trước khi dùng.
- build_tool_plan: intent + entities → danh sách (tool_name, args) CHÍNH XÁC.
"""

import logging
import re

from app.agent.classifier import MODEL_RE, normalize_model

logger = logging.getLogger("bds.intent")

# ── Các intent (enum) ──────────────────────────────────────────────────────
INTENTS = (
    "greeting",  # chào hỏi (xin chào, hello, hi...)
    "thanks",  # cảm ơn, tạm biệt
    "identity",  # bạn là ai, giới thiệu bot
    "price",  # giá / giá niêm yết
    "spec_query",  # hỏi thông số kỹ thuật (có topic)
    "feature_presence",  # "X có Y không?"
    "cross_model_feature",  # "xe nào có Y?"
    "compare",  # so sánh / hơn kém / vs
    "versions_list",  # có mấy phiên bản
    "models_list",  # danh sách xe
    "colors",  # màu sắc
    "utility",  # link / đặt lịch / showroom / trả góp...
    "policy",  # bảo hành / bảo dưỡng / chính sách (nội dung)
    "general",  # chưa xác định
    "out_of_scope",  # không liên quan
)

# Intent liên quan thông số → cần spec_category
_SPEC_INTENTS = {"spec_query", "feature_presence", "cross_model_feature", "compare"}

# Các model chính cho scan cross-model
MAIN_MODELS = ["VF 2", "VF 3", "VF 5", "VF 6", "VF 7", "VF 8", "VF 8 All New", "VF 9", "VF MPV 7"]

# ── BẢNG keyword → spec_category (deterministic — LLM không đụng vào) ───────
# Thứ tự quan trọng: pattern cụ thể trước. None = không lọc (trải nhiều category:
# tiện nghi, giải trí, kết nối... theo prompt rule 5).
_SPEC_CATEGORY_PATTERNS: list[tuple[str | None, tuple[str, ...]]] = [
    (
        "battery",
        (
            r"thời\s*gian\s*sạc",
            r"sạc\s*nhanh",
            r"sạc\s*chậm",
            r"sạc\s*đầy",
            r"nạp\s*pin",
            r"dung\s*lượng\s*pin",
            r"dung\s*lượng",
            r"quãng\s*đường",
            r"đi\s*được",
            r"phạm\s*vi",
            r"tầm\s*di\s*chuyển",
            r"tầm\s*hoạt\s*động",
            r"\brange\b",
            r"pin",
            r"\bkwh\b",
            r"\bsạc\b",
            r"10\s*[-–]\s*70",
            r"10\s*%\s*[-–]\s*70",
        ),
    ),
    (
        "powertrain",
        (
            r"công\s*suất",
            r"mã\s*lực",
            r"mô[\s-]*men",
            r"\btorque\b",
            r"tăng\s*tốc",
            r"0\s*[-–]\s*100",
            r"tốc\s*độ\s*tối\s*đa",
            r"vận\s*tốc",
            r"dẫn\s*động",
            r"\bawd\b",
            r"\bfwd\b",
            r"\brwd\b",
            r"động\s*cơ",
            r"\bmotor\b",
            r"\bhp\b",
            r"\bkw\b",
            r"mô-men xoắn",
            r"cầu\s*trước",
            r"cầu\s*sau",
            r"2\s*cầu",
        ),
    ),
    (
        "dimension",
        (
            r"kích\s*thước",
            r"chiều\s*dài",
            r"chiều\s*rộng",
            r"chiều\s*cao",
            r"khoảng\s*sáng\s*gầm",
            r"trục\s*cơ\s*sở",
            r"\bwheelbase\b",
            r"trọng\s*lượng",
            r"cân\s*nặng",
            r"dung\s*tích\s*cốp",
            r"thể\s*tích\s*cốp",
            r"khoang\s*hành\s*lý",
            r"kích\s*thước\s*lốp",
        ),
    ),
    (
        "safety",
        (
            r"túi\s*khí",
            r"\bairbag\b",
            r"phanh",
            r"\babs\b",
            r"\besc\b",
            r"an\s*toàn",
            r"cảnh\s*báo",
            r"camera\s*360",
            r"camera\s*lùi",
            r"kiểm\s*soát\s*lực\s*kéo",
            r"\btraction\b",
            r"phanh\s*khẩn\s*cấp",
            r"tự\s*động\s*phanh",
        ),
    ),
    (
        "interior",
        (
            r"cửa\s*sổ\s*trời",
            r"kính\s*trần",
            r"\bsunroof\b",
            r"\bpanoramic\b",
            r"nội\s*thất",
            r"ghế",
            r"số\s*chỗ",
            r"chỗ\s*ngồi",
            r"mấy\s*chỗ",
            r"bao\s*nhiêu\s*chỗ",
            r"5\s*chỗ",
            r"7\s*chỗ",
            r"màn\s*hình",
            r"\bloa\b",
            r"âm\s*thanh",
            r"điều\s*hòa",
            r"vô\s*lăng",
            r"\bhud\b",
            r"sạc\s*không\s*dây",
            r"cửa\s*gió",
            r"hàng\s*ghế",
            r"ghế\s*massage",
            r"thông\s*gió",
            r"sưởi",
            r"vật\s*liệu\s*ghế",
        ),
    ),
    (
        "exterior",
        (
            r"ngoại\s*thất",
            r"đèn",
            r"mâm",
            r"la[\s-]*zăng",
            r"gương",
            r"kiểu\s*dáng",
            r"màu\s*sơn",
            r"đèn\s*led",
            r"cốp",
            r"cửa\s*hít",
            r"cửa\s*hút",
            r"đèn\s*phía\s*trước",
        ),
    ),
    (
        "adas",
        (
            r"\badas\b",
            r"\bcruise\b",
            r"ga\s*tự\s*động",
            r"giữ\s*làn",
            r"\blane\b",
            r"va\s*chạm",
            r"\bcollision\b",
            r"\baeb\b",
            r"điểm\s*mù",
            r"blind\s*spot",
            r"đỗ\s*xe",
            r"\bparking\b",
            r"cao\s*tốc",
            r"tắc\s*đường",
            r"biển\s*báo",
            r"hỗ\s*trợ\s*lái",
            r"đèn\s*pha\s*tự\s*động",
        ),
    ),
    (
        "security",
        (
            r"chống\s*trộm",
            r"\bimmobilizer\b",
            r"khóa\s*điện\s*tử",
            r"định\s*vị\s*xe",
        ),
    ),
    (
        "chassis",
        (
            r"hệ\s*thống\s*treo",
            r"khung\s*gầm",
            r"chassis",
            r"đánh\s*lái",
            r"trợ\s*lực\s*lái",
        ),
    ),
    # Tiện nghi / giải trí / kết nối → trải nhiều category → KHÔNG lọc
    (
        None,
        (
            r"tiện\s*nghi",
            r"giải\s*trí",
            r"kết\s*nối",
            r"trợ\s*lý\s*ảo",
            r"\bapp\b",
            r"điều\s*khiển\s*từ\s*xa",
            r"gọi\s*thoại",
            r"cập\s*nhật\s*phần\s*mềm",
            r"có\s*những\s*tính\s*năng",
            r"tính\s*năng\s*nổi\s*bật",
            r"trang\s*bị",
        ),
    ),
]

# ── Intent rules (thứ tự ưu tiên quan trọng) ───────────────────────────────
_GREETING_ONLY_RE = re.compile(
    r"^(xin\s*chào(\s*(bạn|em|ad|admin|vivu|vinfast|mình|nhé|nha))?|chào\s*(bạn|em|ad|admin|vivu|vinfast|mình|nhé|nha)?|hello(\s*(vivu|vinfast|bạn|ad))?|hi(\s*(vivu|vinfast|bạn|ad))?\b|helo|alo|hế\s*lô|chào\s*buổi\s*(sáng|trưa|chiều|tối))\b[\s!.,?~😊👋❤️]*$",
    re.IGNORECASE,
)
_THANKS_ONLY_RE = re.compile(
    r"^(cảm\s*ơn(\s*(bạn|em|ad|admin|vivu|vinfast|mình))?(\s*(nhé|nha|ạ|nhiều|rất\s*nhiều))?|cam\s*on|cám\s*ơn|thank\s*you(\s*so\s*much)?|thanks(\s*a\s*lot)?|tks|tạm\s*biệt|bye\b|bai\s*bai)\b[\s!.,?~😊👋❤️]*$",
    re.IGNORECASE,
)
_IDENTITY_RE = re.compile(
    r"(bạn\s*là\s*ai|bạn\s*tên\s*gì|bạn\s*giúp\s*được\s*gì|chức\s*năng\s*(của\s*bạn|gì)|giới\s*thiệu\s*bản\s*thân|em\s*là\s*ai|vivu\s*là\s*ai|vivi\s*là\s*ai)",
    re.IGNORECASE,
)
_OUT_OF_SCOPE_RE = re.compile(
    r"(thời\s*tiết|chứng\s*khoán|bóng\s*đá|chính\s*trị|tập\s*làm\s*thơ|kể\s*chuyện\s*cười|"
    r"viết\s*code|viết\s*cho\s*tôi\s*.*code|code\s*python|thuật\s*toán|quicksort|dijkstra|"
    r"nấu\s*món|công\s*thức\s*nấu|phở\s*bò|tổng\s*thống|hack\s*|bẻ\s*khóa|mật\s*khẩu\s*wifi)",
    re.IGNORECASE,
)
_PRICE_RE = re.compile(
    r"(giá|giá\s*niêm\s*yết|giá\s*bán|bao\s*nhiêu\s*tiền|hết\s*bao\s*nhiêu|"
    r"mua.*bao\s*nhiêu|đắt\s*không|rẻ\s*không|chi\s*phí.*mua)",
    re.IGNORECASE,
)
_COMPARE_RE = re.compile(
    r"(so\s*sánh|so\s*sanh|\bvs\b|versus|hơn\s*kém|khác\s*gì|tốt\s*hơn|hay\s*hơn|"
    r"đáng\s*mua|nên\s*mua|giữa\s*.*và)",
    re.IGNORECASE,
)
_CROSS_MODEL_RE = re.compile(
    r"(xe\s*nào\s*có|những\s*xe.*có|model\s*nào\s*có|dòng\s*nào\s*có|"
    r"có\s*trên\s*những\s*xe|có\s*trên\s*xe\s*nào)",
    re.IGNORECASE,
)
_FEATURE_PRESENCE_RE = re.compile(
    r"(có\s+[^?]{1,80}\s+(không|ko|hả|nhỉ)\s*\??|"
    r"liệu\s+[^?]{1,60}\s+có\s+.*\?|"
    r"[^?]{1,60}\s+có\s+(không|ko)\s*\??)",
    re.IGNORECASE,
)
_MODELS_LIST_RE = re.compile(
    r"(những\s*xe|danh\s*sách\s*xe|các\s*mẫu\s*xe|mấy\s*loại\s*xe|đang\s*bán\s*những|"
    r"có\s*những\s*xe\s*nào)",
    re.IGNORECASE,
)
_VERSIONS_LIST_RE = re.compile(
    r"(có\s+mấy\s+phiên\s+bản|những\s+phiên\s+bản|phiên\s+bản\s+nào|mấy\s+bản|edition|"
    r"có\s+những\s+bản)",
    re.IGNORECASE,
)
_COLORS_RE = re.compile(
    r"(màu\s*sắc|màu\s*ngoại\s*thất|màu\s*nội\s*thất|màu\s*gì|có\s*những\s*màu|màu\s*sơn)",
    re.IGNORECASE,
)
_POLICY_RE = re.compile(
    r"(bảo\s*hành|bảo\s*dưỡng|chính\s*sách|điều\s*khoản|sửa\s*chữa|cứu\s*hộ|"
    r"dịch\s*vụ\s*sau\s*bán|pháp\s*lý|hỗ\s*trợ\s*kỹ\s*thuật|đặt\s*cọc|đặt\s*coc)",
    re.IGNORECASE,
)


_UTILITY_RE = re.compile(
    r"(showroom|trạm\s*sạc|đại\s*lý|cửa\s*hàng|chi\s*nhánh|"
    r"lái\s*thử|test\s*drive|đăng\s*ký\s*lái|"
    r"đặt\s*lịch|booking|lịch\s*hẹn|"
    r"trả\s*góp|vay|thẩm\s*định|lăn\s*bánh|đăng\s*ký\s*xe|"
    r"khuyến\s*mãi|ưu\s*đãi|voucher|"
    r"hotline|liên\s*hệ|gặp\s*sales|"
    r"link\s*bảo\s*dưỡng|lịch\s*bảo\s*dưỡng)",
    re.IGNORECASE,
)


def extract_spec_category(query: str) -> str | None:
    """Keyword → spec_category (deterministic). None = không lọc (lấy tất cả)."""
    q = query.lower()
    for cat, pats in _SPEC_CATEGORY_PATTERNS:
        for p in pats:
            if re.search(p, q):
                return cat
    return None


# ── BẢNG keyword → spec_key — feature check: chỉ lấy ĐÚNG field cần ────────
# Dùng cho feature_presence / cross_model_feature: context cực nhỏ thay vì cả
# category (VD "cửa sổ trời" → chỉ sunroof_type, không phải 42 dòng interior).
_SPEC_KEY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("sunroof_type", (r"cửa\s*sổ\s*trời", r"kính\s*trần", r"\bsunroof\b", r"\bpanoramic\b")),
    ("airbags", (r"túi\s*khí", r"\bairbag\b")),
    ("power_kw", (r"công\s*suất", r"mã\s*lực")),
    ("torque_nm", (r"mô[\s-]*men", r"\btorque\b")),
    ("range_km", (r"quãng\s*đường", r"đi\s*được", r"phạm\s*vi", r"\brange\b", r"tầm\s*di\s*chuyển")),
    ("battery_kwh", (r"dung\s*lượng\s*pin", r"pin")),
    ("fast_charge_min", (r"sạc\s*nhanh", r"thời\s*gian\s*sạc", r"sạc\s*chậm", r"sạc\s*đầy")),
    ("acceleration_0_100_s", (r"tăng\s*tốc", r"0\s*[-–]\s*100")),
    ("top_speed_kmh", (r"tốc\s*độ\s*tối\s*đa", r"vận\s*tốc")),
    ("drivetrain", (r"dẫn\s*động", r"\bawd\b", r"\bfwd\b", r"\brwd\b", r"cầu\s*trước", r"cầu\s*sau")),
    ("length_mm", (r"chiều\s*dài", r"dài\s*bao\s*nhiêu")),
    ("width_mm", (r"chiều\s*rộng", r"rộng\s*bao\s*nhiêu")),
    ("height_mm", (r"chiều\s*cao", r"cao\s*bao\s*nhiêu")),
    ("wheelbase_mm", (r"trục\s*cơ\s*sở", r"\bwheelbase\b")),
    ("ground_clearance_mm", (r"khoảng\s*sáng\s*gầm",)),
    ("curb_weight_kg", (r"trọng\s*lượng", r"cân\s*nặng")),
    ("seats", (r"số\s*chỗ", r"chỗ\s*ngồi", r"mấy\s*chỗ", r"bao\s*nhiêu\s*chỗ", r"5\s*chỗ", r"7\s*chỗ")),
    ("head_up_display", (r"\bhud\b",)),
    ("surround_view_camera", (r"camera\s*360", r"camera\s*toàn\s*cảnh")),
    ("leatherette_seats", (r"ghế\s*da",)),
    ("speakers", (r"\bloa\b", r"số\s*loa", r"dàn\s*loa")),
    ("display_inch", (r"màn\s*hình",)),
    ("ac_type", (r"điều\s*hòa",)),
    ("trunk_capacity", (r"dung\s*tích\s*cốp", r"cốp")),
    ("wheel_size_inch", (r"mâm", r"la[\s-]*zăng")),
]


def extract_spec_key(query: str) -> str | None:
    """Keyword → spec_key (deterministic) — dùng cho feature check."""
    q = query.lower()
    for key, pats in _SPEC_KEY_KEYWORDS:
        for p in pats:
            if re.search(p, q):
                return key
    return None


def classify_intent(query: str, topic: str = "general") -> str:
    """Rule-based intent. topic từ _classify_topic (nodes/classify.py)."""
    q = query.strip()

    # 1. Chào hỏi / Cảm ơn / Giới thiệu thuần tuý
    if _GREETING_ONLY_RE.match(q):
        return "greeting"
    if _THANKS_ONLY_RE.match(q):
        return "thanks"
    if _IDENTITY_RE.search(q):
        return "identity"

    # 2. Các câu hỏi nghiệp vụ xe VinFast (ưu tiên nhận diện để không chặn câu hỏi có kèm lời chào)
    if _UTILITY_RE.search(q):
        return "utility"
    if _PRICE_RE.search(q):
        return "price"
    if _COMPARE_RE.search(q):
        return "compare"
    if _CROSS_MODEL_RE.search(q):
        return "cross_model_feature"
    if _FEATURE_PRESENCE_RE.search(q):
        return "feature_presence"
    if _MODELS_LIST_RE.search(q):
        return "models_list"
    if _VERSIONS_LIST_RE.search(q):
        return "versions_list"
    if _COLORS_RE.search(q):
        return "colors"
    if _POLICY_RE.search(q):
        return "policy"
    if topic != "general":
        return "spec_query"

    # 3. Câu hỏi ngoài phạm vi
    if _OUT_OF_SCOPE_RE.search(q):
        return "out_of_scope"

    return "general"


def _norm_model(raw: str) -> str:
    """Chuẩn hóa về dạng DB: 'vf8' → 'VF 8', 'VF 8 new' → 'VF 8 All New'."""
    return normalize_model(raw)


# ── LLM fallback (hybrid) — chỉ khi rule không quyết định được ──────────────
_LLM_CLASSIFY_PROMPT = """Phân loại câu hỏi tư vấn xe VinFast. Chỉ trả về JSON:
{{
  "intent": "{intents}",
  "model_code": "tên model nếu có, VD \\"VF 8\\", ngược lại null",
  "version": "Eco/Plus/... nếu có, ngược lại null",
  "spec_category": "{cats} — null nếu không rõ",
  "reason": "ngắn gọn vì sao"
}}
Câu hỏi: {query}
"""

_SPEC_CATEGORIES = [c for c, _ in _SPEC_CATEGORY_PATTERNS if c]


def _validate_llm_result(data: dict) -> dict | None:
    """Validate kết quả LLM — nếu sai format/enum → bỏ (coi như general)."""
    intent = str(data.get("intent", "")).strip()
    if intent not in INTENTS:
        return None
    out: dict = {"intent": intent, "model_code": None, "version": None, "spec_category": None}
    mc = data.get("model_code")
    if mc and isinstance(mc, str) and MODEL_RE.search(mc):
        out["model_code"] = _norm_model(MODEL_RE.search(mc).group(1))
    ver = data.get("version")
    if ver and isinstance(ver, str) and ver.strip():
        out["version"] = ver.strip()
    cat = data.get("spec_category")
    if cat in _SPEC_CATEGORIES:
        out["spec_category"] = cat
    return out


async def llm_classify_fallback(query: str, history: list[dict]) -> dict | None:
    """1 LLM call strict-JSON khi rule intent = general. Trả entities hoặc None."""
    from app.agent.llm import get_llm

    try:
        import json as _json

        client = get_llm()
        prompt = _LLM_CLASSIFY_PROMPT.format(
            intents="|".join(INTENTS),
            cats="|".join(_SPEC_CATEGORIES),
            query=query[:400],
        )
        msgs = []
        if history:
            recent = history[-4:]
            msgs.append(
                {
                    "role": "user",
                    "content": "Hội thoại trước:\n" + "\n".join(f"{m['role']}: {m['content'][:200]}" for m in recent),
                }
            )
        msgs.append({"role": "user", "content": prompt})
        resp = await client.chat.completions.create(
            model="deepseek-ai/DeepSeek-V4-Flash",
            messages=msgs,
            max_tokens=150,
            temperature=0,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content or ""
        return _validate_llm_result(_json.loads(content))
    except Exception as e:
        logger.warning("llm classify fallback failed: %s", e)
        return None
