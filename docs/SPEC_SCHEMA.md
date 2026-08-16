# SPEC_SCHEMA — Thông số kỹ thuật (car_specs)

> Contract cho bảng `car_specs` (Postgres) / `data/clean/<ver>/postgres/specs.csv`.
>
> **Nguồn duy nhất: `data/model_data/*.csv`** (spec sheets 2 cột label, value —
> export từ bảng spec brochure chính hãng) — extract **toàn bộ** spec (BASIC_SPECS
> lẫn feature specs: nội thất, ngoại thất, an toàn, ADAS, túi khí, giải trí...).
> Mỗi file = 1 model + 1 edition (edition đọc từ row "PHIÊN BẢN").
>
> Script: `parse_specs.py` lookup LABEL_MAP trước, fallback FEATURE_NORM_MAP
> (150+ feature aliases) nếu label không phải spec cơ bản.

## BASIC_SPECS Whitelist (12 key, 4 category)

| Category | Key | Nhãn VN | unit | Ghi chú |
|---|---|---|---|---|
| `dimension` | length_mm | Dài | mm | |
| `dimension` | width_mm | Rộng | mm | |
| `dimension` | height_mm | Cao | mm | |
| `dimension` | wheelbase_mm | Chiều dài cơ sở | mm | |
| `dimension` | ground_clearance_mm | Khoảng sáng gầm | mm | |
| `powertrain` | power_kw | Công suất | kW | |
| `powertrain` | torque_nm | Mô-men xoắn | Nm | |
| `powertrain` | drivetrain | Dẫn động | — | value chuẩn: `FWD` / `RWD` / `AWD` |
| `battery` | battery_kwh | Dung lượng pin | kWh | |
| `battery` | range_km | Quãng đường | km | |
| `battery` | dc_charge_kw | Sạc nhanh DC | kW | |
| `interior` | seats | Số chỗ ngồi | — | |

Ngoài BASIC_SPECS, `parse_specs.py` còn extract **feature specs** (mở rộng):
nội thất, ngoại thất, ADAS, an toàn, túi khí, giải trí, kết nối, tiện nghi —
từ bảng so sánh edition trong brochure PDF.

## Chuẩn hóa value

- `spec_value` chỉ chứa số / thuần text; đơn vị tách riêng `spec_unit` (riêng
  `drivetrain`, `seats` để unit rỗng).
- Số phải qua sanity range (`SANITY_RANGES`) — value ngoài khoảng = junk → drop.
- `drivetrain` chuẩn hóa về `FWD` / `RWD` / `AWD` (bỏ "Cầu trước"/"Cầu sau").
- `range_km` / `battery_kwh`: nếu nguồn ghi đồng thời NEDC + WLTP → ưu tiên NEDC
  (VinFast marketing dùng NEDC).
- `dimension` label dạng "Dài x Rộng x Cao" → tách 3 row `length_mm`/`width_mm`/`height_mm`.

## Nguồn

- Chỉ từ `data/model_data/*.csv` (spec sheets — chạy `parse_specs.py`).
- Mỗi file = 1 model + 1 edition (edition đọc từ row "PHIÊN BẢN").
- ⚠️ **`power_kw` lấy token số đầu tiên của label `Công suất tối đa`**. Nếu label có
  dạng `(kW/Hp)` / `(hp/kW)` (VD VF 8: `150/201`), parser lấy **hp** thay vì kW →
  cảnh báo dữ liệu nhưng hiện chưa tự đổi.
- ⚠️ **VF 8 All New** (layout "labels-then-values") chưa get được range/DC/FWD.

## CSV columns (`postgres/specs.csv`)

```
model_code|version_name|version_code|spec_category|spec_category_vn|spec_key|spec_key_vn|spec_value|spec_unit|source_url
```

| Cột | Ví dụ | Ghi chú |
|---|---|---|
| `model_code` | `VF 8` | MODEL_LABEL |
| `version_name` | `Eco` | Edition; rỗng = chung mọi bản |
| `spec_category` | `powertrain` | Category key |
| `spec_category_vn` | `Hệ thống truyền động` | Category VN label |
| `spec_key` | `range_km` | Spec key |
| `spec_key_vn` | `Phạm vi di chuyển` | Spec key VN label |
| `spec_value` | `562 (NEDC)` | Giá trị gốc từ brochure |
| `spec_unit` | `km` | Đơn vị |
| `source_url` | `model_data/vf8-eco.csv` | Path file CSV nguồn |

## Metadata / version

- `model_code`, `version_name`, `version_code` chuẩn hóa từ `car_catalog` (API
  `omapi.vinfastauto.com/fe/v1/carModel`), không tự bịa.
- `source_url` = path tương đối file CSV nguồn (`model_data/<file>.csv`, để audit).

## Liên quan

- Bảng: `docs/DATA_SCHEMA_SPEC.md` §5.x `car_specs`.
- Pipeline: `docs/DATA_PIPELINE.md` bước 3/6 `parse_specs.py`.
- Tool đọc: `get_specs(model_code, version)` — nên dùng VIEW `car_specs_active` thay vì query trực tiếp base table (hỗ trợ rollback version).
- Versioning: `car_specs` có `ingest_version` column — rollback specs được support (cùng với edition/price_list).
