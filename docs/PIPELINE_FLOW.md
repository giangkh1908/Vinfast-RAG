# Data Pipeline Flow - Từ Input đến Output

Tài liệu mô tả chi tiết luồng xử lý data pipeline từ đầu vào đến đầu ra, bao gồm validation, checks và metrics.

---

## 📥 1. Input Data

### 1.1. Raw Data Sources

```
data/
├── raw/              # HTML pages crawled từ website VinFast
│   ├── *.txt        # Text từ các trang dat-coc-xe, policy, maintenance
│   └── link_brochure.md
├── raw_pdf/         # Brochure PDFs (text extracted) → prose cho vector
│   └── *.txt        # Text từ brochure VF2, VF6, VF8, VF9
└── model_data/      # Spec sheets (CSV 2 cột label,value) → specs cho Postgres
    └── *.csv        # 1 file = 1 model + 1 edition
```

**Ví dụ input files:**
- `vn_vi_dat-coc-xe-vf8_html_*.txt` - Trang đặt cọc VF8
- `vn_vi_chinh-sach-bao-hanh-oto_*.txt` - Chính sách bảo hành
- `brochure_VF8_Brochure_*.txt` - Brochure VF8
- `vinfast-data-01_brochure_VF_206_Brochure_*.txt` - Brochure VF2

### 1.2. Input Format

Mỗi file raw là text đã extract từ HTML/PDF, chứa:
- Headers (H1, H2, H3...)
- Paragraphs
- Tables (pipe-delimited)
- Lists
- Metadata (source_url, fetched_at)

---

## 🔄 2. Pipeline Steps (6 bước)

### Bước 1: Clean Data (`clean_to_jsonl.py`)

**Mục tiêu:** Làm sạch raw text → chunks có cấu trúc

**Input:**
```
data/raw/*.txt
data/model_data/*.csv
```

**Xử lý:**
1. Parse metadata (source_url, fetched_at)
2. Loại bỏ noise (footer, navigation, ads)
3. Split thành sections theo headers
4. Chunking (max 800 chars, sentence-aware)
5. Gán metadata:
   - `collection`: vivu_product_info | vivu_policy | vivu_maintenance
   - `model_id`: VF2 | VF6 | VF8 | null
   - `edition_id`: Eco | Plus | null
   - `category`: thong_tin_san_pham | chinh_sach_dich_vu | dat_lich_bao_duong
   - `text_type`: prose | table | list | key_value
   - `tags`: [category_slug, model_id_lower]
   - `confidence`: 1.0 (thủ công) | <1.0 (auto)

**Validation:**
- ✅ Text không được chứa giá tiền (regex check)
- ✅ Chunk phải có text_type hợp lệ
- ✅ Tags phải có ít nhất 1 element

**Output:**
```
data/clean/<version>/intermediate/vector.jsonl
data/clean/<version>/intermediate/hot.jsonl
data/clean/<version>/intermediate/link_only.json
```

**Metrics:**
- Số chunks tạo được
- Số chunks bị drop (chứa giá tiền)

---

### Bước 2: Split Cold/Hot (`split_cold_hot.py`)

**Mục tiêu:** Tách data thành cold (vector) và hot (postgres)

**Input:**
```
data/clean/<version>/intermediate/*.jsonl
```

**Xử lý:**
1. Đọc intermediate files
2. Split theo `is_hot` flag:
   - Cold data → vector collections
   - Hot data → postgres CSVs
3. Gán stable ID: `{collection}:{model}:{edition}:{section_slug}:{seq}`
4. Tính diff với version trước (thêm/sửa/xóa)

**Validation:**
- ✅ Chunk schema validation (Pydantic)
- ✅ Không có giá trong vector text
- ✅ ID phải unique

**Output:**
```
data/clean/<version>/vector/
├── vivu_product_info.jsonl
├── vivu_policy.jsonl
└── vivu_maintenance.jsonl

data/clean/<version>/postgres/
├── edition.csv
├── price_list.csv
└── _manifest.json (partial)
```

**Metrics:**
- Số chunks per collection
- Diff stats: added | modified | removed
- Số hot rows (edition, price_list)

---

### Bước 3: Parse Specs (`parse_specs.py`)

**Mục tiêu:** Extract thông số kỹ thuật từ model_data CSVs

**Input:**
```
data/model_data/*.csv
```

**Xử lý:**
1. Đọc CSV 2 cột (label, value) — 1 file = 1 model + 1 edition
2. Detect section headers (label có value rỗng)
3. Extract specs:
   - Basic specs: công suất, pin, kích thước, trọng lượng
   - Feature specs: ADAS, nội thất, ngoại thất
4. Normalize labels (Vietnamese → English keys)
5. Map to spec categories (powertrain, battery, dimension, interior, safety, adas)

**Validation:**
- ✅ Spec value phải có unit (nếu cần)
- ✅ Spec category phải hợp lệ
- ✅ Model code phải match với known models

**Output:**
```
data/clean/<version>/postgres/specs.csv
```

**Update manifest:**
- Thêm `car_specs` section vào `_manifest.json`
- Count rows per model

**Metrics:**
- Số specs extracted per model
- Số specs per category
- Coverage: models có specs / tổng models

---

### Bước 4: Vector Ingest (`vector_ingest.py`)

**Mục tiêu:** Embed text → Qdrant dense collection

**Input:**
```
data/clean/<version>/vector/*.jsonl
```

**Xử lý:**
1. Load chunks từ JSONL
2. **Validation (Pydantic):**
   - Check chunk schema
   - Check payload schema
3. Compute content hash (để cache)
4. Check vector cache:
   - Hit → reuse old vector
   - Miss → call OpenRouter embed API
5. Upsert vào Qdrant collection `<collection>__<version>`
6. Create payload indexes (model_id, category, source_type)

**Validation:**
- ✅ Chunk validation trước khi embed
- ✅ Payload validation trước khi upsert
- ✅ Vector dimension phải match (1536)

**Checks:**
- Cache hit rate
- API calls count
- Token usage

**Output:**
```
Qdrant collections:
- vivu_product_info__<version>
- vivu_policy__<version>
- vivu_maintenance__<version>
```

**Metrics:**
- Tổng chunks
- Cache hits | misses
- API calls
- Tokens used (input + output)
- Cost (nếu có price info)

---

### Bước 5: Sparse Ingest (`sparse_ingest.py`)

**Mục tiêu:** Build BM25 sparse vectors → Qdrant sparse collection

**Input:**
```
data/clean/<version>/vector/*.jsonl
```

**Xử lý:**
1. Load chunks từ JSONL
2. **Validation (Pydantic):**
   - Check chunk schema
3. Tokenize text (Vietnamese tokenizer)
4. Build vocabulary + IDF
5. Compute BM25 vectors
6. Upsert vào Qdrant `sparse__<version>`
   - Payload: collection, chunk_id, model_id, vector_version, text
7. Create payload index (model_id)

**Validation:**
- ✅ Chunk validation
- ✅ Sparse payload phải có text (không empty)

**Output:**
```
Qdrant collection:
- sparse__<version>

Local file:
- data/clean/<version>/sparse_index.json
```

**Metrics:**
- Vocabulary size
- Average document length
- IDF distribution stats

---

### Bước 6: Postgres Inest (`postgres_ingest.py`)

**Mục tiêu:** Load structured data → PostgreSQL

**Input:**
```
data/clean/<version>/postgres/*.csv
```

**Xử lý:**
1. Load CSVs (edition, price_list, specs)
2. Upsert vào PostgreSQL:
   - `edition` table (model × edition)
   - `price_list` table (giá, khuyến mãi)
   - `car_specs` table (thông số kỹ thuật)
3. Update `ingest_version` table
4. Set `is_current = false` (chưa activate)

**Validation:**
- ✅ CSV schema validation
- ✅ Foreign key checks (edition → price_list)
- ✅ Data type checks (price phải là number)

**Output:**
```
PostgreSQL tables:
- edition (versioned)
- price_list (versioned)
- car_specs (versioned)
- ingest_version (tracking)
```

**Metrics:**
- Rows upserted per table
- Price changes detected
- Specs coverage

---

## ✅ 3. Quality Checks

### 3.1. Inline Validations (trong pipeline)

| Bước | Validation | Action nếu fail |
|------|-----------|----------------|
| Clean | Text có giá tiền? | Drop chunk |
| Split | Chunk schema valid? | Skip chunk + log warning |
| Vector | Payload valid? | Skip chunk + log error |
| Sparse | Text không empty? | Skip chunk + log error |
| Postgres | CSV schema valid? | Abort step |

### 3.2. Smoke Test (sau pipeline)

**Khi nào chạy:**
- Manual: `python scripts/eval/smoke_test.py --version <v>`
- Auto: `run_pipeline.py --promote --smoke-test`

**Test gì:**
- 8 queries mẫu (golden set)
- Cover 3 collections: product_info, policy, maintenance
- Check retrieval quality

**Metrics:**
- **Hit rate@5**: % queries có ≥1 result đúng trong top-5
  - Target: ≥80%
  - Hiện tại: 100% (8/8)
- **Precision@5**: % results đúng trong top-5
  - Target: ≥50%
  - Hiện tại: ~35%

**Golden set format:**
```json
{
  "query": "Câu hỏi mẫu",
  "expected": {
    "collection": "vivu_product_info",
    "model_id": "VF8",
    "keywords": ["thông minh"]
  }
}
```

**Pass/Fail criteria:**
- Pass: Hit rate ≥ 80%
- Fail: Hit rate < 80%

---

## 📤 4. Output

### 4.1. Qdrant Collections (Active = aliased)

```
vivu_product_info → vivu_product_info__<active_version>
vivu_policy → vivu_policy__<active_version>
vivu_maintenance → vivu_maintenance__<active_version>
sparse → sparse__<active_version>
```

**Mỗi point có:**
- Vector (dense hoặc sparse)
- Payload:
  - collection, chunk_id, model_id, edition_id
  - text (sparse) hoặc full fields (dense)
  - category, tags, source_url, confidence
  - vector_version

### 4.2. PostgreSQL Tables (Active = VIEW)

```sql
-- Active views (is_current = true)
SELECT * FROM edition_active;
SELECT * FROM price_list_active;
SELECT * FROM car_specs_active;

-- Tracking
SELECT * FROM ingest_version WHERE is_current = true;
```

### 4.3. Local Artifacts

```
data/clean/<version>/
├── _manifest.json          # Metadata + stats
├── intermediate/           # Cleaned chunks
├── vector/                 # Vector JSONLs
├── postgres/               # CSVs
└── sparse_index.json       # BM25 vocab + IDF
```

---

## 📊 5. Metrics & Monitoring

### 5.1. Pipeline Metrics

**Manifest (_manifest.json):**
```json
{
  "version": "v2",
  "created_at": "2026-08-11T10:00:00Z",
  "vector": {
    "total_chunks": 438,
    "collections": {
      "vivu_product_info": { "chunks": 200, "added": 10, "modified": 5, "removed": 2 },
      "vivu_policy": { "chunks": 150, "added": 8, "modified": 3, "removed": 1 },
      "vivu_maintenance": { "chunks": 88, "added": 2, "modified": 1, "removed": 0 }
    }
  },
  "postgres": {
    "tables": {
      "edition": { "rows": 14, "upserted": 14 },
      "price_list": { "rows": 14, "upserted": 14, "price_changed": 3 },
      "car_specs": { "rows": 245, "upserted": 245 }
    }
  }
}
```

> `sparse_index.json` là file riêng (`data/clean/<ver>/sparse_index.json`), không
> nằm trong manifest. `car_specs` được thêm vào manifest bởi `parse_specs.py`.

### 5.2. Quality Metrics

**Smoke test:**
- Hit rate@5: 100% (8/8)
- Precision@5: 35% (trung bình)

**Vector ingest:**
- Cache hit rate: 80-95% (tùy version)
- API calls: 50-200 (tùy cache)
- Tokens: 100K-500K

### 5.3. Cost Tracking

**OpenRouter API:**
- Embed model: `openai/text-embedding-3-small`
- Price: ~$0.02 per 1M tokens
- Estimated cost per pipeline: $2-10

---

## 🔧 6. Recovery & Rollback

### 6.1. Recovery Command

**Khi nào dùng:**
- Qdrant và PostgreSQL không sync (is_current mismatch)
- Sau khi promote/rollback fail

**Cách dùng:**
```bash
python scripts/version_manager.py recover
```

**Hành động:**
1. Đọc Qdrant alias → xác định active version
2. Sync PostgreSQL is_current → match Qdrant

### 6.2. Rollback

**Khi nào dùng:**
- Smoke test fail sau khi promote
- Phát hiện data quality issues

**Cách dùng:**
```bash
python scripts/version_manager.py rollback --to <version>
```

**Hành động:**
1. Swap Qdrant alias → version cũ
2. Update PostgreSQL is_current → version cũ
3. Atomic: cả 2 DB cùng rollback

---

## 🎯 7. Success Criteria

### 7.1. Pipeline Success

- [ ] Tất cả 6 bước complete (rc=0)
- [ ] Không có validation errors
- [ ] Manifest có đầy đủ stats
- [ ] Smoke test pass (hit rate ≥ 80%)

### 7.2. Quality Success

- [ ] Hit rate@5 ≥ 80%
- [ ] Precision@5 ≥ 30%
- [ ] Không có chunks bị drop (trừ khi có giá)
- [ ] Specs coverage ≥ 80% models

### 7.3. Performance Success

- [ ] Cache hit rate ≥ 80%
- [ ] API calls ≤ 200 (nếu cache tốt)
- [ ] Total time ≤ 30 phút
- [ ] Cost ≤ $10 per run

---

## 📚 8. Commands Reference

### Full Pipeline

```bash
# Chạy pipeline + promote + smoke test
python scripts/run_pipeline.py --version v2 --recreate --promote --smoke-test

# Chạy incremental (không recreate)
python scripts/run_pipeline.py --version v2 --promote --smoke-test

# Chạy không smoke test
python scripts/run_pipeline.py --version v2 --promote
```

### Individual Steps

```bash
# Step 1: Clean
python scripts/clean_data/clean_to_jsonl.py --version v2

# Step 2: Split
python scripts/clean_data/split_cold_hot.py --version v2

# Step 3: Parse specs
python scripts/clean_data/parse_specs.py --version v2

# Step 4: Vector ingest
python scripts/ingest/vector_ingest.py --version v2 --recreate

# Step 5: Sparse ingest
python scripts/ingest/sparse_ingest.py --version v2 --recreate

# Step 6: Postgres ingest
python scripts/ingest/postgres_ingest.py --version v2
```

### Management

```bash
# Xem status
python scripts/version_manager.py status

# List versions
python scripts/version_manager.py list

# Promote version
python scripts/version_manager.py promote --version v2

# Rollback
python scripts/version_manager.py rollback --to v1

# Recover (sync Qdrant + PG)
python scripts/version_manager.py recover

# Delete version
python scripts/version_manager.py delete --version v2
```

### Quality Check

```bash
# Chạy smoke test standalone
python scripts/eval/smoke_test.py --version v2

# Custom top-K
python scripts/eval/smoke_test.py --version v2 --top-k 10
```

---

## 🔍 9. Troubleshooting

### 9.1. Common Issues

**Vấn đề: Smoke test fail (hit rate < 80%)**
- Kiểm tra golden set có đúng không
- Check retrieval quality (xem top-K results)
- Điều chỉnh keywords trong golden set

**Vấn đề: Validation errors**
- Check log để biết chunk nào fail
- Verify chunk schema trong `scripts/schemas.py`
- Fix data trong intermediate files

**Vấn đề: Cache hit rate thấp**
- Check content hash function
- Verify vector cache DB
- Rebuild cache nếu cần

**Vấn đề: Qdrant + PG mismatch**
- Chạy `version_manager.py recover`
- Check alias và is_current

### 9.2. Debug Commands

```bash
# Xem manifest
cat data/clean/v2/_manifest.json | jq

# Check Qdrant collection
curl -X GET "$QDRANT_URL/collections/vivu_product_info__v2"

# Check PostgreSQL
psql $PG_DSN -c "SELECT * FROM ingest_version WHERE is_current = true;"

# Check smoke test results
python scripts/eval/smoke_test.py --version v2 --verbose
```

---

## 📝 10. Summary

**Pipeline flow:**
```
Raw data → Clean → Split → Parse specs → Vector ingest → Sparse ingest → Postgres ingest → Smoke test
   ↓         ↓        ↓          ↓             ↓              ↓              ↓              ↓
  HTML/PDF  Chunks  Cold/Hot   Specs.csv    Dense vec     Sparse vec     PG tables    Quality gate
```

**Key metrics:**
- Hit rate@5: 100% (8/8 queries)
- Precision@5: ~35%
- Cache hit rate: 80-95%
- Cost: $2-10 per run

**Success criteria:**
- Hit rate ≥ 80%
- No validation errors
- All 6 steps complete

**Recovery:**
- `version_manager.py recover` để sync Qdrant + PG
- `version_manager.py rollback` để quay lại version cũ
