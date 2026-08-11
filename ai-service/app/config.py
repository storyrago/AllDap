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
    # gemini-3.5-flash-lite 로 되돌린 이유(2026-08-02): 답변 생성이 Cloudflare 로 옮겨가면서
    # 이 모델의 하루 20회가 <통째로 비었다>. 굳이 다른 모델을 쓸 이유가 없어졌다.
    # (호출 가능 + thoughtsTokenCount=0 이라 JSON 잘림도 없다 — AGENTS.md 의 모델 표 참고)
    # ⚠️ 사고하는 모델로 바꾸면 evaluator.py 의 잘림 문제가 재발한다.
    eval_question_model: str = "gemini-3.5-flash-lite"

    # ── 검색 (W4 에서 켜고 끄며 비교한다) ─────────────────────────────
    top_k: int = 5

    # 리랭커 — 벡터가 가져온 후보를 다시 정렬한다.
    #
    # ⚠️ 기본값이 False 인 이유는 "아직 안 붙였다"가 아니라 <실측 결과 효과가 없어서>다.
    #
    #    최종 측정(2026-08-02, 채점 버그를 고친 뒤 공정한 조건):
    #      리랭커 OFF → 전체 충실성 0.952 · 응답률 1.000 · 60초
    #      리랭커 ON  → 전체 충실성 0.952 · 응답률 1.000 · 191초
    #    <점수는 완전히 같고 3배 느리다.> 그래서 안 켠다.
    #
    #    ⚠️ 처음엔 "한국어에서 나빠서"라고 판정했는데 <그건 틀린 근거였다.>
    #       그때는 리랭커에게 preview(앞 200자)만 넘기고 있었다 — 청크가 500자라
    #       절반 이상을 못 본 상태로 "못 맞힌다"고 판정한 것이다(retriever._rerank 주석 참고).
    #       마이크로 실험(6케이스에서 3/6)은 짧은 지문이라 그 영향이 없었고 지금도 유효하지만,
    #       종단 평가에서는 top_k=5 라는 여유 덕에 순위가 흔들려도 정답이 근거 안에 남는다.
    #       <작은 실험의 지표가 파이프라인 성능의 대리지표가 아니었다.>
    #
    # ── 2026-08-11 재측정: "효과가 없다"도 <틀렸다.> 코퍼스가 쉬웠던 것이다 ──
    #
    #    위 0.952 는 문서 14개(청크 85) 시절 숫자다. 그때는 정답이 항상 top5 안에
    #    들어와서 <재정렬할 것 자체가 없었다.> 코퍼스를 50문서·306청크로 키우고
    #    같은 주제·다른 대상 문서(연구소·공장·자회사 …)를 넣자 결과가 갈렸다:
    #
    #      리랭커 OFF → 전체 충실성 0.781 (3회) · 0.813 (1회) · 채팅 0.72초
    #      리랭커 ON  → 전체 충실성 0.844 (3회 전부 동일)  · 채팅 1.51초
    #
    #    🔴 그런데 <응답률은 0.875 로 양쪽이 같다. 그게 "아무 일도 없었다"가 아니다.>
    #       fallback 2건이 회복되고 <다른> 2건이 새로 fallback 났다. 1:1 대조:
    #         고침 4건: 노트북(fb→1.0) 결혼휴가(fb→1.0) 시용기간(0.0→1.0) 쌍둥이(0.5→1.0)
    #         깨짐 3건: 재택(1.0→fb) 기간제연차(1.0→fb) 영문증명서(1.0→0.5)
    #       깨진 이유는 <리랭커가 정답 청크를 top5 밖으로 밀어낸> 것이다.
    #       리랭커는 순서를 바꾸는 도구이고, 바꾸면 <양방향으로> 바뀐다.
    #
    #    그래도 기본값을 False 로 두는 이유:
    #      ① 순증이 +1.0/16 = +0.063 인데 측정 편차가 0.032 다. OFF 최고값(0.813)과
    #         비교하면 +0.031 로 <편차와 같은 크기>다. 그리고 +0.5 는 flaky 문항에서 왔다.
    #      ② 지연이 2배다.
    #      ③ 🔴 새로 만든 실패가 <근거가 있는데 못 답한> 것이다. 이 제품이 가장 중시하는
    #         축에서 나빠졌다. 평균이 조금 오르는 대가로 그걸 사지 않는다.
    #    → 켜려면 "정답을 밀어내지 않게" 만드는 게 먼저다(rerank_candidates 조정,
    #      벡터 순위와의 점수 결합 등). 그건 별도 슬라이스다.
    #
    # 그럼 왜 코드를 남겼나: 위 숫자가 전부 이 코드로 만든 것이다.
    # 지우면 <재현할 수 없는 주장>이 된다. 한국어 리랭커가 생기면
    # reranker_model 만 바꿔 다시 재면 된다.
    reranker_enabled: bool = False
    reranker_model: str = "@cf/baai/bge-reranker-base"
    # 리랭커는 벡터가 <가져온 것 안에서> 순서만 바꾼다. 후보에 없으면 살릴 수 없다.
    # 그래서 top_k 보다 넉넉히 뽑아 재정렬한 뒤 top_k 만 남긴다.
    rerank_candidates: int = 20
    # ── 하이브리드 검색 (키워드 + 벡터) ──────────────────────────────
    #
    # 왜 붙였나: 리랭커 재측정(2026-08-11)에서 <정답 청크가 밀려나> 새 fallback 이
    # 2건 났는데, 그 청크들은 질문에 그 단어가 <그대로> 들어 있었다
    # ("기간제 근로자…" → `02_계약직_인사규정`). 키워드 매칭이면 놓칠 수 없는 것들이다.
    # 벡터가 약한 자리(부정문·동의어 없는 고유명사)를 키워드가 받쳐주는 게 목적이다.
    hybrid_enabled: bool = False
    # 벡터·키워드 각각 이만큼 뽑아 RRF 로 합친 뒤 top_k 만 남긴다.
    hybrid_candidates: int = 20
    # RRF 상수. 원 논문(Cormack 2009)의 60 을 그대로 쓴다.
    # 값이 클수록 상위권과 하위권의 점수 차가 완만해진다 = 1등을 덜 특별 취급한다.
    # ⚠️ 60 은 <우리가 튜닝한 값이 아니다.> 근거는 "표준값"뿐이다.
    hybrid_rrf_k: int = 60

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
    # ── FriendliAI (실험용) ───────────────────────────────────────────
    # K-EXAONE 같은 국산 모델을 재보려고 붙였다. <프로덕션 경로가 아니다> —
    # K-EXAONE 서버리스 Model API 가 2026-08-20 종료 예정이다.
    # 비어 있으면 friendli.py 가 명확한 오류를 낸다(조용히 건너뛰지 않는다).
    friendli_token: str = ""
    # 여러 팀에 속할 때만 필요하다. 비우면 기본 팀으로 청구된다.
    friendli_team_id: str = ""

    # ── 샘플링 온도 ───────────────────────────────────────────────────
    # 🔴 둘 다 0 이다. 실측으로 필요해진 값이다 (2026-08-03).
    #    온도를 안 정해두면 제공자 기본값(Cloudflare 약 0.6)으로 <매번 샘플링>한다.
    #    같은 설정으로 평가를 4회 돌렸더니 전체 충실성이
    #      1.000 · 0.907 · 1.000 · 1.000
    #    로 흔들렸고, 매번 <다른 문항>이 실패했다. 그 폭(0.093)이 우리가 재려던
    #    개선 폭보다 커서 before/after 비교가 성립하지 않았다.
    #
    #    judge: 채점자는 무조건 0 이어야 한다. 같은 답변에 매번 다른 점수를 주는
    #           자를 기준으로 삼을 수는 없다. 여기엔 창의성이 필요 없다.
    #    chat : 이 제품은 <문서에 있는 사실>을 그대로 전달하는 것이 일이다.
    #           같은 질문에 같은 문서면 같은 답이 나와야 하고, 표현을 바꿔 말하는 것은
    #           기능이 아니라 위험이다(환각 억제가 1순위인 제품이다).
    chat_temperature: float = 0.0
    judge_temperature: float = 0.0

    # ── 청킹 (W4 에서 바꿔가며 비교한다) ──────────────────────────────
    # 🔴 split_headings 는 실측으로 필요해진 값이다 (2026-08-03).
    #    False 였을 때 478자 청크 하나에 조항 4개가 들어갔고, 그 임베딩이
    #    네 주제의 평균이 되어 "노트북 교체 주기" 질문에 안 걸렸다.
    #    답이 문서에 있는데도 검색 5위 안에 그 문서가 안 들어와 fallback 이 났다.
    #    False 로 두면 그때 동작을 그대로 재현한다(before/after 비교용).
    chunk_size: int = 500
    chunk_overlap: int = 50
    chunk_split_headings: bool = True

    eval_min_chunk_chars: int = 100

    # ── 문서 간 모순 탐지 ─────────────────────────────────────────────
    # 후보로 삼을 최대 임베딩 거리. 검색용 max_distance(0.55)보다 <훨씬 조인다>.
    # 모순이려면 두 문장이 같은 주제를 말해야 하는데, 0.55 는 "관련은 있다" 수준이라
    # 무관한 쌍까지 LLM 에 보내게 된다. 판정 비용이 곧 이 값에 달려 있다.
    # ⚠️ 실측으로 조정할 값이다. 낮추면 놓치고, 높이면 돈이 샌다.
    conflict_max_distance: float = 0.35
    # 한 번 스캔에서 판정할 쌍의 상한. <비용 상한이자 시간 상한>이다.
    #
    # 시간이 더 급한 제약이다: 스캔은 동기 API 라 Spring 의 읽기 타임아웃(120초) 안에
    # 끝나야 한다. 판정 1회가 1~2초이므로 30쌍이면 넉넉히 들어온다.
    # 비용은 30쌍 × 약 39뉴런 ≈ 1.2k 뉴런 = 하루 한도(10k)의 12% 다.
    #
    # ⚠️ 후보가 이보다 많으면 <가까운 쌍부터> 처리하고 나머지는 남는다.
    #    판정 결과를 'clear' 로도 저장하므로 버튼을 다시 누르면 남은 것부터 이어서 한다.
    #    (화면은 candidates == 이 값이면 "아직 남았을 수 있다"로 안내한다)
    conflict_max_pairs: int = 30

    # ── 실행 환경 ─────────────────────────────────────────────────────
    # "prod" 로 두면 아래 _check_prod 가 켜진다. 기본은 local 이라 개발이 안 불편하다.
    # Spring 의 SPRING_PROFILES_ACTIVE=prod 와 짝을 이룬다.
    app_env: str = "local"

    class Config:
        env_file = ".env"
        extra = "ignore"


# 개발 편의를 위한 기본값이지만 <운영에 남아 있으면 사고>인 값들.
# 키는 설정 이름, 값은 "그 값이면 안 되는 것".
_LOCAL_DEFAULTS = {
    "database_url": "postgresql://alldap:alldap@localhost:5432/alldap",
}
# 비어 있으면 안 되는 값들. 없으면 기동은 되고 <첫 요청에서> 터진다 — 그게 더 나쁘다.
_REQUIRED_IN_PROD = ("database_url", "cf_account_id", "cf_api_token")


def _check_prod(s: Settings) -> None:
    """운영에서 설정이 빠졌으면 <시끄럽게 죽는다>.

    왜 이게 필요한가
    ─────────────────────────────────────────────────────────────────────────
    Spring 쪽 `application-prod.yaml` 은 이미 이 원칙으로 짜여 있다 —
    "환경변수가 없으면 기동 자체가 실패해야 한다. 차라리 시끄럽게 죽는 편이 안전하다."
    그런데 이 파일은 <전부 기본값이 있어> 정반대였다. 두 서비스가 같은 배포에
    올라가는데 한쪽만 fail-closed 면, 사고는 항상 느슨한 쪽에서 난다.

    구체적으로 무엇이 위험했나:
      · DATABASE_URL 을 빼먹으면 <운영 컨테이너가 localhost 의 DB> 를 찾는다.
      · CF_API_TOKEN 을 빼먹으면 기동은 멀쩡히 되고 <사용자의 첫 질문에서> 터진다.
        기동 실패는 배포하다 바로 보이지만, 첫 질문 실패는 사용자가 먼저 본다.
    """
    if s.app_env != "prod":
        return

    problems = []
    for name in _REQUIRED_IN_PROD:
        if not getattr(s, name):
            problems.append(f"{name.upper()} 가 비어 있습니다")
    for name, local_value in _LOCAL_DEFAULTS.items():
        if getattr(s, name) == local_value:
            problems.append(f"{name.upper()} 가 로컬 개발용 기본값 그대로입니다")

    if problems:
        raise RuntimeError(
            "운영 설정이 올바르지 않아 기동을 중단합니다 (APP_ENV=prod):\n  - "
            + "\n  - ".join(problems)
            + "\n환경변수를 확인해주세요. 항목은 ai-service/.env.example 에 있습니다."
        )


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    # lru_cache 라 프로세스당 한 번만 돈다. 어느 코드가 먼저 설정을 읽든 여기서 걸린다.
    _check_prod(s)
    return s
