"""S4(장애 주입) 실행의 주입 제어 · 회복 확인 · 시작 조건 · 판정.

실행:
    # 판마다 한 번씩. F1 · F2 · F3.
    cd ai-service && .venv/bin/python -m loadtest.s4_context before \\
        --run-id 2026-09-11-F1 --round F1 --password '...'

    # (k6 를 띄운 뒤, 정상 60초가 지나면 주입을 켜고 90초 뒤 끈다)
    cd ai-service && .venv/bin/python -m loadtest.s4_context inject \\
        --run-id 2026-09-11-F1 --round F1

    cd ai-service && .venv/bin/python -m loadtest.s4_context clear \\
        --run-id 2026-09-11-F1

    cd ai-service && .venv/bin/python -m loadtest.s4_context after \\
        --run-id 2026-09-11-F1 --round F1 \\
        --k6-summary loadtest/results/S4-2026-09-11-F1.json

    cd ai-service && .venv/bin/python -m loadtest.s4_context recover \\
        --run-id 2026-09-11-F1

🔴 순서는 before → inject → clear → <after> → recover 다. 2026-09-12 에 바뀌었다
─────────────────────────────────────────────────────────────────────────────
그전에는 clear → recover → after 였다. 그러면 recover 가 서킷을 닫으려고 <직접 만드는>
성공 1건이 after 의 스냅샷에 들어간다. 실제로 F3 의 success 증가분이 1,800 이 아니라
1,801 이었고, 원리적으로는 transition(to=closed) 한 건도 함께 섞인다.
판정은 전부 "늘었나 / 0인가" 라 결론이 뒤집히지는 않았지만, 숫자를 그대로 인용하면
1씩 어긋난다. <측정하는 도구가 측정 대상을 만들어내는> 모양이라 부류 자체가 나쁘다.

그래서 순서를 바꾸고, 순서를 절차가 아니라 <코드로> 못박았다: cmd_recover 는 그 run_id 의
verdict 파일(= after 가 이미 돌았다는 증거)이 없으면 거부한다. 절차로만 지키는 규칙은
빠뜨려도 아무 일이 안 일어나므로 언젠가 빠뜨린다. 봇 소유권을 "검사" 하지 않고 조회 쿼리에
못박은 것(findByIdAndUserId)과 같은 이유다.

설계서: docs/superpowers/specs/2026-09-11-loadtest-pr4b-s4-fault-injection-design.md

무엇을 하는 파일인가
─────────────────────────────────────────────────────────────────────────────
S4 는 "약속대로 실패하는가" 를 재는 시나리오다. 약속 셋이 코드와 주석에 적혀 있다:
재시도는 연결 실패에만 / 서킷은 5회 연속에 열리고 30초 뒤 닫힌다 / 급속 503 과
느린 503 이 지표에서 갈린다. 그리고 넷째로 <약속이 아예 없는 자리> 하나를 드러낸다.

🔴 회복을 시간이 아니라 <상태>로 확인한다
─────────────────────────────────────────────────────────────────────────────
운영 코드에 서킷 리셋 경로가 없다(reset() 은 테스트 전용). 닫는 유일한 방법은 30초가
지난 뒤 성공 한 건이다. "40초쯤 기다리면 되겠지" 로 넘어가면 <닫혔는지 모른 채> 다음
판을 시작하게 되고, 앞 판의 서킷이 다음 판 숫자를 오염시킨다.

⚠️ 그 확인을 Prometheus(9090)에 묻지 않고 /actuator/prometheus 를 직접 긁는다.
   circuit_state 는 게이지라 15초 스크레이프가 어긋나면 <사실이 통째로 사라진다>.
   #112 가 전이 카운터를 함께 둔 이유가 그것이고, 여기서는 아예 원본을 본다.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

# 파서는 loadtest/promtext.py 한 벌만 있다. 여기서 import 해 <이 모듈의 이름으로도>
# 남겨두므로, 이 파일에서 parse_prom_counter 를 가져다 쓰던 곳(s3_check · s4_check)은
# 한 줄도 고치지 않아도 그대로 돈다.
from loadtest.account import env_email, env_password
from loadtest.promtext import MetricUnreadable, parse_prom_counter


RESULTS = Path(__file__).parent / "results"

WATCHED_STATUS = [200, 0, 422, 429, 500, 502, 503, 504]

# AiServiceMetrics.Outcome 의 <태그 값>이다. enum 이름이 아니다.
#
# 🔴 PYTHON_SERVER_ERROR 의 태그가 "python_server_error" 가 아니라 "python_5xx" 다.
#    이름으로 유추하면 틀리는 자리라, 실제 값을 옮겨 적고 여기 근거를 남긴다.
#    (#112 가 enum 을 둔 이유와 같다. 문자열을 손으로 쓰면 오타 한 글자에 시계열이 갈린다)
OUTCOME_SUCCESS = "success"
OUTCOME_CIRCUIT_OPEN = "circuit_open"
OUTCOME_CONNECT_FAILURE = "connect_failure"
OUTCOME_PYTHON_5XX = "python_5xx"
ALL_OUTCOMES = [
    OUTCOME_SUCCESS, OUTCOME_CIRCUIT_OPEN, OUTCOME_CONNECT_FAILURE, "read_timeout",
    "connection_lost", OUTCOME_PYTHON_5XX, "python_4xx", "answer_incomplete", "decode_error",
]

ROUNDS: dict[str, dict] = {
    "F1": {
        "fault": None,      # 가짜 CF 가 아니라 uvicorn 을 죽인다. 코드 0줄.
        "why": "Python 프로세스 종료: 연결 실패 · 재시도 · 서킷 개폐",
        "how": "uvicorn 에 SIGTERM 을 보내고, 주입 구간이 끝나면 다시 띄운다(사람이 한다).",
    },
    "F2": {
        "fault": "error_all",
        "why": "Python 5xx: 재시도가 <안> 도는 것이 산출물",
        "how": "가짜 CF 가 모든 모델 호출에 500 을 낸다.",
    },
    "F3": {
        "fault": "error_rerank",
        "why": "rerank 조용한 실패: 모든 외부 신호가 안 바뀌는 것이 산출물",
        "how": "가짜 CF 가 리랭커 호출에만 500 을 낸다. 지연은 그대로 유지한다.",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# 순수 함수: 서버도 시계도 안 탄다. s4_check.py 가 이것들만 시험한다.
# (파서 parse_prom_counter 도 순수 함수지만 s3 와 공용이라 promtext.py 에 있다)
# ─────────────────────────────────────────────────────────────────────────────

def read_circuit_state(prom_text: str) -> tuple[str, float | None]:
    """지표 본문에서 서킷 상태를 읽는다.
    ("closed"|"half_open"|"open"|"unknown"|"unreadable", 값).

    🔴 시계열이 없을 때 "closed" 를 돌려주면 안 된다. 그건 <닫혔다> 가 아니라
       <못 읽었다> 이고, 둘을 뭉개면 "회복을 확인했다" 고 믿은 채 다음 판을 시작한다.
       AGENTS.md 의 "낸 버그" 절이 모아둔 부류를 회복 확인에서 다시 밟는 셈이 된다.

    🔴 그리고 <없다>(unknown)와 <값이 NaN 이다>(unreadable)도 갈라 돌려준다. 판정은
       어느 쪽이든 "못 읽었다" 로 같지만 <사람이 손쓸 곳>이 다르다. 없는 것은 management
       포트(8081)나 지표 내보내기 문제고, NaN 은 게이지 값 함수가 던지거나 참조가 끊긴
       것이다. 고치기 전에는 둘 다 unknown 이라, 안내가 "시계열이 없다" 고 단언하면서
       실제로는 시계열이 멀쩡히 있는 경우가 생겼다.
    """
    try:
        value = parse_prom_counter(prom_text, "alldap_ai_circuit_state", {})
    except MetricUnreadable:
        return "unreadable", None
    if value is None:
        return "unknown", None
    return {0.0: "closed", 1.0: "half_open", 2.0: "open"}.get(value, "unknown"), value


def recover_gate_reason(verdict_exists: bool, run_id: str) -> str | None:
    """recover 를 지금 돌려도 되는가. 돌려도 되면 None, 안 되면 <안내 문구>를 돌려준다.

    🔴 왜 이것이 필요한가: recover 는 서킷을 닫으려고 성공 한 건을 <직접 만든다>.
       그 건수가 after 스냅샷에 들어가면 측정값이 1 어긋난다(2026-09-12 수정 전에
       F3 의 success 증가분이 실제로 1,801 이었다). after 가 먼저 돌았다는 증거는
       verdict 파일의 존재뿐이라, 그것으로 관문을 만든다.

    🔴 왜 순수 함수로 뽑았는가: 이 판정이 cmd_recover 안에 섞여 있으면 서버 셋을 띄우지
       않고는 시험할 수 없고, 시험할 수 없는 가드는 <있다고 믿는 가드>가 된다.
       이 저장소가 두 번 데인 자리다(redirect.check.ts · Forwarded 점검 명령).
       s4_check.py 가 양쪽 분기를 다 시험한다.
    """
    if verdict_exists:
        return None
    return (
        f"중단: {run_id} 의 verdict 파일이 없다. recover 보다 after 를 먼저 돌려야 한다.\n"
        f"  이유: recover 는 서킷을 닫으려고 채팅 성공 1건을 직접 만든다. after 를 나중에 "
        f"돌리면 그 1건이 스냅샷에 섞여 success 증가분이 1 커진다.\n"
        f"  할 일: `s4_context after --run-id {run_id} --k6-summary loadtest/results/S4-{run_id}.json` "
        f"를 먼저 돌린 뒤 이 명령을 다시 실행할 것.\n"
        f"  (after 를 건너뛰고 싶더라도 건너뛸 수 없다. recover 는 다음 판으로 넘어가는 "
        f"유일한 관문이고, 이 판의 판정이 없으면 다음 판이 무엇 위에 얹히는지 알 수 없다.)"
    )


def judge_fault_round(round_name: str, before: dict, after: dict, k6_counts: dict) -> tuple[bool, list[str]]:
    """한 판의 기대 지표 변화를 전부 대조한다.

    before/after 는 아래 모양이다(둘 다 collect_signals 가 만든다):
        {"outcomes": {태그: float|None}, "retry": float|None, "transitions": {to: float|None},
         "fault_injected": int|None}
    k6_counts 는 {"normal": {상태코드: int}, "inject": {상태코드: int}} 다.

    돌려주는 것은 (성패, 사유들). 사유는 <전부> 돌려준다. 첫 실패에서 멈추면 다른
    신호가 어땠는지를 잃고, 그러면 왜 실패했는지를 다시 돌려봐야 알 수 있다.
    """
    reasons: list[str] = []
    ok = True

    def delta(kind: str, key: str) -> float | None:
        """after - before. 둘 중 하나라도 <시계열이 없다>면 None 이 아니라 규칙이 있다."""
        a = after.get(kind, {}).get(key) if kind != "retry" else after.get("retry")
        b = before.get(kind, {}).get(key) if kind != "retry" else before.get("retry")
        if a is None:
            # after 에도 없다 = 그 태그 조합이 실행 내내 한 번도 안 쓰였다 = 0 이다.
            # 🔴 Micrometer 는 태그 조합이 <처음 쓰일 때> 미터를 만든다. 그래서 after 의
            #    부재는 "안 일어났다" 로 읽는 것이 맞다. before 의 부재와 뜻이 다르다.
            return 0.0
        return a - (b or 0.0)

    def fail(msg: str) -> None:
        nonlocal ok
        ok = False
        reasons.append("실패: " + msg)

    spec = ROUNDS.get(round_name)
    if spec is None:
        return False, [f"무효: 모르는 판 이름 {round_name!r} (아는 것: {sorted(ROUNDS)})"]

    normal = k6_counts.get("normal") or {}
    inject = k6_counts.get("inject") or {}
    if not normal or not inject:
        return False, ["무효: k6 요약에 normal·inject 구간이 둘 다 있어야 한다. "
                       "phase 태그가 안 붙었거나 한 구간이 통째로 비었다."]

    # ── 모든 판에 공통: 대조군이 살아 있는가 ──────────────────────────────
    #
    # 🔴 이것이 <맨 앞>에 있어야 하는 이유가 F3 다. F3 의 통과 조건은 "지표가 안
    #    움직인다" 인데, 계측이 아예 안 붙어도 똑같이 안 움직인다. 정상 구간에 신호가
    #    있었다는 것을 먼저 확인해야 "안 잡힌다" 가 성립한다(설계서 §5-③).
    if normal.get(200, 0) <= 0:
        fail("대조군이 없다. 정상 구간에 200 이 한 건도 없다. 주입 전부터 뭔가 잘못된 것이라, "
             "이 실행으로는 '주입 때문에 바뀌었다' 를 말할 수 없다. "
             "특히 F3 은 <지표가 안 움직이는 것>이 통과 조건이라, 대조군 없이는 "
             "'안 잡힌다' 와 '계측이 죽었다' 가 구별되지 않는다.")
    else:
        reasons.append(f"OK   대조군 살아 있음. 정상 구간 200 {normal[200]}건")

    fallback_total = k6_counts.get("fallback_total", 0)
    if fallback_total:
        fail(f"fallback 이 {fallback_total}건이다. 그 요청들은 게이트에 걸려 LLM 경로를 "
             f"안 탔고, 재려던 실패 처리도 안 지났다.")

    # ── 판별 판정 ────────────────────────────────────────────────────────
    if round_name == "F1":
        connect = delta("outcomes", OUTCOME_CONNECT_FAILURE)
        circuit = delta("outcomes", OUTCOME_CIRCUIT_OPEN)
        retry = delta("retry", "retry")
        opened = delta("transitions", "open")
        if connect <= 0:
            fail(f"connect_failure 가 {connect:.0f} 다. Python 이 정말 죽었는지 확인할 것.")
        else:
            reasons.append(f"OK   연결 실패 {connect:.0f}건")
        if retry <= 0:
            fail(f"재시도가 {retry:.0f}회다. 연결 실패에는 재시도가 <돌아야> 한다 "
                 f"(retry-max-attempts 2). 안 돌면 AiServiceClient.isConnectFailure 가 "
                 f"ConnectException 을 못 알아본 것이다.")
        else:
            reasons.append(f"OK   재시도 {retry:.0f}회: 연결 실패에는 재시도가 돈다")
        if circuit <= 0:
            fail("circuit_open 이 0 이다. 서킷이 한 번도 안 열렸다면 5회 연속 실패가 "
                 "안 쌓였다는 뜻이라, 주입 구간이 너무 짧았거나 부하가 모자랐다.")
        else:
            reasons.append(f"OK   서킷 열린 뒤 급속 거절 {circuit:.0f}건")
        # 🔴 톱니. 30초마다 HALF_OPEN 이 되어 무리가 통과하고 다시 열리는 것이
        #    1순위 가설이다. 90초 주입이면 2회 이상이어야 한다.
        if opened >= 2:
            reasons.append(f"OK   서킷이 {opened:.0f}회 열렸다. 30초 톱니가 재현됐다")
        elif opened == 1:
            reasons.append("참고: 서킷이 1회만 열렸다. 톱니는 안 보인다. 주입 구간을 늘려 "
                           "다시 볼 것(90초면 2~3회가 기대값이다).")
        else:
            fail(f"circuit transition(to=open) 이 {opened:.0f} 다. 급속 거절은 있는데 "
                 f"열린 기록이 없다면 전이 카운터 계측을 의심할 것.")

    elif round_name == "F2":
        py5xx = delta("outcomes", OUTCOME_PYTHON_5XX)
        retry = delta("retry", "retry")
        if py5xx <= 0:
            fail(f"python_5xx 가 {py5xx:.0f} 다. 가짜 CF 의 500 이 FastAPI 500 으로 "
                 f"이어지지 않았다. /fault 가 실제로 켜졌는지 확인할 것.")
        else:
            reasons.append(f"OK   Python 5xx {py5xx:.0f}건")
        # 🔴 이 판을 넣은 유일한 이유다. 여기가 이 PR 에서 유일하게 <반증 가능한> 주장이고,
        #    틀렸다면 LLM 중복 과금이 실재한다는 뜻이라 곧바로 수정 슬라이스가 된다.
        if retry == 0:
            reasons.append("OK   재시도 0회: 5xx 에는 재시도가 안 돈다(중복 과금이 없다)")
        else:
            fail(f"🔴 재시도가 {retry:.0f}회 돌았다. 5xx 는 요청이 Python 에 <도달했다>는 "
                 f"뜻이라 재시도하면 문서 행이 중복되거나 LLM 이 두 번 과금된다. "
                 f"AiServiceClient 주석이 단언하는 약속이 깨진 것이다.")

    elif round_name == "F3":
        # 🔴 여기는 <아무것도 안 바뀌는 것>이 통과다. 그래서 위의 대조군 검사가 없으면
        #    이 판정은 계측이 죽은 경우와 구별되지 않는다.
        injected = after.get("fault_injected")
        injected_before = before.get("fault_injected")
        if injected is None or injected_before is None:
            fail("가짜 CF 의 fault.injected 를 못 읽었다. 주입이 실제로 일어났다는 "
                 "증거가 없으면 '안 잡힌다' 는 주장 자체가 성립하지 않는다.")
        elif injected - injected_before <= 0:
            fail(f"fault.injected 가 안 늘었다({injected_before} → {injected}). "
                 f"리랭커 호출에 500 이 한 번도 안 나갔다는 뜻이다.")
        else:
            reasons.append(f"OK   가짜 CF 가 리랭커 500 을 {injected - injected_before}건 냈다")

        bad_inject = {c: n for c, n in inject.items() if c != 200 and n > 0}
        if bad_inject:
            fail(f"주입 구간에 200 외의 상태코드가 있다: {bad_inject}. F3 은 리랭킹 실패가 "
                 f"200 으로 나가는 것을 보이는 판이라, 다른 코드가 섞이면 다른 장애가 함께 난 것이다.")
        else:
            reasons.append(f"OK   주입 구간이 전부 200 ({inject.get(200, 0)}건): 상태코드가 안 바뀐다")

        moved = {name: delta("outcomes", name) for name in ALL_OUTCOMES if name != OUTCOME_SUCCESS}
        moved = {k: v for k, v in moved.items() if v > 0}
        if moved:
            fail(f"실패 outcome 이 움직였다: {moved}. F3 은 어떤 지표에도 안 잡히는 것이 "
                 f"산출물이라, 잡혔다면 그건 <좋은 소식>이지만 이 판의 전제가 달라진 것이다.")
        else:
            reasons.append("OK   실패 outcome 이 하나도 안 움직였다. 어떤 숫자에도 안 잡힌다")

        reasons.append(
            "🔴 이 판의 '통과' 는 좋은 일이 아니다. <장애가 보이지 않는다는 것이 확인됐다> 는 뜻이다. "
            "드러내는 신호는 uvicorn 로그의 '리랭킹 실패(원래 순서 유지)' 줄뿐이다."
        )

    return ok, reasons


# ─────────────────────────────────────────────────────────────────────────────
# 서버를 타는 부분
# ─────────────────────────────────────────────────────────────────────────────

def _context_path(run_id: str) -> Path:
    return RESULTS / f"S4-{run_id}-context.json"


def _verdict_path(run_id: str) -> Path:
    return RESULTS / f"S4-{run_id}-verdict.json"


def _prom(actuator: str) -> str:
    resp = httpx.get(f"{actuator}/actuator/prometheus", timeout=10.0)
    resp.raise_for_status()
    return resp.text


def read_python_runtime(python_metrics: str) -> dict:
    """측정 대상 <Python 프로세스>의 스레드풀 조건을 읽는다.

    🔴 설정값과 실측값을 <따로> 적는다. 둘을 하나로 적으면 "설정을 40 으로 줬다" 와
       "그 프로세스가 실제로 40 이었다" 가 뭉개진다. 손쓸 곳이 다르다: 앞은 셸을
       고치는 것이고 뒤는 lifespan 이 안 돈 것이다.

    🔴 app/metrics_check.py ⑤ 로는 이걸 대신할 수 없다. 그 검사는 로컬 TestClient 의
       lifespan 을 보는 것이지 <지금 8001 을 듣고 있는 프로세스>를 보는 것이 아니다.

    못 읽으면 None 이 아니라 error 를 남긴다. "안 읽었다" 와 "읽었더니 없더라" 는
    다른 사실이고, 판을 폐기할지 결정하는 근거가 달라진다.
    """
    block: dict = {
        "metrics_url": python_metrics,
        # 🔴 이것은 <드라이버 셸>의 환경변수다. 측정 대상 프로세스의 설정이 아니다.
        #    uvicorn 을 다른 셸에서 띄웠으면 여기가 null 인 것이 정상이고, 그때도
        #    아래 실측값은 40 일 수 있다. 이름에 of_driver 를 박아두지 않으면
        #    "설정이 안 먹었다" 로 오독된다. 판정에 쓰는 것은 <실측값>뿐이다.
        "anyio_max_threads_env_of_driver": os.environ.get("ANYIO_MAX_THREADS"),
        "anyio_threads_total_observed": None,
        "error": None,
    }
    try:
        resp = httpx.get(python_metrics, timeout=10.0)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001 - 원인을 그대로 남기는 것이 목적이다
        block["error"] = f"지표를 못 받았다: {exc!r}"
        return block
    try:
        block["anyio_threads_total_observed"] = parse_prom_counter(
            resp.text, "alldap_anyio_threads_total", {}
        )
    except MetricUnreadable as exc:
        block["error"] = f"alldap_anyio_threads_total 은 <있는데> 값을 못 읽었다: {exc}"
    return block


def collect_signals(actuator: str, cf_base: str | None, operation: str = "chat") -> dict:
    """판정에 쓰는 신호를 한 번에 모은다. before 와 after 가 같은 함수를 쓴다.

    같은 함수로 모으는 이유: 전후를 다르게 모으면 비교가 성립하지 않는다.
    (S1 이 손으로 적은 질문과 테이블 문항이 16건 중 0건 일치였던 것과 같은 부류다)
    """
    text = _prom(actuator)
    state, raw = read_circuit_state(text)
    signals = {
        "outcomes": {
            name: parse_prom_counter(text, "alldap_ai_call_seconds_count",
                                     {"operation": operation, "outcome": name})
            for name in ALL_OUTCOMES
        },
        "retry": parse_prom_counter(text, "alldap_ai_retry_total", {"operation": operation}),
        "transitions": {
            to: parse_prom_counter(text, "alldap_ai_circuit_transition_total", {"to": to})
            for to in ("open", "closed", "half_open")
        },
        "circuit_state": state,
        "circuit_state_raw": raw,
        "fault_injected": None,
    }
    if cf_base:
        try:
            stats = httpx.get(f"{cf_base}/stats", timeout=10.0).json()
            signals["fault_injected"] = int((stats.get("fault") or {}).get("injected", 0))
            signals["fault_mode"] = (stats.get("fault") or {}).get("mode")
        except Exception as exc:   # noqa: BLE001 - 못 읽은 것과 0 을 구별해 남긴다
            signals["fault_error"] = f"{type(exc).__name__}: {exc}"
    return signals


def wait_circuit_closed(actuator: str, timeout_s: int = 120, interval_s: float = 2.0) -> tuple[bool, str]:
    """서킷이 닫힐 때까지 기다린다. 시간이 아니라 <상태>로 판정한다.

    ⚠️ 닫히는 유일한 방법은 30초가 지난 뒤 <성공 한 건>이다. 부하가 멈춘 상태에서는
       아무도 성공시키지 않으므로 영원히 HALF_OPEN 에 머문다. 그래서 부르는 쪽이
       채팅 1건을 태운 <뒤에> 이 함수를 부른다(cmd_recover 가 그렇게 한다).
    """
    deadline = time.time() + timeout_s
    last = "unknown"
    while time.time() < deadline:
        state, raw = read_circuit_state(_prom(actuator))
        last = state
        if state == "closed":
            return True, f"서킷이 닫혔다 (alldap_ai_circuit_state={raw})"
        if state == "unknown":
            return False, ("중단: alldap_ai_circuit_state 시계열이 없다. <닫혔다> 가 아니라 "
                           "<못 읽었다> 이다. management 포트(8081)와 지표 내보내기를 확인할 것.")
        if state == "unreadable":
            return False, ("중단: alldap_ai_circuit_state 는 <있는데> 값이 NaN 이다. 시계열이 "
                           "없는 것과 다른 문제다. 포트나 내보내기가 아니라 게이지 쪽이다. "
                           "Micrometer 는 게이지 값 함수가 예외를 던지거나 참조가 끊기면 NaN 을 "
                           "낸다. 이 상태로는 회복을 확인할 수 없으니 다음 판을 시작하지 말 것.")
        time.sleep(interval_s)
    return False, f"중단: {timeout_s}초 안에 서킷이 안 닫혔다 (마지막 상태 {last})."


def _set_fault(cf_base: str, mode: str, status: int = 500) -> dict:
    resp = httpx.post(f"{cf_base}/fault", json={"mode": mode, "status": status}, timeout=10.0)
    if resp.status_code != 200:
        raise SystemExit(f"중단: /fault 가 {resp.status_code} 를 냈다. body={resp.text[:300]}")
    return resp.json()


def cmd_before(args) -> int:
    spec = ROUNDS[args.round]

    client = httpx.Client(timeout=60.0)
    resp = client.post(f"{args.api}/api/auth/login",
                       json={"email": args.email, "password": args.password})
    resp.raise_for_status()
    token = resp.json()["token"]
    resp = client.get(f"{args.api}/api/bots", headers={"Authorization": f"Bearer {token}"})
    resp.raise_for_status()
    bots = resp.json()
    if not bots:
        raise SystemExit("중단: 이 계정에 봇이 없다.")
    bot = sorted(bots, key=lambda b: (-b["documentCount"], b["createdAt"]))[0]

    # 🔴 시작 전에 서킷이 닫혀 있어야 한다. 앞 판이 남긴 열린 서킷으로 시작하면
    #    이 판의 정상 60초가 대조군 노릇을 못 한다.
    state, raw = read_circuit_state(_prom(args.actuator))
    if state != "closed":
        raise SystemExit(
            f"중단: 시작 전 서킷이 {state} 다(값 {raw}). 앞 판의 서킷이 아직 안 닫혔거나 "
            f"지표를 못 읽었다. `s4_context recover` 를 먼저 돌릴 것."
        )

    # 주입 상태도 깨끗해야 한다. 앞 판의 주입이 남아 있으면 정상 구간이 정상이 아니다.
    signals = collect_signals(args.actuator, args.cf, args.operation)
    if signals.get("fault_mode") not in (None, "none"):
        raise SystemExit(
            f"중단: 가짜 CF 의 주입이 아직 {signals['fault_mode']} 다. "
            f"`s4_context clear` 로 끄고 다시 시작할 것."
        )

    context = {
        "run_id": args.run_id,
        "round": args.round,
        "round_why": spec["why"],
        "round_how": spec["how"],
        "fault_mode": spec["fault"],
        "commit": subprocess.run(["git", "rev-parse", "HEAD"],
                                 capture_output=True, text=True).stdout.strip(),
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "api_base": args.api,
        "actuator_base": args.actuator,
        "cf_base": args.cf,
        "operation": args.operation,
        "bot": {"id": bot["id"], "name": bot["name"], "document_count": bot["documentCount"]},
        "vus": args.vus,
        "normal_seconds": args.normal_s,
        "inject_seconds": args.inject_s,
        "signals_before": signals,
        # 🔴 이 판이 <어떤 스레드 상한에서> 돈 것인지. 설정값과 실측값을 따로 적는다.
        "python_runtime": read_python_runtime(args.python_metrics),
    }
    RESULTS.mkdir(exist_ok=True)
    _context_path(args.run_id).write_text(json.dumps(context, ensure_ascii=False, indent=2, default=str))
    print(json.dumps(context, ensure_ascii=False, indent=2, default=str))
    print(f"\n저장: {_context_path(args.run_id)}")
    print(f"\nBOT_ID={bot['id']}")
    print(f"RUN_ID={args.run_id}")
    print(f"ROUND={args.round}")
    print(f"NORMAL_S={args.normal_s}  INJECT_S={args.inject_s}  VUS={args.vus}")
    print(f"\n다음: k6 를 띄우고 {args.normal_s}초 뒤 `s4_context inject --run-id {args.run_id} "
          f"--round {args.round}` 를 실행할 것.")
    if spec["fault"] is None:
        print("⚠️ F1 은 가짜 CF 가 아니라 <uvicorn 을 죽이는> 판이다. inject 가 그 방법을 안내한다.")
    return 0


def cmd_inject(args) -> int:
    context = json.loads(_context_path(args.run_id).read_text())
    spec = ROUNDS[context["round"]]
    if spec["fault"] is None:
        print("F1: 가짜 CF 주입이 아니다. 지금 uvicorn 프로세스에 SIGTERM 을 보낼 것.")
        print(f"  예: pkill -f 'uvicorn app.main:app'      (주입 {context['inject_seconds']}초)")
        print("  끝나면 같은 명령으로 uvicorn 을 다시 띄우고, `s4_context after` 를 돌린 "
              "<뒤에> `s4_context recover` 를 돌린다.")
        return 0
    state = _set_fault(context["cf_base"], spec["fault"])
    print(f"주입 켬: {state}")
    print(f"{context['inject_seconds']}초 뒤 `s4_context clear --run-id {args.run_id}` 로 끌 것.")
    return 0


def cmd_clear(args) -> int:
    context = json.loads(_context_path(args.run_id).read_text())
    if ROUNDS[context["round"]]["fault"] is None:
        print("F1: 가짜 CF 주입이 아니다. uvicorn 을 다시 띄울 것.")
        print("  다음: after 를 먼저 돌리고(그 뒤에) recover 를 돌린다. "
              "recover 가 만드는 성공 1건이 after 스냅샷에 섞이지 않게 하려는 순서다.")
        return 0
    print(f"주입 끔: {_set_fault(context['cf_base'], 'none')}")
    print("다음: after 를 먼저 돌리고(그 뒤에) recover 를 돌린다. "
          "recover 가 만드는 성공 1건이 after 스냅샷에 섞이지 않게 하려는 순서다.")
    return 0


def cmd_recover(args) -> int:
    """서킷이 닫혔음을 <확인>한다. 다음 판으로 넘어가는 유일한 관문이다.

    ⚠️ after 보다 <뒤에> 돌아야 한다. 근거와 판정은 recover_gate_reason 에 있다.
    """
    context = json.loads(_context_path(args.run_id).read_text())

    # 🔴 순서를 코드로 못박는다. 이 검사가 없으면 순서는 사람의 기억에만 있다.
    gate = recover_gate_reason(_verdict_path(args.run_id).exists(), args.run_id)
    if gate:
        print(gate)
        return 1

    client = httpx.Client(timeout=130.0)
    resp = client.post(f"{context['api_base']}/api/auth/login",
                       json={"email": args.email, "password": args.password})
    resp.raise_for_status()
    token = resp.json()["token"]

    # 🔴 성공 한 건을 <직접 만든다>. 부하가 멈춘 상태에서는 아무도 서킷을 닫아주지 않는다.
    #    서킷이 열려 있으면 이 요청도 503 이므로, 30초가 지나 HALF_OPEN 이 될 때까지
    #    반복해서 두드린다.
    deadline = time.time() + args.recover_timeout
    while time.time() < deadline:
        r = client.post(
            f"{context['api_base']}/api/bots/{context['bot']['id']}/chat",
            json={"message": "S4 회복 확인용 질문입니다", "sessionId": f"s4-recover-{int(time.time())}"},
            headers={"Authorization": f"Bearer {token}"},
        )
        print(f"  회복 시도 → {r.status_code}")
        if r.status_code == 200:
            break
        time.sleep(5)

    ok, why = wait_circuit_closed(context["actuator_base"], timeout_s=60)
    print(("OK   " if ok else "") + why)
    return 0 if ok else 1


def _k6_counts(summary: dict) -> dict:
    metrics = summary.get("metrics", {}) or {}

    def phase_counts(phase: str) -> dict[int, int]:
        out: dict[int, int] = {}
        for code in WATCHED_STATUS:
            m = metrics.get(f"chat_status{{phase:{phase},status:{code}}}")
            # 🔴 여기서는 없는 키를 0 으로 읽어도 된다. s4_faults.js 가 감시 코드 전부에
            #    threshold 를 걸어 <0건이어도 키가 나오게> 해뒀고, 키가 통째로 없다면
            #    아래 "normal·inject 가 둘 다 있어야 한다" 검사에 먼저 걸린다.
            out[code] = int((m.get("values") or {}).get("count", 0)) if m else 0
        return out

    fb = 0
    for phase in ("normal", "inject"):
        m = metrics.get(f"chat_fallback{{phase:{phase}}}")
        fb += int((m.get("values") or {}).get("count", 0)) if m else 0
    return {"normal": phase_counts("normal"), "inject": phase_counts("inject"), "fallback_total": fb}


def cmd_after(args) -> int:
    context = json.loads(_context_path(args.run_id).read_text())
    summary = json.loads(Path(args.k6_summary).read_text())

    after = collect_signals(context["actuator_base"], context["cf_base"], context["operation"])
    k6 = _k6_counts(summary)
    ok, reasons = judge_fault_round(context["round"], context["signals_before"], after, k6)

    result = {
        "run_id": args.run_id,
        "round": context["round"],
        "round_why": context["round_why"],
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "k6_counts": {p: {str(k): v for k, v in c.items()} if isinstance(c, dict) else c
                      for p, c in k6.items()},
        "signals_before": context["signals_before"],
        "signals_after": after,
        "reasons": reasons,
        "valid": ok,
        "valid_means": (
            "이 판의 기대 신호 변화가 전부 맞았다는 뜻이다. F3 에서는 <아무것도 안 바뀌는 것>이 "
            "기대이므로, 통과가 곧 '결함이 재현됐다' 는 뜻이다."
        ),
    }
    _verdict_path(args.run_id).write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    print(f"\n저장: {_verdict_path(args.run_id)}")
    for r in reasons:
        print(f"  {r}")
    print(f"\n다음: `s4_context recover --run-id {args.run_id}` 로 서킷이 닫힌 것을 "
          f"상태로 확인한 뒤 다음 판을 시작할 것.")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="S4 장애 주입: 제어 · 회복 · 판정")
    parser.add_argument("phase", choices=["before", "inject", "clear", "recover", "after"])
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--round", choices=sorted(ROUNDS))
    parser.add_argument("--api", default="http://localhost:8080")
    parser.add_argument("--actuator", default="http://localhost:8081")
    parser.add_argument("--cf", default="http://127.0.0.1:9001")
    parser.add_argument("--operation", default="chat")
    parser.add_argument("--python-metrics",
                        default="http://127.0.0.1:8001/internal/metrics")
    # 계정 기본값은 환경변수에서 온다(loadtest/account.py 가 만든 측정 전용 계정).
    parser.add_argument("--email", default=env_email())
    parser.add_argument("--password", default=env_password())
    parser.add_argument("--vus", type=int, default=20)
    parser.add_argument("--normal-s", type=int, default=60)
    parser.add_argument("--inject-s", type=int, default=90)
    parser.add_argument("--recover-timeout", type=int, default=120)
    parser.add_argument("--k6-summary")
    args = parser.parse_args()

    if args.phase == "before":
        if not args.round:
            print("중단: before 에는 --round 가 필요하다.")
            return 1
        if not args.password:
            print("중단: before 에는 비밀번호가 필요하다. "
                  "LOADTEST_PASSWORD 를 넣거나 --password 로 넘길 것.")
            return 1
        return cmd_before(args)
    if args.phase == "inject":
        return cmd_inject(args)
    if args.phase == "clear":
        return cmd_clear(args)
    if args.phase == "recover":
        if not args.password:
            print("중단: recover 에는 비밀번호가 필요하다. "
                  "LOADTEST_PASSWORD 를 넣거나 --password 로 넘길 것.")
            return 1
        return cmd_recover(args)
    if not args.k6_summary:
        print("중단: after 에는 --k6-summary 가 필요하다.")
        return 1
    return cmd_after(args)


if __name__ == "__main__":
    sys.exit(main())
