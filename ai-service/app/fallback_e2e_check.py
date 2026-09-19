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

import os
import sys
from pathlib import Path

from .db import close_pool, cursor
from .generator import build_system_prompt, fetch_bot_prompt, generate
from .retriever import search
from .schemas import Id

# 평가에 쓰는 봇을 <고른다>. 박아두지 않는다 — 아래 함수의 주석 참고.
#
# 🔴 V9(2026-09-13, 기본키 BIGINT 전환)가 기존 데이터를 전부 비웠다. 전에는
#    UUID("628d2785-a128-486c-a1ac-556f19f06de3") 로 못박아 둘 수 있었지만,
#    이제 봇은 <만들어진 순서대로> 번호를 받으므로 환경마다 값이 다르다.
#    그래서 기본값을 두되 환경변수로 덮어쓸 수 있게 한다. 번호가 안 맞으면
#    코퍼스가 없는 봇을 보게 되어 <전부 fallback> 이 나고, 그것은 10/10 으로
#    통과한다 — 대조군 3건이 있는 이유가 정확히 이것이다(아래 참고).
def resolve_bot_id() -> Id:
    """측정 대상 봇을 정한다. <정하지 못하면 통과가 아니라 실패로 끝낸다.>

    🔴 왜 기본값 상수를 없앴는가 (2026-09-18)
       전에는 `int(os.environ.get("EVAL_BOT_ID", "2"))` 였다. 봇 2 는 이 환경에
       없는 봇이라, 그냥 돌리면 <청크가 0건인 봇>을 보게 된다. 그런데 그때 나오던
       출력이 "임계 0.30 · 정답유지 0/0 · 근거없음차단 0/0 · OK" 였다 —
       **"재봤더니 0/0" 과 "아무것도 재지 못했다" 가 같은 화면이었다.**
       이 저장소가 여덟 번 낸 뭉개기 부류이고, 여덟 번째(`parse_prom_counter` 가
       "읽지 못했다" 와 "읽어서 이 값이었다" 를 뭉갠 것)와 축이 같다.

       기본값을 2 에서 1 로 바꾸는 것으로는 닫히지 않는다. V9(BIGINT 전환) 이후
       봇 번호는 <만들어진 순서>라 환경마다 다르고, 다음에 번호가 또 밀리면 같은
       자리에서 똑같이 뚫린다. 그래서 <박아둔 값>을 지우고 DB 에 실제로 무엇이
       있는지 보고 정한다. 정할 수 없으면 멈춘다.

    규칙
      EVAL_BOT_ID 가 있으면   그 봇이 실재하고 청크가 있는지 확인한다. 아니면 종료코드 1.
      없으면                  청크가 있는 봇이 <정확히 하나>일 때만 그것을 쓴다.
                              0개나 2개 이상이면 사람이 고르라고 하고 종료코드 1.
    """
    env = os.environ.get("EVAL_BOT_ID")
    with cursor() as cur:
        cur.execute(
            """SELECT b.id, b.name, count(c.id)
                 FROM bots b LEFT JOIN chunks c ON c.bot_id = b.id
                GROUP BY b.id, b.name
                ORDER BY b.id"""
        )
        rows = cur.fetchall()

    def _bail(reason: str) -> None:
        print(f"🔴 {reason}")
        if rows:
            print("   이 DB 에 있는 봇:")
            for bot_id, name, n in rows:
                mark = "" if n else "   ← 청크가 없어 측정할 수 없습니다"
                print(f"     id={bot_id}  {name or '(이름 없음)'}  청크 {n}건{mark}")
        else:
            print("   이 DB 에는 봇이 하나도 없습니다.")
            print("   → docker compose up -d 로 DB 를 띄우고 api 를 기동해 스키마를 만든 뒤,")
            print("     코퍼스를 올리세요: AGENTS.md 의 '로컬 실행 순서' 참고")
        # 안내에 <지금 돌린 그 명령>을 되비춘다. 여기에 모듈 이름을 박아두면
        # answerable_check 로 돌린 사람에게 엉뚱한 명령을 알려주게 된다.
        module = Path(sys.argv[0]).stem or "fallback_e2e_check"
        print("   → 잴 봇을 직접 지정하려면:")
        print(f"     cd ai-service && EVAL_BOT_ID=<번호> .venv/bin/python -m app.{module}")
        sys.exit(1)

    if env is not None:
        try:
            wanted = int(env)
        except ValueError:
            _bail(f"EVAL_BOT_ID 가 숫자가 아닙니다: {env!r}")
        found = [r for r in rows if r[0] == wanted]
        if not found:
            _bail(f"EVAL_BOT_ID={wanted} 인 봇이 이 DB 에 없습니다.")
        if not found[0][2]:
            _bail(f"봇 {wanted} 에는 청크가 0건이라 잴 것이 없습니다.")
        # 자동 선택과 <같은 줄>을 찍는다. 한쪽만 조용하면 화면에 빈 절이 남아
        # "무엇을 재고 있는지" 가 출력에서 사라진다.
        print(f"측정 대상: 봇 {wanted} ({found[0][1] or '이름 없음'}) · 청크 {found[0][2]}건"
              f"  [EVAL_BOT_ID 로 지정됨]")
        return Id(wanted)

    usable = [r for r in rows if r[2]]
    if len(usable) != 1:
        _bail(
            "청크가 있는 봇이 하나가 아니라 어느 봇을 재야 할지 정할 수 없습니다"
            f" (후보 {len(usable)}개)."
        )
    bot_id, name, n = usable[0]
    print(f"측정 대상: 봇 {bot_id} ({name or '이름 없음'}) · 청크 {n}건"
          f"  [EVAL_BOT_ID 로 바꿀 수 있습니다]")
    return Id(bot_id)

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
    # 🔴 2026-09-18 교체: 원래 "명절에 선물을 주나요?" (감시 낱말 "명절") 였는데,
    #    같은 날 코퍼스에 더한 `58_촉탁직_재고용규정` 이 "명절 격려금" 을 규정하면서
    #    가드에 걸렸다. 가드가 제 일을 한 것이므로 <문서가 아니라 질문>을 바꾼다
    #    (문서를 고치면 재업로드가 필요하고 측정 중인 코퍼스가 흔들린다).
    #    "샤워"·"탈의"·"세면"·"목욕" 은 56문서에서 전부 0건임을 확인하고 골랐다.
    ("사옥에 샤워실이 있나요?", ("샤워", "탈의실")),
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


def guard(questions: list[tuple[str, tuple[str, ...]]] | None = None,
          *, bot_id: Id) -> bool:
    """감시 낱말이 코퍼스에 나타났는지 본다. 하나라도 나오면 측정을 막는다.

    questions 를 받는 이유: 같은 가드를 <홀드아웃 질문 목록>에도 써야 하는데
    (`answerable_check`), 로직을 복사하면 한쪽만 고쳐지는 사고가 구조적으로 가능해진다.
    기본값이 UNGROUNDED 라 기존 호출부는 그대로 둔다.

    ⚠️ `bot_id` 는 키워드 전용이고 기본값이 없다. 전에는 모듈 상수를 직접 읽었는데,
       그 상수에 기본값이 있어서 <아무 봇도 정해지지 않은 채로> 가드가 돌 수 있었다.
       가드가 "0건이라 깨끗하다" 고 말하는 것과 "그 봇에 청크가 아예 없다" 는
       다른 사실이다.
    """
    questions = UNGROUNDED if questions is None else questions
    ok = True
    with cursor() as cur:
        for question, sentinels in questions:
            for word in sentinels:
                cur.execute(
                    """SELECT count(*), min(d.filename)
                         FROM chunks c JOIN documents d ON d.id = c.document_id
                        WHERE c.bot_id = %s AND c.content LIKE %s""",
                    (bot_id, f"%{word}%"),
                )
                n, filename = cur.fetchone()
                if n:
                    ok = False
                    print(f"⚠️  '{word}' 가 코퍼스에 {n}건 있습니다 ({filename})")
                    print(f"    → \"{question}\" 은 이제 답이 있을 수 있습니다. 질문을 바꾸세요.")
    return ok


def main() -> None:
    guard_only = "--guard-only" in sys.argv

    print("── 측정 대상 확인 ──")
    bot_id = resolve_bot_id()
    print()

    print("── 질문 점검 (감시 낱말이 코퍼스에 없는가) ──")
    if not guard(bot_id=bot_id):
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
    bot_prompt = fetch_bot_prompt(bot_id)
    system_prompt = build_system_prompt(bot_prompt)
    print(f"봇 지침: {'있음 (프로덕션과 동일하게 결합해 태운다)' if bot_prompt else '없음 (기본 규칙만)'}\n")

    print("── 근거 없는 질문 (fallback 이 나와야 한다) ──")
    fallbacks = 0
    cut_by_search = 0
    for question, _ in UNGROUNDED:
        sources = search(bot_id, question)
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
        sources = search(bot_id, question)
        answer, is_fallback = generate(question, sources, system_prompt=system_prompt)
        hit = (not is_fallback) and (expect in answer)
        answered += hit
        print(f"  {'✅' if hit else '❌'} {question[:30]:32s} → {answer[:44]}")

    # 실패해도 종료 코드에 넣지 않는다 — 봇의 고장이 아니라 검색 설정의 알려진 한계다.
    print("\n── 알려진 검색 한계 (기본 설정이 못 찾는다 · 실패로 세지 않음) ──")
    recovered = 0
    for question, expect in KNOWN_RETRIEVAL_GAP:
        sources = search(bot_id, question)
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
