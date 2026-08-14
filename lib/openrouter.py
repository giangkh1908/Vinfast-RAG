#!/usr/bin/env python3
"""
openrouter.py — Helpers dùng chung cho OpenRouter API (embedding + chat).

Đọc key từ .env (python-dotenv). Model mặc định:
  - Embed : openai/text-embedding-3-small  (1536 chiều)
  - Chat  : openai/gpt-4o-mini
Có thể ghi đè qua biến môi trường OPENROUTER_EMBED_MODEL / OPENROUTER_CHAT_MODEL.
"""

import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("openrouter")
# Giảm ồn từ thư viện bên thứ 3 (qdrant_client/httpx)
for noisy in ("httpx", "qdrant_client.http", "urllib3"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

# ── HTTP session dùng chung (keep-alive) ───────────────────────────────────
# requests.post() trực tiếp mở connection MỚI mỗi lần (TCP + TLS handshake).
# Dùng 1 Session tái sử dụng connection → giảm latency từng call.
#
# Retry connect/read ở tầng urllib3 (KHÔNG retry status — status do _post lo):
# connection pooled bị stale (server đóng ngầm) khi send trên Windows trả
# `[Errno 22] Invalid argument` → urllib3 tự bỏ connection hỏng, mở connection
# mới thay vì ném lỗi.
_RETRY = Retry(total=4, connect=4, read=4, status=0, backoff_factor=0.5,
               allowed_methods=frozenset({"GET", "POST", "PUT", "DELETE",
                                          "HEAD", "OPTIONS"}))
_SESSION = requests.Session()
_adapter = HTTPAdapter(pool_connections=8, pool_maxsize=8, max_retries=_RETRY)
_SESSION.mount("https://", _adapter)
_SESSION.mount("http://", _adapter)

# ── Metrics tích lũy: mỗi API call ghi 1 record ───────────────────────────
_METRICS: list[dict] = []


def record_metric(op: str, model: str, start: float, usage: dict | None,
                  batch: int | None = None, ttft: float | None = None) -> None:
    """Ghi latency + token usage (+ TTFT nếu streaming) của 1 API call."""
    usage = usage or {}
    _METRICS.append({
        "op": op,
        "model": model,
        "latency_ms": round((time.time() - start) * 1000, 1),
        "ttft_ms": round(ttft * 1000, 1) if ttft is not None else None,
        "input_tokens": usage.get("input_tokens") or usage.get("prompt_tokens"),
        "output_tokens": usage.get("output_tokens") or usage.get("completion_tokens"),
        "batch": batch,
    })


def get_metrics() -> list[dict]:
    return list(_METRICS)


def summarize_metrics() -> dict:
    """Tổng hợp metrics: số call, tổng latency, TTFT trung bình, token theo op."""
    by_op: dict[str, dict] = {}
    total = {"calls": 0, "latency_ms": 0.0,
             "ttft_ms": 0.0, "ttft_calls": 0,
             "input_tokens": 0, "output_tokens": 0}
    for m in _METRICS:
        op = m["op"]
        acc = by_op.setdefault(op, {"calls": 0, "latency_ms": 0.0,
                                    "ttft_ms": 0.0, "ttft_calls": 0,
                                    "input_tokens": 0, "output_tokens": 0})
        acc["calls"] += 1
        acc["latency_ms"] += m["latency_ms"]
        if m.get("ttft_ms") is not None:
            acc["ttft_ms"] += m["ttft_ms"]
            acc["ttft_calls"] += 1
        acc["input_tokens"] += m["input_tokens"] or 0
        acc["output_tokens"] += m["output_tokens"] or 0
        total["calls"] += 1
        total["latency_ms"] += m["latency_ms"]
        if m.get("ttft_ms") is not None:
            total["ttft_ms"] += m["ttft_ms"]
            total["ttft_calls"] += 1
        total["input_tokens"] += m["input_tokens"] or 0
        total["output_tokens"] += m["output_tokens"] or 0
    return {"by_op": by_op, "total": total}

# Load .env từ repo root (backend/lib/../../.env)
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

BASE_URL = "https://openrouter.ai/api/v1"
API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
EMBED_MODEL = os.environ.get("OPENROUTER_EMBED_MODEL", "openai/text-embedding-3-small")
CHAT_MODEL = os.environ.get("OPENROUTER_CHAT_MODEL", "openai/gpt-4o-mini")
# Reasoning của chat model: "" (không gửi param — giữ nguyên mặc định của model)
#   | "off" (tắt reasoning → TTFT giảm mạnh) | "low" | "high" | "max"
CHAT_REASONING = os.environ.get("OPENROUTER_CHAT_REASONING", "").strip().lower()
MAX_RETRIES = 4


def require_key() -> None:
    if not API_KEY:
        raise RuntimeError(
            "OPENROUTER_API_KEY chưa set. Tạo file .env với OPENROUTER_API_KEY=sk-or-v1-... "
            "(xem .env.example)"
        )


def _headers() -> dict:
    require_key()
    return {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }


def _post(url: str, body: dict, timeout: int) -> requests.Response:
    """POST có retry: rate-limit (429/5xx) + lỗi connection/read (timeout, ChunkedEncodingError)."""
    last = None
    for attempt in range(MAX_RETRIES):
        try:
            r = _SESSION.post(url, headers=_headers(), json=body, timeout=timeout)
            if r.status_code == 429 or r.status_code >= 500:
                last = f"HTTP {r.status_code}"
                time.sleep(2 * (attempt + 1))
                continue
            r.raise_for_status()  # 4xx khác → không retry
            _ = r.content          # đọc body ngay để bắt lỗi kết nối giữa chừng
            return r
        except requests.exceptions.RequestException as e:
            last = str(e)
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"{url} failed after {MAX_RETRIES} retries: {last}")


def _embed_batch(batch: list[str], model: str) -> list[list[float]]:
    t0 = time.time()
    r = _post(f"{BASE_URL}/embeddings", {"model": model, "input": batch}, timeout=300)
    d = r.json()
    data = sorted(d["data"], key=lambda x: x["index"])
    record_metric("embed", model, t0, d.get("usage"), batch=len(batch))
    logger.info("embed %d chunks  model=%s  %.1fs", len(batch), model, time.time() - t0)
    return [x["embedding"] for x in data]


def embed_texts(texts: list[str], model: str = EMBED_MODEL,
                batch_size: int = 64, workers: int = 8) -> list[list[float]]:
    """Embed danh sách text → list vector. Batch lớn + chạy song song `workers` luồng
    (nhanh hơn nhiều so với tuần tự khi có 2000+ chunk)."""
    batches = [texts[i:i + batch_size] for i in range(0, len(texts), batch_size)]
    if len(batches) == 1:
        # Query-time: chỉ 1 batch → gọi TRỰC TIẾP trong chính thread hiện tại.
        # Tránh tạo socket trong worker thread của ThreadPoolExecutor — trên
        # Windows, tái sử dụng pooled connection từ thread khác lúc server chạy
        # lâu (uvicorn threadpool) trả `[Errno 22] Invalid argument`.
        return _embed_batch(batches[0], model)
    results: list[list[list[float]] | None] = [None] * len(batches)
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_embed_batch, b, model): i for i, b in enumerate(batches)}
        for fut in as_completed(futs):
            i = futs[fut]
            results[i] = fut.result()  # lỗi → ném lên, task này chết
            done += 1
            print(f"  [embed] {done}/{len(batches)} batches "
                  f"({min(done * batch_size, len(texts))}/{len(texts)} chunks)",
                  file=sys.stderr, flush=True)
    out: list[list[float]] = []
    for r in results:
        out.extend(r)  # type: ignore[arg-type]
    return out


def embed_text(text: str, model: str = EMBED_MODEL) -> list[float]:
    return embed_texts([text], model, batch_size=1)[0]


def _chat_body(messages: list[dict], model: str, temperature: float,
               max_tokens: int, stream: bool) -> dict:
    """Body cho /chat/completions — thêm `reasoning.effort` nếu được cấu hình."""
    body: dict = {
        "model": model, "messages": messages,
        "temperature": temperature, "max_tokens": max_tokens,
        "stream": stream,
    }
    if CHAT_REASONING:  # "off" | "low" | "medium" | "high"
        body["reasoning"] = {"effort": CHAT_REASONING}
    return body


def chat_completion_stream(messages: list[dict], model: str = CHAT_MODEL,
                           temperature: float = 0.3, max_tokens: int = 4096):
    """Stream chat completions → yield TỪNG TOKEN câu trả lời (str).

    - Reasoning (delta.reasoning) tiêu thụ nội bộ, KHÔNG yield — chỉ dùng tính TTFT.
    - TTFT = thời gian tới token content đầu tiên.
    - Retry chỉ khi chưa yield token nào (rớt giữa stream sau khi đã yield → dừng,
      tránh trùng lặp content khi re-request).
    - Dùng `_SESSION` chung → tái sử dụng TCP/TLS connection (giảm TTFT từng call).
    """
    require_key()
    t0 = time.time()
    ttft: float | None = None
    usage: dict | None = None
    sent_any = False
    out_count = 0  # fallback đếm token thực tế khi usage bị mất (rớt kết nối)
    last_err = None
    body = _chat_body(messages, model, temperature, max_tokens, stream=True)

    for attempt in range(MAX_RETRIES):
        try:
            with _SESSION.post(f"{BASE_URL}/chat/completions",
                               headers=_headers(), json=body,
                               timeout=180, stream=True) as r:
                if r.status_code == 429 or r.status_code >= 500:
                    last_err = f"HTTP {r.status_code}"
                    time.sleep(2 * (attempt + 1))
                    continue
                if r.status_code >= 400:
                    raise RuntimeError(f"chat HTTP {r.status_code}: {r.text[:300]}")
                for line in r.iter_lines():  # bytes — decode UTF-8 thủ công tránh mojibake
                    if not line:
                        continue
                    s = line.decode("utf-8", errors="replace")
                    if not s.startswith("data:"):
                        continue
                    payload = s[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        d = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    if d.get("usage"):
                        usage = d["usage"]
                    delta = (d.get("choices") or [{}])[0].get("delta", {})
                    c = delta.get("content")
                    if c:
                        if ttft is None:
                            ttft = time.time() - t0
                        sent_any = True
                        out_count += 1
                        yield c
                break  # success
        except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
            last_err = str(e)
            if sent_any:
                break  # đã yield → không retry (tránh duplicate content)
            time.sleep(2 * (attempt + 1))

    # Fallback: nếu usage thiếu (rớt kết nối sau content), dùng số token đã yield
    if usage is None:
        usage = {}
    if usage.get("completion_tokens") is None:
        usage["completion_tokens"] = out_count
    record_metric("chat", model, t0, usage, ttft=ttft)
    logger.info("chat  model=%s  ttft=%.0fms  tokens_out=%s",
                model, (ttft or 0) * 1000, usage.get("completion_tokens"))
    if not sent_any:
        raise RuntimeError(f"chat_completion_stream failed after {MAX_RETRIES}: {last_err or 'no content'}")


def chat_completion(messages: list[dict], model: str = CHAT_MODEL,
                    temperature: float = 0.3, max_tokens: int = 4096) -> str:
    """Gọi OpenRouter chat completions (stream) → trả text answer đầy đủ."""
    return "".join(chat_completion_stream(messages, model, temperature, max_tokens)).strip()