def build_structured_context(tool_results: list[dict]) -> str:
    sections = []

    for tr in tool_results:
        if not tr.get("success", True):
            continue

        tool = tr["tool"]
        result = tr["result"]

        if tool == "get_price":
            sections.append(_format_prices(result))
        elif tool == "get_specs":
            sections.append(_format_specs(result))
        elif tool == "search_knowledge_base":
            sections.append(_format_search_results(result))
        elif tool == "search_all":
            if result.get("specs"):
                sections.append(_format_specs(result["specs"]))
            if result.get("knowledge_base"):
                sections.append(_format_search_results(result["knowledge_base"]))
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
    source_url = result.get("source_url", "")
    lines = [f"Giá xe {result['model_code']}:"]
    for p in result.get("prices", []):
        promo = f"{p['promo_price_vnd']:,} VNĐ" if p.get("promo_price_vnd") else "N/A"
        price = f"{p['price_vnd']:,} VNĐ" if p.get("price_vnd") else "N/A"
        lines.append(f"  - {p['version_name']}: Giá niêm yết {price} | Giá ưu đãi {promo}")
    if source_url:
        lines.append(f"\n  Nguồn: {source_url}")
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


def _format_specs(result: dict) -> str:
    source_url = result.get("source_url", "")
    lines = [f"Thông số kỹ thuật {result['model_code']}:"]
    current_cat = None
    for s in result.get("specs", []):
        if s["category"] != current_cat:
            current_cat = s["category"]
            lines.append(f"\n  [{current_cat.upper()}]")
        unit = f" {s['unit']}" if s["unit"] else ""
        page = f" [trang {s['page']}]" if s.get("page") else ""
        ver = s["version_name"]
        if ver == "ALL":
            lines.append(f"    {s['key']}: {s['value']}{unit}{page}")
        else:
            lines.append(f"    {ver} — {s['key']}: {s['value']}{unit}{page}")
    if source_url:
        lines.append(f"\n  Nguồn: {source_url}")
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
        src = r.get("source_url", "")
        lines.append(f"\n  [{i}] ({r['source_type']}, score={r['score']})")
        lines.append(f"      {r['text']}")
        if src:
            lines.append(f"      Nguồn: {src}")
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
    for l in links:
        lines.append(f"  - {l['label']}: {l['url']}")
    return "\n".join(lines)


def _format_maintenance(result: dict) -> str:
    links = result.get("links", [])
    if not links:
        return "Không tìm thấy link bảo dưỡng."
    lines = ["Link bảo dưỡng:"]
    for l in links:
        lines.append(f"  - Năm {l['year']}: {l['source_url']}")
    return "\n".join(lines)
