"""환경 설정. 모든 값은 .env로 주입한다."""
from __future__ import annotations

import os
from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://alldap:alldap@localhost:5432/alldap"

    # 임베딩 — 모델을 바꾸면 embedding_dim과 DB의 VECTOR(n)도 함께 바꿀 것
    openai_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536
    embedding_batch_size: int = 100

    # 생성
    anthropic_api_key: str = ""
    chat_model: str = "claude-sonnet-4-6"
    max_tokens: int = 1024

    # 검색
    top_k: int = 5
    # 이 거리(코사인)보다 먼 청크는 근거로 쓰지 않는다 → fallback 유도
    max_distance: float = 0.55

    upload_max_bytes: int = 20 * 1024 * 1024   # 20MB

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
