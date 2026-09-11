"""가짜 Cloudflare Workers AI 서버. 부하테스트 전용.

실행:
    cd ai-service && .venv/bin/python -m loadtest.fake_cf                  # 게이트 통과 모드
    cd ai-service && .venv/bin/python -m loadtest.fake_cf --vector blocked  # 게이트 차단 모드
    cd ai-service && .venv/bin/python -m loadtest.fake_cf --vector unit     # DB 없이(자체 점검용)

왜 이게 필요한가
─────────────────────────────────────────────────────────────────────────────
근거 있는 질문 1건이 24.64 뉴런이다. 하루 한도 10,000 으로 <406건>밖에 못 한다.
초당 5건으로 2분만 돌려도 600건이라 하루치를 넘긴다.
즉 진짜 LLM 을 태우는 지속 부하는 <원리적으로 불가능>하다.

🔴 임베딩 벡터를 아무거나 주면 안 된다
─────────────────────────────────────────────────────────────────────────────
무작위 벡터를 돌려주면 DB 청크와의 거리도 무작위라, retriever.search 의
answerable_max_distance(0.44) 게이트에 걸려 <LLM 을 아예 안 부른다.>
그러면 재려던 생성 경로를 한 번도 안 타고 "빠르다" 는 거짓 결과가 나온다.

그래서 기동할 때 DB 에서 <진짜 청크 벡터 하나>를 읽어 그대로 돌려준다.
거리가 0 이 되어 게이트를 항상 통과한다.
반대로 그 벡터를 뒤집으면(--vector blocked) 거리가 최대라 항상 차단된다.
<모드 하나로 두 경로를 다 잰다.>
"""
from __future__ import annotations

import argparse
import json
import threading
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.config import get_settings

# 평가에 쓰는 봇(코퍼스 50문서 · 306청크). fallback_e2e_check 와 같은 값이다.
BOT_ID = "628d2785-a128-486c-a1ac-556f19f06de3"

# S1 실측값이다(2026-09-10, loadtest/results/S1-2026-09-10.json · 표본 327건).
# per_model[*].p50 을 반올림했다: 234.986 · 413.973 · 936.853.
#
# 🔴 p95 가 아니라 <p50> 을 쓴다.
#    가짜 서버가 재현해야 하는 것은 최악이 아니라 <보통>이다.
#    p95(752 · 754 · 3,211)를 넣으면 모든 요청이 최악의 시간을 쓰는,
#    실제로는 존재하지 않는 세상을 재게 된다.
#
# ⚠️ 한계: 이 세 값은 <고정 지연>이라 진짜 CF 의 성질 하나를 재현하지 못한다.
#    S1 실행 중 종단 p50 이 단조 상승했다(20건째 1,676ms → 320건째 1,779ms, +6%).
#    350건을 쉬지 않고 순차 호출한 결과인데, Cloudflare 스로틀인지 로컬 누적인지
#    이 데이터로는 못 가른다. 가짜 서버는 몇 건을 돌리든 같은 시간을 잔다.
#    → 장시간 부하에서 진짜 CF 와 수치가 벌어지면 <버그가 아니라 이것>일 수 있다.
LATENCY_MS = {"embed": 235, "rerank": 414, "generate": 937}

# 가짜 답변. 짧고, NO_ANSWER 를 포함하지 않는다(포함하면 전부 fallback 이 된다).
ANSWER = "부하테스트용 고정 답변입니다."

# 🔴 뉴런 0.0 은 <이 서버가 가짜라는 유일한 신호>다. 지우지 말 것.
#    s2_context.judge_fake_cf 가 측정을 시작하기 전에 이 값으로 판정한다:
#    워밍업 호출 뒤 뉴런이 늘면 uvicorn 이 진짜 Cloudflare 를 보고 있다는 뜻이라 중단시킨다.
#    여기서 0 이 아닌 값을 주기 시작하면 그 안전장치가 <조용히> 꺼진다.
#    (loadtest/fake_cf_check.py 가 회귀 검사로 이 사실을 잡는다)
_counts: Counter[str] = Counter()
_lock = threading.Lock()
_vector: list[float] = []

# 🔴 /stats 는 <이 프로세스가 실제로 어떤 설정으로 떠 있는지>를 말하는 자리다.
#    s2_context 가 시작 조건 파일에 적을 값을 여기서 읽어간다. 예전에는 이 모듈의
#    상수를 import 해서 적었는데, 그건 <드라이버 프로세스가 읽은 코드>일 뿐이라
#    다른 지연값으로 떠 있는 서버를 상대로도 그대로 통과했다.
#    설정 항목을 늘릴 때는 여기(_stats_payload)에도 함께 넣을 것.
_vector_mode: str = ""

# ── 장애 주입 (S4) ────────────────────────────────────────────────────
#
# 🔴 <런타임 제어면>이지 기동 옵션이 아니다. 한 판은 "정상 60초 → 주입 90초" 로 도는데,
#    기동 플래그로 만들면 주입할 때마다 서버를 다시 띄워야 하고 그러면 _counts 가
#    초기화된다. 실행 전후 counts 비교는 "그 경로를 실제로 탔는가" 를 가르는 장치라
#    (counts() 주석 참고), 그게 깨지면 측정 자체가 무효가 된다.
#
# 🔴 mode 를 불리언이 아니라 <문자열>로 둔다. error_all 과 error_rerank 는 서로 다른
#    사실이고, 불리언 둘로 두면 "둘 다 켠 상태" 라는 뜻이 없는 조합이 생긴다.
#
# 🔴 _injected 를 <센다>. F3 판(리랭킹 조용한 실패)의 "장애 N 건" 이 이 값이다.
#    이게 없으면 주입이 실제로 일어났다는 증거가 uvicorn 로그 줄 수밖에 없는데,
#    로그는 세기도 어렵고 유실되기도 한다.
#    counts 와 마찬가지로 <누적>이다. 판정은 전후 차이로 하므로(s4_context) 모드를
#    바꿀 때 0 으로 되돌리지 않는다 — 되돌리면 "안 늘었다" 와 "방금 초기화됐다" 가 뭉개진다.
FAULT_MODES = ("none", "error_all", "error_rerank")
_fault_mode: str = "none"
_fault_status: int = 500
_fault_injected: int = 0


def set_fault(mode: str, status: int = 500) -> dict:
    """장애 주입 상태를 바꾸고 바뀐 상태를 돌려준다. 유효성 검사는 호출부에서 끝낸다."""
    global _fault_mode, _fault_status
    with _lock:
        _fault_mode, _fault_status = mode, status
    return fault_state()


def fault_state() -> dict:
    with _lock:
        return {"mode": _fault_mode, "status": _fault_status, "injected": _fault_injected}


def _take_fault(kind: str) -> int | None:
    """이 호출을 주입 대상으로 판정하면 <상태 코드>를, 아니면 None 을 돌려준다.

    판정과 적립을 한 함수에서 <같은 락 안에> 하는 이유: 나눠 두면 모드가 바뀌는 순간
    "500 을 줬는데 injected 는 안 늘었다" 는 어긋난 상태가 나올 수 있다.
    그러면 F3 의 "장애 N 건" 이 실제 주입 건수와 달라진다.
    """
    global _fault_injected
    with _lock:
        hit = _fault_mode == "error_all" or (_fault_mode == "error_rerank" and kind == "rerank")
        if hit:
            _fault_injected += 1
            return _fault_status
    return None


def counts() -> Counter[str]:
    """모델별 호출 횟수. <실행 전후로 비교>해서 그 경로를 실제로 탔는지 본다.

    0 이면 그 경로를 안 탄 것이므로 그 측정은 무효다.
    """
    with _lock:
        return _counts.copy()


def _stats_payload() -> dict:
    """이 서버가 <실제로 떠 있는 설정>. 측정의 시작 조건으로 그대로 기록된다.

    🔴 벡터 모드가 여기 있어야 하는 이유: blocked 로 띄우면 모든 질문이 게이트에
       걸려 생성 경로를 아예 안 탄다. 지연값만 적어두면 나중에 그 실행이 <무엇을
       재고 있었는지>를 알 수 없다. 지연과 벡터 모드는 서로 다른 사실이라 따로 적는다.

    🔴 fault 블록이 여기 있는 이유(2026-09-11 에 약속대로 넣었다): 시작 조건 파일이
       "어떤 장애로 쟀는지" 를 말할 수 있어야 한다. 지연·벡터 모드와 마찬가지로
       <서로 다른 사실>이라 따로 적는다. injected 까지 함께 내보내는 것은, 그 값이
       0 이면 그 판이 무효라는 판정을 드라이버가 여기 하나만 읽고 내릴 수 있어서다.
    """
    return {
        "counts": dict(counts()),
        "latency_ms": dict(LATENCY_MS),
        "vector_mode": _vector_mode,
        "fault": fault_state(),
        # unit 모드는 DB 를 안 읽으므로 출처 봇이 없다. 0 이나 "" 로 뭉개지 않는다.
        "vector_bot_id": BOT_ID if _vector_mode in ("db", "blocked") else None,
    }


def _load_vector(mode: str) -> list[float]:
    s = get_settings()
    if mode == "unit":
        # DB 없이 도는 모드(자체 점검용). 차원만 맞다.
        return [1.0] + [0.0] * (s.embedding_dim - 1)

    from app.db import cursor  # DB 가 필요한 모드에서만 import 한다

    with cursor() as cur:
        cur.execute(
            "SELECT embedding FROM chunks WHERE bot_id=%s AND embedding IS NOT NULL LIMIT 1",
            (BOT_ID,),
        )
        row = cur.fetchone()
    if row is None:
        raise RuntimeError(
            f"봇 {BOT_ID} 에 임베딩된 청크가 없습니다. 코퍼스를 먼저 적재하세요 "
            f"(ai-service/testdata/corpus)."
        )
    vec = [float(x) for x in row[0]]
    # 뒤집으면 코사인 거리가 최대가 되어 answerable 게이트에 <항상> 걸린다.
    return [-x for x in vec] if mode == "blocked" else vec


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args) -> None:  # noqa: D102 - 부하 중 로그가 병목이 된다
        pass

    def _send(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path == "/stats":
            self._send(200, _stats_payload())
        else:
            self._send(404, {"success": False, "errors": ["없는 경로"]})

    def do_POST(self) -> None:
        if self.path == "/fault":
            self._fault()
            return
        if "/ai/run/" not in self.path:
            self._send(404, {"success": False, "errors": ["없는 경로"]})
            return
        model = self.path.split("/ai/run/", 1)[1]
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length) or b"{}")

        with _lock:
            _counts[model] += 1

        s = get_settings()
        if model == s.embedding_model:
            kind = "embed"
        elif model == s.reranker_model:
            kind = "rerank"
        else:
            kind = "generate"

        # 🔴 주입 여부를 <지연 전에> 정하지만 잠은 그대로 잔다. 500 을 즉시 주면 종단
        #    지연이 그 모델의 지연만큼(리랭커면 414ms) 빨라져서 "장애인데 빨라졌다" 가
        #    되고, 그러면 원인이 다른 두 사실(장애 · 지연 변화)이 한 숫자에 섞인다.
        #    이 저장소가 반복해 낸 버그가 정확히 그 부류다(AGENTS.md 의 "낸 버그" 절).
        #    지연을 유지해야 F3 판에서 <모든 외부 신호가 글자 하나 안 바뀌는 것>이 증명된다.
        fault_status = _take_fault(kind)
        time.sleep(LATENCY_MS[kind] / 1000)
        if fault_status is not None:
            # Cloudflare 가 5xx 를 줄 때의 모양을 흉내낸다. app.cf.run 의
            # raise_for_status() 가 여기서 예외를 던지는 것이 이 주입의 목적이다.
            self._send(fault_status, {"success": False, "errors": [
                {"code": 5000, "message": f"부하테스트 장애 주입 ({kind})"}]})
            return

        if kind == "embed":
            result = self._embedding(payload, s.embedding_dim)
        elif kind == "rerank":
            result = self._rerank(payload)
        else:
            result = self._generate()
        self._send(200, {"success": True, "result": result})

    def _fault(self) -> None:
        """POST /fault {"mode": ..., "status": ...} — 장애 주입 제어면.

        ⚠️ 잘못된 입력에 <조용히 기본값으로 떨어지지 않는다.> mode 오타를 "none" 으로
           받아주면 주입했다고 믿은 채 정상 90초를 재게 되고, 그 실행은 대조군과
           구분이 안 된다. 400 으로 되돌려 드라이버가 그 자리에서 멈추게 한다.
        """
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            self._send(400, {"success": False, "errors": ["JSON 본문이 아닙니다"]})
            return
        if not isinstance(payload, dict):
            self._send(400, {"success": False, "errors": ["JSON 객체여야 합니다"]})
            return

        mode = payload.get("mode", "none")
        status = payload.get("status", 500)
        if mode not in FAULT_MODES:
            self._send(400, {"success": False, "errors": [
                f"mode 는 {list(FAULT_MODES)} 중 하나여야 합니다 (받은 값: {mode!r})"]})
            return
        # bool 은 int 의 하위 타입이라 isinstance(True, int) 가 참이다. 따로 막는다.
        if isinstance(status, bool) or not isinstance(status, int) or not 400 <= status <= 599:
            self._send(400, {"success": False, "errors": [
                f"status 는 400~599 의 정수여야 합니다 (받은 값: {status!r})"]})
            return

        self._send(200, set_fault(mode, status))

    @staticmethod
    def _embedding(payload: dict, dim: int) -> dict:
        texts = payload.get("text")
        n = len(texts) if isinstance(texts, list) else 1
        # meta.neurons 인 것에 주의. 임베딩만 usage 가 아예 없다(cf._record_neurons 참고).
        return {"data": [list(_vector) for _ in range(n)], "meta": {"neurons": 0.0}}

    @staticmethod
    def _rerank(payload: dict) -> dict:
        n = len(payload.get("contexts") or [])
        # 순서를 바꾸지 않는다. 부하테스트가 재는 것은 <시간>이지 순위가 아니다.
        return {
            "response": [{"id": i, "score": 1.0 - i * 0.01} for i in range(n)],
            "usage": {"neurons": 0.0},
        }

    @staticmethod
    def _generate() -> dict:
        # 🔴 두 형식을 <둘 다> 준다. cf.text_of 가 둘 다 훑기 때문이다.
        #    한쪽만 주면 지금은 돌지만, 파서를 고치는 순간 조용히 깨진다.
        return {
            "response": ANSWER,
            "choices": [{"message": {"content": ANSWER}, "finish_reason": "stop"}],
            "usage": {"neurons": 0.0},
        }


def build_server(port: int = 9001, vector_mode: str = "db") -> ThreadingHTTPServer:
    """서버를 만들어 돌려준다(아직 안 돈다). 자체 점검이 스레드로 띄우려고 분리했다."""
    global _vector, _vector_mode
    _vector = _load_vector(vector_mode)
    _vector_mode = vector_mode
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main() -> None:
    parser = argparse.ArgumentParser(description="가짜 Cloudflare Workers AI 서버")
    parser.add_argument("--port", type=int, default=9001)
    parser.add_argument("--vector", choices=["db", "blocked", "unit"], default="db")
    args = parser.parse_args()

    server = build_server(args.port, args.vector)
    print(f"가짜 CF 서버 :{args.port} (vector={args.vector}) 지연={LATENCY_MS}")
    print(f"  ai-service 를 CF_BASE_URL=http://127.0.0.1:{args.port} 로 띄우세요")
    server.serve_forever()


if __name__ == "__main__":
    main()
