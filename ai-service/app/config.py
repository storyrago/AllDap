"""환경 설정. 모든 값은 .env로 주입한다."""
from __future__ import annotations

import os
from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://alldap:alldap@localhost:5432/alldap"

    # 임베딩과 생성 모두 Google Gemini 를 쓴다. 키 하나로 둘 다 된다.
    google_api_key: str = ""

    # 임베딩 — 모델을 바꾸면 embedding_dim과 DB의 VECTOR(n)도 함께 바꿀 것.
    # gemini-embedding-001 을 쓰는 이유(gemini-embedding-2 가 아니라):
    #   ① 문자열 리스트를 주면 각각 개별 임베딩을 돌려준다.
    #      embedding-2 는 리스트를 통째로 합쳐 벡터 1개를 반환해서,
    #      청크 100개가 에러 없이 벡터 1개로 뭉개진다. 조용히 깨지는 종류의 버그다.
    #   ② task_type 파라미터가 이 모델에만 있다 (retriever.py 주석 참고)
    embedding_model: str = "gemini-embedding-001"
    # 기본 출력이 3072차원이지만 MRL 기반이라 잘라 쓸 수 있고, 1536은 공식 권장값이다.
    # DB 컬럼이 VECTOR(1536) 이므로 여기에 맞춘다 → 마이그레이션 불필요.
    embedding_dim: int = 1536
    embedding_batch_size: int = 100

    # 생성 — flash 계열은 무료 등급에서 쓸 수 있다(pro 계열은 확인 안 됨).
    #
    # ⚠️ models.list() 에 나오는 모델이라고 다 부를 수 있는 게 아니다.
    #    구세대는 목록에 남아 있으면서 호출하면 404 를 준다:
    #      "This model models/... is no longer available to new users."
    #    2026-08-02 실측으로 gemini-2.5-flash-lite 가 그렇게 막혔다.
    #    <목록만 보고 고르지 말고 반드시 실제로 호출해볼 것.>
    #
    # gemini-3.5-flash 에서 flash-lite 로 바꾼 이유 (2026-08-02):
    #   ① <사고 토큰 문제가 사라진다.> flash 는 사고 토큰이 max_output_tokens 를 함께 먹어
    #      JSON 이 중간에 잘렸다(evaluator.py 주석의 실측 참고). flash-lite 는 같은 요청에
    #      thoughtsTokenCount=0 으로 답한다 — 껄 것이 없다.
    #   ② 비용이 1/4 수준이다(입력 $1.50→$0.30, 출력 $9.00→$2.50 / 1M).
    #      현재 쓰던 3.5-flash 가 Flash 라인에서 가장 비싼 축이었다.
    #   ③ 무료 등급 한도는 <모델별로 따로> 잡힌다
    #      (quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier).
    #      즉 용도별로 모델을 나누면 각각 별도 한도를 받는다.
    #
    # ⚠️ 모델을 바꾸면 fallback 수치를 <반드시 다시 재야 한다>. W1 완료 조건의
    #    "근거 없는 질문 10개 → fallback 10/10" 은 gemini-3.5-flash 기준이었다.
    chat_model: str = "gemini-3.5-flash-lite"
    max_tokens: int = 1024

    # 검색
    top_k: int = 5
    # 이 거리(코사인)보다 먼 청크는 근거로 쓰지 않는다 → fallback 유도
    max_distance: float = 0.55

    upload_max_bytes: int = 20 * 1024 * 1024   # 20MB

    # 평가 (W3)
    # 한 번 호출에 만들 수 있는 질문 수의 상한. 청크 1개당 LLM 을 1번 부르므로
    # 이 값이 곧 <비용 상한>이자 <응답 시간 상한>이다.
    # 20 으로 둔 근거: Spring 의 read-timeout 이 120초(application.yaml)인데
    # 호출 1건이 수 초 걸리므로 그 안에 들어와야 한다. 실측값은 docs/decisions.md 참고.
    eval_max_questions: int = 20
    # 이보다 짧은 청크는 표본에서 뺀다. "1. 총칙" 같은 목차 조각으로는 문제를 낼 수 없고
    # LLM 호출 비용만 나간다. 청크가 500자 단위라 100자면 "내용이 있다"고 보기에 충분하다.
    eval_min_chunk_chars: int = 100

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
