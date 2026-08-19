"""
Semantic pre-filter — classify query specificity using embedding similarity.

No LLM call needed. Uses the same embedding model as retrieval.
Deterministic: same query → same result every time.
"""

from dataclasses import dataclass

import numpy as np
import requests

from app.config import settings

# Category examples — Vietnamese natural language for each topic
CATEGORY_EXAMPLES = {
    "phiên_bản": [
        "VF8 có mấy phiên bản",
        "Eco và Plus khác gì nhau",
        "có những bản nào",
        "VF 6 có mấy loại",
        "phiên bản nào đang bán",
        "bản nào rẻ nhất",
    ],
    "thông_số_kỹ_thuật": [
        "thông số kỹ thuật VF8",
        "công suất động cơ bao nhiêu",
        "mô-men xoắn cực đại",
        "tốc độ tối đa",
        "tăng tốc 0-100",
        "công suất và mô-men xoắn",
    ],
    "kích_thước": [
        "kích thước xe",
        "chiều dài cơ sở",
        "chiều rộng chiều cao",
        "khoảng sáng gầm",
        "xe dài bao nhiêu",
        "bán kính quay vòng",
    ],
    "pin_sạc": [
        "dung lượng pin",
        "sạc đầy mất bao lâu",
        "sạc nhanh từ 10 lên 70",
        "pin bao nhiêu kWh",
        "thời gian sạc nhanh",
        "công suất sạc DC",
    ],
    "phạm_vi_di_chuyển": [
        "đi được bao xa",
        "quãng đường một lần sạc",
        "phạm vi di chuyển",
        "range VF8",
        "đi được bao nhiêu km",
        "autonomy range",
    ],
    "an_toàn": [
        "có an toàn không",
        "túi khí ABS",
        "camera 360",
        "hỗ trợ phanh khẩn cấp",
        "ADAS có gì",
        "cảnh báo va chạm",
    ],
    "nội_thất": [
        "nội thất thế nào",
        "màn hình bao nhiêu inch",
        "ghế da hay nỉ",
        "HUD head-up display",
        "hệ thống loa",
        "cốp xe rộng không",
    ],
    "ngoại_thất": [
        "ngoại thất",
        "màu sắc có gì",
        "đèn pha LED",
        "mâm bao nhiêu inch",
        "kích thước la-zăng",
        "thiết kế bên ngoài",
    ],
    "tính_năng": [
        "tính năng thông minh",
        "ADAS có gì",
        "hỗ trợ lái trên cao tốc",
        "cruise control",
        "trợ lý ảo",
        "kết nối điện thoại",
    ],
}

# Cache embeddings for examples (computed once)
_example_embeddings: dict[str, list[list[float]]] | None = None


def _embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed texts using OpenRouter API."""
    r = requests.post(
        "https://openrouter.ai/api/v1/embeddings",
        headers={
            "Authorization": f"Bearer {settings.openrouter_api_key}",
            "Content-Type": "application/json",
        },
        json={"model": settings.openrouter_embed_model, "input": texts},
        timeout=30,
    )
    r.raise_for_status()
    data = sorted(r.json()["data"], key=lambda x: x["index"])
    return [x["embedding"] for x in data]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    a_arr = np.array(a)
    b_arr = np.array(b)
    dot = np.dot(a_arr, b_arr)
    norm = np.linalg.norm(a_arr) * np.linalg.norm(b_arr)
    if norm == 0:
        return 0.0
    return float(dot / norm)


def _get_example_embeddings() -> dict[str, list[list[float]]]:
    """Cache embeddings for all category examples."""
    global _example_embeddings
    if _example_embeddings is not None:
        return _example_embeddings

    all_texts = []
    category_indices = {}
    idx = 0
    for cat, examples in CATEGORY_EXAMPLES.items():
        category_indices[cat] = (idx, idx + len(examples))
        all_texts.extend(examples)
        idx += len(examples)

    embeddings = _embed_texts(all_texts)

    _example_embeddings = {}
    for cat, (start, end) in category_indices.items():
        _example_embeddings[cat] = embeddings[start:end]

    return _example_embeddings


@dataclass
class SpecificityResult:
    specific: bool
    category: str | None
    top_score: float
    gap: float
    all_scores: dict[str, float]


def classify_specificity(query: str) -> SpecificityResult:
    """
    Classify if a query is specific enough to answer directly.

    Returns:
        SpecificityResult with:
        - specific: True if query matches a clear category
        - category: matched category name (or None if ambiguous)
        - top_score: highest similarity score
        - gap: difference between top and second category
        - all_scores: scores for all categories
    """
    try:
        example_embeddings = _get_example_embeddings()
        query_embedding = _embed_texts([query])[0]

        scores = {}
        for cat, examples_emb in example_embeddings.items():
            similarities = [_cosine_similarity(query_embedding, emb) for emb in examples_emb]
            scores[cat] = max(similarities)

        sorted_scores = sorted(scores.items(), key=lambda x: -x[1])
        top_score = sorted_scores[0][1]
        second_score = sorted_scores[1][1] if len(sorted_scores) > 1 else 0.0
        gap = top_score - second_score

        # Specific: strong match to one category, clear gap from second
        specific = top_score >= 0.55 and gap >= 0.10
        category = sorted_scores[0][0] if specific else None

        return SpecificityResult(
            specific=specific,
            category=category,
            top_score=round(top_score, 3),
            gap=round(gap, 3),
            all_scores={k: round(v, 3) for k, v in scores.items()},
        )

    except Exception as e:
        import logging

        logging.getLogger("semantic_prefilter").warning("Failed: %s", e)
        return SpecificityResult(
            specific=False,
            category=None,
            top_score=0.0,
            gap=0.0,
            all_scores={},
        )
