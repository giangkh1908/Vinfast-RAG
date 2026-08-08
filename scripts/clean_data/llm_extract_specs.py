#!/usr/bin/env python3
"""
llm_extract_specs.py — LLM-powered extraction of vehicle specifications.
Replaces the rule-based parse_specs.py with a semantic parser using OpenRouter (DeepSeek V4 Flash).
Extracts values based on docs/SPEC_SCHEMA.md.
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_BROCHURE_DIR = REPO_ROOT / "data" / "raw" / "brochure"
CLEAN_DIR = REPO_ROOT / "data" / "clean"
SCHEMA_PATH = REPO_ROOT / "docs" / "SPEC_SCHEMA.md"

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
MODEL_NAME = "deepseek/deepseek-v4-flash-0731"

MAX_RETRIES = 3
RETRY_DELAY = 2

VALID_KEYS = {
    "length_mm", "width_mm", "height_mm", "wheelbase_mm", "ground_clearance_mm",
    "power_kw", "torque_nm", "drivetrain",
    "battery_kwh", "range_km", "dc_charge_kw",
    "seats",
}

VALID_CATEGORIES = {"dimension", "powertrain", "battery", "interior"}

SANITY_RANGES: Dict[str, Tuple[float, float]] = {
    "length_mm": (2000, 6000),
    "width_mm": (1000, 2500),
    "height_mm": (1000, 2200),
    "wheelbase_mm": (1500, 3500),
    "ground_clearance_mm": (100, 300),
    "power_kw": (10, 600),
    "torque_nm": (30, 800),
    "battery_kwh": (10, 200),
    "range_km": (50, 1000),
    "dc_charge_kw": (3, 350),
    "seats": (2, 9),
}

KEY_TO_CATEGORY: Dict[str, str] = {
    "length_mm": "dimension",
    "width_mm": "dimension",
    "height_mm": "dimension",
    "wheelbase_mm": "dimension",
    "ground_clearance_mm": "dimension",
    "power_kw": "powertrain",
    "torque_nm": "powertrain",
    "drivetrain": "powertrain",
    "battery_kwh": "battery",
    "range_km": "battery",
    "dc_charge_kw": "battery",
    "seats": "interior",
}

KEY_TO_UNIT: Dict[str, str] = {
    "length_mm": "mm",
    "width_mm": "mm",
    "height_mm": "mm",
    "wheelbase_mm": "mm",
    "ground_clearance_mm": "mm",
    "power_kw": "kW",
    "torque_nm": "Nm",
    "drivetrain": "",
    "battery_kwh": "kWh",
    "range_km": "km",
    "dc_charge_kw": "kW",
    "seats": "",
}

MODEL_SOURCE_URLS: Dict[str, str] = {
    "VF2": "https://shop.vinfastauto.com/vn_vi/vf-2",
    "VF3": "https://shop.vinfastauto.com/vn_vi/vf-3",
    "VF5": "https://shop.vinfastauto.com/vn_ori/vf-5",
    "VF6": "https://shop.vinfastauto.com/vn_ori/vf-6",
    "VF7": "https://shop.vinfastauto.com/vn_ori/vf-7",
    "VF8": "https://shop.vinfastauto.com/vn_ori/vf-8",
    "VF8NEW": "https://shop.vinfastauto.com/vn_ori/vf-8-all-new",
    "VF9": "https://shop.vinfastauto.com/vn_ori/vf-9",
    "VFMPV7": "https://vinfastauto.com/vn_vi/dat-coc-xe-vf-mpv7",
}

MODEL_LABELS = {
    "VF2": "VF 2",
    "VF3": "VF 3",
    "VF5": "VF 5",
    "VF6": "VF 6",
    "VF7": "VF 7",
    "VF8": "VF 8",
    "VF8NEW": "VF 8 All New",
    "VF9": "VF 9",
    "VFMPV7": "VF MPV 7",
}

SYSTEM_PROMPT = """You are a precision data extraction agent for VinFast vehicle specifications.
Your task is to extract structured specifications from raw Vietnamese brochure text.

### SCHEMA
Only extract these exact spec_keys. Ignore everything else.

| Category | Key | Unit |
|---|---|---|
| dimension | length_mm | mm |
| dimension | width_mm | mm |
| dimension | height_mm | mm |
| dimension | wheelbase_mm | mm |
| dimension | ground_clearance_mm | mm |
| powertrain | power_kw | kW |
| powertrain | torque_nm | Nm |
| powertrain | drivetrain | (empty) |
| battery | battery_kwh | kWh |
| battery | range_km | km |
| battery | dc_charge_kw | kW |
| interior | seats | (empty) |

### RULES
1. Extract ONLY numeric values, strip units. "3967 mm" -> "3967".
2. Drivetrain: normalize to FWD / RWD / AWD. "Cầu trước" -> FWD, "Cầu sau" -> RWD, "2 cầu" -> AWD.
3. "Dài x Rộng x Cao" (e.g., "4701 x 1872 x 1670") -> split into length_mm, width_mm, height_mm.
4. Vietnamese decimal comma: "59,6" -> "59.6", "1.635,75" -> "1635.75" (dot=thousands, comma=decimal).
5. power_kw: if label says "(kW/Hp)" or "(hp/kW)", extract the kW value (not hp).
   Example: "150/201" with label "(kW/Hp)" -> 150. "402/300" with label "(hp/kW)" -> 300.
6. range_km: prefer NEDC over WLTP if both exist.
7. If specs differ by edition, create separate rows with the edition name.
   Common editions: Eco, Plus, PlusCaptain. If same value for all editions, use null.
8. Only extract if value is EXPLICITLY in the text. Do NOT guess or calculate.
9. If a spec is mentioned but has no value (e.g., "Dung lượng pin (kWh)" with no number), skip it.

### OUTPUT
Return ONLY a JSON object: {"specs": [...]}
Each element: {"spec_key": "...", "spec_value": "...", "spec_unit": "...", "spec_category": "...", "edition": "..." or null}

Example:
{"specs": [
  {"spec_key": "length_mm", "spec_value": "4701", "spec_unit": "mm", "spec_category": "dimension", "edition": null},
  {"spec_key": "power_kw", "spec_value": "130", "spec_unit": "kW", "spec_category": "powertrain", "edition": "Eco"},
  {"spec_key": "power_kw", "spec_value": "150", "spec_unit": "kW", "spec_category": "powertrain", "edition": "Plus"}
]}"""


def clean_text(text: str) -> str:
    text = re.sub(r"\[Image:[^\]]*\]", "", text)
    text = re.sub(r"^\d+\s*\|\s*VinFast", "", text, flags=re.MULTILINE)
    text = re.sub(r"VinFast\s*\|\s*\d+", "", text)
    # Do not remove standalone numbers: brochure PDFs often put labels and
    # values on separate lines (notably VF5/VF6).
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_source_url(text: str, path: Path) -> str:
    for line in text.splitlines():
        if line.startswith("# Nguồn:"):
            return line.split(":", 1)[1].strip()
    model_id = infer_model_id_from_path(path)
    return MODEL_SOURCE_URLS.get(model_id, "")


def call_llm(messages: List[Dict[str, str]], temperature: float = 0.0) -> Optional[str]:
    if not OPENROUTER_API_KEY:
        print("Error: OPENROUTER_API_KEY not set.")
        return None

    payload: Dict[str, Any] = {
        "model": MODEL_NAME,
        "messages": messages,
        "temperature": temperature,
    }
    if "deepseek" in MODEL_NAME:
        payload["response_format"] = {"type": "json_object"}

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.post(
                url="https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "HTTP-Referer": "https://vinfast-specs-extractor.local",
                    "X-Title": "VinFast Specs Extractor",
                    "Content-Type": "application/json",
                },
                data=json.dumps(payload),
                timeout=120,
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"  Attempt {attempt}/{MAX_RETRIES} failed: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)
    return None


def parse_llm_response(content: str) -> List[Dict[str, Any]]:
    if not content:
        return []

    if "```json" in content:
        content = content.split("```json")[1].split("```")[0].strip()
    elif "```" in content:
        content = content.split("```")[1].split("```")[0].strip()

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return []

    if isinstance(data, dict):
        if "specs" in data and isinstance(data["specs"], list):
            return data["specs"]
        for v in data.values():
            if isinstance(v, list):
                return v
    if isinstance(data, list):
        return data
    return []


def normalize_number(value: str) -> Optional[str]:
    """Normalize Vietnamese/OCR number formatting and strip an optional unit."""
    value = re.sub(r"[*`]", "", str(value or "")).strip()
    value = re.sub(r"\s*(?:mm|kw|kwh|nm|km|inch|ghế|ghe)\b", "", value,
                   flags=re.IGNORECASE).strip()
    match = re.search(r"\d[\d.,]*", value)
    if not match:
        return None
    token = match.group(0)
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", token):
        token = token.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d+,\d+", token):
        token = token.replace(",", ".")
    try:
        number = float(token)
    except ValueError:
        return None
    return str(int(number)) if number.is_integer() else f"{number:g}"


def validate_spec(spec: Dict[str, Any]) -> bool:
    key = spec.get("spec_key", "")
    if key not in VALID_KEYS:
        return False

    value_str = str(spec.get("spec_value", "")).strip()
    if not value_str:
        return False

    if key in SANITY_RANGES:
        normalized = normalize_number(value_str)
        if normalized is None:
            return False
        value_str = normalized
        val = float(value_str)
        lo, hi = SANITY_RANGES[key]
        if val < lo or val > hi:
            print(f"    Sanity FAIL: {key}={val} outside [{lo}, {hi}]")
            return False

    if key == "drivetrain":
        if value_str.upper() not in ("FWD", "RWD", "AWD"):
            return False
        spec["spec_value"] = value_str.upper()
    else:
        spec["spec_value"] = value_str

    spec["spec_category"] = KEY_TO_CATEGORY.get(key, spec.get("spec_category", ""))
    spec["spec_unit"] = KEY_TO_UNIT.get(key, spec.get("spec_unit", ""))

    return True


def get_llm_specs(text: str, model_id: str, source_url: str) -> List[Dict[str, Any]]:
    cleaned = clean_text(text)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Model: {model_id}\nSource: {source_url}\n\n{cleaned}"},
    ]

    content = call_llm(messages)
    raw_specs = parse_llm_response(content or "")

    valid = []
    seen = set()
    for s in raw_specs:
        if not validate_spec(s):
            continue
        edition = s.get("edition") or ""
        dedup_key = (s["spec_key"], edition)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        valid.append(s)

    return valid


def infer_model_id_from_path(path: Path) -> str:
    # Normalize separators so names such as vf8-the-new are recognized.
    name = re.sub(r"[^a-z0-9]", "", path.stem.lower())
    for key, mid in [("vfe34", "VFE34"), ("mpv7", "VFMPV7"),
                       ("vf2", "VF2"), ("vf3", "VF3"), ("vf5", "VF5"),
                       ("vf6", "VF6"), ("vf7", "VF7"),
                       ("vf8theallnew", "VF8NEW"), ("vf8thenew", "VF8NEW"),
                       ("vf8allnew", "VF8NEW"), ("vf8new", "VF8NEW"),
                       ("vf8", "VF8"), ("vf9", "VF9")]:
        if key in name:
            return mid
    return "Unknown"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="v1", help="Clean data version")
    args = parser.parse_args()

    output_file = CLEAN_DIR / args.version / "postgres" / "specs.csv"
    output_file.parent.mkdir(parents=True, exist_ok=True)

    all_extracted: List[List[str]] = []
    raw_files = sorted(RAW_BROCHURE_DIR.glob("*"))

    print(f"Processing {len(raw_files)} files from {RAW_BROCHURE_DIR}...")

    for f_path in raw_files:
        if f_path.suffix not in (".txt", ".md"):
            continue

        model_id = infer_model_id_from_path(f_path)
        if model_id == "Unknown":
            continue

        raw_text = f_path.read_text(encoding="utf-8", errors="replace")
        source_url = parse_source_url(raw_text, f_path)

        if "====" in raw_text:
            raw_text = raw_text.split("====", 1)[1]

        print(f"Extracting {model_id} from {f_path.name}...")
        specs = get_llm_specs(raw_text, model_id, source_url)

        for s in specs:
            edition = s.get("edition") or ""
            row = [
                MODEL_LABELS.get(model_id, model_id),
                edition,
                "",
                s.get("spec_category", ""),
                s.get("spec_key", ""),
                s.get("spec_value", ""),
                s.get("spec_unit", ""),
                source_url,
            ]
            all_extracted.append(row)

        print(f"  -> {len(specs)} valid specs extracted")

    with open(output_file, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="|")
        writer.writerow(["model_code", "version_name", "version_code", "spec_category",
                         "spec_key", "spec_value", "spec_unit", "source_url"])
        writer.writerows(all_extracted)

    print(f"\nDone! Saved {len(all_extracted)} spec rows to {output_file}")


if __name__ == "__main__":
    main()
