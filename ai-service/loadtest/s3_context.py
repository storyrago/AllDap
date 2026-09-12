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
S2 의 s2_context.py 와 같은 이유다. "그때 뭘로 쟀지" 를 못 답하는 측정은 재현할 수
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
from loadtest.promtext import MetricUnreadable, parse_prom_counter

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
          "why": "음성 대조: 한도를 100000 으로 두면 429 가 한 건도 없어야 한다"},
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
#    LLM 0건 · 대화 로그 0건이다. (통과분에 한해 인덱스 SELECT 1회는 돈다. 설계서 §1)
# 🔴 s3_ratelimit.js 의 기본값과 <반드시> 같아야 한다. 다르면 드라이버는 A 키를 404 로
#    확인해놓고 k6 는 B 키를 두드려, 사전 확인이 아무것도 보증하지 못한다.
FAKE_PUBLIC_KEY = "pk_s3loadtestFAKEkeyAAAAA"
FAKE_PUBLIC_KEY_2 = "pk_s3loadtestFAKEkeyBBBBB"

WINDOW_MS = 60_000

# 제한기 지표 이름. 🔴 상수로 뺀 이유는 <부재를 정상으로 읽는 축>이 생겼기 때문이다.
# 이름에 오타가 나면 시계열이 "없는" 것으로 보이고, 그 부재가 통과 사유인 자리에서는
# 오타가 곧 거짓 통과가 된다. 한 곳에만 적어두면 적어도 셋이 함께 틀린다.
M_REJECTED = "alldap_ratelimit_rejected_total"
M_RECORDED = "alldap_ratelimit_recorded_total"
BUCKET_WIDGET = {"bucket": "widget-chat"}


# ─────────────────────────────────────────────────────────────────────────────
# 순수 함수: 서버도 시계도 안 탄다. s3_check.py 가 이것들을 시험한다.
# (지표 본문을 읽는 ratelimit_readings 도 순수 함수인데, _actuator_text 바로 아래에
#  두어야 읽는 경로가 한눈에 보이므로 아래쪽에 있다)
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
    AGENTS.md 의 "낸 버그" 절이 모아둔 "원인이 다른 두 사실을 같은 값으로 뭉개는"
    부류를 여기서 막는다.

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


def judge_ratelimit_axis(
    counts: dict[int, int | None],
    before: dict[str, float | None],
    after: dict[str, float | None],
) -> list[tuple[bool, str]]:
    """k6 가 받은 429 와 <제한기가 센 거절>을 대조한다. (성패, 사유) 목록을 돌려준다.

    judge_round 는 k6 가 센 것만 본다. "k6 가 429 를 80건 받았다" 와 "제한기가 80건을
    거절했다" 는 <다른 사실>이다. 앞단에 429 를 내는 다른 무엇이 끼면 히스토그램만으로는
    구별할 수 없어서, 서버 쪽 지표를 두 번째 축으로 둔다.

    🔴 2026-09-12: 이 축을 <원리적으로 생길 수 없는 시계열>에서 옮겨왔다.
       옛 축은 alldap_ratelimit_recorded_total{bucket="widget-chat"} 의 증가분이었다.
       그런데 그 카운터를 올리는 곳은 RateLimiter.record() 하나이고, 그 호출자는
       AuthService 의 login-failure 버킷뿐이다. 위젯 채팅은 check() 를 지나므로
       그 시계열은 <만들어질 수가 없다>. 그래서 S3 네 판이 전부 멀쩡한 측정을 해놓고도
       valid:false + 종료코드 1 로 끝났다. 이 저장소가 이미 두 번 기각한
       "정상을 실패로 부르는 검사" 부류의 세 번째였다
       (decisions.md 2026-09-09 의 provenance 거짓 경보 · AGENTS.md 의 Forwarded 점검 명령).

    🔴 그래서 옛 축을 지우는 것으로 끝내지 않고 <없는 것이 정상>임을 검사로 남긴다.
       지우기만 하면 다음 사람이 "이 시계열이 왜 안 보이지" 하며 같은 축을 되살린다.
    """
    out: list[tuple[bool, str]] = []

    # ① recorded: 없어야 정상이다. 있으면 S3 의 전제가 깨진 것이다.
    recorded = after["recorded"]
    if recorded is None:
        out.append((True,
            f'OK   {M_RECORDED}{{bucket=widget-chat}} 시계열이 없다. <이것이 정상이다.> '
            f'그 카운터는 RateLimiter.record() 만 올리고 호출자는 login-failure 버킷뿐이며, '
            f'위젯 채팅은 check() 를 지난다. 이 부재를 "제한기를 한 번도 안 지났다" 로 읽지 말 것.'))
    else:
        out.append((False,
            f'무효: {M_RECORDED}{{bucket=widget-chat}} 이 {recorded:.0f} 로 <있다>. '
            f'생길 수 없는 시계열이 생겼다는 뜻이므로 위젯 채팅 경로가 record() 를 부르도록 '
            f'바뀐 것이다. 그러면 아래 429 대조의 전제도 다시 봐야 한다. '
            f'RateLimiter.record() 의 호출자를 먼저 확인할 것.'))

    # ② 거절 모드. 아래 대조는 mode="check" 만 세므로, blocked 가 생기면 그만큼 덜 센다.
    blocked = after["rejected_blocked"]
    if blocked is None:
        out.append((True,
            f'OK   {M_REJECTED}{{bucket=widget-chat,mode=blocked}} 가 없다. 위젯 채팅의 거절은 '
            f'전부 mode="check" 여야 한다(isBlocked() 호출자는 AuthService.login 하나다).'))
    else:
        out.append((False,
            f'무효: {M_REJECTED}{{bucket=widget-chat,mode=blocked}} 가 {blocked:.0f} 로 있다. '
            f'아래 대조는 mode="check" 만 세기 때문에 그만큼 덜 센다. '
            f'WidgetController 가 isBlocked() 를 쓰기 시작했는지 확인할 것.'))

    # ③ 본 대조: k6 가 받은 429 == 제한기가 센 거절 증가분.
    expected = counts.get(429)
    if expected is None:
        out.append((False,
            "무효: k6 요약에 429 시계열이 없다. 0건이라서가 아니라 <세지 않은> 것이라, "
            "제한기 거절 수와 대조할 상대가 아예 없다. s3_ratelimit.js 의 thresholds 를 확인할 것."))
        return out

    b, a = before["rejected_check"], after["rejected_check"]
    # 🔴 여기서 None 을 0 으로 읽어도 되는 이유는 하나뿐이다: cmd_before 가 keys 게이지로
    #    <지표 내보내기 자체가 살아 있다>를 이미 확인하고 나서야 이 판이 시작된다.
    #    그래서 이 자리의 부재는 "계측이 안 붙었다" 가 아니라 "그 태그 조합이 아직 한 번도
    #    안 쓰였다" = 거절 0건이다. 그 가드가 없어지면 이 줄의 근거도 같이 없어진다.
    delta = (a or 0.0) - (b or 0.0)
    if delta < 0:
        out.append((False,
            f"무효: 거절 카운터가 {b} → {a} 로 <줄었다>. 단조 증가해야 하는 값이 줄었다는 것은 "
            f"측정 중에 Spring 이 재기동됐다는 뜻이다. 이 판을 처음부터 다시 돌릴 것."))
        return out
    if abs(delta - expected) < 1e-9:
        out.append((True,
            f"OK   제한기가 센 거절 {delta:.0f}건 = k6 가 받은 429 {expected}건 (정확히 일치). "
            f"사전 확인 요청은 404 로 끝나 거절을 만들지 않으므로 여기에 여유를 두지 않는다."))
    else:
        out.append((False,
            f"무효: 제한기가 센 거절은 {delta:.0f}건인데 k6 는 429 를 {expected}건 받았다. "
            f"둘이 다르면 429 를 낸 주체가 제한기가 아닌 것(앞단 프록시 등)이거나, "
            f"거절이 났는데 k6 가 그 응답을 못 받은 것이다. 어느 쪽이든 이 판의 숫자를 "
            f"제한기 정확성의 근거로 쓸 수 없다."))
    return out


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


def ratelimit_readings(text: str) -> dict[str, float | None]:
    """제한기 쪽 시계열 셋을 한 <번의 노출>에서 함께 읽는다. before 와 after 가 같은 함수를 쓴다.

    셋을 함께 읽는 이유: 하나(거절 증가분)를 믿으려면 나머지 둘이 <없어야> 한다.
    근거는 judge_ratelimit_axis 주석에 있다.

    노출 본문을 인자로 받는 이유: 같은 스냅샷에서 셋을 읽어야 한다. 시계열마다 따로
    긁으면 그 사이에 요청이 들어와 셋이 서로 다른 시점을 가리킬 수 있다.
    """
    return {
        # 본 축. mode="check" 는 카운터를 올린 뒤 난 거절이고, 위젯 채팅이 낼 수 있는 유일한 모드다.
        "rejected_check": parse_prom_counter(text, M_REJECTED, {**BUCKET_WIDGET, "mode": "check"}),
        # 있으면 본 축이 덜 센다. 위젯 채팅에는 없어야 한다.
        "rejected_blocked": parse_prom_counter(text, M_REJECTED, {**BUCKET_WIDGET, "mode": "blocked"}),
        # 원리적으로 생길 수 없는 시계열. <없음>을 확인하는 데 쓴다.
        "recorded": parse_prom_counter(text, M_RECORDED, BUCKET_WIDGET),
    }


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
    # 🔴 `is None` 하나로는 <계측이 죽어 NaN 인 것>을 못 잡는다. float("NaN") 이 예외를
    #    내지 않아 그대로 통과하기 때문이다. 파서가 이제 그것을 예외로 갈라주므로
    #    여기서 <없다>와 <죽었다>를 각각 안내한다. 손쓸 곳이 다르다.
    try:
        keys_gauge = parse_prom_counter(text, "alldap_ratelimit_keys", {})
    except MetricUnreadable as exc:
        raise SystemExit(
            f"중단: alldap_ratelimit_keys 게이지는 <있는데> 값을 못 읽었다. ({exc}) "
            "포트나 내보내기 문제가 아니라 게이지 쪽이다. 이 상태로는 '거절 0' 과 "
            "'계측이 안 붙었다' 를 구별할 수 없으므로 이 판을 시작하지 말 것."
        ) from exc
    if keys_gauge is None:
        raise SystemExit(
            "중단: alldap_ratelimit_keys 게이지가 없다. management 포트(8081)가 아니거나 "
            "지표 내보내기가 꺼져 있다. 이 게이지가 없으면 '거절 0' 과 '계측이 안 붙었다' 를 "
            "구별할 방법이 사라진다(핸드오프 §6-ⓓ)."
        )
    readings_before = ratelimit_readings(text)

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
        #    그리고 열지 않는다. 한도 숫자 하나를 읽으려고 DB 접속 문자열·JWT 시크릿이
        #    같은 응답에 실리는 경로를 만드는 셈이다. 설계서 §5-② 가 근거다.
        "widget_chat_per_minute": {"value": args.limit, "source": "driver"},
        # 한도를 못 물어보는 대신, 제한기가 <실제로 몇 건을 거절했는가>를 다른 축에서 본다.
        "ratelimit_readings_before": readings_before,
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

    verdicts = [("OK   " if ok else "") + reason]

    # 🔴 옛 컨텍스트 파일과 <시계열이 없었다>를 뭉개지 않는다. 필드가 통째로 없는 것은
    #    "그때는 안 읽었다" 이고, 읽어서 None 인 것은 "그 시계열이 없었다" 다. 손쓸 곳이 다르다.
    readings_before = context.get("ratelimit_readings_before")
    if readings_before is None:
        print("중단: 이 컨텍스트 파일에는 ratelimit_readings_before 가 없다. 2026-09-12 이전 "
              "드라이버가 만든 파일이라 제한기 쪽 전값을 아예 안 읽었다. "
              "같은 run-id 로 before 를 다시 돌려 컨텍스트를 새로 만든 뒤 이 판을 다시 측정할 것.")
        return 1

    readings_after = ratelimit_readings(_actuator_text(context["actuator_base"]))
    for axis_ok, axis_why in judge_ratelimit_axis(counts, readings_before, readings_after):
        verdicts.append(axis_why)
        if not axis_ok:
            ok = False

    result = {
        "run_id": args.run_id,
        "round": context["round"],
        "finished_at": datetime.now().isoformat(timespec="milliseconds"),
        "limit": context["widget_chat_per_minute"],
        "counts": {str(k): v for k, v in counts.items()},
        "expected_total": context["expected_total"],
        "expected_pass": context["expected_pass"],
        "ratelimit_readings_before": readings_before,
        "ratelimit_readings_after": readings_after,
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


def build_parser() -> argparse.ArgumentParser:
    """인자 정의를 main 에서 떼어낸다. s3_check.py 가 <기본값>을 단언할 수 있게 하려는 것이다.

    🔴 왜 기본값이 검사 대상인가: --headroom-ms 는 기본값 20000 으로 두고 실사용은 전부
       60000 이었다(A·B·C 판 전부). 기본값과 실사용이 다르면 그 기본값은 거짓말이고,
       다음 사람은 거짓말을 쓴다. 코드 안에 있는 값을 고쳐놓기만 하면 누가 되돌려도
       아무 일이 안 나므로, 검사로 못박는다.
    """
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
    # 🔴 기본값 60000 = 윈도우 하나를 통째로 비우는 값이다. A·B·C 판을 실제로 전부
    #    이 값으로 돌렸다(핸드오프 2026-09-11-3 §3-④). 20000 이던 옛 기본값은
    #    <아무도 쓰지 않는 값>이었고, 기본값과 실사용이 다르면 그 기본값은 거짓말이다.
    #
    #    위험은 "시간이 모자란다" 쪽이 아니다. 100건이 329ms 에 끝나므로 60배 여유다.
    #    반대편이 진짜 위험이었다: cmd_before 는 가짜 키 사전 확인 요청 1건을 <먼저>
    #    보내고 나서 경계 정렬을 한다. 여유가 20초면 그 1건과 같은 윈도우에서 k6 가
    #    시작할 수 있고, 그러면 그 1건이 한도 20 중 하나를 먹어 통과분이 19건이 된다
    #    = 제한기가 정확한데도 판정이 실패한다(거짓 실패).
    #    60000 을 주면 항상 새 윈도우에서 시작하므로 그 1건이 카운터에서 빠진다.
    parser.add_argument("--headroom-ms", type=int, default=60_000)
    parser.add_argument("--k6-summary")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    if args.phase == "before":
        return cmd_before(args)
    if not args.k6_summary:
        print("중단: after 에는 --k6-summary 가 필요하다.")
        return 1
    return cmd_after(args)


if __name__ == "__main__":
    sys.exit(main())
