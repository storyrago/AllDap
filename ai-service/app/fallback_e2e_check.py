"""W1 완료 조건 3번 — <검색까지 포함한> 환각 억제를 잰다.

실행:
    cd ai-service && .venv/bin/python -m app.fallback_e2e_check
    cd ai-service && .venv/bin/python -m app.fallback_e2e_check --guard-only   # LLM 호출 없이 질문만 점검

`noanswer_check` 와 무엇이 다른가 (헷갈리기 쉬우니 반드시 구분할 것)
─────────────────────────────────────────────────────────────────────────────
  noanswer_check      근거를 <코드에 박아넣고> 모델만 본다.
                      "주어진 근거를 두고 모델이 NO_ANSWER 규칙을 지키는가."
                      코퍼스가 바뀌어도 결과가 변하지 않는다 = 모델 교체 시 쓰는 도구.

  fallback_e2e_check  실제 봇의 <DB·검색을 통과>시켜 파이프라인 전체를 본다. (이 파일)
                      "근거가 없는 질문에 이 봇이 fallback 하는가."
                      1차 방어선(max_distance)과 2차 방어선(NO_ANSWER)이 함께 걸린다.
                      코퍼스가 바뀌면 결과가 바뀐다 = 코퍼스를 바꿀 때마다 쓰는 도구.

🔴 이 파일이 생긴 이유 — 질문 목록이 <어디에도 없었다>
─────────────────────────────────────────────────────────────────────────────
W1 완료 조건 3번("문서에 없는 질문 10개 중 8개 이상 fallback")은 2026-07-31 에
통과했다고 기록돼 있는데, **그 질문 10개가 저장소 어디에도 없다.** 수동 curl 로만
돌렸기 때문이다. 그래서 2026-08-11 에 코퍼스를 14 → 50문서로 키운 뒤에도
"다시 재라"는 지시만 남고 <잴 대상이 없었다.>

측정은 재현할 수 없으면 측정이 아니다. 목록을 여기 박제한다.

🔴 그리고 <가드>가 핵심이다 — 실제로 당한 적이 있다
─────────────────────────────────────────────────────────────────────────────
AGENTS.md 의 경고: "코퍼스를 바꾸면 질문 목록도 반드시 함께 점검할 것 —
실제로 코퍼스를 늘리다 기존 질문 3개의 답이 문서에 생겨 7/10 이라는 <거짓 미달>이 났다."

사람이 기억해서 점검하는 규칙은 반드시 잊힌다. 그래서 각 질문에 <감시 낱말>을 달고,
그 낱말이 코퍼스에 하나라도 나타나면 **측정을 시작하지 않고 멈춘다.**
"점수가 낮다"보다 "이 질문은 이제 답이 있을 수 있다"가 먼저 보여야 한다.

⚠️ 감시 낱말은 부분 문자열로 찾는다. 반대 방향(0건 → 확실히 없다)만 신뢰할 수 있고,
   1건 이상이면 <사람이 확인하라>는 뜻이다(오탐 가능 — 예: "생일" 이 "발생일" 에 걸린다).
"""
from __future__ import annotations

import sys
from uuid import UUID

from .db import close_pool, cursor
from .generator import build_system_prompt, fetch_bot_prompt, generate
from .retriever import search

# 평가에 쓰는 봇. 코퍼스 50문서 · 306청크.
BOT_ID = UUID("628d2785-a128-486c-a1ac-556f19f06de3")

# ── 근거가 <없어야> 하는 질문 10개 ──────────────────────────────────────
#
# 각 항목: (질문, 감시 낱말들)
# 감시 낱말은 2026-08-12 기준 코퍼스에서 전부 0건임을 SQL 로 확인하고 골랐다.
# 코퍼스에 그 낱말이 생기면 이 질문은 더 이상 "근거 없는 질문"이 아니다.
UNGROUNDED: list[tuple[str, tuple[str, ...]]] = [
    ("사내 헬스장 이용 시간은 어떻게 되나요?", ("헬스장", "체육관")),
    ("반려동물을 데리고 출근해도 되나요?", ("반려동물",)),
    ("사옥 안에 흡연 구역이 따로 있나요?", ("흡연", "금연")),
    ("스톡옵션은 언제부터 행사할 수 있나요?", ("스톡옵션", "주식매수", "우리사주")),
    ("연말정산 서류는 언제까지 제출해야 하나요?", ("연말정산",)),
    ("안식휴가 제도가 있나요?", ("안식",)),
    ("사내 어린이집에 아이를 맡길 수 있나요?", ("어린이집", "보육시설")),
    ("명절에 선물을 주나요?", ("명절",)),
    ("독감 예방접종 비용을 지원하나요?", ("예방접종", "백신")),
    ("워케이션으로 제주도에서 일해도 되나요?", ("워케이션",)),
]

# ── 대조군: 근거가 <있는> 질문 ──────────────────────────────────────────
#
# 🔴 없으면 <전부 거절하는 고장난 봇>이 10/10 만점을 받는다.
#    지표를 한 방향으로만 검증하면 반대 방향의 고장을 못 잡는다.
#
# 기본 설정(벡터만)에서 <반드시> 답해야 하는 것들. 여기가 깨지면 진짜 고장이다.
GROUNDED: list[tuple[str, str]] = [
    ("인턴 사원의 식대는 월 얼마인가요?", "15만"),
    ("계약직 사원의 출근 시간은 언제인가요?", "9시"),
    ("취업규칙에서 징계의 종류는 몇 가지인가요?", "네 가지"),
]

# ── 🔴 근거는 있지만 <현재 기본 설정이 못 찾는> 질문 ─────────────────────
#
# 이걸 위 GROUNDED 에 섞으면 <봇이 고장난 것>과 <검색 설정의 알려진 한계>가
# 같은 실패로 뭉개진다. 이 저장소가 반복해 낸 바로 그 부류다.
#
# "정규직의 노트북 교체 주기"는 정답(취업규칙 제6조)이 벡터 검색에서 #7 이라
# top_k=5 에 못 든다. 리랭커+하이브리드를 켜면 1.000 으로 답한다(W4 실측).
# 그러니 여기서 fallback 이 나는 것은 <예상된 동작>이고, 실패로 세지 않는다.
#
# 다만 <조용히 넘기지도 않는다.> 표시해서 보여준다 —
# 이 목록이 비는 날이 검색 개선이 실제로 끝난 날이다.
KNOWN_RETRIEVAL_GAP: list[tuple[str, str]] = [
    ("정규직의 노트북 교체 주기는 얼마인가요?", "3년"),
]

PASS_THRESHOLD = 8  # W1 완료 조건 (10개 중 8개 이상)


def guard() -> bool:
    """감시 낱말이 코퍼스에 나타났는지 본다. 하나라도 나오면 측정을 막는다."""
    ok = True
    with cursor() as cur:
        for question, sentinels in UNGROUNDED:
            for word in sentinels:
                cur.execute(
                    """SELECT count(*), min(d.filename)
                         FROM chunks c JOIN documents d ON d.id = c.document_id
                        WHERE c.bot_id = %s AND c.content LIKE %s""",
                    (BOT_ID, f"%{word}%"),
                )
                n, filename = cur.fetchone()
                if n:
                    ok = False
                    print(f"⚠️  '{word}' 가 코퍼스에 {n}건 있습니다 ({filename})")
                    print(f"    → \"{question}\" 은 이제 답이 있을 수 있습니다. 질문을 바꾸세요.")
    return ok


def main() -> None:
    guard_only = "--guard-only" in sys.argv

    print("── 질문 점검 (감시 낱말이 코퍼스에 없는가) ──")
    if not guard():
        print("\n🔴 중단합니다. 이 상태로 재면 <거짓 미달>이 나옵니다.")
        print("   (실제로 2026-08-02 에 같은 일로 7/10 이 나왔습니다)")
        sys.exit(1)
    print(f"OK — 근거 없는 질문 {len(UNGROUNDED)}개 전부 코퍼스에 흔적 없음\n")

    if guard_only:
        return

    # 🔴 프로덕션이 실제로 쓰는 프롬프트를 그대로 태운다.
    #
    #    이 검사는 파일 첫머리에서 "1차·2차 방어선이 함께 걸린다" 고 주장하는데,
    #    봇 지침 없이 기본 SYSTEM_PROMPT 로만 돌면 그 주장이 거짓이 된다.
    #    main.chat 과 evalrun._execute 는 둘 다 build_system_prompt(fetch_bot_prompt(...)) 를 쓴다.
    #
    #    왜 중요한가: 2026-08-13 실측으로 <봇 지침 하나에 fallback 판정이 뚫린다>는 것이
    #    확인돼 있다(AGENTS.md · bot_prompt_check). 지침에 "모르는 것도 아는 척 답해" 계열
    #    문구가 들어가면 근거 없는 질문에 is_fallback=False 로 답한다.
    #    그런데 이 검사는 기본 프롬프트로 돌아 10/10 을 찍는다 —
    #    <W1 완료 조건이 통과했다고 보고하는데 제품은 뚫려 있는> 상태가 된다.
    #
    #    ⚠️ 루프 밖에서 한 번만 읽는다. 질문마다 읽으면 도중에 설정이 바뀔 때
    #       앞뒤 질문이 다른 프롬프트로 판정돼 측정이 섞인다(evalrun 과 같은 이유).
    bot_prompt = fetch_bot_prompt(BOT_ID)
    system_prompt = build_system_prompt(bot_prompt)
    print(f"봇 지침: {'있음 (프로덕션과 동일하게 결합해 태운다)' if bot_prompt else '없음 (기본 규칙만)'}\n")

    print("── 근거 없는 질문 (fallback 이 나와야 한다) ──")
    fallbacks = 0
    cut_by_search = 0
    for question, _ in UNGROUNDED:
        sources = search(BOT_ID, question)
        answer, is_fallback = generate(question, sources, system_prompt=system_prompt)
        fallbacks += is_fallback
        # 근거가 0건이면 1차 방어선(max_distance)이 잡은 것 = LLM 을 아예 안 불렀다.
        line = "✅" if is_fallback else "❌"
        where = "검색컷" if not sources else "생성"
        cut_by_search += not sources
        print(f"  {line} [{where}] {question[:30]:32s} 근거 {len(sources)}건")
        if not is_fallback:
            print(f"      🔴 답해버렸습니다: {answer[:70]}")

    print("\n── 대조군 (답해야 한다) ──")
    answered = 0
    for question, expect in GROUNDED:
        sources = search(BOT_ID, question)
        answer, is_fallback = generate(question, sources, system_prompt=system_prompt)
        hit = (not is_fallback) and (expect in answer)
        answered += hit
        print(f"  {'✅' if hit else '❌'} {question[:30]:32s} → {answer[:44]}")

    # 실패해도 종료 코드에 넣지 않는다 — 봇의 고장이 아니라 검색 설정의 알려진 한계다.
    print("\n── 알려진 검색 한계 (기본 설정이 못 찾는다 · 실패로 세지 않음) ──")
    recovered = 0
    for question, expect in KNOWN_RETRIEVAL_GAP:
        sources = search(BOT_ID, question)
        answer, is_fallback = generate(question, sources, system_prompt=system_prompt)
        hit = (not is_fallback) and (expect in answer)
        recovered += hit
        mark = "🎉 이제 답한다 — 목록에서 빼고 GROUNDED 로 옮길 것" if hit else "예상대로 못 찾음"
        print(f"  {'✅' if hit else '·'} {question[:30]:32s} {mark}")

    print(f"\nfallback {fallbacks}/{len(UNGROUNDED)} (기준 {PASS_THRESHOLD}) "
          f"· 그중 검색컷 {cut_by_search}건 · 대조군 {answered}/{len(GROUNDED)}"
          f" · 알려진 한계 {recovered}/{len(KNOWN_RETRIEVAL_GAP)} 회복")
    if fallbacks < PASS_THRESHOLD or answered < len(GROUNDED):
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    finally:
        # 스크립트로 돌 때는 커넥션 풀을 명시적으로 닫는다.
        # 안 닫으면 종료할 때 "couldn't stop thread" 경고가 쏟아져
        # <측정이 실패한 것처럼> 보인다. 서버(uvicorn)에서는 lifespan 이 닫는다.
        close_pool()
