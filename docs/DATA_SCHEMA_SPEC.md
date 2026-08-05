# Data Schema Spec — 2 DB cho pipeline RAG (Qdrant + PostgreSQL)

> Tài liệu chuẩn (contract) cho phần **Data**. Mọi trường, mục, bảng của 2 DB
> được gom vào 1 file để bên khác merge vào là chạy end-to-end phần data.
>
> **Cấu trúc file:** Phần đầu = **toàn bộ schema đầy đủ** (tra nhanh). Phần sau
> = **giải thích** từng trường / bảng / quy ước.
>
> Trạng thái pipeline hiện tại (version `v1`): clean → vector JSONL + postgres
> CSV → ingest Qdrant + PostgreSQL. Tham khảo triển khai tại
> `scripts/ingest/`, `scripts/clean_data/` (trên nhánh `demo-giang`).

---

## MỤC LỤC SCHEMA (tra nhanh)

- [1. Tổng quan 2 DB](#1-tổng-quan-2-db)
- [2. Schema Qdrant — Vector](#2-schema-qdrant--vector)
  - [2.1. Dense collections](#21-dense-collections)
  - [2.2. Chunk payload (full fields)](#22-chunk-payload-full-fields)
  - [2.3. Sparse collection (BM25)](#23-sparse-collection-bm25)
- [3. Schema PostgreSQL](#3-schema-postgresql)
  - [3.1. DDL đầy đủ](#31-ddl-đầy-đủ)
  - [3.2. CSV nguồn (đầu vào ingest)](#32-csv-nguồn-đầu-vào-ingest)
- [4. `_manifest.json`](#4-_manifestjson)
- [5. Giải thích từng phần](#5-giải-thích-từng-phần)
- [6. Quy ước id / khóa join / routing](#6-quy-ước-id--khóa-join--routing)
- [7. Phụ thuộc & môi trường](#7-phụ-thuộc--môi-trường)

---

## 1. Tổng quan 2 DB

| DB | Loại | Vai trò | Đổi bao lâu | Update |
|---|---|---|---|---|
| **Qdrant** (vector) | Cold | Kiến thức "cứng": specs, mô tả, chính sách, FAQ, link bảo dưỡng | tháng / quý | re-embed đắt → đánh version |
| **PostgreSQL** | Hot | Số liệu "hay đổi": giá niêm yết + ưu đãi | ngày / tuần / chiến dịch | UPSERT rẻ, 1 câu SQL |
| **Link-only** (manifest) | — | Bảo dưỡng, showroom, khuyến mãi, lăn bánh | liên tục | KHÔNG vào DB, chỉ trả link |

**Khóa join trung tâm:** `model_id` + `edition_id` (VD `VF9` + `Eco`).

**Nguyên tắc cứng:** Text vector **KHÔNG** chứa số tiền. Giá chỉ nằm trong
PostgreSQL, được tra tại thời điểm query → không bao giờ trả giá cũ.

```
data/raw/*.txt ──► clean_to_jsonl.py ──► intermediate/{vector,hot}.jsonl + link_only.json
                                          │
                                          ▼
                                     split_cold_hot.py
                                          │
                    ┌─────────────────────┴─────────────────────┐
                    ▼                                            ▼
        data/clean/<ver>/vector/*.jsonl                data/clean/<ver>/postgres/*.csv
                    │                                            │
          vector_ingest.py + sparse_ingest.py          postgres_ingest.py
                    │                                            │
                    ▼                                            ▼
              Qdrant (dense + sparse)                    PostgreSQL
```

**Chunking 1 lần, phân nhiều thùng.** Cắt chunk chỉ diễn ra **1 lần** ở bước
`clean_to_jsonl.py` (theo `max_len=400` chars, nhận biết câu, overlap câu cuối)
→ ra **1 file gộp** `intermediate/vector.jsonl` (mỗi dòng 1 chunk, đã gán sẵn
`collection` theo `category`). Bước `split_cold_hot.py` **không cắt lại** — chỉ
đọc file gộp đó và **chia dòng theo trường `collection`** thành nhiều file
`vector/<collection>.jsonl` (1 file = 1 Qdrant collection). Tổng chunk không đổi:
2333 = 250 + 1447 + 546 + 90 (xem §2.1).

---

## 2. Schema Qdrant — Vector

### 2.1. Dense collections

| Collection | category nguồn | Nội dung | chunks (v1) |
|---|---|---|---|
| `vivu_specs` | `thong_so_ky_thuat` | Thông số kỹ thuật, so sánh, đối chiếu | 250 |
| `vivu_product_info` | `thong_tin_san_pham` | Mô tả sản phẩm, tính năng, dat-coc (không giá) | 1447 |
| `vivu_policy` | `chinh_sach_dich_vu` | Chính sách bảo hành, thuê pin, điều khoản pháp lý, cứu hộ | 546 |
| `vivu_maintenance` | `dat_lich_bao_duong` | Text chung về dịch vụ bảo dưỡng (KHÔNG phải lịch theo xe) | 90 |
| `vivu_faq` *(định nghĩa, chưa có data ở v1)* | `ho_tro_mua_xe` | FAQ bán hàng / lái thử | 0 |

**Cấu hình collection (dense):**

| Tham số | Giá trị |
|---|---|
| Vector size | `1536` (auto-detect từ API probe) |
| Distance | `Cosine` |
| Embed model | `openai/text-embedding-3-small` (qua OpenRouter) |
| Point id | `uuid5(namespace=6ba7b810-9dad-11d1-80b4-00c04fd430c8, chunk_id)` — deterministic từ `id` |
| Upsert batch | 100 points / request |

> Retriever đọc 4 collection `vivu_specs`, `vivu_product_info`, `vivu_policy`,
> `vivu_maintenance`. `vivu_faq` là collection dự phòng (route `ho_tro_mua_xe`),
> chưa có chunk trong v1.

### 2.2. Chunk payload (full fields)

Mỗi dòng trong `data/clean/<ver>/vector/<collection>.jsonl` = 1 chunk. **Toàn
bộ trường (JSON, 1 dòng compact):**

```jsonc
{
  "id":            "vivu_specs:vf8:all:thong_so_ky_thuat:1",
  "collection":    "vivu_specs",
  "vector_version":"v1",
  "model_id":      "VF8",          // nullable
  "edition_id":    null,           // nullable (v1 hiện = null cho mọi chunk)
  "category":     "thong_so_ky_thuat",
  "section_path":  ["thong_so_ky_thuat", "Bảng Đối Chiếu Thông Số ..."],
  "text":         "...",           // KHÔNG chứa số tiền (guard has_money)
  "text_type":    "list",          // prose|table|list|key_value|qa_pair|legal_clause|link_list
  "structured":   {},             // object, tuỳ loại (dimension/powertrain/adas/...)
  "language":     "vi",
  "tags":         ["thongsokythuat", "vf8"],
  "confidence":   0.8,             // 1.0 = verify thủ công; <1.0 = OCR/crawl lỗi
  "source_file":  "data/raw/..._20260730_225643.txt",
  "source_url":   "https://...",
  "source_type":  "raw_html",     // raw_html | raw_pdf | brochure | product_page | faq | ...
  "fetched_at":   "2026-07-30T22:56:43",
  "ingested_at":  "2026-08-03T07:21:26Z",
  "is_hot":       false           // flag cold/hot — KHÔNG được đưa vào Qdrant payload
}
```

**Payload thực tế ghi vào Qdrant** = toàn bộ trường **TRỪ** `{id, text, is_hot}`:

```
collection, vector_version, model_id, edition_id, category, section_path,
text_type, structured, language, tags, confidence, source_file, source_url,
source_type, fetched_at, ingested_at
```

### 2.3. Sparse collection (BM25)

| Tham số | Giá trị |
|---|---|
| Tên collection | `sparse` (cố định, không theo category) |
| Loại vector | SparseVector (BM25/TF-IDF, tự build vocab) |
| Index params | `SparseIndexParams(on_disk=False)` |
| BM25 params | `k1 = 1.5`, `b = 0.75` |
| Tokenizer | NFC normalize → `[a-zà-ỹ0-9]+` → bỏ stopword VI → len > 1 |
| Point id | `uuid5(...)` như dense (cùng namespace, cùng `chunk_id`) → **join được** |

**Payload sparse** (chỉ 3 trường, tối giản để filter):

```jsonc
{ "collection": "vivu_specs", "chunk_id": "vivu_specs:vf8:all:...:1", "model_id": "VF8" }
```

**File index đi kèm** — `data/clean/<ver>/sparse_index.json` (retriever encode
query bằng cùng vocab/idf):

```jsonc
{ "version": "v1", "vocab": { "<term>": <int_idx>, ... }, "idf": [<float>, ...],
  "avgdl": 123.4, "n_docs": 2333, "k1": 1.5, "b": 0.75 }
```

---

## 3. Schema PostgreSQL

- **DSN mặc định:** `postgresql://vivu:vivu@localhost:5432/vivu`
- **Container:** `vivu_postgres` (image `postgres:16-alpine`, xem `docker-compose.yml`)
- **Charset:** UTF-8. CSV nguồn dùng delimiter `|`.

### 3.1. DDL đầy đủ

```sql
-- Bảng trung tâm: mỗi model × edition = 1 row
CREATE TABLE IF NOT EXISTS edition (
    model_id        TEXT NOT NULL,         -- "VF9" (chuẩn hoá, không dấu cách)
    edition_id      TEXT NOT NULL,         -- "Eco" | "Plus" | "PlusCaptain" | "TieuChuan" | "NangCao" | "CaoCap"
    model_label     TEXT NOT NULL,         -- "VF 9" (hiển thị)
    edition_label   TEXT NOT NULL,         -- "Eco"
    year_range      TEXT,                  -- "2025-2026" | "2026"
    is_active       BOOLEAN DEFAULT true,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (model_id, edition_id)
);

-- Giá — đổi liên tục, join qua (model_id, edition_id)
CREATE TABLE IF NOT EXISTS price_list (
    model_id            TEXT NOT NULL,
    edition_id          TEXT NOT NULL,
    price_list_vnd      BIGINT,            -- giá niêm yết gốc
    price_promo_vnd     BIGINT,            -- giá ưu đãi hiện hành (nullable)
    promo_label         TEXT,              -- "Ưu đãi đặt cọc 2026"
    vat_included        BOOLEAN DEFAULT true,
    battery_included    BOOLEAN DEFAULT true,
    valid_from          DATE,
    valid_to            DATE,              -- NULL = vẫn còn hiệu lực
    updated_at          TIMESTAMPTZ DEFAULT now(),
    source_url          TEXT,
    PRIMARY KEY (model_id, edition_id, valid_from),
    FOREIGN KEY (model_id, edition_id) REFERENCES edition(model_id, edition_id)
);
CREATE INDEX IF NOT EXISTS idx_price_active
    ON price_list(model_id, edition_id) WHERE valid_to IS NULL;

-- Tracking version ingest
CREATE TABLE IF NOT EXISTS ingest_version (
    version                 TEXT PRIMARY KEY,   -- "v1", "v2" ...
    created_at              TIMESTAMPTZ DEFAULT now(),
    prev_version            TEXT,
    repo_commit             TEXT,
    vector_chunks_added     INT,
    vector_chunks_modified  INT,
    vector_chunks_removed   INT,
    pg_rows_upserted        INT,
    notes                   TEXT
);
```

**Upsert semantics** (xem `postgres_ingest.py`):

| Bảng | Conflict key | Cập nhật các trường |
|---|---|---|
| `edition` | `(model_id, edition_id)` | model_label, edition_label, year_range, is_active, updated_at |
| `price_list` | `(model_id, edition_id, valid_from)` | price_list_vnd, price_promo_vnd, promo_label, vat_included, battery_included, valid_to, updated_at, source_url |
| `ingest_version` | `(version)` | toàn bộ cột (từ `_manifest.json`) |

### 3.2. CSV nguồn (đầu vào ingest)

Delimiter `|`. Header chính xác:

**`postgres/edition.csv`**
```
model_id|edition_id|model_label|edition_label|year_range|is_active|created_at|updated_at
VF3|Eco|VF 3|Eco|2026|t|2026-08-03T07:21:28Z|2026-08-03T07:21:28Z
```

**`postgres/price_list.csv`**
```
model_id|edition_id|price_list_vnd|price_promo_vnd|promo_label|vat_included|battery_included|valid_from|valid_to|updated_at|source_url
VF3|Eco|285000000|270750000|Ưu đãi đặt cọc 2026|t|t|2026-07-01||2026-08-03T07:21:28Z|https://shop.vinfastauto.com/vn_vi/dat-coc-xe-dien-vf3.html
```

> Bool trong CSV = `t`/`f`; cột trống = NULL. `price_promo_vnd` trống khi không
> có ưu đãi; `valid_to` trống = vẫn còn hiệu lực.

---

## 4. `_manifest.json`

Index mỗi version (`data/clean/<ver>/_manifest.json`). Schema đầy đủ:

```jsonc
{
  "version": "v1",
  "created_at": "2026-08-03T07:21:28Z",
  "created_by": "scripts/clean_to_jsonl.py + scripts/split_cold_hot.py",
  "prev_version": null,
  "repo_commit": "27425c9",

  "vector": {
    "collections": {
      "<collection>": {
        "file": "vector/<collection>.jsonl",
        "chunks": 250, "added": 250, "modified": 0, "removed": 0
      }
    },
    "total_chunks": 2333, "total_added": 2333, "total_modified": 0, "total_removed": 0
  },

  "postgres": {
    "tables": {
      "edition":              { "file": "postgres/edition.csv",    "rows": 14, "upserted": 14 },
      "price_list":           { "file": "postgres/price_list.csv", "rows": 14, "upserted": 14, "price_changed": 11 }
    },
    "total_rows_upserted": 28
  },

  "link_only": {
    "maintenance_url":    "https://vinfastauto.com/vn_vi/dich-vu-bao-duong-oto",
    "brochure_urls":      ["https://..."],
    "brochure_by_model":  { "VF2": ["https://..."], "VF8": ["...", "..."] },
    "showroom_urls":      [],
    "promotion_urls":     [],
    "roadside_cost_urls": []
  },

  "pipeline_steps": ["clean_to_jsonl", "split_cold_hot"],
  "schema_version": "1.0.0"
}
```

---

## 5. Giải thích từng phần

### 5.1. Tại sao chia 2 DB

| Loại kiến thức | Ví dụ | Đặc điểm | Nơi lưu |
|---|---|---|---|
| Cứng (cold) | "VF 9 dài bao nhiêu? Có ADAS gì?" | Ít đổi, tra theo nghĩa | Qdrant |
| Hay đổi (hot) | "VF 9 Eco giá bao nhiêu hôm nay?" | Đổi theo chiến dịch, cần số chính xác | PostgreSQL |
| Cực hay đổi / địa phương | Lăn bánh, khuyến mãi, showroom | Đổi theo tỉnh/năm/đại lý | KHÔNG lưu DB — trả link |

Nếu lưu giá vào vector: VinFast đổi giá → phải tìm/xóa/re-embed đoạn text → tốn
kém + nguy cơ trả giá cũ. Nên text vector chỉ nói *"xe có giá, xem giá hiện
hành"*; con số lấy từ Postgres lúc query.

### 5.2. Chunk — từng trường

| Trường | Kiểu | Bắt buộc | Giải thích |
|---|---|---|---|
| `id` | string | ✓ | Stable, định danh chunk. **Không vào payload Qdrant** (dùng làm nguồn sinh uuid5). Quy ước ở §6 |
| `collection` | string | ✓ | Tên Qdrant collection, khớp tên file `.jsonl` |
| `vector_version` | string | ✓ | `= version` (`v1`, `v2`...) |
| `model_id` | string\|null | ✓* | `VF9`, `VF8`... Bắt buộc khi chunk gắn 1 xe; `null` cho policy/maintenance chung |
| `edition_id` | string\|null | ✓* | `Eco`, `Plus`, `PlusCaptain`, `TieuChuan`, `NangCao`, `CaoCap`. `null` nếu không theo phiên bản (v1 hiện null cho mọi chunk) |
| `category` | string | ✓ | Category ngữ nghĩa: `thong_so_ky_thuat` / `thong_tin_san_pham` / `chinh_sach_dich_vu` / `dat_lich_bao_duong` / `ho_tro_mua_xe` |
| `section_path` | string[] | ✓ | Bread-crumb heading. `[0]` = category, `[-1]` = section hiện tại |
| `text` | string | ✓ | Nội dung clean. **Không chứa số tiền** (guard `has_money` ở split, drop chunk nếu vi phạm) |
| `text_type` | enum | ✓ | `prose` \| `table` \| `list` \| `key_value` \| `qa_pair` \| `legal_clause` \| `link_list` |
| `structured` | object | ✓ | Trường hoá structured (vd `{"dimension": {...}}`). `{}` nếu không có |
| `language` | string | ✓ | Mặc định `vi` |
| `tags` | string[] | ✓ | Token retrieval phụ; `[category_không_gạch, model_id_lower]` |
| `confidence` | float | ✓ | `1.0` = verify thủ công; `<1.0` = OCR/crawl có rủi ro |
| `source_file` | string | ✓ | Path tương đối repo của file gốc |
| `source_url` | string | ✓ | URL gốc (cho citation) |
| `source_type` | string | ✓ | `raw_html` \| `raw_pdf` \| `brochure` \| `product_page` \| `faq` \| `policy_legal` \| `maintenance_link` \| `specs_json` ... |
| `fetched_at` | string | ✓ | ISO timestamp lúc crawl |
| `ingested_at` | string | ✓ | ISO timestamp lúc clean |
| `is_hot` | bool | ✓ | Flag cold/hot cho pipeline. **BỎ khỏi payload Qdrant** (xem `make_payload`) |

### 5.3. PostgreSQL — từng bảng

**`edition`** — bảng trung tâm, 1 row / (model × edition). Là cha của
`price_list` (FK). `model_id` chuẩn hoá không dấu cách (`VF9`), `model_label`
hiển thị (`VF 9`).

**`price_list`** — HOT. Nhiều row / (model × edition) theo thời gian
(`valid_from` khác nhau). Row "đang hiệu lực" = `valid_to IS NULL`; index
`idx_price_active` tối ưu truy vấn này. Khi VinFast đổi giá → `UPDATE` (hoặc
`INSERT` row mới + set `valid_to` cho row cũ). Query chuẩn (retriever):
```sql
SELECT price_list_vnd, price_promo_vnd, promo_label, valid_from, source_url, updated_at
FROM price_list
WHERE model_id=%s [AND edition_id=%s]
  AND (valid_to IS NULL OR valid_to >= CURRENT_DATE)
ORDER BY valid_from DESC LIMIT 1;
```

**`maintenance_schedule`** — ĐÃ BỎ. Lịch bảo dưỡng **không lưu DB** (dễ lỗi thời
theo model × năm × hạng mục). Chatbot chỉ trả **link trang bảo dưỡng chính thức**
của VinFast + text chung từ collection `vivu_maintenance` (xem §5.4).

**`ingest_version`** — audit mỗi đợt ingest: số chunk add/modify/remove, số row
pg upserted, commit repo. Đánh version **sau khi thu thập xong cả đợt**
(crawl → clean → verify), KHÔNG đánh giữa chừng.

### 5.4. Link-only (không vào DB)

`maintenance_url`, `showroom_urls`, `promotion_urls`, `roadside_cost_urls`,
`brochure_urls`, `brochure_by_model` chỉ lưu trong `_manifest.json`. Chatbot trả
link cho user tự xem thông tin mới nhất — tránh lưu dữ liệu dễ lỗi thời vào DB.

**Bảo dưỡng:** chatbot gọi tool `get_maintenance_info` → trả text chung (từ
collection `vivu_maintenance`) + link trang bảo dưỡng chính thức
`https://vinfastauto.com/vn_vi/dich-vu-bao-duong-oto` cho user tự tra cứu theo xe.
**KHÔNG** có bảng `maintenance_schedule` trong PostgreSQL.

---

## 6. Quy ước id / khóa join / routing

### 6.1. Chunk `id`

```
<collection>:<model_lower>:<edition_lower>:<section_slug>:<seq>
```

- `model_lower` = `model_id` lowercase, hoặc `general` nếu null.
- `edition_lower` = `edition_id` lowercase, hoặc `all` nếu null (v1 toàn `all`).
- `section_slug` = `slugify(2 phần cuối section_path)`, lower, `[a-z0-9_]`, ≤ 40 ký tự.
- `seq` = số thứ tự tăng dần trong `(collection, model, edition)`.

Ví dụ: `vivu_specs:vf8:all:thong_so_ky_thuat:1`, `vivu_maintenance:general:all:dat_lich_bao_duong_d_ch_v_b_o_d_ng:1`.

### 6.2. Khóa join

`model_id` + `edition_id` là cầu nối Qdrant ↔ PostgreSQL. Retriever detect
entity từ query (regex `VF 9`, `Plus`, `Eco`...) → filter Qdrant theo
`model_id` → JOIN `price_list` lấy giá tươi → ghép prompt.

**Bảng edition chuẩn** (model_id → editions, để gán khi dat-coc không in rõ):
`VF2: [TieuChuan]`, `VF3: [Eco, Plus]`, `VF5: [Plus]`, `VF6: [Eco, Plus]`,
`VF7: [Eco, Plus, PlusCaptain]`, `VF8: [Eco, Plus]`, `VF9: [Eco, Plus]`,
`VFMPV7: [Eco, Plus]`. Mapping mã nội bộ → edition: `NE3LV→Eco`, `NE3MV→Plus`,
`NE3NV→PlusCaptain`, `JB10V→Eco`, `JB12V→Plus`, `GI10V→TieuChuan`,
`GI11V→Plus`, `TG11V→NangCao`, `TG12V→CaoCap` ...

### 6.3. Category → collection

| category | collection |
|---|---|
| `thong_so_ky_thuat` | `vivu_specs` |
| `thong_tin_san_pham` | `vivu_product_info` |
| `ho_tro_mua_xe` | `vivu_faq` |
| `chinh_sach_dich_vu` | `vivu_policy` |
| `dat_lich_bao_duong` | `vivu_maintenance` |

### 6.4. Routing nguồn (clean_to_jsonl)

Giá chỉ trích từ domain chính thống `{vinfastauto.com, shop.vinfastauto.com}`
vào Postgres. PDF extract → `vivu_policy`. So sánh/đối chiếu → `vivu_specs`.
Article/dealer → `vivu_product_info` (confidence thấp hơn).

---

## 7. Phụ thuộc & môi trường

| Thành phần | Giá trị |
|---|---|
| Qdrant | `qdrant/qdrant:latest`, port `6333` (REST) + `6334` (gRPC) |
| PostgreSQL | `postgres:16-alpine`, port `5432`, user/db/pass `vivu` |
| Embed model | `openai/text-embedding-3-small` (1536-dim, OpenRouter) |
| Rerank model | `cohere/rerank-v3.5` (OpenRouter) — ở retriever, không phải ingest |
| API key | `OPENROUTER_API_KEY` trong `.env` (không commit) |
| Thư viện | `qdrant-client`, `psycopg2-binary`, `requests`, `python-dotenv` |

**Lệnh ingest (run order):**
```bash
docker compose up -d
python scripts/clean_data/clean_to_jsonl.py --version v1
python scripts/clean_data/split_cold_hot.py --version v1 --commit $(git rev-parse --short HEAD)
python scripts/ingest/vector_ingest.py   --version v1 --recreate
python scripts/ingest/sparse_ingest.py   --version v1 --recreate
python scripts/ingest/postgres_ingest.py --version v1
```

**Kiểm tra:**
```bash
curl http://localhost:6333/collections
docker exec -it vivu_postgres psql -U vivu -d vivu -c "SELECT * FROM price_list WHERE model_id='VF9';"
```

---

**Hết file spec.** Đây là contract cho phần Data — mọi thay đổi schema phải cập
nhật file này và bump `schema_version` trong `_manifest.json`.