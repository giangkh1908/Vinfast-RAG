#!/usr/bin/env python3
"""
parse_specs.py — Trích thông số kỹ thuật (số liệu cấu trúc) từ data/raw/*.txt
→ data/clean/<version>/postgres/specs.csv → bảng PostgreSQL `car_specs`.

Vì sao tách riêng: spec số liệu (công suất, momen, quãng đường, kích thước, pin...)
nếu embed trong Qdrant vector sẽ na ná nhau giữa Eco/Plus và giữa các model → vector
search dễ nhầm. Đưa vào `car_specs` (SQL) để retriever query chính xác.

Nguồn: **toàn bộ data/raw/*.txt** (KHÔNG dùng model_specs.json tổng hợp). Mỗi model có
spec rải rác ở nhiều file (dat-coc chính thức, bài so-sanh, thong-so, brochure, product
page) — file nào có thì extract, **union = full coverage**. Conflict giá trị → prefer
nguồn `shop.vinfastauto.com` (chính thống).

3 dạng spec trong raw → 3 parser:
  A. Markdown table (so-sanh / thong-so / VF3 dat-coc): `| label | val1 | val2 |`
     - header có từ khoá edition (Eco/Plus/...) → cột = edition (comparison table)
     - header KHÔNG có edition → cột 1 = value, 1 spec chung mọi bản (vertical list)
  B. Inline same-line (VF5 / MPV7 dat-coc): "label value" trên cùng dòng, label ở đầu.
  C. Line-paired (VF2 / VF8-all-new dat-coc): label 1 dòng, value dòng kế.

Spec "card" (VF6/VF7 dat-coc: value-trước-label) khó parse tin cậy → bỏ qua (model đó
đã có so-sanh/thong-so table bù đắp theo union).

Reuse từ clean_to_jsonl: parse_raw_file, infer_model_raw, MODEL_LABEL, MODEL_EDITIONS,
EDITION_KEYWORDS. Chỉ extract label trong LABEL_MAP (curated spec số liệu/hạng mục
chính); feature mô tả (ADAS, an toàn bullet) KHÔNG extract — giữ ở vector prose.

Usage:
    PYTHONUTF8=1 python scripts/clean_data/parse_specs.py --version v1
"""

import argparse
import asyncio
import base64
import csv
import io
import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
import requests


for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.clean_data.clean_to_jsonl import (  # noqa: E402
    parse_raw_file, infer_model_raw, MODEL_LABEL, MODEL_EDITIONS, EDITION_KEYWORDS,
)

RAW_DIR = REPO_ROOT / "data" / "raw"
CLEAN_DIR = REPO_ROOT / "data" / "clean"

# Ưu tiên nguồn khi conflict giá trị (chính thống nhất → trước).
SOURCE_PRIORITY = ("shop.vinfastauto.com", "vinfastauto.com")
BROCHURE_LINKS = REPO_ROOT / "data" / "raw" / "link_brochure.md"


# ── Normalize ───────────────────────────────────────────────────────────────
def no_diacritics(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s)
                  if unicodedata.category(c) != "Mn")


def norm(s: str) -> str:
    """Normalize label: bỏ dấu, lower, gom space, strip punctuation 2 đầu."""
    s = no_diacritics(s).lower()
    s = s.replace("đ", "d")
    s = re.sub(r"\s+", " ", s).strip()
    return s.strip(":|-–— \t")


# ── LABEL_MAP: alias (đã normalize) → (spec_key, spec_unit, spec_category) ──
# category: dimension | powertrain | interior | safety | adas | exterior | general
# alias = norm(label tiếng Việt). Nhiều alias → cùng (key, unit, category).
_A = {
    # ── powertrain ──
    "cong suat toi da (kw)": ("power_kw", "kW", "powertrain"),
    "cong suat toi da": ("power_kw", "kW", "powertrain"),
    "cong suat toi da (kw/hp)": ("power_kw", "kW", "powertrain"),
    "cong suat": ("power_kw", "kW", "powertrain"),
    "mo men xoan cuc dai (nm)": ("torque_nm", "Nm", "powertrain"),
    "mo-men xoan cuc dai": ("torque_nm", "Nm", "powertrain"),
    "mo men xoan cuc dai": ("torque_nm", "Nm", "powertrain"),
    "quang duong chay mot lan sac day (km) (nedc)": ("range_km", "km", "powertrain"),
    "quang duong chay mot lan sac day (km)": ("range_km", "km", "powertrain"),
    "quang duong chay mot lan sac day": ("range_km", "km", "powertrain"),
    "quang duong chay (nedc)": ("range_km", "km", "powertrain"),
    "quang duong di chuyen (wltp)": ("range_km", "km", "powertrain"),
    "quang duong di chuyen (nedc)": ("range_km", "km", "powertrain"),
    "quang duong di chuyen": ("range_km", "km", "powertrain"),
    "quang duong chay mot lan sac day (km) - dieu kien tieu chuan chau au (wltp)":
        ("range_km", "km", "powertrain"),
    "quang duong": ("range_km", "km", "powertrain"),
    "thoi gian nap pin nhanh nhat": ("fast_charge_min", "phút", "powertrain"),
    "thoi gian nap pin nhanh nhat (10%-70%)": ("fast_charge_min", "phút", "powertrain"),
    "thoi gian nap pin nhanh nhat (phut)": ("fast_charge_min", "phút", "powertrain"),
    "thoi gian sac nhanh (10-70%)": ("fast_charge_min", "phút", "powertrain"),
    "thoi gian nap pin nhanh nhat (tu 10 den 70%) (phut)":
        ("fast_charge_min", "phút", "powertrain"),
    "dung luong pin kha dung": ("battery_kwh", "kWh", "powertrain"),
    "dung luong pin kha dung (kwh)": ("battery_kwh", "kWh", "powertrain"),
    "dung luong pin (kwh) - kha dung": ("battery_kwh", "kWh", "powertrain"),
    "dung luong pin (kwh)": ("battery_kwh", "kWh", "powertrain"),
    "dung luong pin": ("battery_kwh", "kWh", "powertrain"),
    "pack pin": ("battery_kwh", "kWh", "powertrain"),
    "loai pin": ("battery_type", "", "powertrain"),
    "dan dong": ("drivetrain", "", "powertrain"),
    "dong co": ("engine", "", "powertrain"),
    "toc do toi da (km/h) duy tri 1 phut": ("top_speed_kmh", "km/h", "powertrain"),
    "toc do toi da (km/h)": ("top_speed_kmh", "km/h", "powertrain"),
    "toc do toi da": ("top_speed_kmh", "km/h", "powertrain"),
    "tang toc 0-100 km/h": ("acceleration_0_100_s", "s", "powertrain"),
    "tang toc 0-100km/h (s)": ("acceleration_0_100_s", "s", "powertrain"),
    "kha nang tang toc tu 0-100km/h (s) - muc tieu du kien":
        ("acceleration_0_100_s", "s", "powertrain"),
    "cong suat sac nhanh dc toi da": ("dc_charge_kw", "kW", "powertrain"),
    "cong suat sac ac toi da (kw)": ("ac_charge_kw", "kW", "powertrain"),
    "muc tieu thu nhien lieu cong khai": ("consumption", "", "powertrain"),
    "muc cong bo tieu thu dien nang": ("consumption", "", "powertrain"),
    "che do lai": ("drive_modes", "", "powertrain"),
    "chon che do lai": ("drive_modes", "", "powertrain"),
    # ── dimension ──
    "dai x rong x cao (mm)": ("dimension_triple", "mm", "dimension"),
    "dai x rong x cao": ("dimension_triple", "mm", "dimension"),
    "chieu dai co so": ("wheelbase_mm", "mm", "dimension"),
    "khoang sang gam xe": ("ground_clearance_mm", "mm", "dimension"),
    "khoang sang gam": ("ground_clearance_mm", "mm", "dimension"),
    "ban kinh quay xe": ("turning_radius", "", "dimension"),
    # ── exterior / wheels ──
    "kich thuoc mam xe": ("wheel_size_inch", "inch", "exterior"),
    "kich thuoc la-zang": ("wheel_size_inch", "inch", "exterior"),
    "loai la-zang": ("wheel_size_inch", "inch", "exterior"),
    "loai lop": ("tire_type", "", "exterior"),
    "lop du phong": ("spare_tire", "", "exterior"),
    "den chieu sang phia truoc": ("headlights", "", "exterior"),
    "den pha": ("headlights", "", "exterior"),
    "den chieu sang ban ngay": ("drl", "", "exterior"),
    "den suong mu truoc": ("fog_light", "", "exterior"),
    "guong chieu hau": ("mirrors", "", "exterior"),
    "dieu chinh cop sau": ("tailgate", "", "exterior"),
    "dong/mo cop sau": ("tailgate", "", "exterior"),
    # ── interior ──
    "so ghe ngoi": ("seats", "", "interior"),
    "so cho ngoi": ("seats", "", "interior"),
    "cho ngoi": ("seats", "", "interior"),
    "dung thich cop xe": ("trunk_capacity", "L", "interior"),
    "dung tich cop sau": ("trunk_capacity", "L", "interior"),
    "cop sau": ("tailgate", "", "exterior"),
    "man hinh giai tri trung tam": ("display_inch", "inch", "interior"),
    "man hinh giai tri cam ung": ("display_inch", "inch", "interior"),
    "he thong loa": ("speakers", "", "interior"),
    "he thong dieu hoa": ("ac", "", "interior"),
    "chat lieu boc ghe": ("seat_material", "", "interior"),
    "chat lieu ghe": ("seat_material", "", "interior"),
    "ghe lai": ("driver_seat", "", "interior"),
    "ghe phu": ("passenger_seat", "", "interior"),
    "hang ghe thu hai": ("second_row", "", "interior"),
    "hang ghe thu 2": ("second_row", "", "interior"),
    "loai vo lang": ("steering_wheel", "", "interior"),
    # ── safety / chassis ──
    "tui khi": ("airbags", "", "safety"),
    "he thong phanh (truoc/sau)": ("brakes", "", "safety"),
    "he thong phanh truoc/sau": ("brakes", "", "safety"),
    "phanh truoc": ("brakes", "", "safety"),
    "phanh sau": ("brakes", "", "safety"),
    "he thong treo (truoc/sau)": ("suspension", "", "safety"),
    "he thong treo - truoc": ("suspension", "", "safety"),
    "he thong treo - sau": ("suspension", "", "safety"),
    "treo truoc": ("suspension", "", "safety"),
    "treo sau": ("suspension", "", "safety"),
}
# alias dài nhất trước (match ưu tiên chuỗi dài hơn — "cong suat toi da (kw/hp)" trước
# "cong suat toi da").
LABEL_MAP = {alias: v for alias, v in _A.items()}
_ALIASES_BY_LEN = sorted(LABEL_MAP.keys(), key=len, reverse=True)

# ── WHITELIST: chỉ giữ spec cơ bản phục vụ tư vấn mua xe ────────────────────
# (power/torque/range/pin/kích thước/chỗ ngồi). Key ngoài whitelist → drop.
# category: dimension | powertrain | battery | interior
BASIC_SPECS: dict[str, tuple[str, str]] = {
    # key:                      (category, unit)
    "length_mm":            ("dimension", "mm"),
    "width_mm":             ("dimension", "mm"),
    "height_mm":            ("dimension", "mm"),
    "wheelbase_mm":         ("dimension", "mm"),
    "ground_clearance_mm":  ("dimension", "mm"),
    "power_kw":             ("powertrain", "kW"),
    "torque_nm":            ("powertrain", "Nm"),
    "drivetrain":           ("powertrain", ""),
    "battery_kwh":          ("battery",   "kWh"),
    "range_km":             ("battery",   "km"),
    "dc_charge_kw":         ("battery",   "kW"),
    "seats":                ("interior",  ""),
}


# spec_key có giá trị số → chỉ giữ phần số. Còn lại giữ nguyên text (định tính).
NUMERIC_KEYS = {
    "power_kw", "torque_nm", "range_km", "battery_kwh", "fast_charge_min",
    "top_speed_kmh", "acceleration_0_100_s", "dc_charge_kw", "ac_charge_kw",
    "wheelbase_mm", "ground_clearance_mm", "wheel_size_inch", "seats",
    "trunk_capacity", "display_inch", "speakers", "airbags",
}
# Dimension triple → tách 3 row length/width/height (dot = phân cách hàng nghìn → bỏ).
DIMENSION_KEYS = ("length_mm", "width_mm", "height_mm")

# Section divider trong table (PIN, KHUNG GẦM, NGOẠI THẤT...) — value rỗng, skip.
SECTION_HEADERS = {
    "pin", "khung gam", "ngoai that", "ngoai that den pha", "noi that & tien nghi",
    "noi that", "thong so truyen dong khac", "giam xoc", "phanh",
    "vanh va lop banh xe", "ghe toan xe", "ghe lai", "ghe phu", "khung gam khac",
    "phiên ban", "phien ban", "thong so", "dau xe", "hong xe", "duoi xe",
}
PRICE_LABELS = ("gia", "lan bangh", "lan bang", "niem yet", "gia ban", "phien ban")


def lookup_label(label_norm: str) -> tuple[str, str, str] | None:
    """Tra LABEL_MAP: exact match trước, rồi startswith (alias dài nhất)."""
    if label_norm in LABEL_MAP:
        return LABEL_MAP[label_norm]
    for alias in _ALIASES_BY_LEN:
        if label_norm.startswith(alias):
            return LABEL_MAP[alias]
    return None


def is_section_header(label_norm: str) -> bool:
    return label_norm in SECTION_HEADERS


def is_price_row(label_norm: str) -> bool:
    return any(p in label_norm for p in PRICE_LABELS)


def detect_edition(text: str) -> str | None:
    """Từ khoá edition trong 1 đoạn text (header cell / dòng context).
    Đồng nghĩa: 'Base' → 'Eco' (base trim = Eco theo MODEL_EDITIONS)."""
    t = norm(text)
    for kw in EDITION_KEYWORDS:
        if kw.lower() in t:
            return EDITION_SYNONYMS.get(kw.lower(), kw)
    return None


EDITION_SYNONYMS = {"base": "Eco"}


# ── Value cleaning ──────────────────────────────────────────────────────────
def parse_number(s: str) -> tuple[str, float] | None:
    """Trích token số đầu tiên → (canonical_str, float). Trả None nếu không có số.
    Phân biệt dot=phân cách hàng nghìn (vd 2.950) vs comma=thập phân (vd 87,7) vs
    dot=thập phân (vd 7.5). Canonical: bỏ dot hàng nghìn, comma→dot thập phân
    ('2.950'→'2950', '87,7'→'87.7', '4701'→'4701', '5,58'→'5.58')."""
    m = re.search(r"[\d][\d.,]*", s or "")
    if not m:
        return None
    tok = m.group(0)
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", tok):       # 2.950 / 1.234,5
        tok = tok.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d+,\d+", tok):                       # 87,7
        tok = tok.replace(",", ".")
    # else: \d+\.\d+ (7.5) hoặc \d+ → giữ nguyên
    try:
        val = float(tok)
    except ValueError:
        return None
    # canonical: số nguyên → bỏ ".0" (2840.0 → 2840); thập phân → gọn (87.7, 5.58).
    canon = str(int(val)) if val == int(val) else f"{val:g}"
    return canon, val


# Khoảng hợp lý cho spec số liệu — value ngoài khoảng = junk → drop.
SANITY_RANGES = {
    "power_kw": (5, 600), "torque_nm": (30, 1500), "range_km": (50, 1000),
    "battery_kwh": (3, 300), "fast_charge_min": (5, 600), "top_speed_kmh": (50, 400),
    "acceleration_0_100_s": (1, 30), "dc_charge_kw": (1, 500), "ac_charge_kw": (1, 500),
    "wheelbase_mm": (1500, 4000), "ground_clearance_mm": (50, 500),
    "wheel_size_inch": (12, 30), "seats": (2, 9), "trunk_capacity": (50, 3000),
    "display_inch": (5, 30), "speakers": (1, 30), "airbags": (1, 20),
    "length_mm": (2000, 6000), "width_mm": (1000, 3000), "height_mm": (1000, 3000),
}


def clean_value(spec_key: str, raw: str) -> str | None:
    """Chuẩn hóa value. NUMERIC_KEYS → parse_number + sanity range (None = drop).
    Key định tính → giữ text đã strip."""
    v = raw.strip().strip(":|-–—").strip()
    v = re.sub(r"\s+", " ", v)
    if not v:
        return None
    if spec_key in NUMERIC_KEYS or spec_key in DIMENSION_KEYS:
        pn = parse_number(v)
        if not pn:
            return None
        canon, val = pn
        lo, hi = SANITY_RANGES.get(spec_key, (None, None))
        if lo is not None and not (lo <= val <= hi):
            return None
        return canon
    if spec_key == "drivetrain":
        # Chuẩn hóa FWD/RWD/AWD — bỏ "Cầu trước"/"Cầu sau"/tiếng Anh lẫn VN.
        n = v.upper()
        for token in ("AWD", "RWD", "FWD"):
            if token in n:
                return token
        return None  # không nhận diện được (vd VF2 parse nhầm) → drop
    return v


def parse_dimension_triple(value: str) -> list[tuple[str, str]]:
    """'4701 x 1872 x 1670' / '3.967 x 1.723 x 1.579' → [(length_mm,'4701'),...].
    Mỗi phần qua parse_number (dot=thousands → bỏ) + sanity range."""
    parts = re.split(r"\s*[xX×]\s*", value)
    out: list[tuple[str, str]] = []
    for i, key in enumerate(DIMENSION_KEYS):
        if i < len(parts):
            cv = clean_value(key, parts[i])
            if cv:
                out.append((key, cv))
    return out


# ── Table parser (Format A) ─────────────────────────────────────────────────
TABLE_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$")
SEP_RE = re.compile(r"^\s*\|\s*[-:|\s]+\|\s*$")


def split_cells(row: str) -> list[str]:
    inner = row.strip()[1:-1]  # bỏ | đầu/cuối
    return [c.strip() for c in inner.split("|")]


def parse_tables(body: str) -> list[tuple[str, str, str | None]]:
    """Trả list (label_norm, value_raw, edition_or_None)."""
    out: list[tuple[str, str, str | None]] = []
    lines = body.splitlines()
    i = 0
    while i < len(lines):
        if not (TABLE_ROW_RE.match(lines[i]) and i + 1 < len(lines)
                and SEP_RE.match(lines[i + 1])):
            i += 1
            continue
        # header = dòng i, separator = i+1, data rows từ i+2
        header = split_cells(lines[i])
        data_start = i + 2
        # Xác định cột edition từ header (bỏ cột 0 = label)
        edition_cols: dict[int, str] = {}
        for ci in range(1, len(header)):
            ed = detect_edition(header[ci])
            if ed:
                edition_cols[ci] = ed
        j = data_start
        while j < len(lines) and TABLE_ROW_RE.match(lines[j]) and not SEP_RE.match(lines[j]):
            cells = split_cells(lines[j])
            if not cells:
                j += 1
                continue
            label = norm(cells[0])
            if not label or is_section_header(label) or is_price_row(label):
                j += 1
                continue
            if not edition_cols:
                # vertical list: cột 1 = value, 1 spec chung mọi bản
                if len(cells) >= 2 and cells[1]:
                    out.append((label, cells[1], None))
            else:
                for ci, ed in edition_cols.items():
                    if ci < len(cells) and cells[ci]:
                        out.append((label, cells[ci], ed))
            j += 1
        i = j
    return out


# ── Inline + line-paired parser (Format B/C) ────────────────────────────────
def parse_inline(body: str) -> list[tuple[str, str, str | None]]:
    """Duyệt dòng: label ở đầu dòng (norm startswith alias) → value = phần sau
    (Format B); nếu dòng chỉ là label → value = dòng kế (Format C)."""
    out: list[tuple[str, str, str | None]] = []
    lines = body.splitlines()
    n = len(lines)
    for i, line in enumerate(lines):
        if TABLE_ROW_RE.match(line):  # table cell → do parse_tables lo
            continue
        nline = norm(line)
        if not nline or nline.startswith("#"):
            continue
        alias = None
        for a in _ALIASES_BY_LEN:
            if nline.startswith(a):
                alias = a
                break
        if not alias:
            continue
        # value sau label (Format B): phần gốc sau alias.
        # Vì norm có thể co/giãn độ dài (dấu tiếng Việt → 1 char), tìm vị trí cắt
        # bằng cách norm từng prefix đến khi khớp alias.
        value_text = _value_after_alias(line, alias)
        if value_text and not is_section_header(norm(value_text)) \
                and not _looks_like_label(value_text):
            out.append((alias, value_text, None))
            continue
        # Format C: label đứng riêng → value = dòng kế không rỗng.
        if nline == alias or value_text == "":
            k = i + 1
            while k < n:
                nxt = lines[k].strip()
                if not nxt:
                    k += 1
                    continue
                if TABLE_ROW_RE.match(nxt) or nxt.startswith("#"):
                    break
                if not _looks_like_label(nxt) and not is_section_header(norm(nxt)):
                    out.append((alias, nxt, None))
                break
    return out


def _value_after_alias(line: str, alias: str) -> str:
    """Phần gốc của `line` sau khi bỏ prefix label (đã normalize = alias)."""
    # Norm từng ký tự gốc, so khớp với alias; dừng khi đủ alias.
    res: list[str] = []
    ai = 0
    consumed_space_run = False
    i = 0
    while i < len(line) and ai < len(alias):
        ch = line[i]
        if ch.isspace():
            if alias[ai] == " " and not consumed_space_run:
                res.append(" ")
                ai += 1
                consumed_space_run = True
            i += 1
            continue
        seg = norm(ch)
        if not seg:  # combining mark dư
            i += 1
            continue
        if seg == alias[ai]:
            res.append(ch)
            ai += 1
            consumed_space_run = False
            i += 1
        else:
            return ""  # không khớp
    if ai == len(alias):
        return line[i:]
    return ""


def _looks_like_label(text: str) -> bool:
    """True nếu text trông như 1 label spec khác (tránh lấy nhầm label làm value)."""
    nt = norm(text)
    if not nt:
        return True
    if nt in LABEL_MAP:
        return True
    return any(nt.startswith(a) for a in _ALIASES_BY_LEN)


def _find_alias_anywhere(text: str) -> str | None:
    """Alias (label spec) xuất hiện BẤT KỲ đâu trong text (không cần ở đầu dòng)."""
    n = no_diacritics(text).lower().replace("đ", "d")
    for a in _ALIASES_BY_LEN:
        if a in n:
            return a
    return None


# ── Bảng spec 2 cột (VF6/VF7 dat-coc qua Firecrawl) ─────────────────────────
# Format: label rồi 2 giá trị (Eco/Plus) trên dòng riêng, xen dòng trống / label
# lặp đôi (VF7). VD:
#   "Công suất tối đa" / "130 kW/174 hp" / "150 kW/201 hp"
#   "Dài x Rộng x Cao (mm)" / "4.241 x 1.834 x 1.580" / "4.241 x 1.834 x 1.580"
def parse_label_then_values(body: str) -> list[tuple[str, str, str | None]]:
    out: list[tuple[str, str, str | None]] = []
    lines = body.splitlines()
    n = len(lines)
    i = 0
    while i < n:
        line = lines[i].strip()
        if TABLE_ROW_RE.match(line) or not line:
            i += 1
            continue
        # Dòng bắt đầu bằng số = value-first (hero card VF6) → không phải label, bỏ qua.
        if re.match(r"^[0-9]", line):
            i += 1
            continue
        line = line[2:] if line.startswith("- ") else line  # strip markdown list marker (vf8_html)
        alias = _find_alias_anywhere(line)
        if not alias or is_price_row(alias) or is_section_header(alias):
            i += 1
            continue
        # Bỏ qua dòng trống + label lặp đôi để tới dòng giá trị.
        j = i + 1
        base = no_diacritics(line).lower().replace("đ", "d").strip()
        while j < n:
            nxt = re.sub(r"[*`_]", "", lines[j].strip()).strip()
            nxt = nxt[2:] if nxt.startswith("- ") else nxt
            if not nxt or no_diacritics(nxt).lower().replace("đ", "d").strip() == base:
                j += 1
            else:
                break
        # Gom tối đa 2 dòng giá trị (bắt đầu bằng số; dòng prose thì dừng).
        values: list[str] = []
        while j < n and len(values) < 2:
            v = re.sub(r"[*`_]", "", lines[j].strip()).strip()
            v = v[2:] if v.startswith("- ") else v
            if not v:
                j += 1
                continue
            if TABLE_ROW_RE.match(v) or v.startswith("#") or len(v) > 40 \
                    or not re.match(r"^[0-9]", v):
                break
            values.append(v)
            j += 1
        if len(values) == 2:
            out.append((alias, values[0], "Eco"))
            out.append((alias, values[1], "Plus"))
        i = j if j > i + 1 else i + 1
    return out


# ── Value-trên-label (VF8 All New 2026) ─────────────────────────────────────
# Format: value trên dòng TRƯỚC label ('170 kW' / 'Công suất tối đa'). Có thể
# xen dòng trống. VD:
#   "170 kW" / "Công suất tối đa" / "330 Nm" / "Mô men xoắn cực đại" ...
def _value_matches_spec(value: str, spec_key: str) -> bool:
    """Guard unit: value-trên-label chỉ tin khi value khớp unit kỳ vọng của spec.
    Tránh lấy nhầm value của spec khác khi bảng sau trộn format (VD "Số ghế ngồi"
    bên dưới 1 giá trị dimension)."""
    v = value.lower()
    dim = ("dimension",) if spec_key.startswith("length") or spec_key.startswith("width") \
        or spec_key.startswith("height") else ()
    if spec_key in ("length_mm", "width_mm", "height_mm"):
        return "x" in v
    if spec_key in ("power_kw", "dc_charge_kw", "ac_charge_kw"):
        return "kw" in v
    if spec_key == "torque_nm":
        return "nm" in v
    if spec_key == "battery_kwh":
        return "kwh" in v
    if spec_key == "range_km":
        return "km" in v
    if spec_key in ("wheel_size_inch", "display_inch"):
        return "inch" in v
    if spec_key == "seats":
        return "ghế" in v or "ghe" in v
    return True  # các spec khác không ép unit


def parse_value_above_label(body: str) -> list[tuple[str, str, str | None]]:
    out: list[tuple[str, str, str | None]] = []
    lines = body.splitlines()
    n = len(lines)
    for i in range(1, n):
        line = lines[i].strip()
        line = line[2:] if line.startswith("- ") else line
        if TABLE_ROW_RE.match(line) or not line:
            continue
        alias = _find_alias_anywhere(line)
        if not alias or is_price_row(alias) or is_section_header(alias):
            continue
        mapped = lookup_label(alias)
        if not mapped:
            continue
        k = i - 1
        prev = ""
        while k >= 0 and not prev:
            prev = re.sub(r"[*`_]", "", lines[k].strip()).strip()
            prev = prev[2:] if prev.startswith("- ") else prev
            k -= 1
        if re.match(r"^[0-9]", prev) and _value_matches_spec(prev, mapped[0]):
            out.append((alias, prev, None))
    return out


# ── Hero card value-first (VF6 dat-coc) ─────────────────────────────────────
# "59,6 kWDung lượng pin" — value TRƯỚC label CÙNG dòng (Firecrawl merge unit+label).
# Bắt các spec chưa có trong bảng 2 cột (vd dung lượng pin).
def parse_value_first(body: str) -> list[tuple[str, str, str | None]]:
    out: list[tuple[str, str, str | None]] = []
    for line in body.splitlines():
        if TABLE_ROW_RE.match(line):
            continue
        m = re.match(r"^\s*([\d.,]+)(?:\s*/\s*[\d.,]+)?\s*(kW|Nm|kWh|km)?", line, re.IGNORECASE)
        if not m:
            continue
        rest = line[m.end():].strip()
        if not rest:
            continue
        alias = _find_alias_anywhere(rest)
        if not alias or is_price_row(alias) or is_section_header(alias):
            continue
        mapped = lookup_label(alias)
        if not mapped:
            continue
        # Guard unit: value-trước-label chỉ tin khi đơn vị khớp spec.
        # Tránh false positive: "100 km/h khi dung lượng pin >50%" → battery_kwh.
        if not _value_matches_spec(line, mapped[0]):
            continue
        out.append((alias, m.group(1), detect_edition(rest)))
    return out


# ── File → spec rows ────────────────────────────────────────────────────────
def extract_specs_from_file(path: Path) -> list[dict[str, Any]]:
    meta, body = parse_raw_file(path)
    model_id = infer_model_raw(path)
    if not model_id:
        return []
    model_code = MODEL_LABEL.get(model_id, model_id)
    source_url = meta.get("source_url", "")

    raw_pairs: list[tuple[str, str, str | None]] = []
    raw_pairs.extend(parse_tables(body))
    # value-trên-label (VF8 All New) chạy TRƯỚC để aggregate ưu tiên giá trị đúng
    # khi cùng label bị parse_inline/label_then_values đọc nhầm value bên dưới.
    raw_pairs.extend(parse_value_above_label(body))
    raw_pairs.extend(parse_value_first(body))        # hero card value-first (VF6)
    raw_pairs.extend(parse_inline(body))             # label-first B/C
    raw_pairs.extend(parse_label_then_values(body))  # bảng spec 2 cột (VF6/VF7/VF8)

    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str | None, str]] = set()  # (key, edition) trong file
    for label_norm, value_raw, edition in raw_pairs:
        mapped = lookup_label(label_norm)
        if not mapped:
            continue
        spec_key, spec_unit, category = mapped
        if spec_key not in BASIC_SPECS and spec_key != "dimension_triple":
            # Key ngoài whitelist spec cơ bản → drop (không phải yếu tố mua xe).
            continue
        if spec_key == "dimension_triple":
            for sub_key, sub_val in parse_dimension_triple(value_raw):
                if not sub_val:
                    continue
                k = (sub_key, edition)
                if k in seen:
                    continue
                seen.add(k)
                rows.append(_row(model_code, edition, "dimension", sub_key,
                                 sub_val, "mm", source_url))
            continue
        value = clean_value(spec_key, value_raw)
        if value is None:  # junk (sai format / ngoài sanity range) → drop
            continue
        k = (spec_key, edition)
        if k in seen:
            continue
        seen.add(k)
        # category/unit lấy từ BASIC_SPECS (canonical) — bỏ qua mapped của LABEL_MAP.
        cat, unit = BASIC_SPECS.get(spec_key, (category, spec_unit))
        rows.append(_row(model_code, edition, cat, spec_key, value,
                         unit, source_url))
    return rows


def _row(model_code, edition, category, key, value, unit, source_url) -> dict[str, Any]:
    return {
        "model_code": model_code,
        "version_name": edition,  # None = chung mọi bản
        "version_code": None,
        "spec_category": category,
        "spec_key": key,
        "spec_value": value,
        "spec_unit": unit or "",
        "source_url": source_url,
    }


# ── Crawl4AI brochure extraction ────────────────────────────────────────────
def _llm_label_to_key(label: str, value: str) -> str | None:
    """Map occasional LLM labels back to the strict BASIC_SPECS whitelist."""
    n = norm(label)
    v = norm(value)
    if n in BASIC_SPECS:
        return n
    if n in ("dai x rong x cao", "kich thuoc") and re.search(r"[xX×]", value):
        return "dimension_triple"
    if "chieu dai co so" in n:
        return "wheelbase_mm"
    if "khoang sang gam" in n:
        return "ground_clearance_mm"
    if "cong suat sac" in n and ("dc" in n or "nhanh" in n):
        return "dc_charge_kw"
    if "cong suat toi da" in n or n == "cong suat":
        return "power_kw"
    if "mo men xoan" in n:
        return "torque_nm"
    if "dung luong pin" in n or n == "pack pin":
        return "battery_kwh"
    if "quang duong" in n or n == "pham vi di chuyen":
        return "range_km"
    if "dan dong" in n or "he dan dong" in n:
        return "drivetrain"
    if "so cho ngoi" in n or "so ghe ngoi" in n:
        return "seats"
    # Some PDF layouts put the dimension labels in one combined text block.
    if "dai" in n and "rong" in n and "cao" in n and re.search(r"[xX×]", value):
        return "dimension_triple"
    return None


def _normalize_edition(value: Any) -> str | None:
    if not value:
        return None
    text = str(value).strip().lower()
    aliases = {
        "pluscaptain": "PlusCaptain", "plus": "Plus", "eco": "Eco",
        "tieuchuan": "TieuChuan", "nangcao": "NangCao", "caocap": "CaoCap",
    }
    if text in aliases:
        return aliases[text]
    if text == "base":
        return "Eco"
    return None


def _parse_crawl4ai_content(content: str) -> list[dict[str, Any]]:
    if not content:
        return []
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = data.get("specs", data.get("items", []))
    return data if isinstance(data, list) else []


def _vision_extract_brochure(url: str, model_id: str, schema: dict) -> list[dict[str, Any]]:
    """Fallback for image-only PDFs: render pages and send them to a vision LLM."""
    try:
        import fitz
    except ImportError:
        print("  [vision] PyMuPDF missing; cannot render image-only PDF")
        return []

    response = requests.get(url, timeout=120)
    response.raise_for_status()
    prompt = (
        f"Read these brochure pages for VinFast {model_id}. OCR the page images and "
        "extract only explicit basic vehicle specs. Return JSON object {\"specs\": "
        "[...]} with spec_key, spec_value, edition. Allowed keys: "
        "length_mm, width_mm, height_mm, wheelbase_mm, ground_clearance_mm, "
        "power_kw, torque_nm, drivetrain, battery_kwh, range_km, dc_charge_kw, seats. "
        "For dimensions split length/width/height. Normalize drivetrain to FWD/RWD/AWD. "
        "Use kW, not Hp, and prefer NEDC over WLTP. Never guess."
    )
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    with fitz.open(stream=response.content, filetype="pdf") as document:
        for page in document[:20]:
            pix = page.get_pixmap(matrix=fitz.Matrix(1.2, 1.2), alpha=False)
            image = io.BytesIO(pix.tobytes("jpeg", jpg_quality=70))
            encoded = base64.b64encode(image.getvalue()).decode("ascii")
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
            })

    result = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
            "Content-Type": "application/json",
        },
        json={
            "model": os.environ.get("OPENROUTER_CHAT_MODEL", "openai/gpt-4o-mini"),
            "messages": [{"role": "user", "content": content}],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        },
        timeout=300,
    )
    result.raise_for_status()
    body = result.json()
    answer = body["choices"][0]["message"]["content"]
    return _parse_crawl4ai_content(answer)


BROCHURE_MODEL_ORDER = [
    "VF2", "VF3", "VF5", "VF6", "VF7", "VF8", "VF8NEW", "VF9",
]


def _crawl_brochure_urls() -> list[tuple[str, str]]:
    if not BROCHURE_LINKS.exists():
        return []
    urls: list[str] = []
    for line in BROCHURE_LINKS.read_text(encoding="utf-8").splitlines():
        match = re.search(r"https?://\S+", line.strip())
        if match:
            url = match.group(0).rstrip(")\"'")
            if url not in urls:
                urls.append(url)
    return list(zip(BROCHURE_MODEL_ORDER, urls))


async def _crawl_brochure_specs(urls: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """Crawl brochure PDFs with Crawl4AI and return validated raw spec rows."""
    from crawl4ai import (AsyncWebCrawler, BrowserConfig, CacheMode,
                          CrawlerRunConfig, LLMConfig, LLMExtractionStrategy,
                          PDFContentScrapingStrategy)
    from crawl4ai.processors.pdf import PDFCrawlerStrategy

    schema = {
        "type": "object",
        "properties": {
            "spec_key": {"type": "string", "enum": sorted(BASIC_SPECS)},
            "spec_value": {"type": "string"},
            "edition": {"type": ["string", "null"]},
        },
        "required": ["spec_key", "spec_value", "edition"],
    }
    instruction = (
        "Extract only explicit basic VinFast vehicle specs from this brochure. "
        "Return one item per value using exactly the allowed spec_key enum. "
        "For Dài x Rộng x Cao return three items with length_mm, width_mm, height_mm. "
        "For kW/Hp use the kW token, not Hp. Prefer NEDC over WLTP. "
        "Detect Eco, Plus, PlusCaptain editions from table columns. Never guess."
    )
    provider = os.environ.get("OPENROUTER_CHAT_MODEL", "openai/gpt-4o-mini")
    llm = LLMExtractionStrategy(
        llm_config=LLMConfig(
            provider=provider,
            api_token="env:OPENROUTER_API_KEY",
            base_url="https://openrouter.ai/api/v1",
            temperature=0,
        ),
        schema=schema,
        instruction=instruction,
        input_format="markdown",
        force_json_response=True,
        verbose=False,
    )
    crawl_config = CrawlerRunConfig(
        # Brochure images are decorative in this pass. Disabling image parsing
        # avoids broken embedded image streams and keeps text/table extraction fast.
        scraping_strategy=PDFContentScrapingStrategy(extract_images=False),
        extraction_strategy=llm,
        cache_mode=CacheMode.BYPASS,
        page_timeout=120000,
        verbose=False,
    )
    browser = BrowserConfig(headless=True, verbose=False)
    rows: list[dict[str, Any]] = []
    async with AsyncWebCrawler(crawler_strategy=PDFCrawlerStrategy(), config=browser) as crawler:
        for model_id, url in urls:
            result = await crawler.arun(url, config=crawl_config)
            content = result.extracted_content or ""
            raw_items = _parse_crawl4ai_content(content)
            if not raw_items:
                print(f"  [crawl4ai] {model_id}: no text specs; trying vision OCR")
                try:
                    raw_items = _vision_extract_brochure(url, model_id, schema)
                except Exception as exc:  # noqa: BLE001
                    print(f"  [vision] {model_id} failed: {exc}")
            count = 0
            for item in raw_items:
                if not isinstance(item, dict) or item.get("error"):
                    continue
                key = _llm_label_to_key(str(item.get("spec_key", "")),
                                        str(item.get("spec_value", "")))
                value = str(item.get("spec_value", "")).strip()
                edition = _normalize_edition(item.get("edition"))
                if not key:
                    continue
                if key == "dimension_triple":
                    values = parse_dimension_triple(value)
                else:
                    cleaned = clean_value(key, value)
                    values = [(key, cleaned)] if cleaned else []
                for final_key, final_value in values:
                    cat, unit = BASIC_SPECS[final_key]
                    rows.append(_row(MODEL_LABEL[model_id], edition, cat, final_key,
                                     final_value, unit, url))
                    count += 1
            if count:
                print(f"  [crawl4ai] {model_id}: {count} validated specs from {url}")
            else:
                print(
                    f"  [crawl4ai] {model_id}: brochure has no extractable text; "
                    "keep dat-coc/raw fallback specs"
                )
    return rows


def crawl_brochure_specs() -> list[dict[str, Any]]:
    load_dotenv(REPO_ROOT / ".env")
    if not os.environ.get("OPENROUTER_API_KEY"):
        raise RuntimeError("OPENROUTER_API_KEY is required for --crawl-brochures")
    return asyncio.run(_crawl_brochure_specs(_crawl_brochure_urls()))


# ── Aggregate (union all files) ─────────────────────────────────────────────
def _source_rank(url: str) -> int:
    for i, dom in enumerate(SOURCE_PRIORITY):
        if dom in (url or ""):
            return i
    return len(SOURCE_PRIORITY)


def aggregate(all_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Gộp theo (model_code, version_name, category, spec_key); conflict → prefer
    nguồn rank cao hơn (shop.vinfastauto.com). Rồi collapse: spec y hệt cho mọi
    edition của model → 1 row version_name=None."""
    # group key → list rows (giữ source rank)
    grouped: dict[tuple, list[dict[str, Any]]] = {}
    for r in all_rows:
        gk = (r["model_code"], r["version_name"], r["spec_category"], r["spec_key"])
        grouped.setdefault(gk, []).append(r)

    picked: list[dict[str, Any]] = []
    for gk, rows in grouped.items():
        rows.sort(key=lambda r: _source_rank(r["source_url"]))
        picked.append(rows[0])  # value tốt nhất

    # Collapse: trong 1 model, (category, key, value) giống hết mọi edition → NULL.
    by_model: dict[str, list[dict[str, Any]]] = {}
    for r in picked:
        by_model.setdefault(r["model_code"], []).append(r)

    collapsed: list[dict[str, Any]] = []
    for model, rows in by_model.items():
        # nhóm theo (category, key)
        by_ck: dict[tuple, list[dict[str, Any]]] = {}
        for r in rows:
            by_ck.setdefault((r["spec_category"], r["spec_key"]), []).append(r)
        for (cat, key), rs in by_ck.items():
            editions = [r for r in rs if r["version_name"] is not None]
            nulls = [r for r in rs if r["version_name"] is None]
            if editions:
                vals = {r["spec_value"] for r in editions}
                if len(vals) == 1:
                    # mọi edition cùng value → spec chung mọi bản → 1 row NULL.
                    # (bỏ nulls: row "chung" mâu thuẫn khi editions đã khẳng định
                    #  value chung này — hoặc nulls là junk conflict.)
                    base = dict(editions[0])
                    base["version_name"] = None
                    collapsed.append(base)
                else:
                    # editions khác value → giữ từng edition, bỏ nulls (chung sai).
                    collapsed.extend(editions)
            else:
                # chỉ có row chung (không phân edition) → giữ.
                collapsed.extend(nulls)
    return collapsed


# ── Run ─────────────────────────────────────────────────────────────────────
CSV_FIELDS = ["model_code", "version_name", "version_code", "spec_category",
              "spec_key", "spec_value", "spec_unit", "source_url"]


def run(version: str = "v1", crawl_brochures: bool = False) -> int:
    version_dir = CLEAN_DIR / version
    pg_dir = version_dir / "postgres"
    pg_dir.mkdir(parents=True, exist_ok=True)

    if not RAW_DIR.exists():
        print(f"[parse_specs] raw dir not found: {RAW_DIR}", file=sys.stderr)
        return 1

    all_rows: list[dict[str, Any]] = []
    n_files = 0
    by_model: dict[str, int] = {}
    if crawl_brochures:
        print("[parse_specs] crawling brochure PDFs with Crawl4AI...")
        crawled_rows = crawl_brochure_specs()
        all_rows.extend(crawled_rows)
        for r in crawled_rows:
            by_model[r["model_code"]] = by_model.get(r["model_code"], 0) + 1

    for path in sorted(RAW_DIR.iterdir()):
        if not path.is_file() or path.suffix not in (".txt", ".md"):
            continue
        if path.name == "link_brochure.md":
            continue
        rows = extract_specs_from_file(path)
        if rows:
            n_files += 1
            all_rows.extend(rows)
            for r in rows:
                by_model[r["model_code"]] = by_model.get(r["model_code"], 0) + 1

    final = aggregate(all_rows)

    out_path = pg_dir / "specs.csv"
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, delimiter="|")
        w.writeheader()
        for r in final:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in CSV_FIELDS})

    print(f"[parse_specs] version={version}  files_with_specs={n_files}")
    for mc in sorted(by_model):
        print(f"  {mc}: {by_model[mc]} raw specs")
    print(f"  → {out_path.name}: {len(final)} rows (sau aggregate + collapse)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Trích spec kỹ thuật từ raw → specs.csv")
    ap.add_argument("--version", default="v1", help="Output version folder (default v1)")
    ap.add_argument("--crawl-brochures", action="store_true",
                    help="Crawl PDF brochure URLs with Crawl4AI + LLM extraction")
    args = ap.parse_args()
    return run(args.version, crawl_brochures=args.crawl_brochures)


if __name__ == "__main__":
    sys.exit(main())
