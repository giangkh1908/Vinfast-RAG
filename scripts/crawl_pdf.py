#!/usr/bin/env python3
"""
Crawler PDF chuyên dụng — giữ cấu trúc bảng, dòng, cột, lề.
===========================================================

Thay vì ``page.get_text()`` trần (PyMuPDF / pdfplumber) làm mất layout
bảng như crawl.py gốc, script này dùng:

  1. **``page.find_tables()``** (PyMuPDF ≥1.23) — phát hiện bảng có đường
     kẻ / grid, trả về mảng ô chuẩn, render thành Markdown pipe-table
     hoặc CSV.
  2. **Phân tích vị trí (bounding box)** — khi không có bảng rõ ràng
     nhưng nội dung xếp nhiều cột (vd brochure), dùng clustering x0
     để phát hiện cột và tái tạo bảng.
  3. **Fallback ``page.get_text()``** — nếu là trang văn bản thuần.

Cách dùng::

    # Crawl PDF → text có bảng Markdown
    python scripts/crawl_pdf.py <URL>

    # Ghi ra file chỉ định
    python scripts/crawl_pdf.py <URL> --out output.txt

    # Xuất CSV riêng cho từng bảng (kèm text)
    python scripts/crawl_pdf.py <URL> --csv

    # Chỉ crawl một số trang (1-indexed)
    python scripts/crawl_pdf.py <URL> --pages 18,19,20

    # Giữ lại file PDF gốc
    python scripts/crawl_pdf.py <URL> --keep-pdf

    # Verbose — xem thông tin phát hiện cột / bảng
    python scripts/crawl_pdf.py <URL> -v

Output mặc định: ``data/raw_pdf/<slug>_pdf_<timestamp>.txt``
"""

import argparse
import csv
import io
import json
import os
import re
import sys
import time
import warnings
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests

warnings.filterwarnings("ignore", category=DeprecationWarning)

# ── CLI helpers ──────────────────────────────────────────────────────────────


def configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


configure_console()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "vi,en;q=0.9",
}

# ── Data structures ──────────────────────────────────────────────────────────


@dataclass
class TableCell:
    text: str
    row: int
    col: int
    rowspan: int = 1
    colspan: int = 1


@dataclass
class ExtractedTable:
    """Bảng đã trích xuất từ PDF."""
    page: int              # 1-indexed
    headers: list[str]
    rows: list[list[str]]
    bbox: tuple | None = None  # (x0, y0, x1, y1) trên page

    def to_markdown(self) -> str:
        """Pipe‑delimited Markdown table."""
        if not self.headers and not self.rows:
            return ""
        lines: list[str] = []
        # Header
        hdr = self.headers or [""] * (max(len(r) for r in self.rows) if self.rows else 0)
        lines.append("| " + " | ".join(hdr) + " |")
        # Separator
        lines.append("| " + " | ".join("---" for _ in hdr) + " |")
        # Rows
        for row in self.rows:
            padded = list(row) + [""] * (len(hdr) - len(row))
            escaped = [c.replace("|", "\\|") for c in padded]
            lines.append("| " + " | ".join(escaped) + " |")
        return "\n".join(lines)

    def to_csv(self) -> str:
        """CSV string (utf‑8)."""
        buf = io.StringIO()
        w = csv.writer(buf, quoting=csv.QUOTE_ALL)
        if self.headers:
            w.writerow(self.headers)
        for row in self.rows:
            w.writerow(row)
        return buf.getvalue()


@dataclass
class ColumnZone:
    """Vùng cột được phát hiện bằng phân tích vị trí."""
    x0: float          # cạnh trái
    x1: float          # cạnh phải
    label: str = ""    # tiêu đề gợi ý

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2


@dataclass
class PageResult:
    """Kết quả trích xuất một trang."""
    page_num: int       # 1-indexed
    tables: list[ExtractedTable] = field(default_factory=list)
    paragraphs: list[str] = field(default_factory=list)
    has_table_data: bool = False


# ── Download ─────────────────────────────────────────────────────────────────


def fetch_pdf(url: str, timeout: int = 60) -> bytes:
    """Tải PDF, retry nhẹ khi lỗi mạng. Trả về raw bytes."""
    last_err = None
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
            if r.status_code == 403 and attempt == 0:
                HEADERS["Referer"] = urlparse(url).scheme + "://" + urlparse(url).netloc + "/"
                continue
            r.raise_for_status()
            ctype = r.headers.get("Content-Type", "").lower()
            if "application/pdf" not in ctype and not url.lower().endswith(".pdf"):
                print(f"  ⚠  Content-Type={ctype}, URL không đuôi .pdf — thử xử lý như PDF")
            return r.content
        except requests.RequestException as e:
            last_err = e
            time.sleep(1 + attempt)
    raise RuntimeError(f"Không tải được PDF {url}: {last_err}")


# ── Column detection (positional) ────────────────────────────────────────────


def _detect_column_zones(spans: list[dict], verbose: bool = False) -> list[ColumnZone]:
    """Phát hiện vùng cột từ danh sách text span có bbox.

    Giải thuật:
      1. Gom x0 của tất cả span theo cluster (sai số 15pt).
      2. Chọn các cluster có đủ span (>=5% tổng số).
      3. Tính khoảng x0..x1 trung bình cho mỗi cluster.
      4. Sắp xếp theo x0 tăng dần → list zone.
    """
    if not spans:
        return []

    x0s = [s["bbox"][0] for s in spans if s.get("text", "").strip()]
    if len(x0s) < 5:
        return []

    # Cluster x0 (sai số 15pt)
    sorted_x0 = sorted(x0s)
    clusters: list[list[float]] = [[sorted_x0[0]]]
    for x in sorted_x0[1:]:
        if abs(x - clusters[-1][-1]) <= 15:
            clusters[-1].append(x)
        else:
            clusters.append([x])

    # Lọc cluster đủ lớn
    min_count = max(3, len(x0s) * 0.05)
    big_clusters = [c for c in clusters if len(c) >= min_count]
    if len(big_clusters) < 2:
        return []   # chỉ 1 cột → không phải multi‑column

    # Tính x0, x1 trung bình cho mỗi cluster
    zones: list[ColumnZone] = []
    for cl in big_clusters:
        members = [s for s in spans if abs(s["bbox"][0] - cl[0]) <= 15 and s.get("text", "").strip()]
        if not members:
            continue
        avg_x0 = sum(m["bbox"][0] for m in members) / len(members)
        avg_x1 = sum(m["bbox"][2] for m in members) / len(members)
        zones.append(ColumnZone(x0=avg_x0, x1=avg_x1))

    zones.sort(key=lambda z: z.x0)

    # Gộp zone chồng lấn (overlap > 30% diện tích zone nhỏ hơn)
    merged: list[ColumnZone] = []
    for z in zones:
        if not merged:
            merged.append(z)
            continue
        last = merged[-1]
        overlap = min(last.x1, z.x1) - max(last.x0, z.x0)
        min_width = min(last.x1 - last.x0, z.x1 - z.x0)
        if overlap > 0 and min_width > 0 and overlap / min_width > 0.3:
            # Hợp nhất
            last.x0 = min(last.x0, z.x0)
            last.x1 = max(last.x1, z.x1)
        else:
            merged.append(z)
    zones = merged

    if verbose:
        print(f"    → Phát hiện {len(zones)} column zones: " +
              ", ".join(f"{z.x0:.0f}–{z.x1:.0f}" for z in zones))

    return zones


def _assign_column(text: str, bbox: tuple, zones: list[ColumnZone]) -> int:
    """Gán text vào cột dựa trên trung tâm của bbox."""
    cx = (bbox[0] + bbox[2]) / 2
    best, best_d = -1, float("inf")
    for i, z in enumerate(zones):
        if z.x0 <= cx <= z.x1:
            return i
        d = min(abs(cx - z.x0), abs(cx - z.x1))
        if d < best_d:
            best_d = d
            best = i
    return best


# ── Table reconstruction from positional data ────────────────────────────────


def _table_quality_check(rows: list[list[str]], n_cols: int, min_fill_rate: float = 0.35) -> bool:
    """Kiểm tra chất lượng bảng tái tạo — lọc false positive.

    Tiêu chí (cần đạt tất cả):
      - Tỉ lệ ô có text >= min_fill_rate
      - Không có cột nào chiếm >85% tổng text (trừ cột đầu)
      - Ít nhất 25% số row có >=2 cột filled (thường là bảng so sánh)
    """
    if not rows or n_cols < 2:
        return False

    total_cells = len(rows) * n_cols
    filled = sum(1 for row in rows for c in row if c.strip())
    fill_rate = filled / total_cells if total_cells else 0

    # Đếm text mỗi cột
    col_counts = [0] * n_cols
    multi_col_rows = 0  # số row có >=2 cột filled
    for row in rows:
        n_filled = 0
        for ci in range(n_cols):
            if ci < len(row) and row[ci].strip():
                col_counts[ci] += 1
                n_filled += 1
        if n_filled >= 2:
            multi_col_rows += 1

    # Không cột nào >85% tổng filled (trừ cột đầu)
    if filled > 0:
        for ci in range(1, n_cols):
            if col_counts[ci] / filled > 0.85:
                return False

    # Tỉ lệ fill tối thiểu
    if fill_rate < min_fill_rate:
        return False

    # Với bảng 2 cột: cần đa số row có >=2 cột filled (thường là label+value)
    # nếu không → đây là layout 2 cột giả (text chạy quanh ảnh)
    if n_cols == 2 and multi_col_rows < len(rows) * 0.4:
        return False

    return True


def _reconstruct_table_from_positions(
    lines: list[dict], zones: list[ColumnZone],
    verbose: bool = False
) -> Optional[ExtractedTable]:
    """Xây dựng ExtractedTable từ lines đã gán cột.

    Dùng y-center của mỗi line để gom thành row (sai số 8pt),
    sau đó gán text vào cột dựa trên x-center.
    """
    if len(zones) < 2:
        return None

    Y_TOLERANCE = 8

    # Gom dòng theo y-center (sai số 8pt)
    rows_raw: list[list[dict]] = []
    cur_y = -1.0
    cur_group: list[dict] = []

    for line in lines:
        bbox = line["bbox"]
        txt = (line.get("text", "") or "").strip()
        if not txt:
            continue
        cy = (bbox[1] + bbox[3]) / 2  # y-center
        if not cur_group or abs(cy - cur_y) <= Y_TOLERANCE:
            cur_group.append(line)
            if cur_y < 0:
                cur_y = cy
            else:
                cur_y = (cur_y + cy) / 2  # running average
        else:
            rows_raw.append(cur_group)
            cur_group = [line]
            cur_y = cy
    if cur_group:
        rows_raw.append(cur_group)

    if len(rows_raw) < 3:
        return None

    # Xây rows: mỗi row có len(zones) ô
    n_cols = len(zones)
    rows: list[list[str]] = []
    for group in rows_raw:
        row = [""] * n_cols
        for line in group:
            bbox = line["bbox"]
            text = (line.get("text", "") or "").strip()
            col = _assign_column(text, bbox, zones)
            if 0 <= col < n_cols:
                prev = row[col]
                row[col] = (prev + " " + text).strip() if prev else text
        rows.append(row)

    # Kiểm tra chất lượng — loại false positive
    if not _table_quality_check(rows, n_cols):
        if verbose:
            filled = sum(1 for row in rows for c in row if c.strip())
            total = len(rows) * n_cols
            print(f"    → Bỏ qua (quality: {filled}/{total} ô, "
                  f"col_dist={[sum(1 for r in rows if ci<len(r) and r[ci].strip()) for ci in range(n_cols)]})")
        return None

    # Dò header: dòng đầu tiên có text ở tất cả cột (hoặc ít nhất 2 cột)
    header = rows[0] if rows else []
    data_rows = rows[1:] if len(rows) > 1 else []

    if verbose:
        print(f"    → Tái tạo {len(data_rows)} rows × {n_cols} cols từ positional data")

    return ExtractedTable(
        page=0, headers=header, rows=data_rows
    )


# ── Main extraction logic ────────────────────────────────────────────────────


def _page_text_blocks(page) -> list[dict]:
    """Lấy tất cả text line từ page dạng dict {bbox, text}."""
    blocks = page.get_text("dict")["blocks"]
    lines_out: list[dict] = []
    for b in blocks:
        if b["type"] != 0:
            continue
        for line in b["lines"]:
            spans = line["spans"]
            text = "".join(s["text"] for s in spans)
            lines_out.append({
                "bbox": line["bbox"],
                "text": text,
                "font": spans[0]["font"] if spans else "",
                "size": spans[0]["size"] if spans else 0,
            })
    return lines_out


def extract_page(page, page_num: int, verbose: bool = False) -> PageResult:
    """Trích xuất một trang PDF → PageResult.

    Quy tắc:
      1. Thử ``page.find_tables()`` → nếu có bảng hợp lệ, dùng luôn.
      2. Nếu không có bảng, dùng positional analysis:
         - Phát hiện column zones
         - Nếu multi‑column → tái tạo bảng
      3. Fallback: ``page.get_text()`` → paragraphs.
    """
    import pymupdf  # lazy
    result = PageResult(page_num=page_num)

    # ── Bước 1: find_tables ──────────────────────────────────────────────
    try:
        tables = page.find_tables()
        valid_tables = [t for t in tables.tables if t.row_count >= 2 and t.col_count >= 2]
        if valid_tables:
            for ti, ft in enumerate(valid_tables):
                data = ft.extract()
                if not data:
                    continue
                headers = data[0] if data else []
                rows = data[1:] if len(data) > 1 else []
                # Lọc bỏ bảng giả (quá ít hàng/cột)
                if len(rows) < 2:
                    continue
                et = ExtractedTable(
                    page=page_num,
                    headers=[h.strip() if h else "" for h in headers],
                    rows=[[(c or "").strip() for c in row] for row in rows],
                    bbox=ft.bbox,
                )
                result.tables.append(et)
                result.has_table_data = True
                if verbose:
                    print(f"  Page {page_num}: bảng {ti} ({ft.row_count}r×{ft.col_count}c)")

            # Lấy text ngoài bảng (nếu có)
            if result.tables:
                # Dùng clip để loại vùng bảng
                tb_bboxes = [t.bbox for t in valid_tables]
                # Gom text các vùng ngoài bảng
                page_rect = page.rect
                # Vẽ từng vùng không có bảng — đơn giản nhất là get_text()
                # và bỏ các dòng nằm trong bảng
                all_lines = _page_text_blocks(page)
                outside_lines = []
                for line in all_lines:
                    bbox = line["bbox"]
                    inside_table = False
                    for tb in tb_bboxes:
                        if (bbox[0] >= tb[0] and bbox[2] <= tb[2] and
                                bbox[1] >= tb[1] and bbox[3] <= tb[3]):
                            inside_table = True
                            break
                    if not inside_table and line["text"].strip():
                        outside_lines.append(line["text"].strip())

                if outside_lines:
                    result.paragraphs = _merge_paragraphs(outside_lines)
                return result
    except Exception as e:
        if verbose:
            print(f"  Page {page_num}: find_tables() lỗi ({e}), chuyển sang positional")

    # ── Bước 2: Positional analysis ──────────────────────────────────────
    lines = _page_text_blocks(page)
    if len(lines) < 5:
        # Fallback trực tiếp
        raw = page.get_text()
        paras = [p.strip() for p in raw.split("\n\n") if p.strip()]
        result.paragraphs = paras
        return result

    zones = _detect_column_zones(lines, verbose=verbose)
    if len(zones) >= 2:
        table = _reconstruct_table_from_positions(lines, zones, verbose=verbose)
        if table and len(table.rows) >= 3:
            table.page = page_num
            result.tables.append(table)
            result.has_table_data = True
            return result

    # ── Bước 3: Fallback ─────────────────────────────────────────────────
    raw = page.get_text()
    paras = [p.strip() for p in raw.split("\n\n") if p.strip()]
    # Lọc bỏ dòng chỉ có số trang
    paras = [p for p in paras if not re.match(r"^\d+$", p)]
    result.paragraphs = paras
    return result


def _merge_paragraphs(lines: list[str]) -> list[str]:
    """Gom các dòng ngắn thành paragraph."""
    merged, buf = [], []
    for line in lines:
        line = line.strip()
        if not line:
            if buf:
                merged.append(" ".join(buf))
                buf = []
            continue
        if buf and (line[0].islower() or line[0] in ",;:-—"):
            buf.append(line)
        elif buf and len(line) < 60 and buf[-1][-1] not in ".!?":
            buf.append(line)
        else:
            if buf:
                merged.append(" ".join(buf))
            buf = [line]
    if buf:
        merged.append(" ".join(buf))
    return merged


# ── Output rendering ─────────────────────────────────────────────────────────


def render_output(
    results: list[PageResult],
    fmt: str = "txt",
    csv_prefix: str = "",
) -> str | dict:
    """Render kết quả thành text / csv / json.

    Args:
        results: Danh sách PageResult
        fmt: "txt" | "csv" | "json"
        csv_prefix: Đường dẫn gốc cho file CSV (nếu fmt="csv")

    Returns:
        str (txt/csv) hoặc dict (json)
    """
    if fmt == "json":
        return _render_json(results)

    if fmt == "csv":
        return _render_csv(results, csv_prefix)

    return _render_txt(results)


def _render_txt(results: list[PageResult]) -> str:
    """Render text với pipe‑table Markdown."""
    parts: list[str] = []
    for res in results:
        parts.append(f"\n--- Trang {res.page_num} ---\n")
        if res.tables:
            for ti, table in enumerate(res.tables):
                if ti > 0:
                    parts.append("")
                parts.append(table.to_markdown())
        if res.paragraphs:
            if res.tables:
                parts.append("")
            for p in res.paragraphs:
                parts.append(p)
        if not res.tables and not res.paragraphs:
            parts.append("(trang trống)")
    return "\n".join(parts).strip()


def _render_csv(results: list[PageResult], prefix: str) -> str:
    """Ghi mỗi bảng ra file CSV riêng, trả về đường dẫn tổng hợp."""
    saved: list[str] = []
    for res in results:
        for ti, table in enumerate(res.tables):
            if len(res.tables) > 1:
                name = f"{prefix}_trang{res.page_num}_bang{ti}.csv"
            else:
                name = f"{prefix}_trang{res.page_num}.csv"
            with open(name, "w", encoding="utf-8-sig", newline="") as f:
                f.write(table.to_csv())
            saved.append(name)
            print(f"  ✓ Đã lưu CSV: {name}")
    return "CSV files: " + "; ".join(saved) if saved else "(không có bảng)"


def _render_json(results: list[PageResult]) -> dict:
    """Render JSON có cấu trúc."""
    out = {"pages": []}
    for res in results:
        p = {"page": res.page_num}
        if res.tables:
            p["tables"] = []
            for t in res.tables:
                p["tables"].append({
                    "headers": t.headers,
                    "rows": t.rows,
                })
        if res.paragraphs:
            p["paragraphs"] = res.paragraphs
        out["pages"].append(p)
    return out


# ── CLI ──────────────────────────────────────────────────────────────────────


def parse_pages(s: str) -> list[int] | None:
    """Parse '18,19,20' → [18, 19, 20]; None = tất cả."""
    if not s:
        return None
    pages: list[int] = []
    for part in s.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            pages.extend(range(int(a), int(b) + 1))
        elif part:
            pages.append(int(part))
    return sorted(set(pages))


def main() -> int:
    import pymupdf  # lazy import

    ap = argparse.ArgumentParser(
        description="Crawl PDF — giữ cấu trúc bảng, dòng, cột, lề."
    )
    ap.add_argument("url", help="URL file PDF cần crawl")
    ap.add_argument("--out", help="File output (mặc định: data/raw/<slug>_<ts>.txt)")
    ap.add_argument("--csv", action="store_true",
                    help="Xuất CSV riêng cho từng bảng (kèm file text chính)")
    ap.add_argument("--json", action="store_true",
                    help="Xuất JSON có cấu trúc thay vì text")
    ap.add_argument("--pages", help="Chỉ crawl các trang (vd: '18,19,20' hoặc '18-21')")
    ap.add_argument("--keep-pdf", action="store_true",
                    help="Giữ lại file PDF gốc (.pdf) bên cạnh output")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="In thông tin phát hiện cột/bảng")
    ap.add_argument("--print", action="store_true",
                    help="In kết quả ra stdout ngoài việc lưu file")
    args = ap.parse_args()

    # ── Download ─────────────────────────────────────────────────────────
    print(f"→ Đang tải PDF: {args.url}")
    raw_bytes = fetch_pdf(args.url)
    print(f"  Đã tải {len(raw_bytes):,} bytes")

    # ── Mở PDF ───────────────────────────────────────────────────────────
    doc = pymupdf.open(stream=raw_bytes, filetype="pdf")
    total_pages = len(doc)
    print(f"  PDF có {total_pages} trang")

    pages_to_crawl = parse_pages(args.pages) or list(range(1, total_pages + 1))
    pages_to_crawl = [p for p in pages_to_crawl if 1 <= p <= total_pages]
    print(f"  Crawl {len(pages_to_crawl)} trang: {pages_to_crawl[0]}–{pages_to_crawl[-1]}")

    # ── Extract từng trang ───────────────────────────────────────────────
    results: list[PageResult] = []
    for pg in pages_to_crawl:
        page = doc[pg - 1]
        if args.verbose:
            print(f"\n  ⚙  Trang {pg}...")
        res = extract_page(page, pg, verbose=args.verbose)
        results.append(res)

    doc.close()

    # ── Render output ───────────────────────────────────────────────────
    slug = slugify(args.url)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Output mặc định: data/raw_pdf/ (text / json / pdf gốc đều ở đây)
    pdf_dir = os.path.join("data", "raw_pdf")
    os.makedirs(pdf_dir, exist_ok=True)

    if args.json:
        data = render_output(results, fmt="json")
        out_json = args.out or os.path.join(pdf_dir, f"{slug}_pdf_{ts}.json")
        os.makedirs(os.path.dirname(out_json) or ".", exist_ok=True)
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"  ✓ Đã lưu JSON: {out_json}")
        if args.print:
            print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        out_txt = args.out or os.path.join(pdf_dir, f"{slug}_pdf_{ts}.txt")
        os.makedirs(os.path.dirname(out_txt) or ".", exist_ok=True)
        txt = render_output(results, fmt="txt")
        with open(out_txt, "w", encoding="utf-8") as f:
            f.write(f"# Nguồn: {args.url}\n")
            f.write(f"# Crawl lúc: {datetime.now().isoformat(timespec='seconds')}\n")
            f.write(f"# Loại: pdf\n")
            f.write(f"# Trang: {pages_to_crawl[0]}–{pages_to_crawl[-1]}\n")
            f.write("\n" + "=" * 80 + "\n\n")
            f.write(txt)
        print(f"  ✓ Đã lưu text: {out_txt}")

        # CSV (nếu có --csv)
        if args.csv:
            csv_base = os.path.splitext(out_txt)[0]
            render_output(results, fmt="csv", csv_prefix=csv_base)

        if args.print:
            print("\n" + "=" * 80 + "\n")
            print(txt)

    # ── Lưu PDF gốc ─────────────────────────────────────────────────────
    if args.keep_pdf:
        out_pdf = os.path.join(pdf_dir, f"{slug}_pdf_{ts}.pdf")
        with open(out_pdf, "wb") as f:
            f.write(raw_bytes)
        print(f"  ✓ Đã lưu PDF gốc: {out_pdf}")

    # Thống kê
    n_tables = sum(len(r.tables) for r in results)
    n_paras = sum(len(r.paragraphs) for r in results)
    print(f"  📊 Kết quả: {n_tables} bảng, {n_paras} đoạn văn trên {len(pages_to_crawl)} trang")

    return 0


def slugify(url: str) -> str:
    p = urlparse(url)
    base = (p.path.strip("/").replace("/", "_") or p.netloc.replace(".", "_"))
    base = re.sub(r"[^A-Za-z0-9_\-]", "_", base)
    # Bỏ .pdf ở cuối nếu có
    base = re.sub(r"_pdf$", "", base, flags=re.IGNORECASE)
    return base[:80] or "pdf"


# ── Entry point ──────────────────────────────────────────────────────────────


if __name__ == "__main__":
    sys.exit(main())
