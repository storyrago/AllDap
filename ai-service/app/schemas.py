"""API 입출력 스키마."""
from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class DocumentOut(BaseModel):
    id: UUID
    filename: str
    file_type: str
    status: str
    error_message: str | None = None
    char_count: int | None = None
    chunk_count: int | None = None


class Source(BaseModel):
    chunk_id: UUID
    document_id: UUID
    filename: str
    score: float = Field(description="0~1, 높을수록 관련성 높음")
    preview: str


class ChatRequest(BaseModel):
    bot_id: UUID
    message: str = Field(min_length=1, max_length=2000)
    session_id: str = Field(default="local-test", max_length=64)


class ChatResponse(BaseModel):
    answer: str
    sources: list[Source]
    is_fallback: bool
    latency_ms: int
