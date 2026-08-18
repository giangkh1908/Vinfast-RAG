#!/usr/bin/env python3
"""
chunk_filters.py — Filter chunk ở mức nội dung (sau khi đã chunk).

Tách từ clean_to_jsonl.py. Mỗi hàm nhận 1 chunk dict → True nếu chunk cần DROP:
  - is_offmodel_noise   sidebar "tin liên quan" nhắc brand đối thủ, không nhắc model
  - is_junk_chunk       boilerplate site (modal/footer/nav/button từ shop site)
  - is_spec_section / is_spec_table   spec số liệu (đã chuyển sang PostgreSQL car_specs)
"""

import re
from typing import Any

from scripts.clean_data.spec_common import MODEL_LABEL, no_diacritics

# Off-model noise: chunk được tag cho 1 model VinFast nhưng text KHÔNG nhắc tới
# model đó / "vinfast", lại nhắc brand đối thủ → sidebar "tin liên quan" lạc tag
# (VD: bài VF2 kèm headline "Toyota Land Cruiser FJ ra mắt Việt Nam, giá đồng").
# Drop để khỏi bẩn corpus — conservative: chỉ drop khi chắc chắn không nhắc model.
COMPETING_BRANDS = (
    "toyota", "honda", "hyundai", "kia", "mazda", "mitsubishi", "nissan",
    "ford", "suzuki", "lexus", "bmw", "mercedes", "audi", "volkswagen",
    "peugeot", "renault", "byd", "tesla", "geely", "wuling",
)


def is_offmodel_noise(chunk: dict[str, Any]) -> bool:
    """True nếu chunk tag model VinFast nhưng text chỉ nói brand đối thủ.

    So khớp nhiều form model trong text: compact ("vf7"), catalog ("vf 7").
    Nếu text nhắc model hoặc "vinfast" → giữ.
    """
    mid = chunk.get("model_id")
    if not mid:
        return False
    text = chunk.get("text", "") or ""
    low = no_diacritics(text).lower()
    if not low:
        return False
    forms = {mid.lower(), mid.lower().replace(" ", "")}
    cat = MODEL_LABEL.get(mid, "").lower()
    if cat:
        forms.add(cat)
    if any(f and f in low for f in forms) or "vinfast" in low:
        return False
    return any(b in low for b in COMPETING_BRANDS)


# ── Junk chunk filter (boilerplate site) ─────────────────────────────────────
# Rác lặp trên MỌI trang của vinfastauto.com / shop.vinfastauto.com: modal
# đăng ký/email, footer nav links, nav menu của trang, button "Giá bán từ Đặt
# cọc". Là điều hướng/form, KHÔNG phải thông tin xe → drop ở mức chunk (vì là
# khối đa-dòng, lọc theo từng dòng bằng NOISE_PATTERNS không đủ).
_JUNK_SECTION_NORM = {
    "dang ky thanh cong", "kiem tra email", "kiem tra email de kich hoat tai khoan",
    "doi mat khau thanh cong", "nhan bao gia uu dai moi nhat",
    "dich vu khach hang", "speak-up hotline", "speak up hotline",
    "tien ich", "mua sam", "theo doi",
}
_JUNK_TEXT_RE = re.compile(
    r"icon-popup-success|"
    r"d[ăa]ng nh[ậa]p\s*/\s*[đd][ăa]ng k[ýy] tr[ưu]ớc khi mua h[àa]ng|"
    r"gi[áa] b[áa]n t[ừu] đ[ặa]t c[ọo]c đ[ăa]ng k[ýy] l[áa]i th[ửu]|"
    r"vinfast s[ẽe] li[êe]n h[ệe] t[ưu] v[ấa]n|"
    r"c[ảa]m [ơo]n qu[ýy] kh[áa]ch đ[ãa] quan t[âa]m|"
    r"tra cứu tài liệu hướng dẫn|"
    r"vf\s*\d+\s+hero banner|"
    r"checkbox label label\s+consent leg\.interest|"
    r"^\s*-\s*công ty\s*-\s*ô tô điện\s*-\s*xe máy điện\s*$|"
    r"đặt lịch sửa chữa\s+đặt lịch sửa chữa",
    re.IGNORECASE,
)
_JUNK_TEXT_NORM_RE = re.compile(
    r"doi mat khau thanh cong|"
    r"thay doi thanh cong mat khau|"
    r"tra cuu tai lieu huong dan|"
    r"dat lich sua chua\s+dat lich sua chua|"
    r"tim showroom\s*&\s*tram sac.*cau hoi thuong gap|"
    r"san pham dang cap, gia tot, chinh sach hau mai vuot troi",
    re.IGNORECASE | re.DOTALL,
)
_NAV_ITEM_RE = re.compile(
    r"^-\s*(gi[áa] b[áa]n|gi[ớo]i thi[ệe]u|ngo[ạa]i th[ấa]t|n[ộo]i th[ấa]t|"
    r"th[ôo]ng s[ốo]|t[íi]nh n[ăa]ng|t[ổo]ng quan|thi[ếe]t k[ếe]|v[ậa]n h[àa]nh|"
    r"an to[àa]n|ưu đ[ãa]i|c[áa]c phi[êe]n b[ảa]n)\s*$",
    re.IGNORECASE,
)


def is_junk_chunk(chunk: dict[str, Any]) -> bool:
    """True nếu chunk là boilerplate site (modal/footer/nav/button) — drop."""
    text = chunk.get("text", "") or ""
    # (1) section title là header modal hoặc footer
    for sp in chunk.get("section_path", []):
        if no_diacritics(sp).lower().strip() in _JUNK_SECTION_NORM:
            return True
    # (2) text khớp modal/newsletter/price-button
    if (_JUNK_TEXT_RE.search(text)
            or _JUNK_TEXT_NORM_RE.search(no_diacritics(text))):
        return True
    # (3) nav menu leak: KHÔNG có section title (chunk gốc) + text là/mở đầu bằng nav items
    if len(chunk.get("section_path", [])) <= 1:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        nav_lines = [line for line in lines if _NAV_ITEM_RE.match(line)]
        if len(nav_lines) >= 2 and len(nav_lines) / max(len(lines), 1) >= 0.5:
            return True

        if re.search(r"^-\s*(gi[aá] b[aá]n|gi[ớo]i thi[ệe]u|ngo[ạa]i th[ấa]t|"
                     r"n[ộo]i th[ấa]t|th[ôo]ng s[ốo])\s*\n", text, re.MULTILINE):
            return True
    return False


# ── Spec filter (spec số liệu KHÔNG vào vector — chỉ ở PostgreSQL car_specs) ─
# 2 điều kiện drop:
#   (a) section_path có tiêu đề section == "thông số kỹ thuật" (section spec của
#       dat-coc — text_type có thể là prose do flatten "Động cơ 01 Motor...").
#   (b) content-based: chunk ở vivu_product_info có ≥4 ký tự '|' VÀ chứa label spec
#       (công suất / mô men / pin / quãng đường / tải trọng...). Bắt spec-table
#       pipe-delimited bị gán nhãn text_type=prose do chunk-split mất dòng `---`
#       (detector '|'+---' không nhận). Ngưỡng pipe bảo vệ prose mô tả
#       ("VF 8 có công suất 150 kW" — 0 pipe → giữ).
_SPEC_LABELS = (
    "cong suat", "mo men", "mo-men", "dung luong pin", "loai pin",
    "quang duong", "tai trong", "trong luong", "chieu dai co so",
    "chieu dai", "chieu rong", "chieu cao", "khoang sang", "co so",
    "toc do toi da", "tang toc", "so cho ngoi", "cho ngoi",
    "dan dong", "he thong treo", "treo truoc", "treo sau",
    "thoi gian nap", "sac day", "sac nhanh", "khoang chua hanh ly",
)


def is_spec_section(chunk: dict[str, Any]) -> bool:
    """True nếu chunk nằm trong section "thông số kỹ thuật" — drop."""
    for sp in chunk.get("section_path", []):
        if no_diacritics(sp).lower().replace(" ", "") == "thongsokythuat":
            return True
    return False


def is_spec_table(chunk: dict[str, Any]) -> bool:
    """True nếu chunk là spec-table pipe-delimited (≥4 pipe + label spec) — drop."""
    if chunk.get("collection") != "vivu_product_info":
        return False
    text = chunk.get("text", "") or ""
    if text.count("|") < 4:
        return False
    low = no_diacritics(text).lower()
    return any(lbl in low for lbl in _SPEC_LABELS)
