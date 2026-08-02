"""환경 설정. 모든 값은 .env로 주입한다."""
from __future__ import annotations

import os
from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://alldap:alldap@localhost:5432/alldap"

    # ⚠️ Gemini 는 이제 <테스트 질문 생성>에만 쓴다 (eval_question_model).
    #    임베딩·답변생성·채점은 전부 Cloudflare 로 옮겼다. 아래 각 항목 참고.
    #    질문 생성만 남긴 이유는 품질이 아니라 <분리>다 — 질문·답변·채점을 전부
    #    같은 제공자로 두면 셋이 같은 편향을 공유한다.
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

    # ── 답변 생성: Cloudflare Workers AI ──────────────────────────────
    # 2026-08-02 에 gemini-3.5-flash-lite 에서 옮겼다.
    #
    # ⚠️ 품질 때문이 아니라 <무료 한도> 때문이다. Gemini 무료는
    #    GenerateRequestsPerDayPerProjectPerModel-FreeTier — 모델당 하루 20회다(실측).
    #    평가 1회 = 질문 수만큼 답변 생성 호출이라, 21문항 실행이 쿼터에 걸려
    #    5건이 아예 처리되지 못했다. W4 는 설정을 바꿔가며 여러 번 돌려야 하는데
    #    하루 한 번으로는 진도가 안 나간다. Cloudflare 는 10,000 뉴런/일이라 사실상 넉넉하다.
    #
    # 모델 선택 근거 (2026-08-02 실측): <환각 억제(NO_ANSWER) 준수>로 걸렀다.
    # 근거 없는 질문에 정확히 "NO_ANSWER" 를 뱉는지 3회씩 확인:
    #   llama-3.3-70b-fp8-fast : 3/3 · 650~1181ms   ← 채택 (가장 빠름)
    #   gpt-oss-120b           : 3/3 · 1174~2473ms
    #   nemotron-3-120b        : 3/3 · 1980~2742ms
    #   gemma-4-26b            : 3/3 · 3286~5126ms
    #   qwen3-30b-a3b          : 0/3 ❌ — "확인되지 않았습니다"로 <풀어서> 답한다.
    #                            NO_ANSWER 토큰이 없으니 generator 의 부분 문자열 검사에
    #                            안 걸려 fallback 이 아닌 것으로 집계된다 = 환각 억제가 뚫린다.
    #
    # ⚠️ judge_model(mistral-small)과 <반드시 달라야 한다>. 같으면 자기 답을 자기가 채점한다.
    chat_model: str = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
    max_tokens: int = 1024

    # 테스트 질문 생성 전용 모델. <chat_model 과 일부러 다른 모델을 쓴다.>
    #
    # 이유는 품질이 아니라 <무료 한도>다. Gemini 무료 등급은
    # GenerateRequestsPerDayPerProjectPerModel-FreeTier — 즉 <모델별로> 하루 20회다(실측).
    # 질문 생성과 답변 생성이 같은 모델을 쓰면 한 통에서 같이 깎여,
    # 질문 20개를 만들면 그날 평가 실행을 한 번도 못 돌린다.
    # 모델을 나누면 각각 20회를 받는다.
    #
    # gemini-3.1-flash-lite 를 고른 근거(2026-08-02 실측): 호출 가능하고
    # thoughtsTokenCount=0(사고를 안 해 JSON 잘림이 없다). AGENTS.md 의 모델 표 참고.
    # ⚠️ 사고하는 모델로 바꾸면 evaluator.py 의 잘림 문제가 재발한다.
    eval_question_model: str = "gemini-3.1-flash-lite"

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
    #    현재 배치: 답변 = Meta llama-3.3-70b / 채점 = Mistral small-3.1-24b.
    #    제공자는 같지만 <모델 계열이 달라> 가중치를 공유하지 않는다.
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
