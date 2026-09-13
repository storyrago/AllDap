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

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from .config import get_settings
from .db import cursor
from .schemas import Id

# ⚠️ 이 파일이 <이 프로젝트에서 유일하게 남은 Gemini 사용처>다.
#    임베딩은 Cloudflare(retriever), 채점도 Cloudflare(judge), 답변 생성도 Cloudflare(generator)로
#    옮겼고 질문 생성만 Gemini 에 남았다. 남긴 이유는 품질이 아니라 <분리>다 —
#    질문·답변·채점을 전부 같은 제공자로 두면 셋이 같은 편향을 공유한다.
#    (예전에는 generator 의 _gemini() 를 빌려 썼는데, generator 가 Cloudflare 로 가면서 여기로 옮겼다)
_client: genai.Client | None = None


def _gemini() -> genai.Client:
    global _client
    if _client is None:
        s = get_settings()
        if not s.google_api_key:
            raise RuntimeError("GOOGLE_API_KEY가 설정되지 않았습니다 (.env 확인)")
        _client = genai.Client(api_key=s.google_api_key)
    return _client

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

★ 가장 중요한 규칙 — 질문에 <내용의 단어를 그대로 쓰지 마세요>
  이 챗봇은 뜻이 비슷한 문서를 찾아오는 방식이라, 질문이 문서 표현을 그대로 베끼면
  <너무 쉬워서 시험이 되지 않습니다.> 실제 직원은 문서를 안 읽고 자기 말로 묻습니다.

  나쁜 예: "연차 휴가는 1년에 며칠이 부여되나요?"        (문서 표현 그대로)
  좋은 예: "1년에 쉴 수 있는 날이 며칠인가요?"            (같은 뜻, 다른 말)

  나쁜 예: "종합건강검진은 몇 년에 한 번 지원되나요?"
  좋은 예: "건강검진은 얼마나 자주 받을 수 있나요?"

  나쁜 예: "사내 시스템 비밀번호는 며칠마다 변경해야 하나요?"
  좋은 예: "패스워드를 얼마나 자주 바꿔야 하나요?"

  <문서의 제목·소제목에 있는 단어는 특히 피하세요.> 그게 가장 강한 힌트입니다.
  다만 고유한 코드·양식 번호(HR-310, A-3형 등)는 <바꿀 말이 없으므로 그대로 써도> 됩니다.

그 밖의 규칙:
1. 정답은 <내용> 안에 실제로 적혀 있는 것이어야 합니다. 추론하거나 보태지 마세요.
2. "위 문서에 따르면", "이 문단에서" 같은 표현을 쓰지 마세요.
3. 질문은 한 가지만 물어보세요. "A와 B는 각각 무엇인가요?"처럼 여러 개를 묶지 마세요.
4. 정답은 간결하게, 한국어 존댓말로 쓰세요.
5. 대상이 여럿인 규정(정규직/계약직/인턴/파견 등)이라면 <누구에 대한 질문인지 반드시 밝히세요.>
   "연차가 며칠인가요?"는 대상이 없어 정답이 여러 개가 됩니다.
6. 답이 될 만한 사실이 <내용>에 없으면, 목차나 제목뿐이라도 억지로 만들지 말고
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
            # ⚠️ chat_model 이 아니라 <질문 생성 전용 모델>이다.
            #    무료 한도가 모델별로 잡혀서, 답변 생성과 나눠야 서로의 한도를 안 깎는다.
            #    (config.py 의 eval_question_model 주석 참고)
            model=s.eval_question_model,
            contents=f"<내용>\n{content}\n</내용>",
            config=types.GenerateContentConfig(
                system_instruction=GENERATION_PROMPT,
                max_output_tokens=s.max_tokens,
                # 이 두 줄이 구조화 출력이다. mime_type 만으로는 "JSON 이면 아무 모양이나"가 되고,
                # response_schema 까지 줘야 필드 이름·타입이 고정된다.
                response_mime_type="application/json",
                response_schema=QuestionPair,
                # ⚠️ 사고(thinking) 설정을 <여기서 주지 않는다>. 모델이 알아서 꺼져 있다.
                #
                # 배경: gemini-3.5-flash 는 답을 내기 전에 "생각"을 하는데, 그 사고 토큰이
                # max_output_tokens 를 <함께> 소모한다. JSON 자체는 50토큰도 안 되는데
                # 사고에 1024를 다 써버리고 본문이 중간에 잘렸다(finish_reason=MAX_TOKENS).
                # 잘린 JSON 은 파싱이 안 되므로 그 청크가 조용히 버려졌다.
                #   실측(2026-08-02, 같은 청크 5회씩, gemini-3.5-flash):
                #     사고 켬 → 잘림 3회, 평균 3768ms  /  thinking_budget=0 → 잘림 0회, 평균 1164ms
                #
                # 그래서 한동안 `thinking_config=ThinkingConfig(thinking_budget=0)` 을 넣어뒀는데,
                # <그 파라미터를 지웠다.> 이유 두 가지 (둘 다 2026-08-02 실측):
                #   ① gemini-3.5-flash-lite 는 그 인자를 아예 거부한다 — HTTP 400 invalid argument.
                #      즉 남겨두면 모델을 바꾸는 순간 질문 생성이 통째로 죽는다.
                #   ② 그리고 애초에 필요가 없다. flash-lite 는 같은 요청에서
                #      thoughtsTokenCount=0 으로 응답한다(사고를 안 한다). 껄 것이 없다.
                #
                # ⚠️ 모델을 <사고하는 모델>로 되돌리면 잘림이 재발한다. 그때는 이 줄을 되살리지 말고
                #    현행 파라미터인 thinking_level 을 쓸 것 — thinking_budget 은 구버전 이름이라
                #    모델에 따라 400 이 난다.
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

def sample_chunks(bot_id: Id, count: int) -> list[tuple[Id, str]]:
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


def count_ready_chunks(bot_id: Id) -> int:
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
    bot_id: Id, pairs: list[tuple[Id, QuestionPair]]
) -> list[tuple[Id, str, str, Id, bool, object]]:
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
