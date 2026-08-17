# Latency & Optimization

> Đo đạc thực tế sau khi đổi sang hybrid intent + deterministic plan.
> **Kết luận chính**: retrieval/tool-exec cực nhanh; nút thắt là **provider LLM latency variance** — không phải context size của ta.

## 1. Baseline (tháng 8/2026 — DeepInfra, DeepSeek-V4-Flash)

| Case | total | tool-exec | generate | len |
|---|---|---|---|---|
| price (1 tool) | 5.2s | 125ms | 3.5s | 128 |
| spec (1 tool) | 4.8s | 142ms | 4.5s | 53 |
| feature_presence (1 tool) | 3.8s | 136ms | 3.4s | 85 |
| cross_model (9 tool song song) | 11.8s | 331ms | 11.1s | 306 |
| compare (2 tool) | 9.6s | 241ms | 9.0s | 777 |
| policy (KB search) | 12.6s | 2.0s | 10.3s | 297 |
| versions (1 tool) | 4.8s | 235ms | 3.4s | 73 |
| general (LLM fallback + KB) | 10.2s | 2.1s | 4.5s | 480 |
| utility (link) | 5.3s | — | 5.0s | 211 |

**Phân tích**:
- ✅ Deterministic plan + executor song song cực nhanh: **9 tool chỉ 331ms** (không còn LLM loop chọn tool)
- 🔴 Generate chiếm 70–90% tổng — TTFT + tốc độ token của provider
- KB search (embed + sparse + rerank) ~2s — đắt nhất về retrieval nhưng chấp nhận được

## 2. Tối ưu #1 — Feature check (`get_specs(keys=[...])`)

**Vấn đề**: cross_model đổ cả category vào context → 9 model × ~42 dòng interior = ~380 dòng spec (~10K token).

**Fix**: map keyword → spec_key (`extract_spec_key`), plan truyền `keys=[spec_key]`:

```
TRƯỚC: get_specs(VF 8, None, interior)          → 42 dòng/model
SAU:   get_specs(VF 8, None, interior, keys=[sunroof_type]) → 2 dòng/model
       → cross_model context: 380 dòng → ~18 dòng (~200 token, giảm ~40x)
```

**Kết quả**:
- ✅ **Cost token giảm ~40x** cho cross-model (lợi ích lớn nhất — chi phí vận hành)
- ✅ Giảm context-rot (ít noise → chính xác hơn)
- ⚠️ **Latency KHÔNG giảm rõ** — vì generate bị provider khống chế (xem mục 3)

**Phụ trợ**: bỏ KB auto-inject cho intent feature check (specs đã đủ, KB chỉ thêm noise).

## 3. TTFT provider (đo trực tiếp, prompt nhỏ, 2 lần/model)

| Model | TTFT | total |
|---|---|---|
| DeepSeek-V4-Flash | 1.4–1.6s | 1.7–1.8s |
| Claude-Haiku-4-5 | 1.6–1.7s | 2.3–3.0s |

Nhưng generate trong app cho CÙNG câu hỏi nhỏ: **2.9s → 12.4s** (3 lần chạy) → **variance 4x+** giữa các request cùng lúc — thuộc về tải/provider, không phải code.

## 4. Hướng giảm latency thật (xếp ưu tiên)

| Giải pháp | Tác động | Trạng thái |
|---|---|---|
| **Redis response cache** (câu trùng trả ngay <100ms) | ✅ Lớn nhất — bot bán xe nhiều câu trùng ("giá VF8?") | Phase Redis (tiếp theo) |
| Giữ DeepSeek model chính | Nhanh hơn Haiku ~30% | ✅ Đã đúng |
| (Xa) multi-provider fallback khi DeepInfra chậm | Giảm variance | Sau |

## 5. Lưu ý đo đạc

- **Kill hết process python cũ trước khi start server mới** — process cũ giữ port → test nhầm code cũ (đã gặp 2 lần).
- Luôn chạy ≥ 2–3 lần mỗi case — variance provider lớn hơn khác biệt code.
