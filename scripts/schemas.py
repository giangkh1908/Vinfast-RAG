#!/usr/bin/env python3
"""
schemas.py — Pydantic models cho data pipeline.

Validate chunk JSONL + Qdrant payload + sparse payload.
Enforce contract: sparse payload ⊆ dense payload.

Usage:
    from scripts.schemas import Chunk, DensePayload, SparsePayload, validate_chunk, validate_payloads
"""

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class Chunk(BaseModel):
    """Schema cho chunk trong JSONL (đầu vào ingest)."""
    id: str
    collection: str
    vector_version: str
    model_id: Optional[str] = None
    edition_id: Optional[str] = None
    category: str
    section_path: list[str]
    text: str
    text_type: Literal["prose", "table", "list", "key_value", "qa_pair", "legal_clause", "link_list"]
    structured: dict[str, Any]
    language: str = "vi"
    tags: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    source_file: str
    source_url: str
    source_type: str
    fetched_at: str
    ingested_at: str
    page: Optional[int] = None
    is_hot: bool

    @field_validator("text")
    @classmethod
    def text_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("text cannot be empty")
        return v

    @field_validator("section_path")
    @classmethod
    def section_path_not_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("section_path cannot be empty")
        return v

    @field_validator("tags")
    @classmethod
    def tags_not_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("tags cannot be empty")
        return v


class DensePayload(BaseModel):
    """Schema cho payload Qdrant dense (toàn bộ field trừ id/is_hot)."""
    collection: str
    vector_version: str
    model_id: Optional[str] = None
    edition_id: Optional[str] = None
    category: str
    section_path: list[str]
    text: str
    text_type: str
    structured: dict[str, Any]
    language: str
    tags: list[str]
    confidence: float
    source_file: str
    source_url: str
    source_type: str
    fetched_at: str
    ingested_at: str
    page: Optional[int] = None


class SparsePayload(BaseModel):
    """Schema cho payload Qdrant sparse (tối giản để filter)."""
    collection: str
    chunk_id: str
    model_id: Optional[str] = None
    vector_version: str
    text: str

    @field_validator("text")
    @classmethod
    def text_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("sparse payload text cannot be empty")
        return v


def validate_chunk(chunk_dict: dict[str, Any], context: str = "") -> Chunk:
    """Validate chunk dict → Chunk model. Raise ValueError nếu sai schema."""
    try:
        return Chunk(**chunk_dict)
    except Exception as e:
        raise ValueError(f"Chunk validation failed {context}: {e}") from e


def make_dense_payload(chunk: Chunk) -> DensePayload:
    """Tạo DensePayload từ Chunk (bỏ id/is_hot)."""
    data = chunk.model_dump()
    data.pop("id", None)
    data.pop("is_hot", None)
    return DensePayload(**data)


def make_sparse_payload(chunk_id: str, chunk: Chunk) -> SparsePayload:
    """Tạo SparsePayload từ Chunk (5 field tối giản)."""
    return SparsePayload(
        collection=chunk.collection,
        chunk_id=chunk_id,
        model_id=chunk.model_id,
        vector_version=chunk.vector_version,
        text=chunk.text,
    )


def validate_payloads(
    chunks: list[Chunk],
    sparse_chunk_ids: list[str],
    context: str = ""
) -> tuple[list[DensePayload], list[SparsePayload]]:
    """Validate + tạo payload cho dense và sparse.

    Args:
        chunks: list chunks đã validate
        sparse_chunk_ids: chunk_id tương ứng (cùng length với chunks)
        context: context cho error message

    Returns:
        (dense_payloads, sparse_payloads)
    """
    if len(chunks) != len(sparse_chunk_ids):
        raise ValueError(f"Mismatch chunks vs sparse_chunk_ids {context}: {len(chunks)} != {len(sparse_chunk_ids)}")

    dense_payloads = []
    sparse_payloads = []
    errors = []

    for i, (chunk, cid) in enumerate(zip(chunks, sparse_chunk_ids)):
        try:
            dp = make_dense_payload(chunk)
            sp = make_sparse_payload(cid, chunk)
            dense_payloads.append(dp)
            sparse_payloads.append(sp)
        except Exception as e:
            errors.append(f"Chunk {i} ({cid}): {e}")

    if errors:
        raise ValueError(f"Payload validation failed {context}:\n" + "\n".join(errors[:5]))

    return dense_payloads, sparse_payloads


def assert_sparse_subset_dense(dense: DensePayload, sparse: SparsePayload) -> None:
    """Verify sparse payload fields tồn tại trong dense payload."""
    sparse_data = sparse.model_dump()
    dense_data = dense.model_dump()
    for key in sparse_data:
        if key not in dense_data:
            raise ValueError(f"Sparse field '{key}' không tồn tại trong dense payload")
        if dense_data[key] != sparse_data[key]:
            raise ValueError(f"Sparse field '{key}' mismatch: {sparse_data[key]} != {dense_data[key]}")
