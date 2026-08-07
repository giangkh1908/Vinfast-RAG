"""
clean_from_md.py — Clean pipeline từ .md files có sẵn trong codebase.
Không依赖 crawled raw HTML. Xử lý trực tiếp từ markdown files.

Usage:
    python scripts/clean_data/clean_from_md.py --version v1
"""

import argparse
import json
import math
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
CLEAN_DIR = BASE_DIR / "data" / "clean"

NS_UUID = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


# ── Helpers ─────────────────────────────────────────────────────────────────

def chunk_id(*parts: str) -> str:
    return ":".join(parts)


def make_uuid(cid: str) -> str:
    return str(uuid.uuid5(NS_UUID, cid))


def strip_images(text: str) -> str:
    return re.sub(r"!\[.*?\]\(.*?\)", "", text)


def strip_links(text: str) -> str:
    return re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)


def strip_urls(text: str) -> str:
    return re.sub(r"https?://\S+", "", text)


def strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text)


def collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def clean(text: str) -> str:
    text = strip_images(text)
    text = strip_links(text)
    text = strip_urls(text)
    text = strip_html(text)
    text = text.replace("\\*", "").replace("\\(", "(").replace("\\)", ")")
    text = collapse_ws(text)
    return text


def has_money(text: str) -> bool:
    return bool(re.search(r"\d[\d.]*\s*(triệu|tỷ|VNĐ|₫|nghìn)", text, re.IGNORECASE))


def has_specs_numbers(text: str) -> bool:
    return bool(re.search(r"\d+\s*(kW|Nm|kWh|mm|HP)\b", text))


def normalize_versions(text: str) -> str:
    text = re.sub(r"VF\s*7\s*S\b", "VF 7 Eco", text)
    text = re.sub(r"phiên bản S\b", "phiên bản Eco", text)
    text = re.sub(r"bản S\b", "bản Eco", text)
    return text


def split_sections(text: str) -> list[tuple[str, str]]:
    """Split markdown by ## headings → (heading, body) pairs."""
    parts = re.split(r"^(#{1,3}\s+.+)$", text, flags=re.MULTILINE)
    sections = []
    current_title = ""
    current_body = ""

    for part in parts:
        if re.match(r"^#{1,3}\s+", part):
            if current_body.strip():
                sections.append((current_title, current_body.strip()))
            current_title = re.sub(r"^#{1,3}\s+", "", part).strip()
            current_body = ""
        else:
            current_body += part

    if current_body.strip():
        sections.append((current_title, current_body.strip()))

    return sections


def make_chunk(chunk_id_str: str, text: str, model_id: str,
               category: str, section_path: list, text_type: str,
               source_type: str, source_file: str, source_url: str = "",
               structured: dict = None, tags: list = None) -> dict:
    return {
        "id": chunk_id_str,
        "collection": "vivu_product_info",
        "vector_version": "v1",
        "model_id": model_id,
        "edition_id": None,
        "category": category,
        "section_path": section_path,
        "text": text,
        "text_type": text_type,
        "structured": structured,
        "language": "vi",
        "tags": tags or [],
        "confidence": 1.0,
        "source_file": source_file,
        "source_url": source_url,
        "source_type": source_type,
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ingested_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ── Model registry ──────────────────────────────────────────────────────────

MODELS = {
    "VF2":       {"file": "01_thong_tin_san_pham/vf2.md",       "model_id": "VF2",    "source_url": "https://shop.vinfastauto.com/vn_vi/dat-coc-xe-dien-vf2.html"},
    "VF3":       {"file": "01_thong_tin_san_pham/vf3.md",       "model_id": "VF3",    "source_url": "https://shop.vinfastauto.com/vn_vi/dat-coc-xe-dien-vf3.html"},
    "VF5":       {"file": "01_thong_tin_san_pham/vf5.md",       "model_id": "VF5",    "source_url": "https://shop.vinfastauto.com/vn_vi/san-pham-vinfast-vf5.html"},
    "VF6":       {"file": "01_thong_tin_san_pham/vf6.md",       "model_id": "VF6",    "source_url": "https://shop.vinfastauto.com/vn_vi/dat-coc-xe-dien-vf6.html"},
    "VF7":       {"file": "01_thong_tin_san_pham/vf7.md",       "model_id": "VF7",    "source_url": "https://shop.vinfastauto.com/vn_vi/dat-coc-xe-dien-vf7.html"},
    "VF8":       {"file": "01_thong_tin_san_pham/vf8.md",       "model_id": "VF8",    "source_url": "https://shop.vinfastauto.com/vn_vi/dat-coc-xe-vf8-the-all-new-2026.html"},
    "VF9":       {"file": "01_thong_tin_san_pham/vf9.md",       "model_id": "VF9",    "source_url": "https://shop.vinfastauto.com/vn_vi/dat-coc-xe-dien-vf9.html"},
    "VFMPV7":    {"file": "01_thong_tin_san_pham/vf_mpv7.md",   "model_id": "VFMPV7", "source_url": "https://shop.vinfastauto.com/vn_vi/vf-mpv-7.html"},
}

BROCHURES = {
    "VF2":    {"file": "02_thong_so_ky_thuat/vf2_brochure.md",    "model_id": "VF2"},
    "VF5":    {"file": "02_thong_so_ky_thuat/vf5_brochure.md",    "model_id": "VF5"},
    "VF6":    {"file": "02_thong_so_ky_thuat/vf6_brochure.md",    "model_id": "VF6"},
    "VF7":    {"file": "02_thong_so_ky_thuat/vf7_specs.md",       "model_id": "VF7"},
    "VF8":    {"file": "02_thong_so_ky_thuat/vf8_brochure.md",    "model_id": "VF8"},
    "VF9":    {"file": "02_thong_so_ky_thuat/vf9_brochure.md",    "model_id": "VF9"},
}


# ── Parse product landing pages ─────────────────────────────────────────────

def parse_product_page(model_key: str) -> list[dict]:
    info = MODELS[model_key]
    path = DATA_DIR / info["file"]
    if not path.exists() or path.stat().st_size == 0:
        return []

    raw = path.read_text(encoding="utf-8")
    mid = info["model_id"]
    source_url = info["source_url"]
    source_file = str(path.relative_to(BASE_DIR))
    chunks = []

    # Strip navigation/header/footer
    lines = raw.split("\n")
    clean_lines = []
    for line in lines:
        if any(kw in line.lower() for kw in ["reCAPTCHA", "hình xác thực", "đăng nhập / đăng ký"]):
            break
        if re.match(r"^\d+\.\s*\[", line):  # nav links
            continue
        clean_lines.append(line)
    raw = "\n".join(clean_lines)

    # Split by sections
    sections = split_sections(raw)

    for title, body in sections:
        text = clean(body)
        text = normalize_versions(text)

        # Skip empty or too short
        if len(text) < 30:
            continue

        # Skip sections with only numbers/specs
        if has_specs_numbers(text) and not has_money(text):
            # If it's a specs table section, skip from vector
            if "|" in body and "---" in body:
                continue

        # Skip pricing sections (numbers → PostgreSQL only)
        if has_money(text):
            continue

        # Skip comparison calculator sections
        if "so sánh" in title.lower() and "động cơ đốt trong" in title.lower():
            continue

        # Determine category
        cat = "thong_tin_san_pham"
        tags = [mid.lower()]
        title_lower = title.lower()
        if any(kw in title_lower for kw in ["ngoại thất", "exterior", "màu"]):
            tags.append("ngoai_that")
        elif any(kw in title_lower for kw in ["nội thất", "interior"]):
            tags.append("noi_that")
        elif any(kw in title_lower for kw in ["tính năng", "công nghệ", "adas", "trợ lái"]):
            tags.append("tinh_nang")
        elif any(kw in title_lower for kw in ["bảo hành", "hậu mãi"]):
            cat = "chinh_sach_dich_vu"
            tags.append("bao_hanh")
        elif any(kw in title_lower for kw in ["sạc", "trạm sạc"]):
            tags.append("tram_sac")
        elif any(kw in title_lower for kw in ["thiết kế", "design"]):
            tags.append("thiet_ke")

        cid = chunk_id("vivu_product_info", mid, re.sub(r"\s+", "_", title.lower())[:30])
        chunks.append(make_chunk(
            chunk_id_str=cid,
            text=text,
            model_id=mid,
            category=cat,
            section_path=[title],
            text_type="prose",
            source_type="product_page",
            source_file=source_file,
            source_url=source_url,
            tags=tags,
        ))

    # If no sections found, chunk the whole file
    if not chunks:
        text = clean(raw)
        text = normalize_versions(text)
        if len(text) > 50:
            # Split into ~500 char chunks
            words = text.split()
            chunk_words = []
            current = []
            for w in words:
                current.append(w)
                if len(" ".join(current)) > 500:
                    chunk_words.append(" ".join(current))
                    current = []
            if current:
                chunk_words.append(" ".join(current))

            for i, ct in enumerate(chunk_words):
                if has_money(ct) or has_specs_numbers(ct):
                    continue
                cid = chunk_id("vivu_product_info", mid, f"chunk_{i:03d}")
                chunks.append(make_chunk(
                    chunk_id_str=cid, text=ct, model_id=mid,
                    category="thong_tin_san_pham", section_path=[f"Part {i+1}"],
                    text_type="prose", source_type="product_page",
                    source_file=source_file, source_url=source_url,
                    tags=[mid.lower()],
                ))

    return chunks


# ── Parse brochure pages ────────────────────────────────────────────────────

def parse_brochure(model_key: str) -> list[dict]:
    info = BROCHURES[model_key]
    path = DATA_DIR / info["file"]
    if not path.exists() or path.stat().st_size == 0:
        return []

    raw = path.read_text(encoding="utf-8")
    mid = info["model_id"]
    source_file = str(path.relative_to(BASE_DIR))
    source_url = f"https://vinfastauto.com/vn_vi/thong-so-{mid.lower()}"
    chunks = []

    sections = split_sections(raw)

    for title, body in sections:
        text = clean(body)
        text = normalize_versions(text)

        if len(text) < 30:
            continue

        # Skip specs tables (numbers → PostgreSQL)
        if "|" in body and "---" in body:
            continue

        # Skip sections that are mostly numbers
        if has_specs_numbers(text) and len(re.findall(r"\d+", text)) > len(text.split()) * 0.3:
            continue

        # Skip pricing
        if has_money(text):
            continue

        cat = "thong_tin_san_pham"
        tags = [mid.lower(), "brochure"]
        title_lower = title.lower()
        if any(kw in title_lower for kw in ["ngoại thất", "exterior"]):
            tags.append("ngoai_that")
        elif any(kw in title_lower for kw in ["nội thất", "interior"]):
            tags.append("noi_that")
        elif any(kw in title_lower for kw in ["tính năng", "công nghệ", "adas"]):
            tags.append("tinh_nang")
        elif any(kw in title_lower for kw in ["thiết kế", "design"]):
            tags.append("thiet_ke")

        cid = chunk_id("vivu_product_info", mid, f"brochure_{re.sub(r'\s+', '_', title.lower())[:30]}")
        chunks.append(make_chunk(
            chunk_id_str=cid, text=text, model_id=mid,
            category=cat, section_path=[title],
            text_type="prose", source_type="brochure",
            source_file=source_file, source_url=source_url,
            tags=tags,
        ))

    return chunks


# ── Parse FAQ ───────────────────────────────────────────────────────────────

FAQ_SKIP = ["xe máy điện", "đổi pin xe máy", "phụ kiện", "đặt cọc bổ sung", "kiểm tra thông tin đơn"]
FAQ_PRIORITY = ["thẩm định vay", "đặt mua", "huỷ cọc", "hủy cọc", "lăn bánh", "giá xe ô tô", "công cụ hỗ trợ", "thanh toán"]
FAQ_SECONDARY = ["lái thử", "đăng ký lái thử", "giấy tờ", "chuẩn bị gì"]


def parse_faq() -> list[dict]:
    path = DATA_DIR / "04_ho_tro_mua_xe" / "chinh_sach_ban_hang.md"
    if not path.exists() or path.stat().st_size == 0:
        return []

    content = path.read_text(encoding="utf-8")
    source_file = str(path.relative_to(BASE_DIR))

    # Strip frontmatter
    content = re.sub(r"^---\n.*?\n---\n", "", content, flags=re.DOTALL)
    content = re.sub(r"^>.*?\n", "", content, flags=re.MULTILINE)

    pattern = r"## (.*?)\n\n(.*?)(?=\n\n## |\Z)"
    matches = re.findall(pattern, content, re.DOTALL)

    all_qa = []
    for question, answer in matches:
        question = question.strip()
        answer_lines = []
        source_url = ""
        for line in answer.strip().split("\n"):
            line = line.strip()
            if line.startswith("Ngu") and "http" in line:
                url_match = re.search(r"(https?://\S+)", line)
                if url_match:
                    source_url = url_match.group(1)
                continue
            if line:
                answer_lines.append(line)
        all_qa.append({"question": question, "answer": " ".join(answer_lines), "source_url": source_url})

    # Filter
    priority, secondary = [], []
    for qa in all_qa:
        q = qa["question"].lower()
        if any(kw in q for kw in FAQ_SKIP):
            continue
        if any(kw in q for kw in FAQ_PRIORITY):
            priority.append(qa)
        elif any(kw in q for kw in FAQ_SECONDARY):
            secondary.append(qa)

    relevant = priority + secondary
    if len(relevant) < 10:
        for qa in all_qa:
            if qa not in relevant:
                q = qa["question"].lower()
                if not any(kw in q for kw in FAQ_SKIP):
                    relevant.append(qa)
                    if len(relevant) >= 10:
                        break

    chunks = []
    for i, qa in enumerate(relevant[:10]):
        text = f"Q: {qa['question']}\nA: {qa['answer']}"
        cid = chunk_id("vivu_faq", "chinh_sach_ban_hang", f"{i+1:02d}")
        chunks.append(make_chunk(
            chunk_id_str=cid, text=text, model_id=None,
            category="ho_tro_mua_xe", section_path=["FAQ", "Chính sách bán hàng"],
            text_type="qa_pair", source_type="faq",
            source_file=source_file, source_url=qa["source_url"],
            tags=["faq", "chinh_sach_ban_hang"],
            structured={"question": qa["question"], "answer": qa["answer"], "faq_node_url": qa["source_url"]},
        ))

    return chunks


# ── Parse policy ────────────────────────────────────────────────────────────

def parse_policy() -> list[dict]:
    path = DATA_DIR / "05_chinh_sach_dich_vu" / "dieu_khoan_phap_ly.md"
    if not path.exists() or path.stat().st_size == 0:
        return []

    raw = path.read_text(encoding="utf-8")
    source_file = str(path.relative_to(BASE_DIR))
    chunks = []

    sections = split_sections(raw)

    for title, body in sections:
        text = clean(body)

        if len(text) < 30:
            continue

        # Skip if mostly numbers
        if has_specs_numbers(text) and len(re.findall(r"\d+", text)) > len(text.split()) * 0.3:
            continue

        cat = "chinh_sach_dich_vu"
        tags = ["phap_ly", "chinh_sach"]
        title_lower = title.lower()
        if "thuê pin" in title_lower or "pin" in title_lower:
            tags.append("thue_pin")
        elif "bảo hành" in title_lower:
            tags.append("bao_hanh")
        elif "đặt cọc" in title_lower:
            tags.append("dat_coc")
        elif "đổi trả" in title_lower or "hoàn tiền" in title_lower:
            tags.append("doi_tra")

        cid = chunk_id("vivu_policy", re.sub(r"\s+", "_", title.lower())[:40])
        chunks.append(make_chunk(
            chunk_id_str=cid, text=text, model_id=None,
            category=cat, section_path=["Điều khoản pháp lý", title],
            text_type="legal_clause", source_type="policy",
            source_file=source_file,
            source_url="https://vinfastauto.com/vn_vi/dieu-khoan-phap-ly",
            tags=tags,
        ))

    return chunks


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="v1")
    args = parser.parse_args()

    version = args.version
    out_dir = CLEAN_DIR / version
    vector_dir = out_dir / "vector"
    postgres_dir = out_dir / "postgres"
    vector_dir.mkdir(parents=True, exist_ok=True)
    postgres_dir.mkdir(parents=True, exist_ok=True)

    print(f"[clean_from_md] version={version}")
    print(f"  output: {out_dir}")

    # 1. Parse product pages
    product_chunks = []
    for model_key in MODELS:
        chunks = parse_product_page(model_key)
        product_chunks.extend(chunks)
        print(f"  product [{model_key}]: {len(chunks)} chunks")

    # 2. Parse brochures
    brochure_chunks = []
    for model_key in BROCHURES:
        chunks = parse_brochure(model_key)
        brochure_chunks.extend(chunks)
        print(f"  brochure [{model_key}]: {len(chunks)} chunks")

    # 3. Parse FAQ
    faq_chunks = parse_faq()
    print(f"  faq: {len(faq_chunks)} chunks")

    # 4. Parse policy
    policy_chunks = parse_policy()
    print(f"  policy: {len(policy_chunks)} chunks")

    # 5. Write JSONL
    all_product = product_chunks + brochure_chunks
    with open(vector_dir / "vivu_product_info.jsonl", "w", encoding="utf-8") as f:
        for c in all_product:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"\n  vivu_product_info.jsonl: {len(all_product)} chunks")

    with open(vector_dir / "vivu_faq.jsonl", "w", encoding="utf-8") as f:
        for c in faq_chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"  vivu_faq.jsonl: {len(faq_chunks)} chunks")

    with open(vector_dir / "vivu_policy.jsonl", "w", encoding="utf-8") as f:
        for c in policy_chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"  vivu_policy.jsonl: {len(policy_chunks)} chunks")

    # 6. Stats
    total = len(all_product) + len(faq_chunks) + len(policy_chunks)
    print(f"\n  TOTAL: {total} chunks")

    # Count by model
    by_model = {}
    for c in all_product:
        mid = c.get("model_id") or "shared"
        by_model[mid] = by_model.get(mid, 0) + 1
    print("  By model:")
    for m, cnt in sorted(by_model.items()):
        print(f"    {m}: {cnt}")

    # 7. Manifest
    manifest = {
        "version": version,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": "md_files_direct",
        "counts": {
            "product": len(product_chunks),
            "brochure": len(brochure_chunks),
            "faq": len(faq_chunks),
            "policy": len(policy_chunks),
            "total": total,
        },
        "files": {
            "vector": ["vivu_product_info.jsonl", "vivu_faq.jsonl", "vivu_policy.jsonl"],
        },
    }
    with open(out_dir / "_manifest_clean.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"\n[clean_from_md] DONE. {total} clean chunks → {vector_dir}")


if __name__ == "__main__":
    main()
