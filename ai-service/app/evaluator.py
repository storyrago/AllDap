"""테스트 질문 자동 생성 (W3 · 품질 대시보드의 첫 조각).

무엇을 하는가
─────────────────────────────────────────────────────────────────────────────
봇에 올라간 문서의 청크에서 표본을 뽑아, LLM 에게
"이 내용으로 사람이 물어볼 법한 질문 1개와 그 답 1개를 만들어라" 를 시킨다.
그 결과가 `eval_questions` 에 쌓이고, 다음 슬라이스의 <평가 실행>이 이 질문들을
실제 챗봇 파이프라인에 태워 채점한다.

왜 사람이 직접 안 쓰고 LLM 이 만드는가
─────────────────────────────────────────────────────────────────────────────
평가를 하려면 "정답을 아는 질문"이 있어야 하는데, 그걸 사람이 손으로 만들면
문서가 바뀔 때마다 다시 만들어야 한다. 청크에는 이미 정답이 들어 있으므로
LLM 에게 "이 문단을 보고 문제를 내라"고 시키는 게 가장 싸다.

⚠️ 이 방식의 한계 (숨기지 말 것 — 면접 답변거리다)
   여기서 나오는 질문은 <정의상 전부 근거가 있는 질문>이다.
   그래서 이 테스트셋으로는 "근거가 없을 때 침묵하는가"(이 제품의 차별점)를 못 잰다.
   즉 응답률(answered_rate)의 <상한>만 측정된다.
   근거 없는 질문(negative set)은 PRD F-05 가 요구하지 않아 이번엔 만들지 않는다.

파일 위치에 대해
─────────────────────────────────────────────────────────────────────────────
SQL 과 LLM 호출이 한 파일에 같이 있다. `retriever.py` 가 이미 같은 모양이다
(검색 SQL + 임베딩 호출). "질문 생성"이라는 관심사 하나가 한 파일에 모이는 쪽이
main.py 에 SQL 을 또 흘려보내는 것보다 읽기 낫다.
"""
from __future__ import annotations

import json
import logging
from uuid import UUID

from google.genai import types
from pydantic import BaseModel, Field

from .config import get_settings
from .db import cursor
# generator 의 클라이언트를 그대로 쓴다. 같은 코드를 3벌째 복사하지 않으려는 것뿐이다.
# (_gemini 는 이름 앞에 _ 가 붙어 "모듈 내부용"이라는 뜻이지만, 파이썬은 이를 강제하지 않는다.
#  약속을 어기는 셈이라 이유를 남긴다 — 아래 TODO 가 해소되면 이 import 도 없어진다.)
# TODO(W3): _gemini() 가 retriever.py 와 generator.py 에 <이미 2벌> 복사돼 있다.
#           셋을 공용 모듈 하나로 합치는 건 이 슬라이스와 무관하므로 별도 커밋으로 뺀다.
from .generator import _gemini

# uvicorn 이 자기 로거 설정을 그대로 물려주므로 별도 설정 없이 콘솔에 찍힌다.
# 청크를 건너뛴 이유를 남기는 용도다 — 안 남기면 "4개 요청했는데 3개 나온" 이유를 알 수 없다.
_log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 1. LLM 에게 받을 모양
# ─────────────────────────────────────────────────────────────────────────────

class QuestionPair(BaseModel):
    """LLM 이 청크 하나를 보고 만들어야 하는 (질문, 정답) 한 쌍.

    이 클래스를 <응답 스키마>로 넘기면 Gemini 가 이 모양의 JSON 만 뱉는다.
    직접 텍스트를 받아 ```json 코드펜스를 벗기고 json.loads 로 파싱하는 것보다
    코드가 짧고, 형식이 깨질 여지가 줄어든다.

    ⚠️ 그래도 방어는 필요하다 — 안전 필터에 걸리거나 토큰이 잘리면
       구조화 출력을 켜뒀어도 빈 응답이 온다. 아래 make_question 참고.
    """

    question: str = Field(description="문서를 읽지 않은 사람이 물어볼 법한 한국어 질문 한 문장")
    ground_truth: str = Field(description="주어진 내용만으로 답할 수 있는 한국어 정답")


GENERATION_PROMPT = """당신은 사내 문서로 챗봇의 성능을 시험할 문제를 출제하는 사람입니다.

주어진 <내용>을 읽고, 그 내용만으로 답할 수 있는 질문 1개와 그 정답 1개를 만드세요.

반드시 지켜야 할 규칙:
1. 정답은 <내용> 안에 실제로 적혀 있는 것이어야 합니다. 추론하거나 보태지 마세요.
2. 질문은 <내용>을 읽지 않은 사람이 실제로 물어볼 법한 자연스러운 문장이어야 합니다.
   "위 문서에 따르면", "이 문단에서" 같은 표현을 쓰지 마세요. 그런 질문은 실사용과 다릅니다.
3. 질문은 한 가지만 물어보세요. "A와 B는 각각 무엇인가요?"처럼 여러 개를 묶지 마세요.
4. 정답은 간결하게, 한국어 존댓말로 쓰세요.
5. 답이 될 만한 사실이 <내용>에 없으면, 목차나 제목뿐이라도 억지로 만들지 말고
   question 과 ground_truth 를 모두 빈 문자열로 두세요.

절대 쓰지 말 것: "NO_ANSWER"
  (이 단어는 챗봇이 "모르겠다"를 표시하는 신호라, 질문이나 정답에 섞이면
   나중에 채점할 때 그 질문의 답변이 무조건 미답변으로 뒤집힙니다.)"""


def _finish_reason(resp) -> str:
    """응답이 왜 끝났는지. 로그에만 쓴다.

    candidates 가 비어 있을 수 있어서(안전 필터에 통째로 막히면 그렇다)
    그냥 resp.candidates[0] 를 쓰면 IndexError 가 난다.
    """
    if not resp.candidates:
        return "candidates 없음"
    return str(resp.candidates[0].finish_reason)


def make_question(content: str) -> QuestionPair | None:
    """청크 본문 하나 → (질문, 정답) 한 쌍. 못 만들면 None.

    None 을 돌려주는 경우:
      · 안전 필터 차단·토큰 잘림으로 응답이 비었을 때
      · LLM 이 규칙 5에 따라 "만들 게 없다"고 빈 문자열을 돌려줬을 때
      · NO_ANSWER 가 섞여 들어왔을 때 (규칙으로 막았지만 실제로 지켜지는지는 별개다)

    호출하는 쪽은 None 을 <실패가 아니라 건너뛸 것>으로 다룬다.
    청크 하나가 목차라서 문제를 못 낸 것이 요청 전체를 실패시킬 이유는 없다.
    """
    s = get_settings()

    try:
        resp = _gemini().models.generate_content(
            model=s.chat_model,
            contents=f"<내용>\n{content}\n</내용>",
            config=types.GenerateContentConfig(
                system_instruction=GENERATION_PROMPT,
                max_output_tokens=s.max_tokens,
                # 이 두 줄이 구조화 출력이다. mime_type 만으로는 "JSON 이면 아무 모양이나"가 되고,
                # response_schema 까지 줘야 필드 이름·타입이 고정된다.
                response_mime_type="application/json",
                response_schema=QuestionPair,
                # ⚠️ 사고(thinking)를 끈다. 성능 튜닝이 아니라 <버그 수정>이다.
                #
                # gemini-3.5-flash 는 답을 내기 전에 "생각"을 하는데, 그 사고 토큰이
                # max_output_tokens 를 <함께> 소모한다. 그래서 JSON 자체는 50토큰도 안 되는데
                # 사고에 1024를 다 써버리고 본문이 중간에 잘린다(finish_reason=MAX_TOKENS).
                # 잘린 JSON 은 파싱이 안 되므로 그 청크는 조용히 버려진다.
                #
                # 실측(2026-08-02, 같은 청크 5회씩):
                #   사고 켬 → 성공 2/5, MAX_TOKENS 로 잘림 3회, 평균 3768ms
                #   사고 끔 → 성공 2/5, 잘림 0회,             평균 1164ms  (나머지는 429 쿼터)
                # 즉 잘림이 사라지고 3배 빨라진다.
                #
                # 끄는 게 안전한 이유: 이 작업은 "주어진 문단에서 사실 하나를 뽑아 문제로 만들기"라
                # 추론이 필요 없다. 반대로 <채팅 답변 생성은 사고를 켜둔다> — 거기선 필요하다.
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
    except Exception as e:  # noqa: BLE001 - 어떤 실패든 이 청크만 건너뛰면 된다
        # 여기서 예외를 삼키는 이유: 청크 N개를 도는 중 하나가 실패했다고
        # (429 쿼터 초과·일시적 5xx 등) 요청 전체를 죽이면, 이미 만든 것까지 잃는다.
        # 전부 실패하면 호출하는 쪽이 그 사실을 보고 502 로 알린다.
        _log.warning("질문 생성 실패(이 청크는 건너뜀): %s: %s", type(e).__name__, e)
        return None

    # SDK 가 스키마대로 파싱해 .parsed 에 넣어준다. 다만 응답이 비거나 잘리면 None 이므로
    # 텍스트에서 한 번 더 시도한다 — SDK 버전에 따라 .parsed 가 안 채워지는 경우도 있다.
    pair = resp.parsed
    if pair is None:
        raw = (resp.text or "").strip()
        if not raw:
            _log.warning("빈 응답(건너뜀). finish_reason=%s", _finish_reason(resp))
            return None
        try:
            pair = QuestionPair(**json.loads(raw))
        except Exception:  # noqa: BLE001 - JSON 이 아니든 필드가 없든 결론은 같다: 건너뛴다
            # MAX_TOKENS 면 JSON 이 중간에 끊긴 것이다. 이유를 안 남기면
            # "왜 4개 요청했는데 3개만 나오지?" 를 추적할 방법이 없다.
            _log.warning("JSON 파싱 실패(건너뜀). finish_reason=%s", _finish_reason(resp))
            return None

    question = pair.question.strip()
    ground_truth = pair.ground_truth.strip()

    # 둘 중 하나라도 비면 저장할 수 없다. eval_questions.ground_truth 가 NOT NULL 이다.
    if not question or not ground_truth:
        return None

    # 규칙으로 금지했지만 실제로 지켜졌는지는 확인해야 한다.
    # generator.py 의 fallback 판정이 <부분 문자열> 검사라, 이 단어가 정답에 섞이면
    # 채점 단계에서 그 질문의 답변이 무조건 미답변으로 뒤집힌다.
    from .generator import FALLBACK_TOKEN
    if FALLBACK_TOKEN in question or FALLBACK_TOKEN in ground_truth:
        return None

    return QuestionPair(question=question, ground_truth=ground_truth)


# ─────────────────────────────────────────────────────────────────────────────
# 2. 표본 뽑기 (SQL)
# ─────────────────────────────────────────────────────────────────────────────

def sample_chunks(bot_id: UUID, count: int) -> list[tuple[UUID, str]]:
    """질문을 만들 청크를 무작위로 뽑는다. [(chunk_id, content), ...]

    조건이 네 개 붙는다. 하나씩 이유가 있다.

    ① `c.bot_id = %s`
       **이게 봇 간 데이터 격리의 전부다.** `/internal/*` 에는 인증이 없다 —
       여기는 "마지막 방어선"이 아니라 <방어선이 없는 곳>이고, Spring 이 앞에서
       소유권을 확인한다는 전제 위에 있다. 그래도 SQL 에 못박는다.
       조건을 빼면 남의 봇 문서로 문제를 내게 된다.

    ② `d.status = 'ready'`
       chunks 테이블에는 상태가 없어서 documents 를 조인해야 안다.
       빼면 처리에 실패한 문서의 잔여 청크나 처리 중인 문서의 절반짜리 청크가
       테스트셋에 섞인다. 그러면 점수가 낮게 나와도 원인이 검색인지 문서인지 모른다.

    ③ 길이 하한
       청커가 500자 단위로 자르지만 문서 끝이나 목차는 짧게 남는다.
       "1. 총칙" 같은 청크로는 문제를 낼 수 없고, LLM 호출 비용만 나간다.

    ④ 이미 질문이 있는 청크 제외 (`NOT EXISTS`)
       같은 봇에 두 번 호출하면 <기존 질문은 두고 새 것만 더한다>.
       관리자가 고쳐둔 질문을 지우지 않기 위해서다(PRD F-05 는 수정·비활성을 요구한다).
       DB 에 UNIQUE 제약이 없어 중복을 막아주지 않으므로, 이 한 줄이
       "누적"과 "중복 방지"를 동시에 해결한다.

    임베딩(`c.embedding IS NOT NULL`)은 <일부러 안 건다>. 질문을 만드는 데
    벡터가 필요 없기 때문이다. retriever.search 는 벡터로 검색하므로 그 조건이 있다.
    """
    s = get_settings()
    with cursor() as cur:
        cur.execute(
            """SELECT c.id, c.content
                 FROM chunks c
                 JOIN documents d ON d.id = c.document_id
                WHERE c.bot_id = %s
                  AND d.status = 'ready'
                  AND length(c.content) >= %s
                  AND NOT EXISTS (
                        SELECT 1 FROM eval_questions q
                         WHERE q.source_chunk_id = c.id
                      )
                ORDER BY random()
                LIMIT %s""",
            (bot_id, s.eval_min_chunk_chars, count),
        )
        return cur.fetchall()


def count_ready_chunks(bot_id: UUID) -> int:
    """이 봇에 <쓸 수 있는> 청크가 몇 개나 있는지.

    표본이 0건일 때 이유를 갈라 말하려고 부른다.
      0 이면  → "아직 올린 문서가 없거나 처리가 안 끝났다"
      0 아니면 → "있는 청크로는 이미 다 만들었다"
    안내 문구가 달라야 관리자가 무엇을 해야 할지 알 수 있다.
    표본이 나왔을 때는 부르지 않는다(쓸데없는 쿼리 한 번을 아낀다).
    """
    with cursor() as cur:
        cur.execute(
            """SELECT count(*)
                 FROM chunks c
                 JOIN documents d ON d.id = c.document_id
                WHERE c.bot_id = %s AND d.status = 'ready'""",
            (bot_id,),
        )
        return cur.fetchone()[0]


# ─────────────────────────────────────────────────────────────────────────────
# 3. 저장
# ─────────────────────────────────────────────────────────────────────────────

def save_questions(
    bot_id: UUID, pairs: list[tuple[UUID, QuestionPair]]
) -> list[tuple[UUID, str, str, UUID, bool, object]]:
    """만들어진 질문들을 한 트랜잭션에 저장하고, 저장된 행을 그대로 돌려준다.

    왜 executemany 가 아니라 for 문인가:
      돌려줄 값(생성된 id, created_at)이 필요한데 executemany 로 RETURNING 을 받으려면
      psycopg 3.2 의 `returning=True` + `nextset()` 이라는 덜 익숙한 API 를 써야 한다.
      개수가 최대 수십 건이라 한 건씩 execute 해도 느리지 않고, 코드가 읽힌다.
      <중요한 건 반복이 아니라 `with cursor(commit=True)` 블록 하나 안에 있다는 점>이다 —
      중간에 실패하면 전부 롤백되므로 "앞부분만 저장" 이 남지 않는다.
    """
    saved = []
    with cursor(commit=True) as cur:
        for chunk_id, pair in pairs:
            cur.execute(
                """INSERT INTO eval_questions (bot_id, question, ground_truth, source_chunk_id)
                   VALUES (%s, %s, %s, %s)
                   RETURNING id, question, ground_truth, source_chunk_id, is_active, created_at""",
                (bot_id, pair.question, pair.ground_truth, chunk_id),
            )
            saved.append(cur.fetchone())
    return saved
