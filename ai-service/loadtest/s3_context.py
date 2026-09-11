"""S3(rate limit 정확성) 실행의 <시작 조건>을 남기고, 실행 뒤 <판정>한다.

실행:
    # 판마다 한 번씩. 판 이름은 N · A · B · C 넷 중 하나다(아래 ROUNDS).
    cd ai-service && .venv/bin/python -m loadtest.s3_context before \\
        --run-id 2026-09-11-A --round A

    cd ai-service && .venv/bin/python -m loadtest.s3_context after \\
        --run-id 2026-09-11-A --round A \\
        --k6-summary loadtest/results/S3-2026-09-11-A.json

설계서: docs/superpowers/specs/2026-09-11-loadtest-pr4a-s3-ratelimit-design.md

왜 이 파일이 있는가
─────────────────────────────────────────────────────────────────────────────
S2 의 s2_context.py 와 같은 이유다 — "그때 뭘로 쟀지" 를 못 답하는 측정은 재현할 수
없고, 재현할 수 없으면 측정이 아니다.

S3 는 거기에 하나를 더 얹는다: <판정 그 자체>다. S1·S2 는 숫자를 내고 사람이 읽었지만
S3 는 "정확히 20건이 통과했는가" 라는 예/아니오가 산출물이라, 그 판정을 사람의 눈이
아니라 코드가 한다. 그래서 이 파일에서 <틀리면 가장 비싼 코드>가 판정 로직이고,
그 부분만 서버도 시계도 안 타는 순수 함수로 뽑아 loadtest/s3_check.py 가 따로 시험한다.

🔴 2026-09-09 사고를 코드로 막는다
─────────────────────────────────────────────────────────────────────────────
그때 rate limit 점검 명령은 <돌아가는데 아무것도 검증하지 않는> 상태였다. 본문에
sessionId 가 없어 @Valid 에서 400 이 났고 rateLimiter.check 를 지나가지도 못했는데,
25건 전부 400 인 모습이 문서의 실패 판정 기준과 겹쳐 <언제 돌려도 실패를 보고했다.>

그래서 이 파일의 판정은 "429 가 나왔는가" 를 묻지 않는다. 상태코드 히스토그램
<전체>가 기대와 일치하는지를 묻고, 400 이나 200 이 한 건이라도 섞이면 그 실행을
무효로 돌린다. 근거는 judge_round 주석에 있다.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

# 파서는 loadtest/promtext.py 한 벌만 있다. 여기서 import 해 <이 모듈의 이름으로도>
# 남겨두므로, 이 파일에서 parse_prom_counter 를 가져다 쓰던 곳(s3_check · s4_check)은
# 한 줄도 고치지 않아도 그대로 돈다.
from loadtest.promtext import parse_prom_counter

RESULTS = Path(__file__).parent / "results"

# 감시할 상태코드. k6 쪽 WATCHED_STATUS 와 같아야 한다.
#
# 🔴 400 과 200 이 여기 있는 이유는 <안 나와야 정상>이기 때문이다.
#    400 = @Valid 에서 튕긴 것(2026-09-09 사고) / 200 = 진짜 봇을 때린 것.
#    "안 나와야 하는 것" 은 세지 않으면 안 났는지 알 수가 없다.
WATCHED_STATUS = [404, 429, 400, 200, 0, 500, 503]

# 판 정의. k6 스크립트와 이 파일이 각자 숫자를 들고 있으므로 <서로 대조용>으로 쓴다.
#
# 🔴 일부러 한 곳으로 합치지 않았다. 두 프로세스가 같은 상수를 공유하면 둘이 함께
#    틀렸을 때 아무도 못 잡는다. 따로 두고 합계가 어긋나면 무효로 돌리는 쪽이,
#    "k6 가 내가 생각한 수만큼 쐈는가" 를 검사로 만들어준다.
#
# expected_total : 그 판이 보낼 요청 수
# expect_pass    : 제한기를 통과해 404 로 끝나야 하는 수 ("limit 의 몇 배인가" 로 적는다)
ROUNDS: dict[str, dict] = {
    # 음성 대조. 한도를 아주 크게 두고 돌려 429 가 0 건임을 본다.
    "N": {"expected_total": 100, "pass_multiple": None, "expect_all_pass": True,
          "why": "음성 대조 — 한도를 100000 으로 두면 429 가 한 건도 없어야 한다"},
    # 본 판정. 동시 100건에 정확히 한도만큼만 통과해야 한다.
    "A": {"expected_total": 100, "pass_multiple": 1, "expect_all_pass": False,
          "why": "동시 폭주에서 카운터가 새는가"},
    # 고정 윈도우의 경계 버스트. 분 경계를 사이에 두고 2N 이 통과한다.
    "B": {"expected_total": 40, "pass_multiple": 2, "expect_all_pass": False,
          "why": "고정 윈도우 경계에서 2N 이 통과하는가"},
    # publicKey 축으로 버킷이 갈리는가. 키가 둘이면 통과분도 2배다.
    "C": {"expected_total": 200, "pass_multiple": 2, "expect_all_pass": False,
          "why": "publicKey 축으로 버킷이 갈리는가"},
}

# 형식만 맞는 가짜 publicKey. Bot.generatePublicKey() 는 "pk_" + Base64 22자를 만든다.
#
# 🔴 존재하지 않는 키를 쓰는 이유: WidgetController 의 순서가
#    requirePlausiblePublicKey → rateLimiter.check → chatService 라, 형식만 맞고 없는 키는
#    <카운터는 정상으로 세면서> findByPublicKey 에서 404 로 끝난다.
#    LLM 0건 · 대화 로그 0건이다. (통과분에 한해 인덱스 SELECT 1회는 돈다 — 설계서 §1)
# 🔴 s3_ratelimit.js 의 기본값과 <반드시> 같아야 한다. 다르면 드라이버는 A 키를 404 로
#    확인해놓고 k6 는 B 키를 두드려, 사전 확인이 아무것도 보증하지 못한다.
FAKE_PUBLIC_KEY = "pk_s3loadtestFAKEkeyAAAAA"
FAKE_PUBLIC_KEY_2 = "pk_s3loadtestFAKEkeyBBBBB"

WINDOW_MS = 60_000


# ─────────────────────────────────────────────────────────────────────────────
# 순수 함수 — 서버도 시계도 안 탄다. s3_check.py 가 이 둘만 시험한다.
# ─────────────────────────────────────────────────────────────────────────────

def next_window_start(now_ms: int, min_headroom_ms: int) -> int:
    """이 판을 시작해도 되는 시각. 지금 분에 여유가 없으면 다음 경계를 돌려준다.

    왜 필요한가: RateLimiter 가 고정 윈도우(now // 60000)라 100건이 분 경계를 넘으면
    카운터가 둘로 갈려 <정상인데도 404 가 40건>으로 나온다. 그건 정확히 B 판이 일부러
    재는 현상이라, 정렬하지 않으면 A 와 B 를 구별할 수 없다.

    파이썬 관용구 메모: `//` 는 내림 나눗셈이다. now_ms // WINDOW_MS 가 자바 쪽
    `currentTimeMillis() / window` 와 같은 windowIndex 가 된다(자바의 정수 나눗셈도
    양수에서는 내림이다).
    """
    elapsed = now_ms % WINDOW_MS          # 이번 분에서 흘러간 시간
    remaining = WINDOW_MS - elapsed       # 이번 분에 남은 시간
    if remaining >= min_headroom_ms:
        return now_ms                     # 여유가 있으면 지금 시작한다
    return now_ms + remaining             # 없으면 다음 경계까지 기다린다


def judge_round(round_name: str, counts: dict[int, int | None], limit: int) -> tuple[bool, str]:
    """상태코드 히스토그램 하나로 그 판의 성패를 가른다.

    counts 의 값이 `None` 이면 <k6 요약에 그 시계열이 아예 없었다>는 뜻이다.
    0 과 뭉개지 않는 이유: 0 은 "그 코드가 안 났다" 이고 None 은 "k6 가 안 셌다" 이다.
    후자는 thresholds 등록이 빠졌다는 뜻이라, 그 상태로는 <400 이 났어도 0 으로 보인다.>
    이 저장소가 일곱 번 낸 "원인이 다른 두 사실을 같은 값으로 뭉개는" 부류를 여기서 막는다.

    파이썬 문법 메모: `int | None` 은 3.10+ 의 Optional 표기다. 값이 둘 중 하나라는 것을
    타입으로 적어두면, 이 함수를 고치는 사람이 None 분기를 빠뜨리기 어려워진다.
    """
    spec = ROUNDS.get(round_name)
    if spec is None:
        return False, f"무효: 모르는 판 이름 {round_name!r} (아는 것: {sorted(ROUNDS)})"

    # ① 계측 자체가 붙었는가. 다른 무엇보다 먼저 본다.
    missing = sorted(code for code, n in counts.items() if n is None)
    if missing:
        return False, (
            f"무효: k6 요약에 상태코드 {missing} 의 시계열이 없다. "
            f"0건이라서가 아니라 <세지 않은> 것이다. s3_ratelimit.js 의 thresholds 등록을 확인할 것. "
            f"이대로면 400 이 나도 0 으로 보인다."
        )
    watched = sorted(counts)
    if sorted(WATCHED_STATUS) != watched:
        return False, (
            f"무효: 감시 목록이 어긋난다. 기대 {sorted(WATCHED_STATUS)}, 받은 것 {watched}. "
            f"k6 의 WATCHED_STATUS 와 이 파일의 것이 다르다."
        )

    got = {code: int(n) for code, n in counts.items()}   # 여기서부터 None 은 없다

    # ② 2026-09-09 사고. 요청이 제한기까지 갔다는 증거가 404 다.
    if got[400] > 0:
        return False, (
            f"무효: 400 이 {got[400]}건이다. @Valid 에서 튕겨 rateLimiter.check 를 "
            f"지나가지도 못했다는 뜻이다(2026-09-09 사고와 같은 모양). "
            f"본문에 message 와 sessionId 가 둘 다 들어 있는지 확인할 것."
        )

    # ③ 진짜 봇을 때렸는가. 200 은 LLM 이 돌았다는 뜻이다.
    if got[200] > 0:
        return False, (
            f"무효: 200 이 {got[200]}건이다. publicKey 가 <실재하는 봇>이라 채팅이 실제로 돌았다. "
            f"LLM 을 그만큼 태웠다. 가짜 키로 다시 돌릴 것."
        )

    # ④ 실행이 온전히 끝났는가. 연결 실패(0)나 5xx 가 섞이면 표본이 그만큼 빈다.
    broken = {code: got[code] for code in (0, 500, 503) if got[code] > 0}
    if broken:
        return False, f"무효: 실행 중 {broken} 가 났다. 제한기와 무관한 실패라 표본이 온전하지 않다."

    total = sum(got.values())
    if total != spec["expected_total"]:
        return False, (
            f"무효: 총 {total}건인데 이 판은 {spec['expected_total']}건이어야 한다. "
            f"k6 스크립트의 VU·반복 수가 이 파일의 ROUNDS 와 어긋났거나, 요청이 덜 나갔다."
        )

    # ⑤ 판별 판정.
    if spec["expect_all_pass"]:
        # N 판(음성 대조): 한도를 아주 크게 뒀으니 거절이 하나도 없어야 한다.
        if got[429] != 0:
            return False, (
                f"무효: 음성 대조인데 429 가 {got[429]}건 났다. "
                f"한도를 크게 올리고 Spring 을 <다시 띄웠는지> 확인할 것 "
                f"(WIDGET_CHAT_PER_MINUTE 는 기동 시 바인딩되어 실행 중에 안 바뀐다). "
                f"이 판이 깨지면 A 판의 429 가 제한기에서 나온 것이라고 말할 수 없다."
            )
        return True, f"통과: 429 0건 · 404 {got[404]}건. 제한기 밖의 거절원이 없다."

    expect_pass = limit * spec["pass_multiple"]
    expect_reject = spec["expected_total"] - expect_pass
    if got[404] == expect_pass and got[429] == expect_reject:
        return True, (
            f"통과: 404 {got[404]}건 · 429 {got[429]}건 "
            f"(기대 {expect_pass} / {expect_reject}, 한도 {limit} × {spec['pass_multiple']})."
        )

    direction = "샜다(더 통과)" if got[404] > expect_pass else "과하게 셌다(덜 통과)"
    return False, (
        f"실패: 404 {got[404]}건 · 429 {got[429]}건인데 기대는 {expect_pass} / {expect_reject} 다. "
        f"카운터가 {direction}. 분 경계를 넘겨 카운터가 둘로 갈렸을 수도 있으니 "
        f"시작 조건 파일의 started_at_ms 와 분 경계까지 남은 시간을 먼저 볼 것."
    )


# ─────────────────────────────────────────────────────────────────────────────
# k6 요약 읽기
# ─────────────────────────────────────────────────────────────────────────────

def extract_counts(summary: dict, round_name: str) -> dict[int, int | None]:
    """k6 요약에서 상태코드별 건수를 꺼낸다. 시계열이 없으면 None 을 남긴다.

    k6 는 thresholds 에 등록된 서브지표만 요약에 싣는다(s2_breakpoint.js 가 더미
    threshold 를 거는 이유가 그것이다). 그래서 <없다> 는 것 자체가 신호다.
    """
    metrics = summary.get("metrics", {}) or {}
    out: dict[int, int | None] = {}
    for code in WATCHED_STATUS:
        # round 태그가 붙은 키를 먼저 보고, 없으면 태그 없는 키를 본다.
        # k6 스크립트가 어느 쪽으로 내든 받아주되, 둘 다 없으면 None 이다.
        for key in (f"chat_status{{round:{round_name},status:{code}}}",
                    f"chat_status{{status:{code}}}"):
            m = metrics.get(key)
            if m is not None:
                out[code] = int((m.get("values") or {}).get("count", 0))
                break
        else:
            out[code] = None
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 실행 단계
# ─────────────────────────────────────────────────────────────────────────────

def _context_path(run_id: str) -> Path:
    return RESULTS / f"S3-{run_id}-context.json"


def _verdict_path(run_id: str) -> Path:
    return RESULTS / f"S3-{run_id}-verdict.json"


def _actuator_text(actuator: str) -> str:
    resp = httpx.get(f"{actuator}/actuator/prometheus", timeout=10.0)
    resp.raise_for_status()
    return resp.text


def _ratelimit_recorded(actuator: str) -> float | None:
    """제한기가 <실제로 몇 건을 셌는가>. 한도 값을 못 물어보는 것을 이것으로 갈음한다."""
    return parse_prom_counter(
        _actuator_text(actuator), "alldap_ratelimit_recorded_total", {"bucket": "widget-chat"}
    )


def _assert_key_is_fake(api: str, public_key: str) -> None:
    """그 키가 정말 <없는 봇>인지 확인한다. 아니면 여기서 멈춘다.

    🔴 이 검사가 없으면 실수로 진짜 publicKey 를 넣었을 때 LLM 이 한도만큼 돈다.
       설계서가 "가짜 키 확인" 을 무효화 방지 장치로 올려둔 자리다.
    """
    body = {"message": "S3 사전 확인용 요청입니다", "sessionId": "s3-precheck"}
    resp = httpx.post(f"{api}/api/w/{public_key}/chat", json=body, timeout=30.0)
    if resp.status_code == 404:
        return
    if resp.status_code == 429:
        raise SystemExit(
            f"중단: {public_key} 가 이미 429 다. 앞 판의 카운터가 아직 살아 있다. "
            f"1분 이상 쉬었다가 다시 실행할 것."
        )
    raise SystemExit(
        f"중단: {public_key} 로 친 요청이 {resp.status_code} 다(기대 404). "
        f"200 이면 <실재하는 봇>이라 LLM 이 돈다. 400 이면 본문이 @Valid 를 못 넘긴 것이라 "
        f"요청이 제한기에 도달조차 못 한다(2026-09-09 사고). body={resp.text[:200]}"
    )


def cmd_before(args) -> int:
    spec = ROUNDS[args.round]

    # ① 이 키가 정말 없는 봇인지. k6 를 띄우기 전에 본다.
    _assert_key_is_fake(args.api, args.public_key)
    if args.round == "C":
        _assert_key_is_fake(args.api, args.public_key_2)

    # ② 제한기 계측이 살아 있는지. keys 게이지는 <거절이 0이어도 항상> 나온다.
    text = _actuator_text(args.actuator)
    keys_gauge = parse_prom_counter(text, "alldap_ratelimit_keys", {})
    if keys_gauge is None:
        raise SystemExit(
            "중단: alldap_ratelimit_keys 게이지가 없다. management 포트(8081)가 아니거나 "
            "지표 내보내기가 꺼져 있다. 이 게이지가 없으면 '거절 0' 과 '계측이 안 붙었다' 를 "
            "구별할 방법이 사라진다(핸드오프 §6-ⓓ)."
        )
    recorded_before = parse_prom_counter(
        text, "alldap_ratelimit_recorded_total", {"bucket": "widget-chat"}
    )

    # ③ 분 경계 정렬. 이 판의 요청이 전부 같은 윈도우 안에서 끝나야 한다.
    #    🔴 사전 확인 요청(위 ①)도 카운터를 <이미 하나 올렸다.> 그래서 경계를 넘겨
    #       새 윈도우에서 시작하는 것이 A·C 판에서는 오히려 정확하다.
    now_ms = int(time.time() * 1000)
    start_ms = next_window_start(now_ms, args.headroom_ms)
    waited_ms = start_ms - now_ms
    if waited_ms > 0:
        print(f"분 경계까지 {waited_ms}ms 기다린다 (이번 분에 남은 여유가 "
              f"{args.headroom_ms}ms 에 못 미친다).")
        time.sleep(waited_ms / 1000)
    # 사전 확인 요청이 올린 카운터를 버리려면 어차피 다음 윈도우여야 한다.
    if waited_ms == 0:
        remaining = WINDOW_MS - (int(time.time() * 1000) % WINDOW_MS)
        print(f"이번 분에 {remaining}ms 남았다. 사전 확인 요청 1건이 이미 세어져 있으므로, "
              f"A·C 판의 기대 통과분은 그만큼 줄어들 수 있다. "
              f"정확을 기하려면 --headroom-ms 를 60000 으로 주어 항상 새 윈도우에서 시작할 것.")

    started_ms = int(time.time() * 1000)
    context = {
        "run_id": args.run_id,
        "round": args.round,
        "round_why": spec["why"],
        "commit": subprocess.run(["git", "rev-parse", "HEAD"],
                                 capture_output=True, text=True).stdout.strip(),
        "started_at": datetime.now().isoformat(timespec="milliseconds"),
        "started_at_ms": started_ms,
        "window_index": started_ms // WINDOW_MS,
        "ms_left_in_window": WINDOW_MS - (started_ms % WINDOW_MS),
        "api_base": args.api,
        "actuator_base": args.actuator,
        "public_key": args.public_key,
        "public_key_2": args.public_key_2 if args.round == "C" else None,
        # 🔴 한도 값은 <드라이버 값>이다. 도는 서버에게 물어볼 길이 없다.
        #    /actuator/configprops 는 노출 목록(health,metrics,prometheus)에 없고,
        #    열더라도 SecurityConfig 가 /actuator/prometheus 하나만 permitAll 이라 401 이다.
        #    그리고 열지 않는다 — 한도 숫자 하나를 읽으려고 DB 접속 문자열·JWT 시크릿이
        #    같은 응답에 실리는 경로를 만드는 셈이다. 설계서 §5-② 가 근거다.
        "widget_chat_per_minute": {"value": args.limit, "source": "driver"},
        # 한도를 못 물어보는 대신, 제한기가 <실제로 몇 건을 셌는가>를 다른 축에서 본다.
        "ratelimit_recorded_before": recorded_before,
        "ratelimit_keys_gauge_before": keys_gauge,
        "expected_total": spec["expected_total"],
        "expected_pass": (None if spec["expect_all_pass"]
                          else args.limit * spec["pass_multiple"]),
        "watched_status": WATCHED_STATUS,
    }

    RESULTS.mkdir(exist_ok=True)
    _context_path(args.run_id).write_text(
        json.dumps(context, ensure_ascii=False, indent=2, default=str)
    )
    print(json.dumps(context, ensure_ascii=False, indent=2, default=str))
    print(f"\n저장: {_context_path(args.run_id)}")
    print(f"\nROUND={args.round}")
    print(f"RUN_ID={args.run_id}")
    print(f"PUBLIC_KEY={args.public_key}")
    if args.round == "C":
        print(f"PUBLIC_KEY_2={args.public_key_2}")
    return 0


def cmd_after(args) -> int:
    context = json.loads(_context_path(args.run_id).read_text())
    summary = json.loads(Path(args.k6_summary).read_text())

    counts = extract_counts(summary, context["round"])
    ok, reason = judge_round(context["round"], counts, context["widget_chat_per_minute"]["value"])

    recorded_after = _ratelimit_recorded(context["actuator_base"])
    recorded_before = context["ratelimit_recorded_before"]
    verdicts = [("OK   " if ok else "") + reason]

    # 다른 축에서의 대조. 제한기가 센 건수가 k6 가 보낸 건수와 맞는가.
    #
    # 🔴 None 을 0 으로 바꾸지 않는다. "거절 0" 과 "계측이 안 붙었다" 를 가르는 것이
    #    이 지표를 쓰는 이유다. before 가 None 이었다면 그건 이 판이 <그 버킷의 첫 사용>
    #    이었다는 뜻이라 정상이고, after 까지 None 이면 계측이 안 붙은 것이다.
    if recorded_after is None:
        verdicts.append(
            "무효: alldap_ratelimit_recorded_total{bucket=widget-chat} 시계열이 실행 뒤에도 없다. "
            "제한기를 한 번도 안 지났다는 뜻이다."
        )
        ok = False
    else:
        delta = recorded_after - (recorded_before or 0.0)
        total = sum(n for n in counts.values() if n is not None)
        # 사전 확인 요청 1건(C 판은 2건)이 before 를 찍기 전에 이미 세어졌다.
        precheck = 2 if context["round"] == "C" else 1
        if abs(delta - total) <= precheck:
            verdicts.append(f"OK   제한기가 센 건수 {delta:.0f} ≈ k6 가 보낸 {total}건")
        else:
            verdicts.append(
                f"무효: 제한기가 센 건수는 {delta:.0f} 인데 k6 는 {total}건을 보냈다. "
                f"둘이 다르면 그 차이만큼 요청이 제한기를 <거치지 않고> 끝난 것이다."
            )
            ok = False

    result = {
        "run_id": args.run_id,
        "round": context["round"],
        "finished_at": datetime.now().isoformat(timespec="milliseconds"),
        "limit": context["widget_chat_per_minute"],
        "counts": {str(k): v for k, v in counts.items()},
        "expected_total": context["expected_total"],
        "expected_pass": context["expected_pass"],
        "ratelimit_recorded_before": recorded_before,
        "ratelimit_recorded_after": recorded_after,
        "verdicts": verdicts,
        "valid": ok,
        # 🔴 "valid" 는 <그 판이 기대대로 나왔다> 는 뜻이다. 결과가 좋다는 뜻이 아니다.
        #    A 판이 실패하면 그것도 값진 발견이고(카운터가 샌다), 그때 이 값은 False 다.
        "valid_means": "이 판의 상태코드 히스토그램이 기대와 정확히 일치한다는 뜻이다.",
    }

    _verdict_path(args.run_id).write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n저장: {_verdict_path(args.run_id)}")
    for v in verdicts:
        print(f"  {v}")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="S3 시작 조건 · 판정")
    parser.add_argument("phase", choices=["before", "after"])
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--round", required=True, choices=sorted(ROUNDS))
    parser.add_argument("--api", default="http://localhost:8080")
    parser.add_argument("--actuator", default="http://localhost:8081")
    parser.add_argument("--public-key", default=FAKE_PUBLIC_KEY)
    parser.add_argument("--public-key-2", default=FAKE_PUBLIC_KEY_2)
    # 🔴 기본값이 20 인 것은 application.yaml 의 기본값을 옮긴 것이다. N 판은
    #    --limit 100000 을 <반드시> 함께 준다. 안 주면 판정이 조용히 틀린다.
    parser.add_argument("--limit", type=int, default=20,
                        help="WIDGET_CHAT_PER_MINUTE 로 띄운 값. 드라이버 값이라 직접 적어야 한다")
    parser.add_argument("--headroom-ms", type=int, default=20_000)
    parser.add_argument("--k6-summary")
    args = parser.parse_args()

    if args.phase == "before":
        return cmd_before(args)
    if not args.k6_summary:
        print("중단: after 에는 --k6-summary 가 필요하다.")
        return 1
    return cmd_after(args)


if __name__ == "__main__":
    sys.exit(main())
