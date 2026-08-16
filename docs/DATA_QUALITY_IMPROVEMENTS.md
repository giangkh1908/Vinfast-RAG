# Data Quality & Reliability Improvements

Tài liệu về các cải tiến chất lượng và độ tin cậy của data pipeline.

## Tổng quan

Đã triển khai 4 cải tiến không ảnh hưởng production:

1. **Data Validation (Pydantic)** - Enforce schema contract
2. **Recovery Command** - Fix 2-store atomicity issues
3. **Car Specs Tracking** - Track specs trong manifest
4. **Smoke Test Framework** - Evaluate retrieval quality

---

## 1. Data Validation (Pydantic)

### Mục đích

Đảm bảo tất cả chunks và payloads tuân thủ schema contract, phát hiện sớm lỗi trước khi ingest.

### Triển khai

**File:** `scripts/schemas.py`

Định nghĩa 3 Pydantic models:

- `Chunk` - Schema cho chunk JSONL (đầu vào)
- `DensePayload` - Schema cho Qdrant dense payload
- `SparsePayload` - Schema cho Qdrant sparse payload

**Validation points:**

1. `split_cold_hot.py` - Validate chunks sau khi split
2. `vector_ingest.py` - Validate trước khi embed và upsert
3. `sparse_ingest.py` - Validate trước khi upsert

### Cách dùng

Validation tự động chạy khi execute pipeline scripts. Nếu chunk không valid:

```bash
# split_cold_hot.py sẽ skip invalid chunks và log warning
python scripts/clean_data/split_cold_hot.py --version v2

# vector_ingest.py sẽ raise error nếu payload invalid
python scripts/ingest/vector_ingest.py --version v2

# sparse_ingest.py sẽ skip invalid chunks
python scripts/ingest/sparse_ingest.py --version v2
```

### Schema contract

**Chunk fields (required):**

```json
{
  "id": "string",
  "collection": "string",
  "vector_version": "string",
  "text": "string (non-empty)",
  "model_id": "string | null",
  "edition_id": "string | null",
  "category": "string",
  "section_path": ["string"],
  "text_type": "string",
  "structured": "object",
  "language": "string",
  "tags": ["string"],
  "confidence": "float (0-1)",
  "source_file": "string",
  "source_url": "string",
  "source_type": "string",
  "fetched_at": "ISO8601",
  "ingested_at": "ISO8601",
  "page": "int | null (optional)",
  "is_hot": "bool"
}
```

**Sparse payload fields (5 fields):**

```json
{
  "collection": "string",
  "chunk_id": "string",
  "model_id": "string | null",
  "vector_version": "string",
  "text": "string (non-empty)"
}
```

---

## 2. Recovery Command

### Mục đích

Fix 2-store atomicity issues khi Qdrant và PostgreSQL bị out of sync sau khi promote/rollback fail.

### Vấn đề

Khi `version_manager.py promote` hoặc `rollback`:

1. Qdrant alias swap thành công
2. PostgreSQL `is_current` update fail (network issue, timeout, etc.)

→ Qdrant và PostgreSQL chỉa đến versions khác nhau.

### Triển khai

**File:** `scripts/version_manager.py`

Thêm command `recover`:

- Đọc Qdrant alias để xác định version thực tế
- Update PostgreSQL `is_current` để match với Qdrant
- Idempotent - có thể chạy nhiều lần

### Cách dùng

```bash
# Kiểm tra status hiện tại
python scripts/version_manager.py status

# Recover nếu thấy inconsistency
python scripts/version_manager.py recover

# Verify sau khi recover
python scripts/version_manager.py status
```

### Output mẫu

```
Checking consistency...
  Qdrant alias 'vivu_product_info' -> vivu_product_info__v2
  PostgreSQL is_current: v1

Detected inconsistency: Qdrant=v2, PostgreSQL=v1

Recovering...
  Updated PostgreSQL is_current to v2

Recovery complete. All stores now consistent.
```

---

## 3. Car Specs Tracking

### Mục đích

Track số lượng car_specs rows trong manifest để dễ audit và debug.

### Triển khai

**File:** `scripts/clean_data/parse_specs.py`

Sau khi parse specs từ model_data CSVs:

1. Count tổng số rows
2. Count theo từng model
3. Ghi vào `_manifest.json`:

```json
{
  "postgres": {
    "tables": {
      "edition": {...},
      "price_list": {...},
      "car_specs": {
        "total_rows": 245,
        "by_model": {
          "VF8": 120,
          "VF6": 85,
          "VF3": 40
        }
      }
    }
  }
}
```

### Lợi ích

- Biết được version nào có bao nhiêu specs
- Phát hiện sớm nếu parse bị thiếu specs
- Dễ so sánh giữa các versions

---

## 4. Smoke Test Framework

### Mục đích

Đánh giá chất lượng retrieval sau mỗi ingest, phát hiện regression.

### Triển khai

**Files:**

- `scripts/eval/smoke_test.py` - Test runner
- `scripts/eval/golden_set.json` - Test queries và expected results

**Integration:**

- `scripts/run_pipeline.py` - Thêm flag `--smoke-test`

### Golden Set

File `golden_set.json` chứa các test queries:

```json
{
  "queries": [
    {
      "id": "q1",
      "query": "Chính sách bảo hành pin như thế nào?",
      "expected": {
        "collection": "vivu_policy",
        "keywords": ["bảo hành", "pin"]
      }
    },
    {
      "id": "q2",
      "query": "VF 6 có mấy chỗ ngồi?",
      "expected": {
        "collection": "vivu_product_info",
        "model_id": "VF6",
        "keywords": ["chỗ ngồi"]
      }
    }
  ]
}
```

### Metrics

- **Hit rate**: Tỷ lệ queries có ít nhất 1 result đúng trong top-K
- **Precision@K**: Tỷ lệ results đúng trong top-K results

### Cách dùng

**Standalone:**

```bash
# Chạy smoke test với golden set hiện tại
python scripts/eval/smoke_test.py --version v2

# Custom top-K
python scripts/eval/smoke_test.py --version v2 --top-k 10

# Xem verbose output
python scripts/eval/smoke_test.py --version v2 --verbose
```

**Integrated with pipeline:**

```bash
# Chạy pipeline + smoke test tự động
python scripts/run_pipeline.py --version v2 --promote --smoke-test
```

### Output mẫu

```
[smoke_test] Running smoke test on version: v2
[smoke_test] Top-K: 5
[smoke_test] Queries: 8

[1/8] PASS Chính sách bảo hành pin...  hit@5=True  prec@5=0.80
[2/8] PASS VF 6 có mấy chỗ ngồi...  hit@5=True  prec@5=1.00
[3/8] FAIL VF 8 giá bao nhiêu...  hit@5=False  prec@5=0.00
...

[smoke_test] Results:
  Hit rate: 87.50% (7/8)
  Avg precision@5: 75.00%

[smoke_test] PASS (hit rate >= 80%)
```

### Thresholds

- **Pass**: Hit rate >= 80%
- **Fail**: Hit rate < 80%

Nếu fail, pipeline sẽ log warning nhưng vẫn tiếp tục (không block deployment).

### Customizing Golden Set

Chỉnh sửa `scripts/eval/golden_set.json`:

```json
{
  "queries": [
    {
      "id": "unique_id",
      "query": "Câu hỏi thực tế",
      "expected": {
        "collection": "vivu_product_info|vivu_policy|vivu_maintenance",
        "model_id": "VF3|VF5|VF6|VF8|...",  // optional
        "keywords": ["keyword1", "keyword2"]
      }
    }
  ]
}
```

**Tips:**

- Thêm queries từ real user questions
- Cover nhiều collections và models
- Keywords nên là những từ quan trọng trong expected answer
- Regularly update khi có data mới

---

## Installation

Pydantic đã được thêm vào `requirements.txt`:

```bash
pip install -r requirements.txt
```

---

## Migration Notes

**Không cần migration** - tất cả improvements là additive:

- Validation: chỉ thêm check, không thay đổi data structure
- Recovery: thêm command mới, không ảnh hưởng existing commands
- Car specs tracking: chỉ thêm field vào manifest
- Smoke test: thêm script mới, optional flag

---

## Troubleshooting

### Validation errors

Nếu thấy validation errors khi chạy pipeline:

```bash
# Xem chi tiết lỗi
python scripts/clean_data/split_cold_hot.py --version v2 2>&1 | grep -A 5 "Validation error"

# Check schema trong scripts/schemas.py
cat scripts/schemas.py
```

### Recovery không hoạt động

Nếu `recover` command không fix được:

```bash
# Manual check
python scripts/version_manager.py status

# Manual fix nếu cần
psql $PG_DSN -c "UPDATE ingest_version SET is_current = false;"
psql $PG_DSN -c "UPDATE ingest_version SET is_current = true WHERE version = 'v2';"
```

### Smoke test fail liên tục

Nếu hit rate thấp:

1. Check golden set có đúng không
2. Tăng top-K (ví dụ `--top-k 10`)
3. Review retrieval logic trong retriever
4. Check nếu data bị thiếu hoặc sai

---

## Future Improvements

- [ ] Add more golden set queries (hiện tại chỉ 8 queries)
- [ ] Add performance benchmarks (latency, throughput)
- [ ] Add data drift detection
- [ ] Integrate with CI/CD pipeline
- [ ] Add automated golden set generation from production logs

---

## References

- [Data Pipeline Documentation](./DATA_PIPELINE.md)
- [Versioning Documentation](./VERSIONING.md)
- [Data Schema Specification](./DATA_SCHEMA_SPEC.md)
