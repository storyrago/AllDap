"""loadtest/s3_context.py 의 판정 로직 자체 점검. 서버도 k6 도 DB 도 없이 돈다.

실행:
    cd ai-service && .venv/bin/python -m loadtest.s3_check

무엇을 재나
─────────────────────────────────────────────────────────────────────────────
S3 의 산출물은 곡선이 아니라 <예/아니오>다. 그 예/아니오를 사람이 아니라 judge_round
가 낸다. 즉 **이 함수가 틀리면 측정이 통째로 거짓이 된다.**

그래서 여기서는 "정상 입력이 통과하는가" 보다 <일부러 깨뜨린 입력이 실제로 실패를
보고하는가> 를 더 많이 본다. 이 저장소는 "짜뒀는데 아무것도 검사하지 않는 검사" 로
두 번 데였다(2026-09-08 오픈 리다이렉트의 redirect.check.ts, 2026-09-09 rate limit
점검 명령). 둘 다 "돌려봤더니 통과했다" 상태였고, 통과는 아무것도 검사하지 않아도 나온다.
"""
from __future__ import annotations

from loadtest.promtext import MetricUnreadable
from loadtest.s3_context import (
    WATCHED_STATUS,
    WINDOW_MS,
    extract_counts,
    judge_round,
    next_window_start,
    parse_prom_counter,
)

_failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'OK  ' if ok else 'FAIL'} {name} {detail}")
    if not ok:
        _failures.append(name)


def counts(**kw: int | None) -> dict[int, int | None]:
    """감시 코드 전부를 채운 히스토그램. 적지 않은 코드는 0 이다.

    🔴 0 으로 채우는 것이 맞는 이유: k6 는 threshold 가 걸린 서브지표를 <표본이 0건이어도>
       요약에 싣는다(s3_ratelimit.js 가 감시 코드 전부에 count>=0 을 걸어둔 이유).
       그래서 실제 실행에서 오는 값은 0 이지 누락이 아니다.
       누락(None)을 시험하고 싶을 때만 명시적으로 None 을 넣는다.

    파이썬 메모: `**kw` 는 키워드 인자를 dict 로 받는다. 파이썬 식별자는 숫자로 시작할 수
    없어 호출은 `counts(s404=20)` 처럼 접두사를 붙이고 여기서 떼어낸다.
    """
    out: dict[int, int | None] = {code: 0 for code in WATCHED_STATUS}
    for key, value in kw.items():
        out[int(key.lstrip("s"))] = value
    return out


def main() -> int:
    print("judge_round — 정상 입력")
    # 설계서 §5-④ 표의 첫 줄. A 판은 한도 20 에 100건이면 404 20 · 429 80 이다.
    ok, why = judge_round("A", counts(s404=20, s429=80), 20)
    check("A: {404:20, 429:80} 통과", ok, f"({why})")

    ok, why = judge_round("N", counts(s404=100), 100_000)
    check("N: 429 0건 통과", ok, f"({why})")

    ok, why = judge_round("B", counts(s404=40), 20)
    check("B: 경계 버스트 2N=40 통과", ok, f"({why})")

    ok, why = judge_round("C", counts(s404=40, s429=160), 20)
    check("C: 키 둘이면 통과분도 2배 통과", ok, f"({why})")

    print("\njudge_round — 일부러 깨뜨린 입력 (여기가 이 파일의 본체다)")
    # 🔴 아래는 전부 `not ok` 만 보지 않고 <사유까지> 단언한다.
    #    이 파일의 음성 대조에서 실제로 드러난 약점이다: 400 가드를 통째로 없앴는데도
    #    "400 이면 실패" 케이스가 그대로 통과했다. 400 만 100건이면 404 개수 검사에도
    #    어차피 걸려서, <다른 이유로> 실패하고 있었던 것이다.
    #    "실패했다" 와 "그 이유로 실패했다" 는 다른 사실이고, 뭉개면 가드가 사라져도 모른다.
    def fails_because(name: str, round_name: str, hist, limit: int, needle: str) -> None:
        ok_, why_ = judge_round(round_name, hist, limit)
        check(name, (not ok_) and needle in why_, f"({why_[:50]}…)")

    # 카운터가 샌 경우. 동시성 하에서 increment 를 잃으면 이 모양이 된다.
    fails_because("A: 404 가 21이면 실패(카운터가 샜다)", "A", counts(s404=21, s429=79), 20, "샜다")

    # 합계가 모자란 경우. 요청이 덜 나갔다는 뜻이라 그 표본으로는 아무 말도 못 한다.
    fails_because("A: 합계 99면 실패(요청이 덜 나갔다)", "A", counts(s404=20, s429=79), 20, "총 99건")

    # 🔴 2026-09-09 사고. 본문에 sessionId 가 없어 @Valid 에서 튕기면 이 모양이다.
    #    요청이 rateLimiter.check 를 지나가지도 못했는데 "돌아갔다" 로 읽히면 안 된다.
    fails_because("A: 400 100건이면 실패(제한기에 도달 못 함)", "A", counts(s400=100), 20, "2026-09-09")
    # 404 개수 검사에 가려지지 않는지도 본다 — 히스토그램이 정상인데 400 만 1건 섞인 경우.
    fails_because("A: 정상 히스토그램에 400 이 1건만 섞여도 실패", "A",
                  counts(s404=20, s429=79, s400=1), 20, "2026-09-09")

    # 진짜 봇을 때린 경우. LLM 이 실제로 돌았다는 뜻이다.
    fails_because("A: 200 이 1건이면 실패(진짜 봇)", "A", counts(s404=20, s429=79, s200=1), 20, "실재하는 봇")

    # 음성 대조가 깨진 경우. 이게 통과하면 A 판의 429 를 제한기 것이라고 말할 수 없다.
    fails_because("N: 429 가 1건이면 실패(음성 대조 붕괴)", "N", counts(s404=99, s429=1), 100_000, "음성 대조")

    # 실행 중 연결 실패·5xx 가 섞인 경우. 제한기와 무관한 실패다.
    fails_because("A: 연결 실패가 섞이면 실패", "A", counts(s404=20, s429=79, s0=1), 20, "제한기와 무관")

    # 모르는 판 이름. 오타로 다른 기대값을 적용하는 것을 막는다.
    fails_because("모르는 판 이름은 실패", "Z", counts(s404=20, s429=80), 20, "모르는 판 이름")

    print("\njudge_round — 0건과 <안 셌다> 를 가르는가")
    # 🔴 이 저장소가 반복해 낸 부류(AGENTS.md 의 "낸 버그" 절). None(시계열 없음)을 0 으로 뭉개면
    #    400 이 났는데도 0 으로 보여 위의 사고 검사가 통째로 무력해진다.
    fails_because("400 시계열이 없으면 실패(0 이 아니다)", "A",
                  counts(s404=20, s429=80, s400=None), 20, "세지 않은")
    ok, why = judge_round("A", counts(s404=20, s429=80, s400=0), 20)
    check("400 이 0건이면 통과(같은 값이 아니다)", ok)

    # 감시 목록이 어긋난 경우. k6 와 드라이버의 WATCHED_STATUS 가 갈리면 조용히 틀린다.
    partial: dict[int, int | None] = {404: 20, 429: 80}
    fails_because("감시 목록이 모자라면 실패", "A", partial, 20, "감시 목록이 어긋난다")

    print("\nextract_counts — k6 요약 읽기")
    summary = {"metrics": {f"chat_status{{status:{c}}}": {"values": {"count": 0}}
                           for c in WATCHED_STATUS}}
    summary["metrics"]["chat_status{status:404}"]["values"]["count"] = 20
    summary["metrics"]["chat_status{status:429}"]["values"]["count"] = 80
    got = extract_counts(summary, "A")
    check("태그 없는 키를 읽는다", got[404] == 20 and got[429] == 80, f"({got[404]}/{got[429]})")
    check("나머지는 0 이지 None 이 아니다", all(got[c] == 0 for c in (400, 200, 0, 500, 503)))

    # 키가 아예 없으면 None 이어야 한다. 0 으로 돌려주면 위의 구분이 무너진다.
    del summary["metrics"]["chat_status{status:400}"]
    got = extract_counts(summary, "A")
    check("키가 없으면 None", got[400] is None, f"({got[400]!r})")

    # round 태그가 붙은 키도 읽는다(k6 쪽이 태그를 붙이도록 바뀌어도 안 깨지게).
    tagged = {"metrics": {f"chat_status{{round:A,status:{c}}}": {"values": {"count": 1}}
                          for c in WATCHED_STATUS}}
    got = extract_counts(tagged, "A")
    check("round 태그가 붙은 키도 읽는다", all(got[c] == 1 for c in WATCHED_STATUS))

    print("\nnext_window_start — 분 경계 정렬")
    base = 1_700_000_000_000 - (1_700_000_000_000 % WINDOW_MS)   # 어떤 분의 0초
    check("여유가 충분하면 지금 시작", next_window_start(base + 1_000, 20_000) == base + 1_000)
    check("여유가 딱 맞으면 지금 시작", next_window_start(base + 40_000, 20_000) == base + 40_000)
    check("여유가 모자라면 다음 경계", next_window_start(base + 50_000, 20_000) == base + WINDOW_MS)
    check("경계 직전 1ms 도 다음 경계", next_window_start(base + 59_999, 20_000) == base + WINDOW_MS)
    # 🔴 돌려준 시각은 <반드시> 윈도우 경계이거나 지금이다. 그 사이 아무 값이면
    #    기다린 뒤에도 경계를 넘어 카운터가 둘로 갈린다.
    nxt = next_window_start(base + 59_999, 20_000)
    check("돌려준 경계가 정확히 윈도우 시작", nxt % WINDOW_MS == 0, f"({nxt % WINDOW_MS})")

    print("\nparse_prom_counter — 0 과 <계측 없음> 을 가르는가")
    text = (
        "# HELP alldap_ratelimit_recorded_total 설명\n"
        "# TYPE alldap_ratelimit_recorded_total counter\n"
        'alldap_ratelimit_recorded_total{bucket="widget-chat",} 41.0\n'
        'alldap_ratelimit_recorded_total{bucket="login",} 7.0\n'
        "alldap_ratelimit_keys 3.0\n"
    )
    check("라벨로 골라 읽는다",
          parse_prom_counter(text, "alldap_ratelimit_recorded_total", {"bucket": "widget-chat"}) == 41.0)
    check("다른 라벨은 다른 값",
          parse_prom_counter(text, "alldap_ratelimit_recorded_total", {"bucket": "login"}) == 7.0)
    check("라벨 없는 게이지도 읽는다", parse_prom_counter(text, "alldap_ratelimit_keys", {}) == 3.0)
    # 🔴 없는 시계열에 0.0 을 돌려주면 "거절 0" 과 "계측이 안 붙었다" 가 같은 값이 된다.
    check("없는 라벨은 None (0.0 이 아니다)",
          parse_prom_counter(text, "alldap_ratelimit_rejected_total", {"bucket": "widget-chat"}) is None)

    print("\nparse_prom_counter — 이름이 <접두사만> 같은 줄을 집지 않는가")
    # 🔴 2026-09-11. RateLimiter 가 등록하는 alldap.ratelimit.keys(게이지)와
    #    alldap.ratelimit.keys.cleared(카운터)는 Micrometer 를 거치면
    #    alldap_ratelimit_keys 와 alldap_ratelimit_keys_cleared_total 이 되어
    #    <앞이 뒤의 접두사>다. 게다가 이 조회는 라벨 조건이 {} 라 빈 시퀀스의 all() 이
    #    True 가 되어 라벨로도 걸러지지 않는다. 즉 경계 검사가 없으면 두 줄이 다 통과하고
    #    <먼저 나오는 줄이 이긴다>. 지금까지 값이 맞았던 이유는 파서가 아니라
    #    prometheus-metrics 1.x 의 알파벳 순 출력이었고, 파서에는 그 순서에 기댄다는
    #    근거가 한 줄도 없었다. 그래서 <줄 순서를 뒤집어도 같은 값>까지 단언한다.
    gauge_line = "alldap_ratelimit_keys 3.0\n"
    cleared_line = "alldap_ratelimit_keys_cleared_total 1.0\n"
    for order, body in (("노출 순", gauge_line + cleared_line),
                        ("뒤집은 순", cleared_line + gauge_line)):
        got = parse_prom_counter(body, "alldap_ratelimit_keys", {})
        check(f"게이지가 _cleared_total 줄을 집지 않는다({order})", got == 3.0, f"({got!r})")
        got = parse_prom_counter(body, "alldap_ratelimit_keys_cleared_total", {})
        check(f"긴 이름 쪽도 제 값을 읽는다({order})", got == 1.0, f"({got!r})")

    print("\nparse_prom_counter: <살아 있다> 와 <죽어서 NaN 이다> 를 가르는가")
    # 🔴 Micrometer 의 DefaultGauge.value() 는 약한 참조가 끊겼을 때<뿐 아니라>
    #    값 함수가 Throwable 을 던졌을 때도 NaN 을 돌려준다(1.16.4 바이트코드로 확인).
    #    그 NaN 은 prometheus-metrics 의 TextFormatUtil.writeDouble 이 Double.toString 으로
    #    흘려 "NaN" 이라는 글자로 노출된다. 파이썬 float("NaN") 은 <예외를 내지 않으므로>
    #    경계 검사만 있던 파서는 그것을 정상 값으로 통과시켰다.
    #    그러면 아래 cmd_before 의 "게이지가 있는가" 가드(`is None`)가 통과해버려
    #    <계측이 죽은 채로 측정 한 판이 돈다>. 이 저장소가 일곱 번 낸 부류 그대로다.
    for token in ("NaN", "+Inf", "-Inf"):
        body = f"alldap_ratelimit_keys {token}\n"
        try:
            got = parse_prom_counter(body, "alldap_ratelimit_keys", {})
        except MetricUnreadable:
            check(f"값이 {token} 이면 MetricUnreadable", True)
        else:
            check(f"값이 {token} 이면 MetricUnreadable", False, f"({got!r} 로 통과했다)")
    # 🔴 <없다>(None)로 뭉개도 안 된다. judge_fault_round 의 delta 가 after 의 None 을
    #    0.0 으로 읽기 때문에, 죽은 계측이 "그 일이 0번 일어났다" 로 둔갑한다.
    try:
        parse_prom_counter("alldap_ratelimit_keys NaN\n", "alldap_ratelimit_keys", {})
    except MetricUnreadable:
        check("NaN 을 None 으로 뭉개지 않는다", True)
    except Exception as exc:   # noqa: BLE001
        check("NaN 을 None 으로 뭉개지 않는다", False, f"({type(exc).__name__})")
    else:
        check("NaN 을 None 으로 뭉개지 않는다", False, "(None 또는 값으로 돌아왔다)")
    # 대조군: 시계열이 아예 없는 것은 여전히 None 이다(예외가 아니다).
    check("시계열이 없는 것은 여전히 None",
          parse_prom_counter("", "alldap_ratelimit_keys", {}) is None)

    print(f"\n{'실패 ' + ', '.join(_failures) if _failures else '전부 통과'}")
    return 1 if _failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
