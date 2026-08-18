import re

_TOKEN_RE = re.compile(r"[a-zà-ỹ0-9]+", re.UNICODE)

# Nguồn tham khảo hiển thị qua SourcesBox (UI) — KHÔNG để URL lọt vào context
# để tránh LLM copy thành "Chi tiết: ..." / "Nguồn: ..." inline.
_URL_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")  # markdown link [text](url) → text
_BARE_URL_RE = re.compile(r"https?://\S+")  # url trần


def _strip_urls(text: str) -> str:
    """Bỏ URL khỏi text context (giữ label text của markdown link)."""
    text = _URL_RE.sub(r"\1", text)
    text = _BARE_URL_RE.sub("", text)
    return text

# Query keywords → relevant spec categories
_QUERY_TOPIC_MAP = {
    "sạc": ["battery"], "pin": ["battery"], "charge": ["battery"], "kwh": ["battery"],
    "range": ["battery"], "phạm vi": ["battery"], "đi được": ["battery"], "quãng đường": ["battery"],
    "công suất": ["powertrain"], "power": ["powertrain"], "torque": ["powertrain"],
    "mô-men": ["powertrain"], "xoắn": ["powertrain"], "tốc độ": ["powertrain"],
    "tăng tốc": ["powertrain"], "acceleration": ["powertrain"], "drivetrain": ["powertrain"],
    "kích thước": ["dimension"], "chiều dài": ["dimension"], "chiều rộng": ["dimension"],
    "chiều cao": ["dimension"], "trọng lượng": ["dimension"], "wheelbase": ["dimension"],
    "túi khí": ["safety"], "airbag": ["safety"], "phanh": ["safety"], "abs": ["safety"],
    "esc": ["safety"], "an toàn": ["safety"],
    "adas": ["adas"], "cruise": ["adas"], "lane": ["adas"], "collision": ["adas"],
    "aeb": ["adas"], "blind spot": ["adas"], "parking": ["adas"],
    "nội thất": ["interior"], "ghế": ["interior"], "chỗ ngồi": ["interior"], "số chỗ": ["interior"], "màn hình": ["interior"],
    "loa": ["interior"], "điều hòa": ["interior"], "hud": ["interior"], "display": ["interior"],
    "cửa sổ trời": ["interior"], "kính trần": ["interior"], "sunroof": ["interior"], "panoramic": ["interior"],
    "ngoại thất": ["exterior"], "đèn": ["exterior"], "mâm": ["exterior"],
    "wheel": ["exterior"], "la-zăng": ["exterior"], "headlight": ["exterior"],
    "giá": ["price"], "price": ["price"],
    "phiên bản": [], "version": [],  # All categories
    "so sánh": [], "compare": [],  # All categories
    "tính năng": ["adas", "interior", "exterior", "safety", "infotainment"],
    "trang bị": ["adas", "interior", "exterior", "safety", "infotainment"],
}


def _query_relevant_categories(query: str) -> set[str] | None:
    """Extract relevant spec categories from query. None = all categories."""
    if not query:
        return None
    q_lower = query.lower()
    cats = set()
    for keyword, categories in _QUERY_TOPIC_MAP.items():
        if keyword in q_lower:
            if not categories:  # Empty = all categories
                return None
            cats.update(categories)
    return cats if cats else None


def build_structured_context(tool_results: list[dict], query: str = "") -> str:
    sections = []
    relevant_cats = _query_relevant_categories(query)

    for tr in tool_results:
        if not tr.get("success", True):
            continue

        tool = tr["tool"]
        result = tr["result"]

        if tool == "get_price":
            sections.append(_format_prices(result))
        elif tool == "get_specs":
            sections.append(_format_specs(result, relevant_cats))
        elif tool == "search_knowledge_base":
            sections.append(_format_search_results(result))
        elif tool == "get_colors":
            sections.append(_format_colors(result))
        elif tool == "list_available_models":
            sections.append(_format_models(result))
        elif tool == "get_active_promotions":
            sections.append(_format_promotions(result))
        elif tool == "get_onroad_cost_link":
            sections.append(_format_link(result, "chi phí lăn bánh"))
        elif tool == "get_loan_estimate_link":
            sections.append(_format_links(result, "trả góp/thẩm định vay"))
        elif tool == "get_showroom_charging_link":
            sections.append(_format_link(result, "showroom/trạm sạc"))
        elif tool == "get_booking_link":
            sections.append(_format_link(result, "đặt lịch"))
        elif tool == "get_maintenance_link":
            sections.append(_format_maintenance(result))

    return "\n\n".join(sections)


def _format_prices(result: dict) -> str:
    lines = [f"Giá xe {result['model_code']}:"]
    for p in result.get("prices", []):
        promo = f"{p['promo_price_vnd']:,} VNĐ" if p.get("promo_price_vnd") else "N/A"
        price = f"{p['price_vnd']:,} VNĐ" if p.get("price_vnd") else "N/A"
        lines.append(f"  - {p['version_name']}: Giá niêm yết {price} | Giá ưu đãi {promo}")
    related = result.get("related_models", [])
    if related:
        lines.append("\n  Model liên quan:")
        for rm in related:
            rm_price = f"{rm['price_vnd']:,} VNĐ" if rm.get("price_vnd") else "N/A"
            lines.append(f"    - {rm['model_code']} ({rm.get('version_name', '')}): từ {rm_price}")
    note = result.get("note", "")
    if note:
        lines.append(f"\n  Lưu ý: {note}")
    return "\n".join(lines)


_SPEC_KEY_LABELS = {
    "power_kw": "Công suất tối đa",
    "torque_nm": "Mô-men xoắn cực đại",
    "range_km": "Quãng đường di chuyển",
    "battery_kwh": "Dung lượng pin",
    "fast_charge_min": "Thời gian sạc nhanh (10%-70%)",
    "acceleration_0_100_s": "Tăng tốc 0-100 km/h",
    "top_speed_kmh": "Tốc độ tối đa",
    "drivetrain": "Dẫn động",
    "seats": "Số chỗ ngồi",
    "airbags": "Túi khí",
    "length_mm": "Dài",
    "width_mm": "Rộng",
    "height_mm": "Cao",
    "wheelbase_mm": "Chiều dài cơ sở",
    "ground_clearance_mm": "Khoảng sáng gầm",
    "curb_weight_kg": "Trọng lượng không tải",
    "wheel_size_inch": "Kích thước mâm",
    "trunk_capacity": "Dung tích cốp",
    "head_up_display": "Màn hình HUD",
    "surround_view_camera": "Camera 360",
    "leatherette_seats": "Ghế bọc da",
    "speakers": "Số loa",
    "display_inch": "Màn hình cảm ứng",
    "sunroof_type": "Cửa sổ trời",
    "wireless_charging": "Sạc không dây điện thoại",
    "ac_type": "Điều hòa",
    "cabin_air_filter": "Lọc không khí cabin",
    "rear_ac_vents": "Cửa gió điều hòa hàng ghế sau",
    "smart_key": "Chìa khóa thông minh",
    "subwoofer": "Loa trầm",
    "tpms": "Cảnh báo áp suất lốp",
    "usb_port_type_a": "Cổng USB-A",
    "usb_port_type_c": "Cổng USB-C",
    "isofix": "Móc ghế trẻ em ISOFIX",
    "windshield_type": "Kính chắn gió",
    "rollover_mitigation": "Hệ thống chống lật",
    "frunk_capacity_l": "Dung tích cốp trước",
    "privacy_glass": "Kính tối màu",
    "battery_heater": "Gia nhiệt pin",
    "charge_management": "Quản lý sạc",
    "charger_map": "Bản đồ trạm sạc",
}


def _format_colors(result: dict) -> str:
    mc = result.get("model_code", "")
    colors = result.get("colors", [])
    interiors = result.get("interiors", [])
    variants = result.get("variants", [])

    lines = [f"Màu sắc {mc}:"]
    if colors:
        lines.append(f"  Màu ngoại thất ({len(colors)}): {', '.join(colors)}")
    if interiors:
        lines.append(f"  Màu nội thất ({len(interiors)}): {', '.join(interiors)}")

    if variants:
        # Group by color to show fee
        seen = set()
        lines.append("\n  Chi tiết màu:")
        for v in variants:
            key = f"{v['color']}|{v['interior']}"
            if key in seen:
                continue
            seen.add(key)
            fee = v.get("color_fee_vnd") or 0
            color_type = v.get("color_type") or ""
            fee_str = f" (+{fee:,} VNĐ)" if fee > 0 else ""
            type_str = f" [{color_type}]" if color_type else ""
            lines.append(f"    - {v['color']}{type_str} / Nội thất: {v['interior']}{fee_str}")

    return "\n".join(lines)


def _format_specs(result: dict, relevant_cats: set[str] | None = None) -> str:
    lines = [f"Thông số kỹ thuật {result['model_code']}:"]
    current_cat = None
    for s in result.get("specs", []):
        # Filter: only show relevant categories when query is specific
        if relevant_cats is not None and s["category"] not in relevant_cats:
            continue
        if s["category"] != current_cat:
            current_cat = s["category"]
            lines.append(f"\n  [{current_cat.upper()}]")
        unit = f" {s['unit']}" if s["unit"] else ""
        page = f" [trang {s['page']}]" if s.get("page") else ""
        ver = s["version_name"]
        key = s["key"]
        label = _SPEC_KEY_LABELS.get(key, "")
        label_str = f" ({label})" if label else ""
        if ver == "ALL":
            lines.append(f"    {key}{label_str}: {s['value']}{unit}{page}")
        else:
            lines.append(f"    {ver} — {key}{label_str}: {s['value']}{unit}{page}")
    related = result.get("related_models", [])
    if related:
        lines.append("\n  Model liên quan:")
        for rm in related:
            lines.append(f"    - {rm['model_code']}")
    note = result.get("note", "")
    if note:
        lines.append(f"\n  Lưu ý: {note}")
    return "\n".join(lines)


def _format_search_results(result: dict) -> str:
    lines = [f"Kết quả tìm kiếm cho: \"{result['query']}\":"]
    for i, r in enumerate(result.get("results", []), 1):
        lines.append(f"\n  [{i}] ({r['source_type']}, score={r['score']})")
        # strip URL khỏi text — tránh LLM copy link inline
        lines.append(f"      {_strip_urls(r['text'])}")
    return "\n".join(lines)


def _format_models(result: dict) -> str:
    lines = ["Danh sách xe VinFast:"]
    for m in result.get("models", []):
        vers = ", ".join(m.get("versions", []))
        lines.append(f"  - {m['model_code']} — Phiên bản: {vers}")
    return "\n".join(lines)


def _format_promotions(result: dict) -> str:
    url = result.get("url", "")
    label = result.get("label", "Khuyến mãi")
    note = result.get("note", "")
    if url:
        return f"{label}: {url}\n{note}" if note else f"{label}: {url}"
    return "Hiện tại không có thông tin khuyến mãi."


def _format_link(result: dict, label: str) -> str:
    url = result.get("url", "")
    lbl = result.get("label", label)
    if url:
        return f"Link {label}: {lbl}\n  URL: {url}"
    return f"Không tìm thấy link {label}."


def _format_links(result: dict, label: str) -> str:
    links = result.get("links", [])
    if not links:
        return f"Không tìm thấy link {label}."
    lines = [f"Link {label}:"]
    for item in links:
        lines.append(f"  - {item['label']}: {item['url']}")
    return "\n".join(lines)


def _format_maintenance(result: dict) -> str:
    links = result.get("links", [])
    if not links:
        return "Không tìm thấy link bảo dưỡng."
    lines = ["Link bảo dưỡng:"]
    for item in links:
        lines.append(f"  - Năm {item['year']}: {item['source_url']}")
    return "\n".join(lines)

