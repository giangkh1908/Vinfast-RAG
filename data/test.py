import re
from pathlib import Path

import fitz  # PyMuPDF
import pdfplumber


# ==========================
# CONFIG
# ==========================

PDF_PATH = "VF5.pdf"

OUTPUT_MD = "VF5.md"

TITLE = "VF5 Brochure"

VEHICLE = "VF5"

URL = "https://..."

VERIFY_DATE = "2026-07-28"


# ==========================
# TEXT
# ==========================

def extract_text(pdf_path):

    doc = fitz.open(pdf_path)

    text = ""

    for page in doc:

        text += page.get_text()

        text += "\n"

    return text


# ==========================
# TABLES
# ==========================

def extract_tables(pdf_path):

    rows = []

    with pdfplumber.open(pdf_path) as pdf:

        for page in pdf.pages:

            tables = page.extract_tables()

            for table in tables:

                for row in table:

                    if not row:
                        continue

                    cleaned = []

                    for cell in row:

                        if cell:

                            cell = re.sub(r"\s+", " ", cell)

                            cleaned.append(cell.strip())

                        else:

                            cleaned.append("")

                    rows.append(cleaned)

    return rows


# ==========================
# PAIR FIELD VALUE
# ==========================

def table_to_dict(rows):

    result = {}

    for row in rows:

        if len(row) < 2:
            continue

        for i in range(0, len(row)-1, 2):

            key = row[i].strip()

            value = row[i+1].strip()

            if key:

                result[key] = value

    return result


# ==========================
# FIND VALUE
# ==========================

def get(data, *keys):

    for k in keys:

        if k in data:

            return data[k]

    return ""


# ==========================
# MARKDOWN
# ==========================

def build_markdown(spec):

    md = f"""---
url: "{URL}"
title: "{TITLE}"
vehicle: "{VEHICLE}"
language: "vi"
source: "official brochure"
last_verified: "{VERIFY_DATE}"
---

## THÔNG SỐ KỸ THUẬT

### Kích thước

- Dài × Rộng × Cao (mm): {get(spec,"Dài x Rộng x Cao","Dài × Rộng × Cao")}
- Chiều dài cơ sở (mm): {get(spec,"Chiều dài cơ sở")}
- Khoảng sáng gầm (mm): {get(spec,"Khoảng sáng gầm")}

### Động cơ

- Công suất tối đa: {get(spec,"Công suất tối đa")}
- Mô-men xoắn cực đại: {get(spec,"Mô men xoắn cực đại")}
- Tốc độ tối đa: {get(spec,"Tốc độ tối đa")}

## PIN

- Dung lượng pin: {get(spec,"Dung lượng pin")}
- Quãng đường: {get(spec,"Quãng đường")}
- Công suất sạc AC: {get(spec,"Sạc AC")}
- Công suất sạc DC: {get(spec,"Sạc DC")}

## NGOẠI THẤT

### Đèn

- Đèn trước: {get(spec,"Đèn trước")}
- Đèn hậu: {get(spec,"Đèn hậu")}

## NỘI THẤT

### Tiện nghi

- Điều hòa: {get(spec,"Điều hòa")}
- Màn hình trung tâm: {get(spec,"Màn hình trung tâm")}
- Âm thanh: {get(spec,"Âm thanh")}

## AN TOÀN

- ABS: {get(spec,"ABS")}
- EBD: {get(spec,"EBD")}
- ESC: {get(spec,"ESC")}
- TCS: {get(spec,"TCS")}

## MÀU SẮC

- {get(spec,"Màu sắc")}
"""

    return md


# ==========================
# MAIN
# ==========================

if __name__ == "__main__":

    text = extract_text(PDF_PATH)

    tables = extract_tables(PDF_PATH)

    spec = table_to_dict(tables)

    markdown = build_markdown(spec)

    Path(OUTPUT_MD).write_text(markdown, encoding="utf8")

    print("Done.")