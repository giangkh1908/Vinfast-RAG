#!/usr/bin/env python3
"""
clean_to_jsonl.py — Clean raw crawled files (data/raw/) into intermediate JSONL
following the UC-01 data-format contract.

Source:  data/raw/*.txt   (crawl output: "# Nguồn" header comments + body)
         data/raw/link_brochure.md (brochure URLs, link-only)

Output:  data/clean/<version>/intermediate/<collection>.jsonl
Each line = one chunk:
  { id, collection, vector_version, model_id, edition_id, category,
    section_path, text, text_type, structured, language, tags,
    confidence, source_file, source_url, source_type, fetched_at,
    ingested_at, is_hot }

Rules:
  * Prices (VNĐ) NEVER go into vector text — stripped at clean time and
    extracted to hot rows (Postgres) only from authoritative VinFast pages.
  * Chunking: heading-based first, then sentence-aware split (max_len=400,
    overlap = last complete sentence), khớp cửa sổ embedding ~128 token.
"""

import argparse
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Paths ──────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
CLEAN_DIR = DATA_DIR / "clean"

# ── Canonical mappings ─────────────────────────────────────────────────────
MODEL_ID_MAP = {
    "Products-Car-ECVAN": "ECVAN",
    "Products-Car-FADIL": "FADIL",
    "Products-Car-HerioGreen": "HERIO",
    "Products-Car-LimoGreen": "LIMO",
    "Products-Car-LUX-A": "LUXA",
    "Products-Car-LUX-SA": "LUXSA",
    "Products-Car-MinioGreen": "MINIO",
    "Products-Car-NerioGreen": "NERIO",
    "Products-Car-VF2": "VF2",
    "Products-Car-VF3": "VF3",
    "Products-Car-VF5": "VF5",
    "Products-Car-VF6": "VF6",
    "Products-Car-VF7": "VF7",
    "Products-Car-VF8": "VF8",
    "Products-Car-VF9": "VF9",
    "Products-Car-VFMPV7": "VFMPV7",
    "Products-Car-MPV7": "VFMPV7",
}

EDITION_ID_MAP = {
    "NE3LV": "Eco",
    "NE3MV": "Plus",
    "NE3NV": "PlusCaptain",
    "ND42V": "Eco",
    "ND43V": "Plus",
    "JB10V": "Eco",
    "JB12V": "Plus",
    "JA10V": "Eco",
    "JA12V": "Plus",
    "GA12V": "Eco",
    "GA13V": "Plus",
    "GI10V": "TieuChuan",
    "GI11V": "Plus",
    "TI1CV": "Eco",
    "TI1BV": "Plus",
    "MDS34": "Eco",
    "MDS35": "Plus",
    "TG10V": "TieuChuan",
    "TG11V": "NangCao",
    "TG12V": "CaoCap",
}

MODEL_LABEL = {
    "VF2": "VF 2",
    "VF3": "VF 3",
    "VF5": "VF 5",
    "VF6": "VF 6",
    "VF7": "VF 7",
    "VF8": "VF 8",
    "VF9": "VF 9",
    "VFMPV7": "VF MPV 7",
    "VFE34": "VF e34",
    "ECVAN": "EC Van",
    "FADIL": "Fadil",
    "HERIO": "Herio Green",
    "LIMO": "Limo Green",
    "LUXA": "LUX A",
    "LUXSA": "LUX SA",
    "MINIO": "Minio Green",
    "NERIO": "Nerio Green",
}

# Collection / category routing
COLLECTION_BY_CATEGORY = {
    "thong_so_ky_thuat": "vivu_specs",
    "thong_tin_san_pham": "vivu_product_info",
    "ho_tro_mua_xe": "vivu_faq",
    "chinh_sach_dich_vu": "vivu_policy",
    "dat_lich_bao_duong": "vivu_maintenance",
}

# Edition names xuất hiện trực tiếp trong dat-coc / article
EDITION_KEYWORDS = ["PlusCaptain", "Plus", "Eco", "TieuChuan", "NangCao", "CaoCap", "Base"]

# Danh sách edition theo thứ tự giá tăng dần — dùng để gán edition khi
# dat-coc page không in rõ edition (VF5/VF6/VF8): block rẻ nhất = edition đầu.
MODEL_EDITIONS = {
    "VF2": ["TieuChuan"],
    "VF3": ["Eco", "Plus"],
    "VF5": ["Plus"],
    "VF6": ["Eco", "Plus"],
    "VF7": ["Eco", "Plus", "PlusCaptain"],
    "VF8": ["Eco", "Plus"],
    "VF9": ["Eco", "Plus"],
    "VFMPV7": ["Eco", "Plus"],
}

# Domain chính thống — chỉ những trang này mới được trích giá vào Postgres
AUTHORITATIVE_DOMAINS = {"vinfastauto.com", "shop.vinfastauto.com"}

# ── Helpers ────────────────────────────────────────────────────────────────
def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def no_diacritics(s: str) -> str:
    """Bỏ dấu tiếng Việt → so khớp label/section không phân biệt dấu."""
    return "".join(c for c in unicodedata.normalize("NFD", s)
                  if unicodedata.category(c) != "Mn").replace("đ", "d")


def to_model_id(raw: str) -> str:
    return MODEL_ID_MAP.get(raw, raw.replace("Products-Car-", ""))


def to_edition_id(raw: str) -> str:
    return EDITION_ID_MAP.get(raw, raw)


def get_domain(url: str) -> str:
    m = re.search(r"https?://([^/]+)", url or "")
    return m.group(1).lower() if m else ""


def parse_price(value: Any) -> int | None:
    """Extract integer VND from a price string/number."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        s = value.strip().lower()
        s = s.replace("vnđ", "").replace("vnd", "").replace("đ", "").replace(",", "").strip()
        if s == "" or s == "0":
            return None
        try:
            return int(float(s))
        except ValueError:
            digits = re.sub(r"[^0-9]", "", s)
            if digits:
                return int(digits)
    return None


# ── Raw file parsing ───────────────────────────────────────────────────────
def parse_raw_file(path: Path) -> tuple[dict[str, Any], str]:
    """Parse a crawl output file: header comments (# Nguồn / # Crawl lúc /
    # Loại / # Selector) + body after the '====' separator."""
    text = path.read_text(encoding="utf-8", errors="replace")
    meta = {"source_url": "", "fetched_at": "", "source_type": "", "selector": ""}
    lines = text.splitlines()
    body_start = 0
    for i, line in enumerate(lines):
        if line.startswith("# Nguồn:"):
            meta["source_url"] = line.split(":", 1)[1].strip()
        elif line.startswith("# Crawl lúc:"):
            meta["fetched_at"] = line.split(":", 1)[1].strip()
        elif line.startswith("# Loại:"):
            meta["source_type"] = line.split(":", 1)[1].strip().lower()
        elif line.startswith("# Selector:"):
            meta["selector"] = line.split(":", 1)[1].strip()
        elif re.match(r"^={5,}$", line.strip()):
            body_start = i + 1
            break
    return meta, "\n".join(lines[body_start:])


def infer_model_raw(path: Path) -> str | None:
    """Infer model_id from raw filename (vf3, vf5, vf8-the-all-new, mpv7, e34...)."""
    name = re.sub(r"[^a-z0-9]", "", path.stem.lower())
    # thứ tự quan trọng: e34 trước vf3, mpv7 trước vf7
    for key, model in [("vfe34", "VFE34"), ("mpv7", "VFMPV7"),
                       ("vf2", "VF2"), ("vf3", "VF3"), ("vf5", "VF5"),
                       ("vf6", "VF6"), ("vf7", "VF7"), ("vf8", "VF8"), ("vf9", "VF9")]:
        if key in name:
            return model
    return None


def classify_raw(path: Path, meta: dict[str, Any]) -> dict[str, Any] | None:
    """Route a raw file to collection/category/model/confidence + authoritative."""
    name = path.stem.lower()
    url = meta.get("source_url", "")
    domain = get_domain(url)
    authoritative = domain in AUTHORITATIVE_DOMAINS
    stype = meta.get("source_type", "")
    model = infer_model_raw(path)

    def route(collection, category, confidence, kind):
        return {"collection": collection, "category": category,
                "model_id": model, "confidence": confidence,
                "authoritative": authoritative, "kind": kind}

    # Official VinFast pages
    if authoritative:
        if "dat-coc" in url:
            return route("vivu_product_info", "thong_tin_san_pham", 1.0, "dat-coc")
        if "dich-vu-bao-duong" in url:
            return route("vivu_maintenance", "dat_lich_bao_duong", 1.0, "service")
        if any(k in url for k in ("dich-vu-pin", "dich-vu-sua-chua",
                                  "chinh-sach-bao-hanh", "thong-tin-cuu-ho",
                                  "ve-chung-toi", "chinh-sach")):
            return route("vivu_policy", "chinh_sach_dich_vu", 1.0, "policy")
        return route("vivu_product_info", "thong_tin_san_pham", 0.9, "other")

    # PDF extracts: sổ bảo hành / brochure (warranty & service terms)
    if stype == "pdf":
        return route("vivu_policy", "chinh_sach_dich_vu", 0.9, "pdf-manual")

    # Web articles / dealer pages
    if any(k in name for k in ("so-sanh", "bang-doi-chieu")):
        return route("vivu_specs", "thong_so_ky_thuat", 0.8, "comparison")
    if any(k in name for k in ("thong-so-ky-thuat", "thong-so-")):
        return route("vivu_specs", "thong_so_ky_thuat", 0.8, "specs-article")
    return route("vivu_product_info", "thong_tin_san_pham", 0.7, "article")


# ── Cleaning ───────────────────────────────────────────────────────────────
NOISE_PATTERNS = [
    r"^Đăng nhập\s*/\s*Đăng ký$",
    r"^Banner top bar$",
    r"^Google tag \(gtag\.js\)$",
    r"^End Navigation$",
    r"^END BREADCRUMB$",
    r"^1\.\s*TRANG CHỦ\s*$",
    r"^\s*[0-9]+\.\s*(?:TRANG CHỦ|Trang chủ|Tin tức|Cộng đồng)\s*$",
    r"^Tìm xe VinFast",
    r"^Nhập ít nhất 2 ký tự",
    r"^Chọn địa chỉ nhận hàng$",
    r"^Chọn Tỉnh/Thành",
    r"^Thay đổi địa chỉ khác$",
    r"^Hotline\s*\d",
    r"^Quên mật khẩu\?$",
    r"^Share$",
    r"^\s*star \| Đã bán \d+$",
    r"^\s*\* \* \*\s*$",
    r"^\s*---\s*$",
    r"^\s*#+$",
    r"^\s*\[.*\]\(.*\)\s*$",  # bare link lines
    r"^\s*!\[.*\]\(.*\)\s*$",  # bare image lines
    r"^\s*Đặt lịch\s*$",
    r"^\s*Đăng ký\s*$",
    # HTML / template artifacts
    r"^\s*\[if\s+[^\]]*\]\s*$",
    r"^\s*<!\[endif\]",
    r"^\s*\[endif\]\s*$",
    r"^\s*end\s+\w+\s+category\s*$",
    r"^\s*end\s+title\s*$",
    r"^\s*Banner\s+top\s+bar\s*$",
    r"^\s*not found\s*$",
    r"^\s*Không tìm thấy kết quả phù hợp\s*$",
    r"^\s*Hãy thử lại với từ khoá khác\s*$",
    r"^\s*Chọn\s+\w+\s*$",
    # Contact / phone / date-only lines
    r"^[\d.\s]{9,}$",                     # phone number
    r"^\d{1,2}\s+\d{2}-\d{4}$",           # "30 07-2026"
    r"^\s*[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\s*$",  # email
    r"^\s*Xin hãy gọi ngay.*$",
]
NOISE_RE = [re.compile(p, flags=re.IGNORECASE) for p in NOISE_PATTERNS]

# Unicode private-use (PUA) — ký tự lạ từ PDF/WingDings như  (bullet)
PUA_RE = re.compile(r"[-]")
HTML_COMMENT_RE = re.compile(r"<!\s*\[[^\]]*\]>|<![^>]{0,80}>")

MONEY_RE = re.compile(
    r"\b(?:\d{1,3}(?:[.,]\d{3})+|\d+)(?:\s*(?:triệu|tr|tỷ|nghìn|đồng|VNĐ|VND|\bđ\b))?",
    flags=re.IGNORECASE,
)
PRICE_KEYWORDS = [
    "giá bán", "giá niêm yết", "giá ưu đãi", "giá xe", "triệu đồng", "vnđ",
    "đặt cọc", "cọc", "lăn bánh",
]


def strip_markdown_images(line: str) -> str:
    return re.sub(r"!\[([^\]]*)\]\([^)]+\)", lambda m: m.group(1) if m.group(1) else "", line)


def strip_html_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text)


def clean_line(line: str) -> str:
    line = strip_markdown_images(line)
    line = strip_html_tags(line)
    line = HTML_COMMENT_RE.sub(" ", line)
    line = PUA_RE.sub("", line)
    line = line.replace("&amp;", "&").replace("&nbsp;", " ")
    line = re.sub(r"\s+", " ", line).strip()
    for pat in NOISE_RE:
        if pat.match(line):
            return ""
    return line


def remove_money_sentences(paragraphs: list[str]) -> list[str]:
    """Drop paragraphs dominated by price info (price keyword + money number)."""
    cleaned = []
    money_re = re.compile(
        r"(?:\d{1,3}(?:[.,]\d{3})+|\d{6,})\s*(?:triệu|tr|tỷ|nghìn|đồng|VNĐ|VND|\bđ\b)|"
        r"(?:triệu|tr|tỷ|nghìn|đồng|VNĐ|VND|\bđ\b)\s*(?:\d{1,3}(?:[.,]\d{3})+|\d+)",
        flags=re.IGNORECASE,
    )
    for p in paragraphs:
        lowered = p.lower()
        has_price_kw = any(kw in lowered for kw in PRICE_KEYWORDS)
        money_hits = len(money_re.findall(p))
        if has_price_kw and money_hits >= 1:
            continue
        cleaned.append(p)
    return cleaned


def strip_price_spans(text: str) -> str:
    """Remove price statements (amount + currency unit) that leaked into text.

    Handles amount and unit split across lines (e.g. "613.700.000\\n\\nVNĐ\\*")
    which remove_money_sentences misses because it checks per-paragraph.
    Also drops leftover standalone price phrases such as "Giá bán từ".
    """
    amount = r"\d{1,3}(?:[.,]\d{3})+(?:\d{2})?|\d{6,}"
    unit = r"(?:triệu|tr\b|tỷ|nghìn|đồng|VNĐ|VND|\bđ\b)"
    marker = r"(?:\\?\*+)?"
    span_re = re.compile(
        rf"(?:{amount})\s*{marker}\s*(?:{unit}){marker}"
        rf"|(?:{unit})\s*{marker}\s*(?:{amount}){marker}",
        flags=re.IGNORECASE,
    )
    text = span_re.sub("", text)
    text = re.sub(
        r"(?im)^[ \t]*(?:"
        r"\d{1,3}(?:[.,]\d{3})+(?:\d{2})?|\d{6,}|"
        r"(?:triệu|tr\b|tỷ|nghìn|đồng|VNĐ|VND|\bđ\b)\\?\*+|"
        r"(?:giá\s+(?:bán|niêm\s*yết|ưu\s*đãi|x)|đặt\s*cọc|lăn\s*bánh)"
        r"\s*(?:từ|cho|và)?[^a-zà-ỹ]*"
        r")[ \t]*$",
        "",
        text,
    )
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def normalize_numbers(text: str) -> str:
    """Unify numeric formatting: '5.119 x 2.254' -> '5119 × 2254' (dimensions)."""
    text = re.sub(
        r"(\d{1,3}(?:[.,]\d{3}){1,2})\s*[xX×]\s*(\d{1,3}(?:[.,]\d{3}){1,2})\s*[xX×]?\s*(\d{1,3}(?:[.,]\d{3}){1,2})?",
        lambda m: " × ".join(p.replace(".", "").replace(",", "") for p in m.groups() if p),
        text,
    )
    return text


def fix_pdf_spacing(text: str) -> str:
    """PDF text extract đôi khi cách một ký tự giữa các chữ (chỉ dòng Mục lục).

    Fix theo dòng: nếu >50% token chỉ có 1 ký tự -> ghép lại thành từ.
    """
    out = []
    for line in text.splitlines():
        tokens = line.split()
        if len(tokens) >= 3 and sum(len(t) == 1 for t in tokens) / len(tokens) > 0.5:
            out.append("".join(tokens))
        else:
            out.append(line)
    return "\n".join(out)


# ── Price extraction (authoritative dat-coc only) ──────────────────────────
def parse_edition_from_label(label: str) -> str | None:
    for kw in EDITION_KEYWORDS:
        if kw.lower() in label.lower():
            return kw
    return None


def extract_dat_coc_prices(text: str) -> list[dict[str, Any]]:
    """Extract (label, promo, list) price blocks from an official dat-coc page.

    Handles nhiều cấu trúc thực tế:
      VF 3 Eco / Giá bán từ / 270.750.000 VNĐ* / 285.000.000 VNĐ
      VF 7 Plus / - **Giá bán từ**: 788.500.000 VNĐ*
      Giá bán từ: 712.500.000 VNĐ* 750.000.000 VNĐ
      ### Giá bán VF 5 / 471.200.000 VNĐ* / 496.000.000 VNĐ
    """
    text = text.replace("**", "")
    rows: list[dict[str, Any]] = []
    # Pattern 1: label + (Giá bán từ) + promo VNĐ* + list VNĐ  (multi-line)
    pat1 = re.compile(
        r"(?:([^\n]{2,35})\n)?"
        r"(?:[-*]?\s*Giá\s*bán(?: từ)?:?\s*\n?\s*)?"
        r"([\d.,]+)\s*VNĐ\*?\s*\n\s*([\d.,]+)\s*VNĐ",
        flags=re.IGNORECASE,
    )
    for m in pat1.finditer(text):
        rows.append({"label": (m.group(1) or "").strip().strip("-* "),
                     "promo": m.group(2), "list": m.group(3)})
    # Pattern 2: inline "Giá bán từ: A VNĐ* B VNĐ" trên cùng dòng
    pat2 = re.compile(
        r"(?:([^\n]{2,35})\n)?"
        r"(?:[-*]?\s*Giá\s*bán(?: từ)?:?\s*)"
        r"([\d.,]+)\s*VNĐ\*?\s+([\d.,]+)\s*VNĐ",
        flags=re.IGNORECASE,
    )
    for m in pat2.finditer(text):
        rows.append({"label": (m.group(1) or "").strip().strip("-* "),
                     "promo": m.group(2), "list": m.group(3)})
    # Pattern 3: bold "- **Giá bán từ**: A VNĐ*" (promo only, vf7) — amount CÙNG DÒNG.
    # [ \t]* (không \s*) để không qua dòng mới; lookahead tránh trùng inline 2 giá (pat2).
    pat3 = re.compile(
        r"(?:([^\n]{2,35})\n)?"
        r"-?\s*Giá\s*bán(?: từ)?:[ \t]*([\d.,]+)\s*VNĐ\*?(?!\s+[\d.,]+\s*VNĐ)",
        flags=re.IGNORECASE,
    )
    seen = set()
    for m in pat3.finditer(text):
        key = (m.group(2), m.start())
        if key in seen:
            continue
        seen.add(key)
        rows.append({"label": (m.group(1) or "").strip().strip("-* "),
                     "promo": m.group(2), "list": m.group(2)})
    # Dedupe rows by (promo, list)
    uniq: list[dict[str, Any]] = []
    seen_keys = set()
    for r in rows:
        k = (r["promo"], r["list"])
        if k in seen_keys:
            continue
        # Drop block promo==list spurious (pat3 trùng với block thật 2 giá cùng promo)
        if r["promo"] == r["list"]:
            if any(o["promo"] == r["promo"] and o["list"] != r["promo"] for o in rows):
                continue
        seen_keys.add(k)
        uniq.append(r)
    return uniq


def prices_to_hot_rows(prices: list[dict[str, Any]], model_id: str | None,
                       meta: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert extracted prices to hot rows (edition + price_list schema).

    Edition được gán theo thứ tự giá tăng dần (block rẻ nhất = edition đầu của
    MODEL_EDITIONS) — dat-coc page thường không in rõ edition.
    """
    if not model_id:
        return []
    editions = MODEL_EDITIONS.get(model_id, ["TieuChuan"])
    # Sắp theo list price tăng dần (fallback promo nếu list trùng)
    def price_key(p: dict[str, Any]) -> int:
        return parse_price(p.get("list")) or parse_price(p.get("promo")) or 0
    blocks = sorted(prices, key=price_key)

    rows = []
    for i, p in enumerate(blocks):
        edition_id = editions[i] if i < len(editions) else "TieuChuan"
        list_vnd = parse_price(p.get("list"))
        promo_vnd = parse_price(p.get("promo"))
        rows.append({
            "model_id": model_id,
            "edition_id": edition_id,
            "model_label": MODEL_LABEL.get(model_id, model_id),
            "edition_label": edition_id,
            "year_range": "2026",
            "is_active": True,
            "price_list_vnd": list_vnd,
            "price_promo_vnd": promo_vnd if promo_vnd and promo_vnd != list_vnd else None,
            "promo_label": "Ưu đãi đặt cọc 2026" if promo_vnd and promo_vnd != list_vnd else "",
            "vat_included": True,
            "battery_included": True,
            "valid_from": "2026-07-01",
            "valid_to": None,
            "updated_at": now_iso(),
            "source_url": meta.get("source_url", ""),
        })
    return rows


# ── Text → chunks ──────────────────────────────────────────────────────────
def chunks_from_text(text: str, meta: dict[str, Any], cls: dict[str, Any],
                     path: Path) -> list[dict[str, Any]]:
    """Clean raw text + split by headings (and size) into vector chunks."""
    # Loại bỏ dòng noise, nhóm theo heading
    lines = []
    for line in text.splitlines():
        if line.strip().startswith(">"):
            continue
        cl = clean_line(line)
        if cl == "" or cl in {"---", "", "*", "#"}:
            continue
        lines.append(line)

    # Bỏ dòng lặp lại >=3 lần (nav/sidebar lặp) — giữ lần đầu
    from collections import Counter
    line_counts = Counter(clean_line(l) for l in lines)
    seen_dup: set[str] = set()
    deduped: list[str] = []
    for l in lines:
        key = clean_line(l)
        if line_counts.get(key, 0) >= 3:
            if key in seen_dup:
                continue
            seen_dup.add(key)
        deduped.append(l)
    lines = deduped

    chunks: list[dict[str, Any]] = []
    section_stack: list[tuple[int, str]] = []
    buf: list[str] = []

    def current_section_title() -> str:
        return section_stack[-1][1] if section_stack else ""

    def emit() -> None:
        if not buf:
            return
        paragraphs = [clean_line(line) for line in buf]
        paragraphs = [p for p in paragraphs if p]
        paragraphs = remove_money_sentences(paragraphs)
        if not paragraphs:
            buf.clear()
            return

        # Merge fragment ngắn
        merged, carry = [], ""
        for p in paragraphs:
            if len(p) < 25 and not any(c in p for c in (".", ":", ";", "-", "|")):
                carry = (carry + " " + p).strip() if carry else p
            else:
                if carry:
                    merged.append(carry)
                    carry = ""
                merged.append(p)
        if carry:
            merged.append(carry)

        body_text = "\n\n".join(merged)
        body_text = normalize_numbers(body_text)
        body_text = strip_price_spans(body_text)
        if len(body_text) < 20:
            buf.clear()
            return

        model_id = cls.get("model_id")
        section_title = current_section_title()
        section_path = [cls.get("category", "thong_tin_san_pham")]
        if section_title:
            section_path.append(section_title)

        text_type = "prose"
        if "|" in body_text and "---" in body_text:
            text_type = "table"
        elif all(line.strip().startswith(("- ", "1. ", "2. ", "3. ", "4. ", "5. ", "6. ", "7. ", "8. ", "9. ")) for line in body_text.splitlines() if line.strip()):
            text_type = "list"
        elif "Q:" in body_text and "A:" in body_text:
            text_type = "qa_pair"

        collection = COLLECTION_BY_CATEGORY.get(cls.get("category", ""), "vivu_product_info")

        chunk = {
            "id": "",
            "collection": collection,
            "vector_version": None,
            "model_id": model_id,
            "edition_id": None,
            "category": cls.get("category", "thong_tin_san_pham"),
            "section_path": section_path,
            "text": body_text,
            "text_type": text_type,
            "structured": {},
            "language": "vi",
            "tags": [cls.get("category", "").replace("_", "")] + ([model_id.lower()] if model_id else []),
            "confidence": cls.get("confidence", 0.7),
            "source_file": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
            "source_url": meta.get("source_url", ""),
            "source_type": f"raw_{meta.get('source_type', 'txt')}",
            "fetched_at": meta.get("fetched_at", ""),
            "ingested_at": "",
            "is_hot": False,
        }
        chunks.append(chunk)
        buf.clear()

    for raw in lines:
        m = re.match(r"^(#{1,6})\s+(.*)", raw.strip())
        if m:
            emit()
            level = len(m.group(1))
            title = clean_line(m.group(2))
            while section_stack and section_stack[-1][0] >= level:
                section_stack.pop()
            section_stack.append((level, title))
            continue
        buf.append(raw)
    emit()

    return chunks


# ── Sentence-aware chunking (max_len=400, overlap last sentence) ───────────
def split_sentences(text: str, max_len: int) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    sents: list[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        # Sub-split rất dài không có dấu câu (specs key:value nối bằng "; ")
        if len(p) > max_len and "; " in p:
            sents.extend(s.strip() for s in p.split("; ") if s.strip())
        else:
            sents.append(p)
    return sents


def split_long_line(s: str, max_len: int, overlap: int = 80) -> list[str]:
    """Fallback: 1 câu dài không có biên câu -> cắt theo ký tự ở biên câu/"; "/space."""
    pieces: list[str] = []
    start, n = 0, len(s)
    while start < n:
        end = min(start + max_len, n)
        if end < n:
            for sep in (". ", "; ", " "):
                cut = s.rfind(sep, start, end)
                if cut > start + max_len // 2:
                    end = cut + len(sep)
                    break
        piece = s[start:end].strip()
        if piece:
            pieces.append(piece)
        if end < n:
            next_start = end - overlap
            sp = s.find(" ", next_start)
            if 0 <= sp < n:
                next_start = sp + 1
            start = max(next_start, start + 1)
        else:
            start = n
    return pieces


def split_table(text: str, max_len: int) -> list[str]:
    """Bảng markdown: lặp header ở mỗi mảnh, mảnh ≤ max_len."""
    lines = text.split("\n")
    header, body = lines[0:2], lines[2:]
    pieces, cur, cur_len = [], [], 0
    for line in body:
        add = len(line) + 1
        if cur and cur_len + add > max_len:
            pieces.append("\n".join(header + cur).strip())
            cur, cur_len = [], 0
        cur.append(line)
        cur_len += add
    if cur:
        pieces.append("\n".join(header + cur).strip())
    return [p for p in pieces if p.strip()] or [text]


def split_by_sentences(text: str, max_len: int = 400) -> list[str]:
    """Sentence-aware split: gom câu tới max_len, cắt ở biên câu,
    overlap = câu cuối hoàn chỉnh của mảnh trước."""
    sents = split_sentences(text, max_len)
    pieces, buf, last = [], "", ""
    for s in sents:
        if buf and len(buf) + 1 + len(s) > max_len:
            pieces.append(buf.strip())
            if last and len(last) + 1 + len(s) <= max_len:
                buf = last + " " + s
            else:
                buf = s
        else:
            buf = (buf + " " + s) if buf else s
        last = s
    if buf:
        pieces.append(buf.strip())
    # hard fallback: câu đơn vẫn > max_len (không có biên câu/"; ") -> cắt ký tự
    final: list[str] = []
    for p in pieces:
        if len(p) > max_len:
            final.extend(split_long_line(p, max_len))
        else:
            final.append(p)
    return [p for p in final if len(p.strip()) >= 20]


def apply_chunking(chunks: list[dict[str, Any]], max_len: int = 400) -> list[dict[str, Any]]:
    """Chunk > max_len -> cắt theo câu (bảng thì lặp header). Giữ metadata gốc."""
    out: list[dict[str, Any]] = []
    for chunk in chunks:
        if len(chunk["text"]) <= max_len:
            out.append(chunk)
            continue
        lines = chunk["text"].split("\n")
        if lines and lines[0].lstrip().startswith("|") and len(lines) >= 2 \
                and lines[1].strip().startswith("|") and "---" in lines[1]:
            pieces = split_table(chunk["text"], max_len)
        else:
            pieces = split_by_sentences(chunk["text"], max_len)
        for p in pieces:
            out.append({**chunk, "text": p})
    return out


# ── Link-only (brochure URLs) ──────────────────────────────────────────────
# Mỗi dòng trong `link_brochure.md` có format `<url> (<model_label>)`,
# ví dụ: `https://.../vf634chxm5b.pdf (vf6)` — label để phân loại theo model.
_BROCHURE_LABEL_RE = re.compile(r"\(([a-z0-9\-]+)\)\s*$", re.I)
_BROCHURE_LABEL_TO_MODEL = {
    "vf2": "VF2", "vf3": "VF3", "vf5": "VF5", "vf6": "VF6",
    "vf7": "VF7", "vf8": "VF8", "vf8-the-new": "VF8",
    "vf9": "VF9",
}


def link_only_files() -> dict[str, list[str]]:
    result: dict[str, list[str]] = {
        "brochure_urls": [],
        "brochure_by_model": {},
        "showroom_urls": [],
        "promotion_urls": [],
        "roadside_cost_urls": [],
    }
    link_file = RAW_DIR / "link_brochure.md"
    if link_file.exists():
        txt = link_file.read_text(encoding="utf-8")
        urls = [u.strip().rstrip(')"') for u in re.findall(r"https?://\S+", txt)]
        result["brochure_urls"] = [u for u in urls if u]

        by_model: dict[str, list[str]] = {}
        for line in txt.splitlines():
            line = line.strip()
            m = _BROCHURE_LABEL_RE.search(line)
            if not m:
                continue
            model = _BROCHURE_LABEL_TO_MODEL.get(m.group(1).lower())
            if not model:
                continue
            url = line[: m.start()].strip().rstrip(')"')
            if url and url not in by_model.setdefault(model, []):
                by_model[model].append(url)
        result["brochure_by_model"] = by_model
    return result


# ── Run / Main ──────────────────────────────────────────────────────────────
def run(version: str = "v1", max_len: int = 400) -> int:
    """Clean raw -> intermediate JSONL. Trả 0 nếu OK, 1 nếu lỗi."""
    version_dir = CLEAN_DIR / version
    intermediate_dir = version_dir / "intermediate"
    intermediate_dir.mkdir(parents=True, exist_ok=True)

    all_vector: list[dict[str, Any]] = []
    all_hot: list[dict[str, Any]] = []
    ingested_at = now_iso()

    if not RAW_DIR.exists():
        print(f"[clean_to_jsonl] raw dir not found: {RAW_DIR}", file=sys.stderr)
        return 1

    n_files = 0
    for path in sorted(RAW_DIR.iterdir()):
        if not path.is_file():
            continue
        if path.suffix not in (".txt", ".md") or path.name == "link_brochure.md":
            continue
        meta, body = parse_raw_file(path)
        cls = classify_raw(path, meta)
        if cls is None:
            continue
        n_files += 1

        if meta.get("source_type") == "pdf":
            body = fix_pdf_spacing(body)

        chunks = chunks_from_text(body, meta, cls, path)
        all_vector.extend(chunks)

        # Giá chỉ từ trang dat-coc chính thống
        if cls["kind"] == "dat-coc" and cls["authoritative"]:
            prices = extract_dat_coc_prices(body)
            hot_rows = prices_to_hot_rows(prices, cls.get("model_id"), meta)
            all_hot.extend(hot_rows)
            print(f"  [dat-coc] {path.stem}: {len(prices)} price blocks -> {len(hot_rows)} hot rows")

    for c in all_vector:
        c["vector_version"] = version
        c["ingested_at"] = ingested_at
        if not c.get("fetched_at"):
            c["fetched_at"] = ingested_at

    before = len(all_vector)
    all_vector = apply_chunking(all_vector, max_len=max_len)
    print(f"  chunking: {before} -> {len(all_vector)} chunks (max_len={max_len})")

    # Bỏ spec cấu trúc khỏi vector — spec số liệu giờ ở PostgreSQL `car_specs`
    # (retriever query SQL chính xác, tránh nhầm Eco/Plus khi embed na ná nhau).
    # 3 điều kiện drop:
    #   (a) section_path có tiêu đề section == "thông số kỹ thuật" (section spec của
    #       dat-coc — text_type có thể là prose do flatten "Động cơ 01 Motor...").
    #   (b) collection == vivu_specs VÀ text_type in {table, list, key_value}
    #       (bảng spec so-sanh — chỉ vivu_specs chứa spec; bảng ở collection khác
    #       như vivu_policy là điều khoản, KHÔNG drop).
    #   (c) content-based: chunk ở {vivu_specs, vivu_product_info} có ≥4 ký tự '|' VÀ
    #       chứa label spec (công suất / mô men / pin / quãng đường / tải trọng...).
    #       Bắt spec-table pipe-delimited bị gán nhãn text_type=prose do chunk-split
    #       mất dòng `---` (detector '|'+---' không nhận). Ngưỡng pipe bảo vệ prose
    #       mô tả ("VF 8 có công suất 150 kW" — 0 pipe → giữ).
    def _is_spec_section(chunk: dict[str, Any]) -> bool:
        for sp in chunk.get("section_path", []):
            if no_diacritics(sp).lower().replace(" ", "") == "thongsokythuat":
                return True
        return False

    _SPEC_LABELS = (
        "cong suat", "mo men", "mo-men", "dung luong pin", "loai pin",
        "quang duong", "tai trong", "trong luong", "chieu dai co so",
        "chieu dai", "chieu rong", "chieu cao", "khoang sang", "co so",
        "toc do toi da", "tang toc", "so cho ngoi", "cho ngoi",
        "dan dong", "he thong treo", "treo truoc", "treo sau",
        "thoi gian nap", "sac day", "sac nhanh", "khoang chua hanh ly",
    )

    def _is_spec_table(chunk: dict[str, Any]) -> bool:
        if chunk.get("collection") not in ("vivu_specs", "vivu_product_info"):
            return False
        text = chunk.get("text", "") or ""
        if text.count("|") < 4:
            return False
        low = no_diacritics(text).lower()
        return any(lbl in low for lbl in _SPEC_LABELS)

    pre = len(all_vector)
    n_section = 0
    n_table = 0
    n_spec_table = 0
    kept: list[dict[str, Any]] = []
    for c in all_vector:
        if _is_spec_section(c):
            n_section += 1
            continue
        if c.get("collection") == "vivu_specs" \
                and c.get("text_type") in {"table", "list", "key_value"}:
            n_table += 1
            continue
        if _is_spec_table(c):
            n_spec_table += 1
            continue
        kept.append(c)
    all_vector = kept
    print(f"  dropped spec chunks: {n_section} (section) + {n_table} (vivu_specs table/list) "
          f"+ {n_spec_table} (spec-table pipe-delimited) | {pre} -> {len(all_vector)}")

    # Write intermediate
    with (intermediate_dir / "vector.jsonl").open("w", encoding="utf-8") as f:
        for c in all_vector:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    with (intermediate_dir / "hot.jsonl").open("w", encoding="utf-8") as f:
        for h in all_hot:
            f.write(json.dumps(h, ensure_ascii=False) + "\n")

    link_only = link_only_files()
    (intermediate_dir / "link_only.json").write_text(
        json.dumps(link_only, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[clean_to_jsonl] version={version}, files={n_files}")
    print(f"  vector chunks: {len(all_vector)}")
    print(f"  hot rows:      {len(all_hot)}")
    print(f"  brochure urls: {len(link_only['brochure_urls'])}")
    print(f"  output dir:    {intermediate_dir}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Clean raw crawled files into intermediate JSONL.")
    ap.add_argument("--version", default="v1", help="Output version folder (default: v1)")
    ap.add_argument("--max-len", type=int, default=400,
                    help="Chunk max length in chars (embedding window ~400 chars)")
    args = ap.parse_args()
    return run(args.version, args.max_len)


if __name__ == "__main__":
    sys.exit(main())
