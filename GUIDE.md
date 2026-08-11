# Vivu — Hướng dẫn chạy

## Yêu cầu

- Python 3.11+
- API key TokenRouter (hoặc OpenAI)

---

## 1. Clone & Install

```bash
cd C:\Users\admin\Documents\GitHub\vivu
git checkout Trust-Foundation/Bao
pip install -r requirements.txt
```

## 2. Config .env

File `.env` đã có sẵn cloud endpoints. Chỉ cần verify:

```
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://api.tokenrouter.com/v1
LLM_MODEL=openai/gpt-4o-mini

POSTGRES_URL=postgresql+asyncpg://neondb_owner:...@neon.tech/neondb?sslmode=require
PG_DSN=postgresql://neondb_owner:...@neon.tech/neon.db?sslmode=require

QDRANT_URL=https://xxx.eu-central-1-0.aws.cloud.qdrant.io
QDRANT_API_KEY=eyJhbGci...

SCOPE_ENABLED=true
SCOPE_MODELS=VF 6,VF 8
SCOPE_VERSIONS=Eco,Plus
```

---

## 3. Start Server

```bash
uvicorn app.main:app --reload --port 8000
```

Mo http://localhost:8000

---

## 4. Check Data

### PostgreSQL (Neon Cloud)

Dung VS Code extension **Database Client**:

1. Sidebar trai -> icon **Database** (hinh tru)
2. Click **+** -> **PostgreSQL**
3. Dien:
   - Host: `ep-falling-band-az3x86f6.c-3.ap-southeast-1.aws.neon.tech`
   - Port: `5432`
   - User: `neondb_owner`
   - Password: `npg_Sf6WZ9FalKDE`
   - Database: `neondb`
   - SSL: ✅
4. Query thu:

```sql
SELECT * FROM edition_active;
SELECT * FROM car_specs WHERE model_code = 'VF 6';
SELECT * FROM price_list_active;
```

### Qdrant Cloud

Dung Python:

```python
from qdrant_client import QdrantClient

client = QdrantClient(
    url="https://daf7ffca-...qdrant.io",
    api_key="eyJhbGci..."
)

for c in client.get_collections().collections:
    print(c.name)
```

Hoac mo https://cloud.qdrant.io -> Dashboard.

---

## 5. Check Logs

### Xem logs trong session hien tai

```bash
curl http://localhost:8000/api/logs
```

### Export logs ra JSONL

```bash
curl http://localhost:8000/api/logs/export > logs.jsonl
```

### Log schema (P0 — 30 fields)

Moi request log:

```json
{
  "schema_version": "1.0",
  "request_id": "req_abc123",
  "timestamp": "2026-08-08T19:00:00Z",
  "run_id": "run_20260808_190000",
  "build_version": "8162953",
  "prompt_version": "a1b2c3d4e5f6",
  "data_snapshot_id": "v1_2026-08-07",
  "user_query": "VF 6 Eco cong suat bao nhieu?",
  "detected_vehicle_model": "VF 6",
  "detected_vehicle_version": "Eco",
  "detected_topic": "thong_so_ky_thuat",
  "decision": "answer",
  "reason_code": "sufficient_direct_evidence",
  "retrieval_status": "success",
  "retrieved_chunks": [...],
  "displayed_answer": "...",
  "displayed_citations": [...],
  "latency_total_ms": 10200.5,
  "latency_retrieval_ms": 5300.2,
  "latency_generation_ms": 3400.1
}
```

### Reason codes (21 enum)

| Decision         | Reason codes                                                                                                                                                                                                                                      |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `answer`       | `sufficient_direct_evidence`, `partial_direct_evidence`                                                                                                                                                                                       |
| `clarify`      | `missing_model`, `missing_version`, `missing_topic`, `ambiguous_context`                                                                                                                                                                  |
| `refuse`       | `insufficient_evidence`, `indirect_evidence`, `invalid_source`, `source_conflict`, `citation_failure`, `system_error`, `grounding_failure`                                                                                          |
| `out_of_scope` | `unsupported_model`, `unsupported_comparison`, `unsupported_recommendation`, `unsupported_pricing_policy`, `unsupported_after_sales`, `unsupported_safety_diagnosis`, `unsupported_contact_workflow`, `external_source_requested` |

---

## 6. Eval — Batch Runner (P0)

Chay test cases qua API, export JSONL:

```bash
python scripts/eval_runner.py --input eval/smoke_test.csv --output eval/eval_report.jsonl
```

Input CSV format:

```csv
test_id,user_query
TF-SM-01,VF 6 co nhung phien ban nao?
TF-SM-02,Xe di duoc bao xa sau mot lan sac?
```

Output: JSONL voi P0 schema per request.

---

## 7. Eval — RAGAS (Automated Metrics)

### Chay RAGAS eval

```bash
python scripts/ragas_eval.py --input eval/golden_dataset.csv --output eval/ragas_results.jsonl
```

Input CSV can them cot `expected_answer`:

```csv
test_id,user_query,expected_decision,expected_answer
TF-ANS-01,VF 6 co nhung phien ban nao?,answer,VF 6 co 2 phien ban: Eco va Plus.
```

### RAGAS Metrics

| Metric                      | Y nghia                                           | Range |
| --------------------------- | ------------------------------------------------- | ----- |
| **Faithfulness**      | Answer co dua tren retrieved context khong?       | 0-1   |
| **Answer Relevancy**  | Answer co lien quan den question khong?           | 0-1   |
| **Context Precision** | Retrieved chunks co dung khong?                   | 0-1   |
| **Context Recall**    | Ground truth co nam trong retrieved chunks khong? | 0-1   |

### Output

```
=== RAGAS Scores ===
  Faithfulness:      0.850
  Answer Relevancy:  0.920
  Context Precision: 0.780
  Context Recall:    0.700
```

Results saved to `eval/ragas_results.jsonl` + `eval/ragas_results.summary.json`.

---

## 8. Phoenix Tracing (Optional)

### Enable Phoenix

Trong `.env`:

```
PHOENIX_ENABLED=true
```

### Start Phoenix UI

```bash
python -m phoenix.server.main serve
```

Mo http://localhost:6006

### Chay app voi Phoenix

```bash
uvicorn app.main:app --reload --port 8000
```

Phoenix tu dong capture:

- OpenAI API calls (LLM + Embedding)
- Latency per call
- Token usage
- Input/Output messages

---

## 9. Test Queries

| Query                         | Decision mong doi           | Tool                    |
| ----------------------------- | --------------------------- | ----------------------- |
| VF 6 co may phien ban?        | `answer`                  | get_specs / list_models |
| VF 6 Eco cong suat bao nhieu? | `answer`                  | get_specs               |
| Xe di duoc bao xa?            | `clarify` (missing_model) | —                      |
| Cho toi biet ve VF 6          | `clarify` (missing_topic) | —                      |
| So sanh VF 6 va VF 8          | `out_of_scope`            | —                      |
| Gia VF 8 bao nhieu?           | `out_of_scope`            | —                      |

---




View Langgraph: langgraph dev

[smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024](https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024)

## Cau truc thu muc

```
vivu/
├── .env                              # Config (API keys, DB URLs)
├── requirements.txt                  # Python dependencies
├── GUIDE.md                          # This file
│
├── app/
│   ├── main.py                       # FastAPI + Phoenix tracing
│   ├── config.py                     # Settings (load .env)
│   ├── tracing.py                    # Phoenix instrumentation
│   ├── agent/
│   │   ├── agent_loop.py            # Agent loop + eval logging
│   │   ├── classifier.py            # BDS classifier (topic, scope)
│   │   ├── decision.py              # DecisionLog P0 schema + reason codes
│   │   ├── tools.py                 # 10 tools (get_specs, get_price, ...)
│   │   ├── schemas.py               # Dynamic tool schemas
│   │   ├── prompts.py               # System prompt (BDS/Full)
│   │   └── context_builder.py       # Format tool results
│   ├── api/chat.py                   # /api/chat, /api/logs, /api/logs/export
│   ├── core/retrieval.py            # Hybrid search (dense + sparse + rerank)
│   └── static/index.html            # Chat UI
│
├── scripts/
│   ├── batch_runner.py              # Eval: CSV -> API -> JSONL
│   ├── ragas_eval.py                # Eval: RAGAS automated scoring
│   ├── run_pipeline.py              # Data pipeline orchestrator
│   └── ...
│
├── eval/
│   ├── smoke_test.csv               # 8 smoke test cases
│   ├── golden_dataset.csv           # 10 cases with expected answers
│   └── smoke_results.jsonl          # Smoke test output
│
└── data/
    ├── clean/v1/                     # Cleaned vector + postgres data
    └── raw/                          # Raw crawled files
```

---

## Loi thuong gap

| Loi                               | Nguyen nhan          | Fix                                                                |
| --------------------------------- | -------------------- | ------------------------------------------------------------------ |
| `Connection refused` Qdrant     | Sai URL hoac API key | Check`.env` QDRANT_URL, QDRANT_API_KEY                           |
| `Connection refused` PostgreSQL | Sai PG_DSN           | Check`.env` PG_DSN                                               |
| `403 Forbidden` OpenAI          | Sai API key          | Check`.env` OPENAI_API_KEY                                       |
| `ModuleNotFoundError: ragas`    | Chua install         | `pip install ragas datasets`                                     |
| `RAGAS scoring failed`          | Thieu ground_truth   | CSV phai co cot`expected_answer`                                 |
| `Phoenix not installed`         | Chua install         | `pip install arize-phoenix openinference-instrumentation-openai` |
