"""loadtest/s4_context.py 의 판정 로직 자체 점검. 서버도 k6 도 DB 도 없이 돈다.

실행:
    cd ai-service && .venv/bin/python -m loadtest.s4_check

무엇을 재나
─────────────────────────────────────────────────────────────────────────────
S4 의 판정에는 <다른 두 판과 성격이 정반대인 판>이 하나 있다. F3(rerank 조용한 실패)은
지표가 <안 움직이는 것>이 통과 조건이라, 계측이 아예 죽은 경우와 겉모습이 같다.
그래서 여기서 가장 공들여 보는 것은 "F3 이 통과하는가" 가 아니라
**"계측이 죽었을 때 F3 이 통과해버리지 않는가"** 다.

그리고 회복 확인(read_circuit_state)에서 <시계열 없음>을 "닫혔다" 로 읽으면,
서킷이 열린 채로 다음 판이 시작돼 그 판의 숫자가 통째로 오염된다. 그것도 여기서 본다.

🔴 실패 케이스는 `not ok` 만 보지 않고 <사유까지> 단언한다.
   s3_check 의 음성 대조에서 실제로 드러난 약점이다: 가드를 통째로 없앴는데도
   다른 검사에 걸려 실패해서, "가드가 사라진 것" 을 못 잡았다.
   "실패했다" 와 "그 이유로 실패했다" 는 다른 사실이다.
"""
from __future__ import annotations

from loadtest.s4_context import (
    ALL_OUTCOMES,
    OUTCOME_CIRCUIT_OPEN,
    OUTCOME_CONNECT_FAILURE,
    OUTCOME_PYTHON_5XX,
    OUTCOME_SUCCESS,
    judge_fault_round,
    parse_prom_counter,
    read_circuit_state,
)

_failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'OK  ' if ok else 'FAIL'} {name} {detail}")
    if not ok:
        _failures.append(name)


def signals(outcomes: dict | None = None, retry=0.0, transitions: dict | None = None,
            injected: int | None = 0, fault_mode: str = "none") -> dict:
    """collect_signals 가 만드는 모양의 신호 묶음."""
    base = {name: 0.0 for name in ALL_OUTCOMES}
    base.update(outcomes or {})
    trans = {"open": 0.0, "closed": 0.0, "half_open": 0.0}
    trans.update(transitions or {})
    return {"outcomes": base, "retry": retry, "transitions": trans,
            "fault_injected": injected, "fault_mode": fault_mode}


def k6(normal: dict | None = None, inject: dict | None = None, fallback: int = 0) -> dict:
    n = {code: 0 for code in (200, 0, 422, 429, 500, 502, 503, 504)}
    i = dict(n)
    n.update(normal or {200: 500})
    i.update(inject or {})
    return {"normal": n, "inject": i, "fallback_total": fallback}


def judged(round_name, before, after, counts) -> tuple[bool, str]:
    """판정을 부르되 <예외로 죽는 것>도 하나의 결과로 돌려준다.

    🔴 예외를 그냥 올려보내면 이 파일이 그 자리에서 멈춰, 뒤의 케이스가 아예 안 돈다.
       그러면 점검이 "무엇이 깨졌는지" 를 이름으로 못 대고 traceback 만 남는다.
       음성 대조에서 실제로 겪었다: injected 의 None 가드를 없앴더니 TypeError 로 죽어
       종료코드는 1 인데 <어느 케이스가 문제인지는 출력에 안 나왔다.>
       판정 함수가 죽는 것은 <틀린 판정>이므로, 실패로 세되 이름을 붙여 계속 간다.
    """
    try:
        ok, reasons = judge_fault_round(round_name, before, after, counts)
    except Exception as exc:  # noqa: BLE001 - 죽는 것도 결과다
        return False, f"판정이 예외로 죽었다: {type(exc).__name__}: {exc}"
    return ok, " | ".join(reasons)


def fails_because(name: str, round_name, before, after, counts, needle: str) -> None:
    ok, why = judged(round_name, before, after, counts)
    check(name, (not ok) and needle in why, f"({why[:60]}…)")


def main() -> int:
    print("parse_prom_counter — 0 과 <계측 없음> 을 가르는가")
    # ⚠️ s3_context 에 같은 함수가 있다(복사한 이유는 s4_context 의 그 함수 주석 참고).
    #    복사본이라고 점검을 생략하면, 한쪽만 고쳐졌을 때 조용히 갈린다.
    prom = (
        'alldap_ai_call_seconds_count{operation="chat",outcome="success",} 700.0\n'
        'alldap_ai_call_seconds_count{operation="chat",outcome="circuit_open",} 12.0\n'
        "alldap_ai_retry_total 40.0\n"
    )
    check("태그 둘로 골라 읽는다",
          parse_prom_counter(prom, "alldap_ai_call_seconds_count",
                             {"operation": "chat", "outcome": "circuit_open"}) == 12.0)
    # 🔴 없는 태그 조합에 0.0 을 돌려주면 "안 일어났다" 와 "계측이 안 붙었다" 가 같은 값이 된다.
    check("없는 태그 조합은 None (0.0 이 아니다)",
          parse_prom_counter(prom, "alldap_ai_call_seconds_count",
                             {"operation": "chat", "outcome": "read_timeout"}) is None)
    check("라벨 없는 카운터도 읽는다", parse_prom_counter(prom, "alldap_ai_retry_total", {}) == 40.0)

    print("read_circuit_state — <닫혔다> 와 <못 읽었다> 를 가르는가")
    closed = "alldap_ai_circuit_state 0.0\n"
    check("0 이면 closed", read_circuit_state(closed)[0] == "closed")
    check("1 이면 half_open", read_circuit_state("alldap_ai_circuit_state 1.0\n")[0] == "half_open")
    check("2 이면 open", read_circuit_state("alldap_ai_circuit_state 2.0\n")[0] == "open")
    # 🔴 여기가 핵심이다. 시계열이 없을 때 closed 를 돌려주면 회복 확인이 <항상 통과>하고,
    #    서킷이 열린 채로 다음 판이 시작돼 그 판의 숫자가 통째로 오염된다.
    state, raw = read_circuit_state("# 다른 지표만 있는 본문\nalldap_ratelimit_keys 3.0\n")
    check("시계열이 없으면 unknown (closed 가 아니다)", state == "unknown", f"({state!r})")
    check("그때 값은 None", raw is None, f"({raw!r})")

    print("\njudge_fault_round — F1 (프로세스 종료)")
    before = signals()
    good_f1 = signals(outcomes={OUTCOME_CONNECT_FAILURE: 40.0, OUTCOME_CIRCUIT_OPEN: 300.0},
                      retry=40.0, transitions={"open": 3.0})
    ok, why = judged("F1", before, good_f1, k6(inject={503: 340}))
    check("F1 정상: 연결실패 · 재시도 · 서킷 개폐가 다 있으면 통과", ok, f"({why[:60]}…)")
    check("F1 이 톱니를 알아본다", "톱니" in why)

    fails_because("F1: 재시도가 0이면 실패(연결 실패에는 돌아야 한다)", "F1", before,
                  signals(outcomes={OUTCOME_CONNECT_FAILURE: 40.0, OUTCOME_CIRCUIT_OPEN: 300.0},
                          retry=0.0, transitions={"open": 3.0}),
                  k6(inject={503: 340}), "재시도가 0회다")
    fails_because("F1: 서킷이 안 열리면 실패", "F1", before,
                  signals(outcomes={OUTCOME_CONNECT_FAILURE: 40.0}, retry=40.0),
                  k6(inject={503: 40}), "circuit_open 이 0")
    # 전이 카운터만 0 인 경우. 급속 거절은 있는데 열린 기록이 없다 = 계측 의심.
    fails_because("F1: 급속거절은 있는데 전이가 0이면 실패", "F1", before,
                  signals(outcomes={OUTCOME_CONNECT_FAILURE: 40.0, OUTCOME_CIRCUIT_OPEN: 300.0},
                          retry=40.0, transitions={"open": 0.0}),
                  k6(inject={503: 340}), "전이 카운터 계측을 의심")

    print("\njudge_fault_round — F2 (Python 5xx). 이 PR 에서 유일한 반증 가능한 주장")
    ok, why = judged("F2", before, signals(outcomes={OUTCOME_PYTHON_5XX: 200.0}, retry=0.0),
                     k6(inject={503: 200}))
    check("F2 정상: 5xx 가 늘고 재시도가 0이면 통과", ok, f"({why[:60]}…)")
    check("F2 통과 사유가 중복 과금을 말한다", "중복 과금이 없다" in why)
    # 🔴 여기가 틀리면 LLM 이 두 번 과금된다. 반드시 잡혀야 한다.
    fails_because("F2: 재시도가 1회라도 돌면 실패(중복 과금)", "F2", before,
                  signals(outcomes={OUTCOME_PYTHON_5XX: 200.0}, retry=1.0),
                  k6(inject={503: 200}), "두 번 과금")
    fails_because("F2: 5xx 가 안 늘면 실패(주입이 안 켜졌다)", "F2", before,
                  signals(retry=0.0), k6(inject={503: 200}), "python_5xx 가 0")

    print("\njudge_fault_round — F3 (조용한 실패). <안 움직이는 것>이 통과다")
    f3_after = signals(outcomes={OUTCOME_SUCCESS: 700.0}, injected=150)
    ok, why = judged("F3", signals(injected=0), f3_after, k6(inject={200: 200}))
    check("F3 정상: 200 뿐이고 실패 outcome 이 안 움직이면 통과", ok, f"({why[:60]}…)")
    check("F3 통과가 <결함 재현>임을 말한다", "좋은 일이 아니다" in why)

    # 🔴 이 파일에서 가장 중요한 케이스. 계측이 죽어도 F3 은 겉보기에 똑같다.
    #    정상 구간에 200 이 없으면 <대조군이 없는 것>이라 통과시키면 안 된다.
    fails_because("F3: 정상 구간에 200 이 없으면 실패(계측 죽음과 구별 불가)", "F3",
                  signals(injected=0), f3_after,
                  k6(normal={200: 0}, inject={200: 200}), "대조군")
    fails_because("F3: injected 가 안 늘면 실패(주입이 실제로 안 일어났다)", "F3",
                  signals(injected=0), signals(outcomes={OUTCOME_SUCCESS: 700.0}, injected=0),
                  k6(inject={200: 200}), "안 늘었다")
    fails_because("F3: injected 를 못 읽으면 실패(None 을 0 으로 뭉개지 않는다)", "F3",
                  signals(injected=0), signals(outcomes={OUTCOME_SUCCESS: 700.0}, injected=None),
                  k6(inject={200: 200}), "증거가 없으면")
    fails_because("F3: 주입 구간에 503 이 섞이면 실패", "F3",
                  signals(injected=0), f3_after,
                  k6(inject={200: 190, 503: 10}), "다른 장애가 함께")
    fails_because("F3: 실패 outcome 이 움직이면 실패(전제가 달라졌다)", "F3",
                  signals(injected=0),
                  signals(outcomes={OUTCOME_SUCCESS: 700.0, OUTCOME_PYTHON_5XX: 3.0}, injected=150),
                  k6(inject={200: 200}), "실패 outcome 이 움직였다")

    print("\n공통 가드")
    fails_because("fallback 이 섞이면 실패(LLM 경로를 안 탔다)", "F2", before,
                  signals(outcomes={OUTCOME_PYTHON_5XX: 200.0}, retry=0.0),
                  k6(inject={503: 200}, fallback=4), "게이트에 걸려")
    ok, why = judged("F9", before, before, k6())
    check("모르는 판 이름은 실패", (not ok) and "모르는 판 이름" in why, f"({why[:40]}…)")
    ok, why = judge_fault_round("F1", before, good_f1, {"normal": {}, "inject": {}})
    check("구간이 비면 실패", (not ok) and "둘 다 있어야" in " | ".join(why))

    print("\ndelta 규칙 — after 에 시계열이 없는 것은 <0> 이다")
    # Micrometer 는 태그 조합이 처음 쓰일 때 미터를 만든다. 그래서 after 의 부재는
    # "그 일이 한 번도 안 일어났다" 로 읽는 것이 맞다. before 의 부재와 뜻이 다르다.
    after_missing = signals(outcomes={OUTCOME_PYTHON_5XX: 200.0}, retry=None)
    ok, why = judged("F2", before, after_missing, k6(inject={503: 200}))
    check("retry 시계열이 없으면 0 회로 읽어 F2 가 통과", ok, f"({why[:50]}…)")

    print(f"\n{'실패 ' + ', '.join(_failures) if _failures else '전부 통과'}")
    return 1 if _failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
