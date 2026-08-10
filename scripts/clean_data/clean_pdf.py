#!/usr/bin/env python3
"""
clean_pdf.py — Clean raw PDF brochure output thành intermediate JSONL.

Source:  data/raw/crawl_pdf/*.txt   (crawl_pdf output từ crawl_pdf.py,
         có header metadata (# Nguồn, # Loại...) + body với pipe-table
         Markdown + page markers (--- Trang N ---).

Output:  data/clean/<version>/intermediate/pdf_vector.jsonl
         (cùng schema chunk với clean_to_jsonl)

Clean PDF-specific noise:
  1. Số trang đơn độc:          "01", "02", "03" … (dòng chỉ có 1-2 chữ số)
  2. Disclaimer lặp:            "Hình ảnh mang tính chất minh họa…"
  3. Footnote kiểu:             "*Phiên bản VF 8 PLUS", "(*) Thông số…"
  4. Table rows bị xoá:         bảng brochure sẽ vào specs.csv riêng
"""
import argparse
import json
import os
import re
import sys
import unicodedata
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import unicodedata

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_PDF_DIR = REPO_ROOT / "data" / "raw_pdf"
CLEAN_DIR = REPO_ROOT / "data" / "clean"

# ── Mappings (copy từ clean_to_jsonl) ───────────────────────────────────────
MODEL_ID_MAP = OrderedDict({
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
    "Products-Car-VF8NEW": "VF8NEW",
    "Products-Car-VF9": "VF9",
    "Products-Car-VFMPV7": "VFMPV7",
    "Products-Car-MPV7": "VFMPV7",
})

COLLECTION_BY_CATEGORY = {
    "thong_tin_san_pham": "vivu_product_info",
    "ho_tro_mua_xe": "vivu_faq",
    "chinh_sach_dich_vu": "vivu_policy",
    "dat_lich_bao_duong": "vivu_maintenance",
}

AUTHORITATIVE_DOMAINS = {"vinfastauto.com", "shop.vinfastauto.com"}

_MISC_REPLACEMENTS = {
    "m": "m",
    "n": "n",
    "o": "o",  # nếu có PUA
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def no_diacritics(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn").replace("đ", "d")


def slugify(name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_\-]", "_", name)
    return name[:80]


def infer_model_from_path(path: Path) -> str | None:
    """Rút model_id từ tên file / URL trong metadata."""
    name = re.sub(r"[^a-z0-9]", "", path.stem.lower())
    keys = sorted([
        ("mpv7", "VFMPV7"),
        ("vf206", "VF6"), ("vf6", "VF6"),
        ("vf2", "VF2"), ("vf3", "VF3"), ("vf5", "VF5"),
        ("vf7", "VF7"), ("vf8theallnew", "VF8NEW"),
        ("vf8thenew", "VF8NEW"), ("vf8allnew", "VF8NEW"),
        ("vf8", "VF8"), ("vf9", "VF9"),
    ], key=lambda x: -len(x[0]))
    for key, model in keys:
        if key in name:
            return model
    return None


def classify_pdf(path: Path, meta: dict[str, Any]) -> dict[str, Any]:
    """Route PDF raw → category/collection."""
    name = path.stem.lower()
    url = meta.get("source_url", "")
    domain = ""
    if m := re.search(r"https?://([^/]+)", url or ""):
        domain = m.group(1).lower()
    authoritative = domain in AUTHORITATIVE_DOMAINS
    model = infer_model_from_path(path)

    route_data = {
        "model_id": model,
        "authoritative": authoritative,
    }

    if "brochure" in name or "brochure" in url.lower():
        route_data.update(collection="vivu_product_info",
                          category="thong_tin_san_pham",
                          confidence=0.9, kind="brochure")
    else:
        route_data.update(collection="vivu_policy",
                          category="chinh_sach_dich_vu",
                          confidence=0.9, kind="pdf-manual")
    return route_data


# ── PDF Noise patterns ──────────────────────────────────────────────────────

# Số trang đơn độc: "01", "02", …, "22" (mà không phải trong bảng / heading)
# Chỉ match khi dòng là 1-2 chữ số và không có | (không phải table cell)
PAGE_NUM_RE = re.compile(r"^\s*(\d{1,2})\s*$")

# Disclaimer chính xác và các biến thể bị xuống dòng
DISCLAIMER_FULL = (
    "Hình ảnh mang tính chất minh họa và có thể khác so với xe thực tế. "
    "Tính năng, đặc điểm, thông số kỹ thuật có thể thay đổi mà không thông báo trước."
)
DISCLAIMER_PREFIX = "Hình ảnh mang tính chất minh họa"

# Thêm disclaimer patterns (không prefix match, nhưng có phrase key)
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

# Footnote: "(*)" ở đầu dòng hoặc "*Phiên bản", "** Phiên bản"
FOOTNOTE_RE = re.compile(
    r"^\s*\*{1,2}\s*(?:Phiên bản).*$",
    flags=re.IGNORECASE,
)
FOOTNOTE_PAREN_RE = re.compile(
    r"^\s*\(\*\)\s*.*$",
)

# "(*) Thông số kỹ thuật có thể thay đổi mà không báo trước."
SPEC_FOOTNOTE_RE = re.compile(
    r"^\s*\(\*\)\s*Thông số kỹ thuật.*$",
    flags=re.IGNORECASE,
)

# Page marker: --- Trang N ---  (giữ lại để track, không xoá)
PAGE_MARKER_RE = re.compile(r"---\s*Trang\s*(\d+)\s*---")

# Spec sheet / table residue (không có pipe nhưng là header table)
SPEC_SHEET_RE = re.compile(
    r"^(thông số kỹ thuật|kích thước|màn hình và kết nối|tính năng điều khiển thông minh)",
    flags=re.IGNORECASE,
)
TABLE_HEADER_RESIDUE_RE = re.compile(
    r"^(kích thước|tính năng|điều khiển thông minh)\s+vf\s+\d+\s+(eco|plus)",
    flags=re.IGNORECASE,
)

# PUA characters (Unicode private-use)
PUA_RE = re.compile(r"[-]")

# Soft hyphen & invisible chars
SOFT_HYPHEN_RE = re.compile(r"­|​|‌|‍")


def no_diacritics(s: str) -> str:
    """Bỏ dấu + đổi đ→d để match kể cả OCR lỗi dấu."""
    s = s.lower()
    s = "".join(c for c in unicodedata.normalize("NFD", s)
                 if unicodedata.category(c) != "Mn")
    return s.replace("đ", "d").replace("­", "")


# ── Parsing ──────────────────────────────────────────────────────────────────

def parse_raw_file(path: Path) -> tuple[dict[str, Any], str]:
    """Parse file từ crawl_pdf: header metadata + body."""
    text = path.read_text(encoding="utf-8", errors="replace")
    meta = {"source_url": "", "fetched_at": "", "source_type": "pdf", "selector": ""}
    lines = text.splitlines()
    body_start = 0
    for i, line in enumerate(lines):
        if line.startswith("# Nguồn:"):
            meta["source_url"] = line.split(":", 1)[1].strip()
        elif line.startswith("# Crawl lúc:"):
            meta["fetched_at"] = line.split(":", 1)[1].strip()
        elif line.startswith("# Loại:"):
            meta["source_type"] = line.split(":", 1)[1].strip().lower()
        elif line.startswith("# Trang:"):
            meta["pages"] = line.split(":", 1)[1].strip()
        elif re.match(r"^={5,}$", line.strip()):
            body_start = i + 1
            break
    return meta, "\n".join(lines[body_start:])


# ── Cleaning ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def clean_line(line: str) -> str:
    """Clean một dòng text."""
    line = PUA_RE.sub("", line)
    line = re.sub(r"\s+", " ", line).strip()
    return line


def is_disclaimer(line: str) -> bool:
    """True nếu dòng là disclaimer hoặc một phần của disclaimer."""
    line = clean_line(line)
    if not line:
        return False
    line_nd = no_diacritics(line)

    # Full match
    if line == DISCLAIMER_FULL:
        return True
    # Bắt đầu bằng prefix
    if line.startswith(DISCLAIMER_PREFIX):
        return True
    # Là phần cuối bị xuống dòng của disclaimer
    if "thông số kỹ thuật" in line.lower() and "có thể thay đổi" in line.lower():
        return True
    if "khác so với xe thực tế" in line.lower():
        return True
    # Disclaimer phrases — match trên no_diacritics (chịu được OCR lỗi dấu)
    for phrase in DISCLAIMER_PHRASES:
        if phrase in line_nd:
            return True
    # Thêm pattern chung: "Hình ảnh mang tính chất minh hoạ" (OCR hay sai a/ă/ạ)
    if "hinh anh mang tinh chat minh hoa" in line_nd:
        return True
    if "thong so ky thuat" in line_nd and "co the thay doi" in line_nd:
        return True
    return False


def is_page_number(line: str, in_table: bool = False) -> bool:
    """True nếu dòng chỉ là số trang.

    in_table=True → dòng là cell trong bảng (bắt đầu bằng |) → không xoá.
    """
    if in_table:
        return False
    stripped = line.strip()
    if not stripped:
        return False
    m = PAGE_NUM_RE.match(stripped)
    if not m:
        return False
    num = m.group(1)
    # Không xoá số lớn (tỉ lệ cao là nội dung thật)
    if int(num) > 60:
        return False
    # Kiểm tra: nếu dòng có context xung quanh (trong table, heading) → giữ
    return True


# ── Page grouping ────────────────────────────────────────────────────────────

def parse_pages(body: str) -> list[dict[str, Any]]:
    """Tách body thành list page {page_num, table_text, non_table_text}.

    Giữ nguyên --- Trang N --- markers.
    """
    pages: list[dict[str, Any]] = []
    current_page = 0
    current_lines: list[str] = []

    def emit():
        if current_lines:
            text = "\n".join(current_lines).strip()
            if text:
                pages.append({"page": current_page, "text": text})
        current_lines.clear()

    for line in body.splitlines():
        pm = PAGE_MARKER_RE.match(line.strip())
        if pm:
            emit()
            current_page = int(pm.group(1))
            continue
        # Bỏ header "= ... =" separator
        if re.match(r"^={5,}$", line.strip()):
            continue
        current_lines.append(line)
    emit()
    return pages


# ── Text cleaning (per page) ────────────────────────────────────────────────

def _rejoin_table_wrap(text: str) -> str:
    """Nối dòng table bị wrap (cell xuống dòng).

    Pattern: dòng table kết thúc mà không có | ở cuối, dòng sau có | nhưng không
    bắt đầu bằng | → nối vào dòng trước.

    Ví dụ:
        | Gương chiếu hậu gập điện, sấy mặt gương, tự động
        chỉnh phía hành khách khi lùi | Không | Có |
    →   | Gương chiếu hậu gập điện, sấy mặt gương, tự động chỉnh phía hành khách khi lùi | Không | Có |
    """
    lines = text.split("\n")
    merged: list[str] = []
    for line in lines:
        stripped = line.strip()
        # Dòng KHÔNG bắt đầu bằng | nhưng có chứa | → continuation của dòng trước
        if stripped and not stripped.startswith("|") and "|" in stripped and merged:
            merged[-1] = merged[-1].rstrip() + " " + stripped
        else:
            merged.append(line)
    return "\n".join(merged)


def clean_page(page: dict[str, Any]) -> dict[str, Any]:
    """Clean trash noise khỏi page text.

    - Table rows bị xoá (bảng sẽ vào specs.csv riêng)
    - Prose text giữ lại, làm sạch disclaimer/page-number/footnote
    """
    text = page["text"]
    if not text.strip():
        return {**page, "text": ""}

    # Nối dòng table bị wrap trước khi clean
    text = _rejoin_table_wrap(text)

    lines = text.split("\n")
    in_table = False
    cleaned: list[str] = []

    for line in lines:
        stripped = line.strip()

        # Track table context
        if stripped.startswith("|") and "---" in stripped:
            in_table = True
            continue  # bỏ separator
        if stripped.startswith("|"):
            in_table = True
            continue  # bỏ table data row
        else:
            if in_table:
                in_table = False
                if not stripped:
                    continue
            # else: đang ở prose

        if not stripped:
            cleaned.append(line)
            continue

        # Lọc noise
        if is_disclaimer(stripped):
            continue
        if is_page_number(stripped, in_table=False):
            continue
        if FOOTNOTE_RE.match(stripped):
            continue
        if SPEC_FOOTNOTE_RE.match(stripped):
            continue
        if FOOTNOTE_PAREN_RE.match(stripped):
            continue
        # Spec sheet header / table residue (không pipe nhưng là table)
        if SPEC_SHEET_RE.match(stripped):
            continue
        if TABLE_HEADER_RESIDUE_RE.match(stripped):
            continue
        # Dòng chỉ toàn "ECO" / "PLUS" (table edition label)
        if stripped.strip() in ("ECO", "PLUS", "VF 6 ECO", "VF 6 PLUS"):
            continue
        # Table residue có | nhưng ko bắt đầu bằng |
        if "|" in stripped:
            # Strip | và trim
            stripped = stripped.replace("|", "").strip()
            if not stripped:
                continue
            line = stripped

        cleaned.append(line)

    return {**page, "text": "\n".join(cleaned).strip()}


# ── Chunking ─────────────────────────────────────────────────────────────────

def chunks_from_page(page: dict[str, Any], cls: dict[str, Any],
                     meta: dict[str, Any], path: Path) -> list[dict[str, Any]]:
    """Chia page đã clean → list chunk (chỉ prose, tables đã bỏ)."""
    text = page["text"]
    if not text:
        return []

    chunks: list[dict[str, Any]] = []
    page_num = page["page"]
    model_id = cls.get("model_id")

    # Page nhỏ → 1 chunk (bỏ nếu quá ngắn)
    if len(text) <= 800:
        if len(text.strip()) < 30:
            return []
        return [_make_chunk(text, page_num, model_id, "prose", cls, meta, path)]

    # Page lớn → split theo dòng trống
    segments = re.split(r"\n\n+", text)
    for seg in segments:
        seg = seg.strip()
        if len(seg) < 30:
            continue
        chunks.append(_make_chunk(seg, page_num, model_id, "prose", cls, meta, path))
    return chunks


def _make_chunk(text: str, page: int, model_id: str | None, text_type: str,
                cls: dict[str, Any], meta: dict[str, Any],
                path: Path) -> dict[str, Any]:
    """Tạo 1 chunk dict theo schema clean_to_jsonl."""
    category = cls.get("category", "thong_tin_san_pham")
    section_path = [category]
    if page:
        section_path.append(f"Trang {page}")

    body = text.strip()
    if not body:
        body = text

    collection = COLLECTION_BY_CATEGORY.get(category, "vivu_product_info")
    tags = [category.replace("_", "")]
    if model_id:
        tags.append(model_id.lower())

    return {
        "id": "",
        "collection": collection,
        "vector_version": None,
        "model_id": model_id,
        "edition_id": None,
        "category": category,
        "section_path": section_path,
        "text": body,
        "text_type": text_type,
        "structured": {},
        "language": "vi",
        "tags": tags,
        "confidence": cls.get("confidence", 0.9),
        "source_file": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "source_url": meta.get("source_url", ""),
        "source_type": "raw_pdf",
        "fetched_at": meta.get("fetched_at", ""),
        "ingested_at": "",
        "is_hot": False,
        "page": page,
    }


# ── Run ──────────────────────────────────────────────────────────────────────

def run(version: str = "v1") -> int:
    """Clean PDF raw → intermediate JSONL."""
    version_dir = CLEAN_DIR / version
    intermediate_dir = version_dir / "intermediate"
    intermediate_dir.mkdir(parents=True, exist_ok=True)

    if not RAW_PDF_DIR.exists():
        print(f"[clean_pdf] crawl_pdf dir not found: {RAW_PDF_DIR}", file=sys.stderr)
        return 1

    all_vector: list[dict[str, Any]] = []
    n_files = 0

    for path in sorted(RAW_PDF_DIR.iterdir()):
        if not path.is_file() or path.suffix not in (".txt",):
            continue
        n_files += 1
        print(f"  📄 {path.name}")

        meta, body = parse_raw_file(path)
        cls = classify_pdf(path, meta)
        pages = parse_pages(body)

        n_before = 0
        for pg in pages:
            n_before += len(pg["text"]) if pg["text"] else 0

        cleaned = [clean_page(pg) for pg in pages]
        # Lọc bỏ page không còn text sau clean
        cleaned = [c for c in cleaned if c["text"].strip()]

        n_after = sum(len(c["text"]) for c in cleaned)
        print(f"    {len(pages)} trang → {len(cleaned)} trang sau clean "
              f"({n_before:,} → {n_after:,} ký tự)")

        for pg in cleaned:
            chunks = chunks_from_page(pg, cls, meta, path)
            all_vector.extend(chunks)

    # Stats
    n_table_chunks = sum(1 for c in all_vector if c["text_type"] == "table")
    n_prose_chunks = sum(1 for c in all_vector if c["text_type"] == "prose")

    # Gán ID và timestamp
    ingested_at = now_iso()
    for i, c in enumerate(all_vector):
        c["id"] = f"pdf_{slugify(c['source_file'])}_{i:04d}"
        c["vector_version"] = version
        c["ingested_at"] = ingested_at
        if not c.get("fetched_at"):
            c["fetched_at"] = ingested_at

    # Ghi JSONL
    out_file = intermediate_dir / "pdf_vector.jsonl"
    with out_file.open("w", encoding="utf-8") as f:
        for c in all_vector:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    print(f"\n[clean_pdf] version={version}, files={n_files}")
    print(f"  vector chunks: {len(all_vector)} ({n_table_chunks} table, {n_prose_chunks} prose)")
    print(f"  output:        {out_file}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Clean raw PDF brochure output into intermediate JSONL.")
    ap.add_argument("--version", default="v1", help="Output version folder (default: v1)")
    args = ap.parse_args()
    return run(args.version)


if __name__ == "__main__":
    sys.exit(main())
