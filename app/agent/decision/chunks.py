"""Chunk & citation builders — tool_results → P0 retrieved_chunks / displayed_citations."""

import logging

from app.agent.decision.evidence import _TOKEN_RE, _query_tokens, _spec_relevance_score
from app.agent.decision.models import DisplayedCitation, RetrievedChunk

logger = logging.getLogger("bds.decision")


def build_retrieved_chunks(tool_results: list[dict], query: str = "", topic: str = "") -> list[dict]:
    """Convert tool_results → P0 retrieved_chunks schema.

    Scoring bằng keyword overlap (nhanh, không network) — embedding chỉ dùng
    trong background logging.
    """
    from app.agent.nodes.classify import _TOPIC_KEYWORDS

    chunks = []
    rank = 0
    MAX_CHUNKS = 30
    MIN_SCORE = 0.3
    qtokens = _query_tokens(query) if query else set()

    topic_keywords: set[str] = set()
    if topic and topic in _TOPIC_KEYWORDS:
        for pattern in _TOPIC_KEYWORDS[topic]:
            topic_keywords.update(_TOKEN_RE.findall(pattern.lower()))
    topic_keywords |= qtokens - {
        "xe",
        "vinfast",
        "vf",
        "của",
        "và",
        "là",
        "cho",
        "tôi",
        "bạn",
        "có",
        "không",
        "nào",
        "gì",
    }

    def _embed_score(texts: list[str]) -> list[float]:
        """Score texts vs query — keyword overlap ONLY (nhanh, không network).

        Không gọi embedding trong answer path — keyword đủ cho ranking.
        Embedding chỉ dùng trong background logging.
        """
        results = []
        for t in texts:
            t_tokens = set(_TOKEN_RE.findall(t.lower()))
            overlap = t_tokens & qtokens - {"xe", "vinfast", "vf", "có", "không"}
            results.append(min(0.9, 0.3 + 0.1 * len(overlap)))
        return results

    for tr in tool_results:
        if not tr.get("success"):
            continue
        result = tr["result"]
        tool = tr["tool"]

        if tool == "search_knowledge_base" and result.get("results"):
            for r in result["results"]:
                score = r.get("score", 0.0)
                if score < MIN_SCORE:
                    continue
                text = r.get("text", "").lower()
                text_tokens = set(_TOKEN_RE.findall(text))
                if topic_keywords and not (topic_keywords & text_tokens):
                    continue
                rank += 1
                page = r.get("page", "")
                page_str = f" (trang {page})" if page else ""
                chunks.append(
                    RetrievedChunk(
                        rank=rank,
                        chunk_id=r.get("id", f"kb_{rank}"),
                        source_id=r.get("source_type", ""),
                        source_title=r.get("source_type", ""),
                        source_url=r.get("source_url", ""),
                        document_name=r.get("document_name", ""),
                        page=page,
                        section=r.get("section", ""),
                        content=f"{text[:500]}{page_str}",
                        vehicle_model=r.get("model_id", "") or "",
                        vehicle_version="all_versions",
                        topic=topic or "",
                        market="Vietnam",
                        language="vi",
                        approval_status="approved",
                        retrieval_score=round(score, 4),
                    ).__dict__
                )

        elif tool == "get_specs" and result.get("specs"):
            specs = result["specs"]
            # Use keyword scoring for log (more granular than hybrid embedding).
            # Hybrid scoring is used in assess_evidence for validation decisions.
            scores = (
                [_spec_relevance_score(qtokens, s.get("key", ""), s.get("value", "")) for s in specs]
                if qtokens
                else [0.5] * len(specs)
            )
            for i, s in enumerate(specs):
                score = scores[i] if i < len(scores) else 0.0
                if score < MIN_SCORE:
                    continue
                rank += 1
                page = s.get("page", "")
                page_str = f" (trang {page})" if page else ""
                chunks.append(
                    RetrievedChunk(
                        rank=rank,
                        chunk_id=f"spec_{result.get('model_code', '')}_{s.get('key', '')}",
                        source_id="car_specs",
                        source_title=f"Specs {result.get('model_code', '')}",
                        source_url=result.get("source_url", ""),
                        document_name=result.get("document_name", ""),
                        page=page,
                        section=s.get("category", ""),
                        content=f"{s.get('key', '')}: {s.get('value', '')} {s.get('unit', '')}{page_str}",
                        vehicle_model=result.get("model_code", ""),
                        vehicle_version=s.get("version_name", "all_versions"),
                        topic="thông_số_kỹ_thuật",
                        market="Vietnam",
                        language="vi",
                        approval_status="approved",
                        retrieval_score=round(score, 4),
                    ).__dict__
                )

        elif tool == "get_colors" and result.get("colors"):
            mc = result.get("model_code", "")
            variants = result.get("variants", [])
            # Build text representations and score by keyword overlap

            variant_texts = []
            for v in variants[:10]:
                variant_texts.append(f"{v.get('color', '')} {v.get('color_type', '')} {v.get('interior', '')}")
            if variant_texts:
                scores = _embed_score(variant_texts)
                for v, sc in zip(variants[:10], scores, strict=False):
                    if sc < MIN_SCORE:
                        continue
                    rank += 1
                    chunks.append(
                        RetrievedChunk(
                            rank=rank,
                            chunk_id=f"color_{mc}_{v.get('color', '')}_{v.get('interior', '')}",
                            source_id="car_colors",
                            source_title=f"Màu sắc {mc}",
                            source_url="",
                            document_name="",
                            page="",
                            section="colors",
                            content=f"{v.get('color', '')} / {v.get('interior', '')}",
                            vehicle_model=mc,
                            vehicle_version=v.get("version", "all_versions"),
                            topic="ngoại_thất",
                            market="Vietnam",
                            language="vi",
                            approval_status="approved",
                            retrieval_score=round(sc, 4),
                        ).__dict__
                    )

        elif tool == "get_price" and result.get("prices"):
            # Build text representations and score by keyword overlap
            price_texts = [
                f"{p.get('version_name', '')} {p.get('price_vnd', '')} {p.get('promo_label', '') or ''}"
                for p in result["prices"]
            ]
            scores = _embed_score(price_texts) if price_texts else []
            for i, p in enumerate(result["prices"]):
                score = scores[i] if i < len(scores) else 0.5
                if score < MIN_SCORE:
                    continue
                rank += 1
                chunks.append(
                    RetrievedChunk(
                        rank=rank,
                        chunk_id=f"price_{result.get('model_code', '')}_{p.get('version_name', '')}",
                        source_id="price_list",
                        source_title=f"Giá {result.get('model_code', '')}",
                        source_url=result.get("source_url", ""),
                        document_name="",
                        page="",
                        section="pricing",
                        content=f"{p.get('version_name', '')}: {p.get('price_vnd', '')}",
                        vehicle_model=result.get("model_code", ""),
                        vehicle_version=p.get("version_name", "all_versions"),
                        topic="pricing",
                        market="Vietnam",
                        language="vi",
                        approval_status="approved",
                        retrieval_score=round(score, 4),
                    ).__dict__
                )

    # Sort by score descending and limit
    chunks.sort(key=lambda x: x.get("retrieval_score", 0), reverse=True)
    for i, c in enumerate(chunks):
        c["rank"] = i + 1
    return chunks[:MAX_CHUNKS]


def build_displayed_citations(citations: list[dict], retrieved_chunks: list[dict] | None = None) -> list[dict]:
    """Convert citations → P0 displayed_citations schema."""
    chunk_ids_by_url: dict[str, list[str]] = {}
    pages_by_url: dict[str, set[str]] = {}
    if retrieved_chunks:
        for rc in retrieved_chunks:
            url = rc.get("source_url", "")
            cid = rc.get("chunk_id", "")
            page = rc.get("page", "")
            if url and cid:
                chunk_ids_by_url.setdefault(url, [])
                if cid not in chunk_ids_by_url[url]:
                    chunk_ids_by_url[url].append(cid)
            if url and page:
                pages_by_url.setdefault(url, set()).add(str(page))

    seen = set()
    cit_counter = 0
    result = []
    for c in citations:
        url = c.get("source_url", "")
        if not url or url in seen:
            continue
        seen.add(url)
        cit_counter += 1
        model = c.get("model_code", "")
        label = c.get("source_type", "")
        text = f"{model} — {label}" if model and label else (label or url)
        pages = sorted(pages_by_url.get(url, set()), key=lambda x: int(x) if x.isdigit() else 0)
        page_str = ", ".join(pages) if pages else ""
        if page_str:
            text += f" (trang {page_str})"
        cids = chunk_ids_by_url.get(url, [])
        if not cids and c.get("chunk_id"):
            cids = [c["chunk_id"]]
        result.append(
            DisplayedCitation(
                citation_id=f"cit_{cit_counter:03d}",
                display_text=text,
                source_id=label,
                chunk_ids=cids,
                source_url=url,
                document_name=c.get("document_name", ""),
                page=page_str,
                section=c.get("section", ""),
            ).__dict__
        )
    return result
