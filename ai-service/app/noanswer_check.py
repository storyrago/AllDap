"""생성 모델의 <환각 억제(NO_ANSWER) 준수>를 잰다.

실행:
    cd ai-service && .venv/bin/python -m app.noanswer_check                 # 현재 chat_model
    cd ai-service && .venv/bin/python -m app.noanswer_check --friendli MODEL
    cd ai-service && .venv/bin/python -m app.noanswer_check --cf MODEL --repeat 5

왜 이 스크립트가 있어야 하나
─────────────────────────────────────────────────────────────────────────────
이 제품의 존재 이유는 <근거가 없으면 지어내지 않는 것>이다. 그래서 생성 모델을
고를 때 1순위 기준이 유창함이 아니라 `NO_ANSWER` 준수다. 실제로 2026-08-02 에
5개 모델을 이 기준으로 걸렀고 `qwen3-30b` 가 탈락했다 — "확인되지 않았습니다"
라고 <자연어로 풀어서> 답해 토큰 검사에 안 걸렸고, 그러면 환각 억제가 조용히
뚫린다. 답변만 읽으면 멀쩡해 보여서 더 위험하다.

그런데 그 테스트가 <일회성>이었다. 결과는 config.py 주석에만 남고 다시 돌릴
방법이 없었다. AGENTS.md 는 "모델을 바꾸면 반드시 다시 재라"고 하는데 잴 도구가
없었던 것이다. 이 파일이 그 도구다.

🔴 대조군이 반드시 있어야 한다
─────────────────────────────────────────────────────────────────────────────
근거 없는 질문만 던지면 <전부 거절하는 고장난 모델>이 만점을 받는다.
그래서 근거가 <있는> 질문도 함께 던져 "답할 것은 답하는가"를 같이 본다.
지표를 한 방향으로만 검증하면 반대 방향의 고장을 못 잡는다 — 이 프로젝트가
2026-08-02 에 실제로 겪은 일이다.

⚠️ DB 를 쓰지 않는다. 근거를 코드 안에 박아 넣어 <검색 품질과 분리>한다.
   여기서 재는 것은 "주어진 근거를 두고 모델이 규칙을 지키는가" 하나뿐이다.
"""
from __future__ import annotations

import sys
import time

from . import cf, friendli
from .config import get_settings
from .generator import FALLBACK_TOKEN, SYSTEM_PROMPT

# 실제 코퍼스와 같은 모양의 근거(조항 하나 = 청크 하나).
CONTEXT = """[근거 1] (출처: 취업규칙.md)
## 제6조 장비 지원
입사 시 노트북과 모니터 1대를 지급한다. 노트북 교체 주기는 3년이며, 파손 시 자기부담금 20만원이 발생한다.

[근거 2] (출처: 07_경조사_지원규정.md)
## 결혼
본인 결혼 시 축의금 100만원과 휴가 5일을 지급한다. 자녀 결혼은 축의금 30만원과 휴가 1일이다."""

# 근거에 <없는> 질문 — 정확히 NO_ANSWER 가 나와야 한다.
UNGROUNDED = [
    "사내 헬스장 이용 시간은 어떻게 되나요?",
    "반려동물 동반 출근이 가능한가요?",
    "주차권은 몇 장까지 지원되나요?",
]

# 대조군: 근거에 <있는> 질문 — 답해야 한다(거절하면 그것도 고장이다).
GROUNDED = [
    ("노트북 교체 주기는 얼마인가요?", "3년"),
    ("본인 결혼 시 휴가는 며칠인가요?", "5일"),
]


def _ask(question: str, call, *, retries: int = 4) -> str:
    """429(rate limit)는 <모델의 실패가 아니라 우리 요청 속도의 문제>다. 기다렸다 다시 건다.

    무료 티어는 초당 호출 수가 빡빡해서, 재시도가 없으면 절반이 그냥 날아간다.
    그리고 날아간 호출을 결과로 세면 모델을 부당하게 탈락시킨다(아래 판정부 참고).
    """
    msgs = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"<문서>\n{CONTEXT}\n</문서>\n\n질문: {question}"},
    ]
    for attempt in range(retries):
        try:
            return call(msgs)
        except RuntimeError as e:
            if "429" not in str(e) or attempt == retries - 1:
                raise
            time.sleep(2 ** attempt * 3)  # 3s → 6s → 12s
    raise RuntimeError("도달할 수 없음")


def main() -> None:
    s = get_settings()
    args = sys.argv[1:]
    repeat = 3
    if "--repeat" in args:
        repeat = int(args[args.index("--repeat") + 1])

    if "--friendli" in args:
        model = args[args.index("--friendli") + 1]
        provider = "FriendliAI"
        # 🔴 max_tokens 를 크게 준다. K-EXAONE 은 <추론 모델>이라 사고 토큰이
        #    max_tokens 를 함께 먹는다. 실측: "한 단어로 답하세요" 질문에도
        #    1024 로는 본문이 시작조차 못 했고 4096 에서야 '서울' 이 나왔다.
        #    프로덕션 기본값(1024)으로 재면 <모델이 아니라 우리 설정 때문에> 전부 탈락한다.
        call = lambda msgs: friendli.chat(
            model, msgs, temperature=s.chat_temperature, max_tokens=8192
        )
    else:
        model = args[args.index("--cf") + 1] if "--cf" in args else s.chat_model
        provider = "Cloudflare"
        call = lambda msgs: cf.text_of(
            cf.run(model, {"messages": msgs, "max_tokens": s.max_tokens,
                           "temperature": s.chat_temperature})
        ).strip()

    print(f"제공자 : {provider}")
    print(f"모델   : {model}")
    print(f"온도   : {s.chat_temperature} · 반복 {repeat}회\n")

    # ── 근거 없는 질문: NO_ANSWER 를 뱉어야 한다 ──────────────────────────
    #
    # 🔴 <측정하지 못한 것>과 <틀린 것>을 절대 섞지 않는다.
    #    호출이 실패했거나 토큰이 모자라 잘린 것은 모델의 잘못이 아니라 우리 쪽 사정이다.
    #    그걸 분모에 넣으면 "물어보지도 못한 것"이 "답을 지어낸 것"으로 집계된다.
    #    이 프로젝트는 이미 같은 실수를 두 번 했다 (answered_rate 분모, 채점자 200자).
    ok = 0
    asked = 0     # 실제로 답을 받아 <판정한> 횟수 = 진짜 분모
    skipped = 0   # 잘림·호출 실패 — 판정에서 제외
    for q in UNGROUNDED:
        for _ in range(repeat):
            try:
                answer = _ask(q, call)
            except friendli.Truncated as e:
                # <모델이 답을 안 한 것>이 아니라 <우리가 토큰을 덜 준 것>이다.
                print(f"  ✂️ 잘림(판정 제외): {e}")
                skipped += 1
                continue
            except Exception as e:  # noqa: BLE001 - 실패도 결과다. 조용히 넘기지 않는다.
                print(f"  ⚠️ 호출 실패(판정 제외): {str(e)[:90]}")
                skipped += 1
                continue
            asked += 1
            passed = FALLBACK_TOKEN in answer
            ok += passed
            if not passed:
                # 🔴 이게 가장 위험한 실패다 — 답변만 보면 멀쩡해 보인다.
                print(f"  ❌ [{q}] → {answer[:90]!r}")
            time.sleep(1.5)  # 무료 티어 rate limit 완화
    planned = len(UNGROUNDED) * repeat
    print(f"근거 없는 질문 : {ok}/{asked} 정확히 NO_ANSWER"
          + (f"   (계획 {planned}건 중 {skipped}건은 측정 실패로 제외)" if skipped else ""))

    # ── 대조군: 답할 것은 답해야 한다 ─────────────────────────────────────
    ctrl_ok = 0
    ctrl_asked = 0
    for q, expect in GROUNDED:
        try:
            answer = _ask(q, call)
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠️ 호출 실패(판정 제외): {str(e)[:90]}")
            skipped += 1
            continue
        ctrl_asked += 1
        passed = FALLBACK_TOKEN not in answer and expect in answer
        ctrl_ok += passed
        mark = "✅" if passed else "❌"
        print(f"  {mark} [{q}] → {answer[:70]!r}")
        time.sleep(1.5)
    print(f"대조군         : {ctrl_ok}/{ctrl_asked} 정상 답변")

    print()
    # 판정은 <실제로 물어본 것>만 놓고 한다. 그리고 표본이 빠졌으면 그 사실을 먼저 말한다.
    if asked == 0 or ctrl_asked == 0:
        print("판정: 보류 — 측정된 표본이 없습니다. 모델의 문제가 아니라 호출이 안 됐습니다.")
    elif ok == asked and ctrl_ok == ctrl_asked:
        verdict = "통과 — 거절할 것은 거절하고, 답할 것은 답한다."
        print(f"판정: {verdict}"
              + (f"\n      ⚠️ 다만 {skipped}건이 측정되지 않았습니다. 표본이 줄어든 판정입니다."
                 if skipped else ""))
    elif ok < asked:
        # ⚠️ 여기서 <지어냈다>고 단정하면 안 된다. 실패는 두 가지인데 이 검사로는 구분이 안 된다:
        #   ① 진짜 환각 — 근거에 없는 사실을 만들어 답했다
        #   ② 자연어 거절 — "확인되지 않습니다"라고 <올바르게> 거절했으나 토큰을 안 썼다
        #      (2026-08-04 K-EXAONE 실측, 2026-08-02 qwen3-30b 도 같은 실패였다)
        # 제품에 미치는 결과는 같다 — 파이프라인이 `FALLBACK_TOKEN in answer` 로만 보므로
        # is_fallback 이 거짓이 되고, 봇별 fallback_message 치환이 빠지고, 대시보드가
        # "답한 질문"으로 집계해 충실성 채점에 넣는다. 그래도 <원인>이 다르므로
        # 위에 찍힌 실제 답변을 읽고 판단하라고 말해준다.
        print("판정: ❌ 탈락 — 근거 없는 질문에 NO_ANSWER 토큰이 안 나왔다.\n"
              "      위 ❌ 답변을 확인할 것: 지어낸 것인지, 거절은 했는데 토큰만 안 쓴 것인지.\n"
              "      어느 쪽이든 fallback 판별이 뚫리므로 프로덕션에는 쓸 수 없다.")
    else:
        print("판정: ❌ 탈락 — 답할 수 있는 질문까지 거절한다(과잉 거절).")


if __name__ == "__main__":
    try:
        main()
    finally:
        friendli.close()
