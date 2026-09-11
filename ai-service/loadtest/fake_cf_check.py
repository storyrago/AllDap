"""가짜 CF 서버 자체 점검. LLM 도 DB 도 없이 돈다.

실행:
    cd ai-service && .venv/bin/python -m loadtest.fake_cf_check

무엇을 재나
─────────────────────────────────────────────────────────────────────────────
"서버가 200 을 준다" 가 아니라 <가짜 응답이 app/ 의 진짜 파서를 통과하는가> 를 잰다.
응답 모양이 조금만 달라도:
  · cf.text_of 가 빈 문자열을 돌려주고 → generate 가 GenerationFailed 를 던지고
  · 부하테스트가 <503 을 재는> 측정이 된다. 그런데 k6 화면에는 "빠르다" 로 보인다.
이 저장소가 반복해 걸린 부류다(원인이 다른 두 사실을 같은 값으로 뭉개는 것).
"""
from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ⚠️ get_settings 는 lru_cache 라 <처음 읽는 순간> 값이 굳는다.
#    그래서 app.* 을 import 하기 <전에> 환경변수를 세팅한다.
os.environ["CF_BASE_URL"] = "http://127.0.0.1:9101"
os.environ.setdefault("CF_ACCOUNT_ID", "fake")
os.environ.setdefault("CF_API_TOKEN", "fake")

from app import cf                      # noqa: E402
from app.config import get_settings     # noqa: E402
from app.generator import FALLBACK_TOKEN  # noqa: E402
from loadtest import fake_cf            # noqa: E402
from loadtest import s2_context        # noqa: E402


def _stub_server(port: int, payload: dict) -> ThreadingHTTPServer:
    """/stats 에 <다른 값>을 주는 가짜의 가짜. 진짜로 읽어오는지 확인하는 데만 쓴다."""

    class Stub(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args) -> None:
            pass

        def do_GET(self) -> None:
            data = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return ThreadingHTTPServer(("127.0.0.1", port), Stub)


def main() -> int:
    s = get_settings()
    server = fake_cf.build_server(port=9101, vector_mode="unit")
    threading.Thread(target=server.serve_forever, daemon=True).start()

    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  {'OK  ' if ok else 'FAIL'} {name} {detail}")
        if not ok:
            failures.append(name)

    # ① 임베딩: 요청한 개수만큼, 설정된 차원으로 돌아와야 한다.
    #    개수가 안 맞으면 retriever.embed 가 "모델이 입력을 합쳤다"고 판단해 죽는다.
    result = cf.run(s.embedding_model, {"text": ["가", "나", "다"]})
    vectors = result["data"]
    check("임베딩 개수", len(vectors) == 3, f"({len(vectors)})")
    check("임베딩 차원", len(vectors[0]) == s.embedding_dim, f"({len(vectors[0])})")

    # ② 생성: text_of 가 내용을 꺼낼 수 있어야 하고, finish_reason 이 length 가 아니어야 한다.
    result = cf.run(s.chat_model, {"messages": [], "max_tokens": 1024})
    answer = cf.text_of(result)
    check("생성 본문", bool(answer.strip()), f"({answer[:20]!r})")
    check("생성 finish_reason", cf.finish_reason(result) == "stop")
    # 🔴 답변에 NO_ANSWER 가 섞이면 <모든 요청이 fallback> 이 된다.
    #    그러면 리랭커도 생성도 안 탄 채 "빠르다" 는 거짓 결과가 나온다.
    check("생성 본문에 fallback 토큰 없음", FALLBACK_TOKEN not in answer)

    # ③ 리랭커: retriever._rerank 는 result["response"][i]["id"] 를 읽는다.
    result = cf.run(s.reranker_model, {"query": "q", "contexts": [{"text": "a"}, {"text": "b"}]})
    ids = [item["id"] for item in result["response"]]
    check("리랭커 id 목록", ids == [0, 1], f"({ids})")

    # ④ 호출 카운터. 0 이면 <그 경로를 안 탄 것>이라 측정이 무효라는 신호다.
    counts = fake_cf.counts()
    check("카운터", counts[s.chat_model] == 1, f"({dict(counts)})")

    # ⑤ 지연 계측. 가짜 서버가 자는 시간을 알고 있으므로 계측이 맞는지 <검증할 수 있다>.
    #    생성은 fake_cf.LATENCY_MS["generate"] 만큼 잔다.
    stats = cf.latency_percentiles()
    p50 = stats[s.chat_model]["p50"]
    expected = fake_cf.LATENCY_MS["generate"]
    check(
        "생성 p50 계측",
        expected <= p50 <= expected + 300,   # 상한은 HTTP 왕복 여유
        f"({p50:.0f}ms, 기대 {expected}ms 이상)",
    )

    # ⑥ 지연 링버퍼. 창이 상한에서 멈추되 <호출 수는 계속 늘어야> 한다.
    #    HTTP 로 2000번 두드리면 오래 걸리므로 적립 함수를 직접 부른다
    #    (재는 대상이 네트워크가 아니라 자료구조라 그게 맞는 층위다).
    probe = "ringbuffer-probe"
    overflow = cf._LATENCY_WINDOW + 5
    for i in range(overflow):
        cf._record_latency(probe, float(i))
    row = cf.latency_percentiles()[probe]
    check("링버퍼 창 상한", row["latency_window"] == cf._LATENCY_WINDOW, f"({row['latency_window']})")
    check("링버퍼 호출 수는 안 잘림", row["count"] == overflow, f"({row['count']})")
    # 오래된 값이 밀려났는지: 0..4 가 빠졌으므로 최솟값이 5 다.
    check("오래된 값 축출", min(cf._latencies[probe]) == 5.0, f"({min(cf._latencies[probe])})")

    # ⑦ 뉴런이 0 이어야 한다. <가짜라는 것을 알아볼 수 있는 유일한 신호>다.
    #    s2_context 가 측정을 시작하기 전에 이 값으로 진짜 CF 를 걸러낸다.
    #    가짜 서버가 언젠가 0 이 아닌 값을 주기 시작하면 그 안전장치가 조용히 꺼지므로
    #    여기서 회귀로 잡는다.
    used = cf.neurons_used()
    check(
        "가짜 CF 는 뉴런을 0 으로 준다",
        all(v == 0.0 for v in used.values()),
        f"({used})",
    )
    # 세 모델이 <전부> 적립 경로를 지났는지도 본다. 응답에 뉴런 필드가 아예 없으면
    # _record_neurons 가 아무것도 안 남겨 "0 이다" 와 "안 쟀다" 가 구분되지 않는다.
    for model in (s.embedding_model, s.reranker_model, s.chat_model):
        check(f"뉴런 적립됨 {model}", model in used, f"({used.get(model)})")

    # ⑧ 판정 함수 자체. 실제 CF 를 부르지 않고 <세 상황>을 다 태운다.
    #    ①판정 불가 ②진짜 CF ③가짜 CF 가 서로 다른 결과여야 한다(뭉치면 안 된다).
    def stats(count: int, neurons: float) -> dict:
        return {"m": {"count": count, "neurons": neurons}}

    ok_fake, _ = s2_context.judge_fake_cf(stats(0, 0.0), stats(1, 0.0))
    ok_real, msg_real = s2_context.judge_fake_cf(stats(0, 0.0), stats(1, 24.6))
    ok_none, msg_none = s2_context.judge_fake_cf(stats(3, 0.0), stats(3, 0.0))
    check("판정: 가짜 CF 는 통과", ok_fake)
    check("판정: 진짜 CF 는 중단", not ok_real and "진짜 Cloudflare" in msg_real)
    check("판정: 호출이 안 늘면 중단", not ok_none and "판정하지 못한" in msg_none)

    # ⑨ /stats 는 <도는 서버의 설정>을 내보내야 한다. s2_context 가 시작 조건 파일에
    #    적을 값을 여기서 읽어간다.
    stats_payload = s2_context.read_fake_cf_stats("http://127.0.0.1:9101")
    check("/stats latency_ms", stats_payload["latency_ms"] == fake_cf.LATENCY_MS,
          f"({stats_payload['latency_ms']})")
    check("/stats vector_mode", stats_payload["vector_mode"] == "unit",
          f"({stats_payload['vector_mode']})")
    # unit 모드는 DB 를 안 읽으므로 출처 봇이 없다. 0 이나 "" 로 뭉개지 않는다.
    check("/stats vector_bot_id (unit 은 없음)", stats_payload["vector_bot_id"] is None,
          f"({stats_payload['vector_bot_id']})")

    # ⑩ 🔴 여기가 이 파일의 핵심 회귀 검사다.
    #    <다른 지연값으로 떠 있는 서버>를 세워두고, s2_context 가 그 값을 읽는지 본다.
    #    import 로 되돌아가면 모듈 상수(235/414/937)를 돌려주므로 이 검사가 깨진다.
    other = {"embed": 1, "rerank": 2, "generate": 3}
    stub = _stub_server(9102, {"counts": {}, "latency_ms": other,
                               "vector_mode": "blocked", "vector_bot_id": "other-bot"})
    threading.Thread(target=stub.serve_forever, daemon=True).start()
    read = s2_context.read_fake_cf_stats("http://127.0.0.1:9102")
    check("다른 서버의 지연값을 그대로 읽는다", read["latency_ms"] == other, f"({read['latency_ms']})")
    check("모듈 상수를 섞지 않는다", read["latency_ms"] != fake_cf.LATENCY_MS)
    stub.shutdown()

    # ⑪ 못 읽었을 때 <조용히 넘어가지 않는지>. 되돌아갈 기본값이 있으면 고치기 전과 같아진다.
    #    · 아무도 안 뜬 포트 → 연결 실패
    #    · 떠 있지만 다른 서버(필수 키 없음) → 응답은 200 인데 시작 조건을 적을 수 없다
    for name, port, payload in (
        ("연결 실패", 9103, None),
        ("필수 키 없는 응답", 9104, {"hello": "world"}),
    ):
        if payload is not None:
            bad = _stub_server(port, payload)
            threading.Thread(target=bad.serve_forever, daemon=True).start()
        try:
            s2_context.read_fake_cf_stats(f"http://127.0.0.1:{port}")
            check(f"/stats {name} 시 중단", False, "(중단하지 않았다)")
        except SystemExit as e:
            check(f"/stats {name} 시 중단", "중단" in str(e), f"({str(e)[:30]}...)")
        if payload is not None:
            bad.shutdown()

    server.shutdown()
    print(f"\n{'실패 ' + ', '.join(failures) if failures else '전부 통과'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
