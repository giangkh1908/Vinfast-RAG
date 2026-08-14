#!/usr/bin/env python3
"""
noise_patterns.py — Lọc noise (rác) từ raw text: theo dòng, theo đoạn, theo PDF.

Tách từ clean_to_jsonl.py — các hàm ở đây KHÔNG biết gì về chunk/collection,
chỉ xử lý text thuần:

  - clean_line / NOISE_PATTERNS      lọc dòng rác (nav, form, contact, HTML...)
  - remove_money_sentences / strip_price_spans   loại giá tiền khỏi text
  - normalize_numbers / fix_pdf_spacing          chuẩn hóa số, khoảng cách PDF
  - clean_pdf_prose                  làm sạch prose từ brochure PDF (brochure/manual)
"""

import re

from scripts.clean_data.spec_common import no_diacritics

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

# Page marker từ crawl PDF: --- Trang N ---
PAGE_MARKER_RE = re.compile(r"---\s*Trang\s*(\d+)\s*---")

# Unicode private-use (PUA) — ký tự lạ từ PDF/WingDings như U+E000 (bullet).
# Không dùng raw string: cần escape \u thật sự.
PUA_RE = re.compile("[\ue000-\uf8ff]")
HTML_COMMENT_RE = re.compile(r"<!\s*\[[^\]]*\]>|<![^>]{0,80}>")

PRICE_KEYWORDS = [
    "giá bán", "giá niêm yết", "giá ưu đãi", "giá xe", "triệu đồng", "vnđ",
    "đặt cọc", "cọc", "lăn bánh",
]

# PDF-specific noise patterns (từ brochure PDF text-extract)
DISCLAIMER_FULL = (
    "Hình ảnh mang tính chất minh họa và có thể khác so với xe thực tế. "
    "Tính năng, đặc điểm, thông số kỹ thuật có thể thay đổi mà không thông báo trước."
)
DISCLAIMER_PREFIX = "Hình ảnh mang tính chất minh họa"
DISCLAIMER_PHRASES = [
    "mot so tinh nang se chua co san",
    "chua duoc kich hoat tai thoi diem giao xe",
    "se duoc cap nhat phan mem tu xa",
    "quang duong di chuyen duoc tinh toan dua tren",
    "quang duong di chuyen thuc te co the giam",
    "phu thuoc vao toc do lai xe, nhiet do, dia hinh",
    "de dam bao an toan, toi uu tuoi tho",
    "khuyen cao nguoi su dung cac dong xe dien",
    "chi nen su dung pin chinh hang",
]
FOOTNOTE_RE = re.compile(r"^\s*\*{1,2}\s*(?:Phiên bản).*$", flags=re.IGNORECASE)
FOOTNOTE_PAREN_RE = re.compile(r"^\s*\(\*\)\s*.*$")
PAGE_NUM_RE = re.compile(r"^\s*(\d{1,2})\s*$")
SPEC_SHEET_RE = re.compile(
    r"^(thông số kỹ thuật|kích thước|màn hình và kết nối|tính năng điều khiển thông minh)",
    flags=re.IGNORECASE,
)
TABLE_HEADER_RESIDUE_RE = re.compile(
    r"^(kích thước|tính năng|điều khiển thông minh)\s+vf\s+\d+\s+(eco|plus)",
    flags=re.IGNORECASE,
)


def strip_markdown_images(line: str) -> str:
    return re.sub(r"!\[([^\]]*)\]\([^)]+\)", lambda m: m.group(1) if m.group(1) else "", line)


def strip_html_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text)


def clean_line(line: str) -> str:
    """Clean 1 dòng: bỏ markdown-img/html/comment/PUA, gom space, drop nếu khớp noise."""
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
        r"(?:\d{1,3}(?:[.,]\d{3})+|\d{6,})\s*(?:triệu|tr\b|tỷ|nghìn|đồng|VNĐ|VND|\bđ\b)|"
        r"(?:triệu|tr\b|tỷ|nghìn|đồng|VNĐ|VND|\bđ\b)\s*(?:\d{1,3}(?:[.,]\d{3})+|\d+)",
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

    Handles amount and unit split across lines (e.g. "613.700.000\n\nVNĐ\*")
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


# ── PDF-specific cleaning (brochure / manual prose) ───────────────────────
def _is_disclaimer(line: str) -> bool:
    """True nếu dòng là disclaimer hoặc một phần của disclaimer (PDF brochure)."""
    line = line.strip()
    if not line:
        return False
    line_nd = no_diacritics(line)

    if line == DISCLAIMER_FULL or line.startswith(DISCLAIMER_PREFIX):
        return True
    if "thông số kỹ thuật" in line.lower() and "có thể thay đổi" in line.lower():
        return True
    if "khác so với xe thực tế" in line.lower():
        return True
    for phrase in DISCLAIMER_PHRASES:
        if phrase in line_nd:
            return True
    if "hinh anh mang tinh chat minh hoa" in line_nd:
        return True
    if "thong so ky thuat" in line_nd and "co the thay doi" in line_nd:
        return True
    return False


def _is_page_number(line: str) -> bool:
    """True nếu dòng chỉ là số trang PDF (1-2 chữ số, không trong table)."""
    if line.strip().startswith("|"):
        return False
    m = PAGE_NUM_RE.match(line.strip())
    if not m:
        return False
    num = int(m.group(1))
    if num > 60:
        return False
    return True


def _is_footnote(line: str) -> bool:
    """True nếu dòng là footnote PDF (*Phiên bản, (**) ...)."""
    return bool(FOOTNOTE_RE.match(line.strip())
                or FOOTNOTE_PAREN_RE.match(line.strip()))


def clean_pdf_prose(text: str) -> str:
    """Clean PDF prose: bỏ disclaimer, số trang, footnote, spec-sheet residue.

    Giữ nguyên pipe-table rows (specs) — chúng sẽ bị lọc ở bước
    is_spec_table() sau chunking, không xoá ở đây.
    """
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            out.append(line)
            continue
        # Bỏ dòng table separator |---|
        if stripped.startswith("|") and "---" in stripped:
            continue
        # Bỏ table data rows (specs không vào vector prose)
        if stripped.startswith("|"):
            continue
        # PDF noise
        if _is_disclaimer(stripped):
            continue
        if _is_page_number(stripped):
            continue
        if _is_footnote(stripped):
            continue
        if SPEC_SHEET_RE.match(stripped):
            continue
        if TABLE_HEADER_RESIDUE_RE.match(stripped):
            continue
        if stripped in ("ECO", "PLUS", "VF 6 ECO", "VF 6 PLUS"):
            continue
        # Dòng có | nhưng ko bắt đầu bằng | → table residue
        if "|" in stripped:
            stripped = stripped.replace("|", "").strip()
            if not stripped:
                continue
            line = stripped
        out.append(line)
    return "\n".join(out)
