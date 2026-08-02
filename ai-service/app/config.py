"""환경 설정. 모든 값은 .env로 주입한다."""
from __future__ import annotations

import os
from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://alldap:alldap@localhost:5432/alldap"

    # 생성(답변·질문)은 Google Gemini 를 쓴다.
    # ⚠️ 임베딩은 더 이상 Gemini 가 아니다 — 아래 Cloudflare 항목 참고.
    google_api_key: str = ""

    # ── 임베딩: Cloudflare Workers AI ──────────────────────────────────
    # 2026-08-02 에 gemini-embedding-001(1536차원) 에서 옮겼다.
    #
    # ⚠️ 성능 때문이 아니다. 두 모델을 <같은 한국어 검색 벤치마크에서 나란히 잰
    #    측정치가 존재하지 않는다>. 옮긴 이유는 두 가지다:
    #      ① 약관 — Gemini 무료 등급은 공식 가격표에 "Used to improve our products: Yes",
    #         즉 입력을 학습에 쓴다고 적혀 있다. 이 제품은 고객 사내 문서를 받는 것이 목적이다.
    #         Cloudflare 는 "고객 콘텐츠를 모델 학습에 쓰지 않는다"를 문서에 명시한다.
    #      ② 한도 — Gemini 무료 한도는 수치가 비공개인데, Cloudflare 는
    #         10,000 뉴런/일(bge-m3 기준 약 930만 토큰/일)이 공개돼 있고 매일 리셋된다.
    #    "한국어 성능이 더 좋다"고 말하면 출처를 대라는 순간 무너진다. 그건 W4 에서 직접 잰다.
    #
    # 실측(2026-08-02): 차원 1024 / 입력 2개→벡터 2개 / 배치 100개 705ms /
    #                   응답 경로는 result.data
    embedding_model: str = "@cf/baai/bge-m3"
    # ⚠️ 이 값과 DB 의 VECTOR(n) 은 <반드시 함께> 바꿔야 한다.
    #    하나만 바꾸면 INSERT 할 때까지 아무 에러도 안 나고 조용히 깨진다.
    #    (현재 1024 ↔ V2__embedding_1024.sql)
    embedding_dim: int = 1024
    # Cloudflare 배열 상한은 문서에 없다. 100개가 되는 것은 실측으로 확인했다.
    embedding_batch_size: int = 100
    cf_account_id: str = ""
    cf_api_token: str = ""

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

    # 채점(LLM-as-Judge) 모델. Cloudflare Workers AI 라 임베딩과 같은 계정·토큰을 쓴다.
    #
    # ⚠️ <답변 생성 모델(chat_model)과 반드시 달라야 한다.> 같은 모델이 자기 답변을
    #    채점하면 자기 실수를 그대로 통과시킨다. 자세한 근거는 judge.py 첫 주석 참고.
    #    지금은 생성 Google Gemini / 채점 Cloudflare Mistral 로 제공자까지 갈라져 있다.
    #
    # 이 모델을 고른 근거(2026-08-02 실측): 정답이 정해진 한국어 3케이스
    # (충실한 답 / 지어낸 답 / 절반만 맞는 답)에서 1 / 0 / 0.5 를 정확히 매겼고 가장 빨랐다.
    # 후보 비교표는 judge.py 주석에 있다.
    judge_model: str = "@cf/mistralai/mistral-small-3.1-24b-instruct"
    # 이보다 짧은 청크는 표본에서 뺀다. "1. 총칙" 같은 목차 조각으로는 문제를 낼 수 없고
    # LLM 호출 비용만 나간다. 청크가 500자 단위라 100자면 "내용이 있다"고 보기에 충분하다.
    eval_min_chunk_chars: int = 100

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
