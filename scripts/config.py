#!/usr/bin/env python3
"""
config.py — Cấu hình dùng chung cho pipeline scripts.

Mọi script nên import từ đây thay vì tự khai báo lại:
  - Paths chuẩn (REPO_ROOT, data dirs)
  - sys.path setup cho `from scripts...` và `from lib...` import
  - Env vars DB (QDRANT_URL, QDRANT_API_KEY, PG_DSN, QDRANT_TIMEOUT)

.env được load NGAY khi import module này (python-dotenv) — script không cần
gọi load_dotenv() riêng. Lưu ý: nếu script đọc os.environ ở module level,
phải import config TRƯỚC (import config là đủ).
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
RAW_PDF_DIR = DATA_DIR / "raw_pdf"
MODEL_DATA_DIR = DATA_DIR / "model_data"
CLEAN_DIR = DATA_DIR / "clean"

# Cho phép `from scripts... import` và `from lib... import` từ mọi nơi
sys.path.insert(0, str(REPO_ROOT))

load_dotenv(REPO_ROOT / ".env")

QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:16333")
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY", "")
PG_DSN = os.environ.get("PG_DSN", "postgresql://vivu:vivu@localhost:15432/vivu")
QDRANT_TIMEOUT = int(os.environ.get("QDRANT_TIMEOUT", "300"))
