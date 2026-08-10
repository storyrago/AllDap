"""문서끼리 어긋나는 곳을 찾는다.

왜 이게 필요한가
─────────────────────────────────────────────────────────────────────────────
RAG 는 <문서가 진리>라고 가정한다. 그런데 실제 사내 문서는 서로 모순된다 —
구버전 규정과 신버전이 같이 올라가 있고, 부서별로 다른 숫자를 적어둔다.

그러면 챗봇은 둘 중 하나를 골라 <자신 있게> 답한다. 근거를 표시해도 소용없다:
표시된 그 근거가 틀린 쪽일 수 있다. 환각 억제(NO_ANSWER·max_distance)는
"문서에 없는 것" 을 막지만 "문서에 <둘 다> 있는 것" 은 못 막는다.

어떻게 찾나 — 3단계이고, 돈이 드는 것은 마지막 하나뿐이다
─────────────────────────────────────────────────────────────────────────────
  ① 청크마다 <다른 문서>의 가장 가까운 청크 1개를 pgvector 로 찾는다   (LLM 미사용)
  ② 너무 먼 쌍은 버린다 — 주제가 다르면 애초에 모순일 수 없다           (LLM 미사용)
  ③ 남은 쌍만 judge 모델에게 "서로 다른 말을 하나?" 물어본다             ← 여기만 유료

🔴 왜 top-1 만 보나 (top-3 가 아니라)
   청크 80개에 top-3 이면 240쌍, 판정 1회가 약 39뉴런이니 4.7k — <하루 한도의 절반>이다.
   top-1 이면 80쌍, 중복 제거 후 ~50쌍이라 2k 로 떨어진다.
   그리고 가장 가까운 하나가 모순 후보로 제일 유력하다. 늘리는 것은 값이 확인된 뒤에 한다.

🔴 유사도가 높다 ≠ 모순이다
   같은 말을 반복하는 두 청크가 유사도 최고다. 그래서 임베딩은 <후보를 좁히는 용도>일 뿐,
   판정은 반드시 LLM 이 한다. 거리로 모순을 판정하려 들면 오탐이 쏟아진다.

🔴 거짓 양성이 재앙이다
   10건 중 8건이 헛짚으면 관리자는 이 화면을 두 번 다시 안 본다. 그래서 프롬프트가
   "확실하지 않으면 모순 아님" 으로 기울어 있다 — 이 제품의 fallback 철학과 같다.
   놓치는 것보다 <틀린 지적>이 비싸다.
"""
from __future__ import annotations

import logging
from uuid import UUID

from pydantic import BaseModel

from . import cf
from .config import get_settings
from .db import cursor
from .judge import _extract_json   # 모델이 코드펜스·잡소리를 섞는 버릇은 여기서도 같다

_log = logging.getLogger(__name__)


class Candidate(BaseModel):
    """판정 대상 한 쌍. a 가 항상 <작은 UUID> 다 (아래 SQL 의 LEAST/GREATEST)."""

    a_id: UUID
    b_id: UUID
    distance: float
    a_content: str
    a_filename: str
    b_content: str
    b_filename: str


class Verdict(BaseModel):
    conflict: bool
    topic: str = ""
    a_says: str = ""
    b_says: str = ""
    reason: str = ""


SYSTEM_PROMPT = """당신은 한 조직의 내부 문서 두 조각을 비교해,
<같은 사실에 대해 서로 다른 값을 말하는지>만 판정합니다.

[모순이다]
같은 대상·같은 항목에 대해 <양립할 수 없는> 값을 말할 때만 해당합니다.
  예: 한쪽 "노트북 교체 주기는 3년" / 다른 쪽 "노트북 교체 주기는 4년"

[모순이 아니다] — 대부분 여기에 해당합니다
- 같은 내용을 다르게 표현한 것
- <서로 다른 대상>에 대한 규정 (정규직 vs 인턴, 국내 vs 해외, 팀장 이상 vs 전 직원)
- <조건이 다른> 경우 (근속 1년 미만 vs 1년 이상)
- 한쪽에만 있는 내용 — 빠진 것은 모순이 아닙니다
- 그냥 주제가 비슷하기만 한 것

🔴 확실하지 않으면 반드시 "모순 아님"으로 답하세요.
   틀린 지적 하나가 관리자의 신뢰를 잃게 만듭니다. 놓치는 것보다 헛짚는 것이 나쁩니다.

반드시 아래 JSON 형식으로만 답하세요. 다른 말을 덧붙이지 마세요.
{"conflict": true 또는 false, "topic": "무엇에 대한 충돌인가", "a_says": "문서A 의 값", "b_says": "문서B 의 값", "reason": "한국어 한 문장"}
모순이 아니면 topic·a_says·b_says 는 빈 문자열로 두세요."""


# 후보 쌍을 뽑는 질의.
#
# 조건 하나하나에 이유가 있다:
#   bot_id                      → 봇 간 격리. 남의 봇 문서와 비교하면 안 된다
#   documents.status='ready'    → 파싱 실패한 문서의 깨진 청크를 후보로 삼지 않는다
#   c.document_id <> a.document_id
#                               → <같은 문서 안>은 제외한다. 인접 청크는 이어지는 내용이라
#                                 유사도가 높지만 모순이 아니다. 노이즈의 대부분이 여기서 나온다
#   embedding IS NOT NULL       → 차원 변경 중이거나 재임베딩 전인 청크를 건너뛴다
#   NOT EXISTS                  → 이미 기록된 쌍은 다시 판정하지 않는다.
#                                 특히 관리자가 'ignored' 로 치운 것이 재스캔마다 되살아나면
#                                 그 화면은 두 번 다시 안 보게 된다
_CANDIDATE_SQL = """
WITH nearest AS (
    SELECT a.id AS a_id, b.id AS b_id, (a.embedding <=> b.embedding) AS distance
      FROM chunks a
      JOIN documents da ON da.id = a.document_id AND da.status = 'ready'
      CROSS JOIN LATERAL (
          SELECT c.id, c.embedding
            FROM chunks c
            JOIN documents dc ON dc.id = c.document_id AND dc.status = 'ready'
           WHERE c.bot_id = a.bot_id
             AND c.document_id <> a.document_id
             AND c.embedding IS NOT NULL
           ORDER BY c.embedding <=> a.embedding
           LIMIT 1
      ) AS b
     WHERE a.bot_id = %(bot_id)s
       AND a.embedding IS NOT NULL
),
deduped AS (
    -- (a,b) 와 (b,a) 는 같은 쌍이다. UUID 크기로 정렬해 하나로 접는다.
    -- 이 정렬이 V4 의 유니크 인덱스가 기대하는 순서이기도 하다.
    SELECT LEAST(a_id, b_id) AS lo_id,
           GREATEST(a_id, b_id) AS hi_id,
           MIN(distance) AS distance
      FROM nearest
     WHERE distance <= %(max_distance)s
     GROUP BY 1, 2
)
SELECT d.lo_id, d.hi_id, d.distance,
       ca.content, da.filename,
       cb.content, db.filename
  FROM deduped d
  JOIN chunks ca    ON ca.id = d.lo_id
  JOIN documents da ON da.id = ca.document_id
  JOIN chunks cb    ON cb.id = d.hi_id
  JOIN documents db ON db.id = cb.document_id
 WHERE NOT EXISTS (
       SELECT 1 FROM doc_conflicts x
        WHERE x.bot_id = %(bot_id)s
          AND x.chunk_a_id = d.lo_id
          AND x.chunk_b_id = d.hi_id
 )
 -- 가까운 것부터. 상한에 걸려 잘릴 때 <가장 유력한 쌍>이 남아야 한다.
 ORDER BY d.distance
 LIMIT %(limit)s
"""


def find_candidates(bot_id: UUID) -> list[Candidate]:
    """판정할 쌍을 고른다. 여기까지는 LLM 을 부르지 않으므로 공짜다."""
    s = get_settings()
    with cursor() as cur:
        cur.execute(_CANDIDATE_SQL, {
            "bot_id": str(bot_id),
            "max_distance": s.conflict_max_distance,
            "limit": s.conflict_max_pairs,
        })
        rows = cur.fetchall()

    return [
        Candidate(
            a_id=r[0], b_id=r[1], distance=float(r[2]),
            a_content=r[3], a_filename=r[4],
            b_content=r[5], b_filename=r[6],
        )
        for r in rows
    ]


def judge_pair(c: Candidate) -> Verdict | None:
    """한 쌍을 판정한다. 실패하면 None.

    None 은 "모순 아님"이 아니라 <판정하지 못했다>이다.
    호출하는 쪽이 저장하지 않고 넘어가야 한다 — 모순 아님으로 처리하면
    호출 실패가 "문서가 깨끗하다"로 둔갑한다.
    (evalrun 이 채점 실패를 0점으로 세지 않는 것과 같은 이유다)
    """
    s = get_settings()
    user = (
        f"<문서A> (출처: {c.a_filename})\n{c.a_content}\n</문서A>\n\n"
        f"<문서B> (출처: {c.b_filename})\n{c.b_content}\n</문서B>"
    )

    try:
        result = cf.run(s.judge_model, {
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            "max_tokens": 1024,
            # 판정자는 무조건 0 이다. 같은 문서 쌍에 매번 다른 답을 주면
            # 스캔을 돌릴 때마다 목록이 바뀌어 관리자가 믿을 수 없다.
            "temperature": s.judge_temperature,
        })
    except Exception as e:  # noqa: BLE001 - 한 쌍 실패가 스캔 전체를 죽이면 안 된다
        _log.warning("모순 판정 호출 실패: %s: %s", type(e).__name__, e)
        return None

    raw = cf.text_of(result)
    d = _extract_json(raw)
    if d is None:
        _log.warning("모순 판정 응답을 JSON 으로 읽지 못했습니다. 원문=%r",
                     raw[:300] or "(비어 있음)")
        return None

    # ⚠️ 모델이 문자열 "false" 를 줄 수 있다. 파이썬에서 bool("false") 는 True 다.
    #    그대로 믿으면 <모순 아님이 모순으로 뒤집힌다.>
    conflict = d.get("conflict")
    if isinstance(conflict, str):
        conflict = conflict.strip().lower() == "true"

    return Verdict(
        conflict=bool(conflict),
        topic=str(d.get("topic") or "").strip(),
        a_says=str(d.get("a_says") or "").strip(),
        b_says=str(d.get("b_says") or "").strip(),
        reason=str(d.get("reason") or "").strip(),
    )


class ScanResult(BaseModel):
    """스캔 한 번의 결과.

    세 숫자를 <따로> 센다. 합쳐 놓으면 "깨끗해서 0건" 과 "못 재서 0건" 이 구분되지 않는데,
    이 프로젝트가 그 부류의 버그를 이미 네 번 냈다.
    """

    candidates: int   # 판정 대상으로 고른 쌍 (= LLM 을 부른 횟수의 상한)
    judged: int       # 실제로 판정이 돌아온 쌍
    conflicts: int    # 그중 모순으로 기록된 쌍
    failed: int       # 판정하지 못한 쌍 (호출 실패·파싱 실패)


def scan(bot_id: UUID) -> ScanResult:
    """봇 하나의 문서 모순을 훑어 `doc_conflicts` 에 기록한다."""
    candidates = find_candidates(bot_id)
    if not candidates:
        return ScanResult(candidates=0, judged=0, conflicts=0, failed=0)

    rows: list[tuple] = []
    judged = failed = conflicts_found = 0
    for c in candidates:
        # ⚠️ LLM 호출을 cursor() 블록 <밖>에서 한다.
        #    커넥션 풀이 10개뿐이라 안에 두면 스캔 도는 동안 채팅·업로드까지 멈춘다.
        #    (evaluator 가 같은 이유로 같은 모양이다)
        v = judge_pair(c)
        if v is None:
            failed += 1
            continue
        judged += 1
        # 🔴 모순이 아닌 것도 'clear' 로 남긴다. 안 남기면 스캔할 때마다 <같은 답을 받으려고>
        #    LLM 을 다시 부른다. 실측: 청크 80개 봇의 후보 49쌍 중 모순 0건이었다 —
        #    그걸 매 스캔마다 49번씩 다시 묻게 된다. temperature=0 이라 답도 안 바뀐다.
        #    문서가 바뀌면 청크가 새로 생기고 이 행은 CASCADE 로 사라져 자동 재판정된다.
        if v.conflict:
            conflicts_found += 1
            rows.append((str(bot_id), str(c.a_id), str(c.b_id), "open",
                         v.topic or "(주제 미상)", v.a_says, v.b_says, c.distance))
        else:
            rows.append((str(bot_id), str(c.a_id), str(c.b_id), "clear",
                         "", "", "", c.distance))

    if rows:
        with cursor(commit=True) as cur:
            cur.executemany(
                """INSERT INTO doc_conflicts
                       (bot_id, chunk_a_id, chunk_b_id, status, topic, a_says, b_says, distance)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   -- 유니크 인덱스와 짝을 이룬다. 스캔이 동시에 두 번 돌아도 터지지 않고,
                   -- 관리자가 ignored 로 치워둔 것을 open 으로 되살리지도 않는다.
                   ON CONFLICT (bot_id, chunk_a_id, chunk_b_id) DO NOTHING""",
                rows,
            )

    _log.info("모순 스캔 완료 bot_id=%s 후보=%d 판정=%d 모순=%d 실패=%d",
              bot_id, len(candidates), judged, conflicts_found, failed)
    return ScanResult(candidates=len(candidates), judged=judged,
                      conflicts=conflicts_found, failed=failed)
