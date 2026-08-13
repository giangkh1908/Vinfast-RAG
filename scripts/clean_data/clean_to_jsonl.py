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
  * Chunking: heading-based first, then sentence-aware split (max_len=800,
    overlap = last complete sentence), khớp cửa sổ embedding ~128 token.
"""

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Chạy trực tiếp (`python scripts/clean_data/clean_to_jsonl.py`) → repo root vào sys.path
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# ── Paths ──────────────────────────────────────────────────────────────────
from scripts.config import CLEAN_DIR, RAW_DIR, RAW_PDF_DIR, REPO_ROOT  # noqa: E402
from scripts.clean_data.spec_common import (  # noqa: E402
    MODEL_EDITIONS, MODEL_LABEL, infer_model, parse_raw_file,
)
from scripts.clean_data.noise_patterns import (  # noqa: E402
    PAGE_MARKER_RE, clean_line, clean_pdf_prose, fix_pdf_spacing,
    normalize_numbers, remove_money_sentences, strip_price_spans,
)
from scripts.clean_data.chunk_filters import (  # noqa: E402
    is_junk_chunk, is_offmodel_noise, is_spec_section, is_spec_table,
)
from scripts.clean_data.chunking import apply_chunking  # noqa: E402

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
    "Products-Car-VF8NEW": "VF8NEW",
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

# Collection / category routing  (spec số liệu KHÔNG vào vector — chỉ ở car_specs SQL;
# prose mô tả/so sánh model hiện nằm trong vivu_product_info)
COLLECTION_BY_CATEGORY = {
    "thong_tin_san_pham": "vivu_product_info",
    "ho_tro_mua_xe": "vivu_faq",
    "chinh_sach_dich_vu": "vivu_policy",
    "dat_lich_bao_duong": "vivu_maintenance",
}

# Edition names xuất hiện trực tiếp trong dat-coc / article
EDITION_KEYWORDS = ["PlusCaptain", "Plus", "Eco", "TieuChuan", "NangCao", "CaoCap", "Base"]

# Domain chính thống — chỉ những trang này mới được trích giá vào Postgres
AUTHORITATIVE_DOMAINS = {"vinfastauto.com", "shop.vinfastauto.com"}

# ── Helpers ────────────────────────────────────────────────────────────────
def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

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

def classify_raw(path: Path, meta: dict[str, Any]) -> dict[str, Any] | None:
    """Route a raw file to collection/category/model/confidence + authoritative."""
    name = path.stem.lower()
    url = meta.get("source_url", "")
    domain = get_domain(url)
    authoritative = domain in AUTHORITATIVE_DOMAINS
    stype = meta.get("source_type", "")
    model = infer_model(path)

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

    # Chỉ brochure PDF có chữ "brochure" trong tên/URL vào product info.
    # Các file *_svc* và *_wb* là sổ bảo hành dù tên file có mã model.
    if stype == "pdf":
        if model and ("brochure" in name or "brochure" in url.lower()):
            return route("vivu_product_info", "thong_tin_san_pham", 0.9, "brochure")
        return route("vivu_policy", "chinh_sach_dich_vu", 0.9, "pdf-manual")

    # Web articles / dealer pages — prose mô tả/so sánh model → vivu_product_info
    # (spec số liệu → car_specs qua parse_specs, không vào vector)
    if any(k in name for k in ("so-sanh", "bang-doi-chieu")):
        return route("vivu_product_info", "thong_so_ky_thuat", 0.8, "comparison")
    if any(k in name for k in ("thong-so-ky-thuat", "thong-so-")):
        return route("vivu_product_info", "thong_so_ky_thuat", 0.8, "specs-article")
    return route("vivu_product_info", "thong_tin_san_pham", 0.7, "article")

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
            body_text = f"{section_title}\n{body_text}"

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
        # Page marker: --- Trang N ---  →  flush chunk hiện tại (boundary giữa các trang)
        pm = PAGE_MARKER_RE.match(raw.strip())
        if pm:
            emit()
            continue
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
def run(version: str = "v1", max_len: int = 800) -> int:
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

    # 2. Xử lý raw_pdf (brochure/manual prose)
    if RAW_PDF_DIR.exists():
        for path in sorted(RAW_PDF_DIR.iterdir()):
            if not path.is_file() or path.suffix not in (".txt",):
                continue
            meta, body = parse_raw_file(path)
            cls = classify_raw(path, meta)
            if cls is None:
                continue
            n_files += 1

            # PDF-specific cleaning + spacing fix
            body = clean_pdf_prose(body)
            body = fix_pdf_spacing(body)

            chunks = chunks_from_text(body, meta, cls, path)
            all_vector.extend(chunks)

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
    # Filter chi tiết (is_spec_section / is_spec_table) xem chunk_filters.py.
    pre = len(all_vector)
    n_section = 0
    n_spec_table = 0
    kept: list[dict[str, Any]] = []
    for c in all_vector:
        if is_spec_section(c):
            n_section += 1
            continue
        if is_spec_table(c):
            n_spec_table += 1
            continue
        kept.append(c)
    all_vector = kept
    print(f"  dropped spec chunks: {n_section} (section) "
          f"+ {n_spec_table} (spec-table pipe-delimited) | {pre} -> {len(all_vector)}")

    # Drop off-model noise (sidebar "tin liên quan" lạc tag — VD Toyota trong VF2)
    n_offmodel = 0
    kept_off: list[dict[str, Any]] = []
    for c in all_vector:
        if is_offmodel_noise(c):
            n_offmodel += 1
            continue
        kept_off.append(c)
    all_vector = kept_off
    print(f"  dropped off-model noise: {n_offmodel}")

    # Drop junk boilerplate (modal/footer/nav/button từ shop site)
    n_junk = 0
    kept_junk: list[dict[str, Any]] = []
    for c in all_vector:
        if is_junk_chunk(c):
            n_junk += 1
            continue
        kept_junk.append(c)
    all_vector = kept_junk
    print(f"  dropped junk boilerplate: {n_junk}")

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
    ap.add_argument("--max-len", type=int, default=800,
                    help="Chunk max length in chars (default 800; use 400 for finer retrieval)")
    args = ap.parse_args()
    return run(args.version, args.max_len)

if __name__ == "__main__":
    sys.exit(main())
