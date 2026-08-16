#!/usr/bin/env python3
"""
schemas.py — Pydantic models cho data pipeline.

Validate chunk JSONL + Qdrant payload + sparse payload.

Usage:
    from scripts.schemas import Chunk, DensePayload, SparsePayload, validate_chunk
"""

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


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
