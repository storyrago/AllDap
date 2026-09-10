"""S2 실행의 <시작 조건>을 파일로 찍고, 실행 뒤 <경로를 진짜 탔는지> 대조한다.

실행:
    # 실행 전 — 봇을 고르고 조건을 남긴다. 인쇄된 두 줄을 k6 에 그대로 넘긴다.
    cd ai-service && .venv/bin/python -m loadtest.s2_context before \\
        --run-id 2026-09-10-1 --email w2check@example.com --password 'S1loadtest!2026'

    # 실행 후 — 가짜 CF 호출 수를 요청 수와 맞춰본다.
    cd ai-service && .venv/bin/python -m loadtest.s2_context after \\
        --run-id 2026-09-10-1 --k6-summary loadtest/results/S2-2026-09-10-1.json

왜 이 파일이 있는가
─────────────────────────────────────────────────────────────────────────────
"그때 뭘로 쟀지" 를 못 답하는 측정은 재현할 수 없고, 재현할 수 없으면 측정이 아니다
(s1_baseline._conditions 와 같은 근거다).

S2 는 여기에 둘을 더 얹는다: <진짜 CF 를 태우고 있지 않은지>(실행 전)와
<경로를 진짜 탔는지>(실행 후).

🔴 실행 전 검사는 환경변수가 아니라 <뉴런>으로 한다. 환경변수는 드라이버 프로세스의
   것이라 요청을 처리하는 uvicorn 이 무엇을 보는지 말해주지 못한다. 가짜 서버는 뉴런을
   0 으로 주고 진짜 Cloudflare 는 호출마다 값을 준다. 그 차이는 <응답에서> 오므로
   uvicorn 을 통과해야만 보인다. 자세한 근거는 judge_fake_cf 주석에 있다.

실행 후 검사가 보는 것은 <경로를 진짜 탔는지>다. k6 가 200 을 받았다는 것만으로는
그 요청이 embed·rerank·generate 를 다 지났는지 알 수 없다. 캐시·조기 반환·설정 착오로
경로를 건너뛰어도 200 은 200 이다. 가짜 CF 의 호출 수를 실행 전후로 빼면 그게 드러난다.

🔴 기대 배수를 상수로 박지 않는다. reranker_enabled 가 켜져 있으면 요청당 3건
   (embed·rerank·generate), 꺼져 있으면 2건이다. 상수로 박으면 설정을 바꾼 날
   <정상 실행이 무효로 판정된다> — 그리고 그건 "경로를 안 탔다" 와 구분이 안 된다.

⚠️ cf-stats 는 프로세스 시작 뒤 누적이고 리셋 API 가 없다(cf._latencies 주석이 근거를
   적어둔 자리). 여기서는 <전후 차이>만 쓰므로 문제되지 않는다. 백분위는
   _LATENCY_WINDOW=2000 창에 걸리지만 이 스크립트가 쓰는 것은 count 뿐이고,
   count 와 latency_window 는 cf_stats 가 이미 따로 내보낸다(cf.py:144).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import httpx

RESULTS = Path(__file__).parent / "results"


def _context_path(run_id: str) -> Path:
    return RESULTS / f"S2-{run_id}-context.json"


def _verdict_path(run_id: str) -> Path:
    return RESULTS / f"S2-{run_id}-verdict.json"


def _cf_stats(ai_base: str) -> dict[str, dict]:
    """cf-stats 원본을 그대로 읽는다. 호출 수도 뉴런도 여기서 갈라 쓴다."""
    resp = httpx.get(f"{ai_base}/internal/debug/cf-stats", timeout=30.0)
    resp.raise_for_status()
    return resp.json()


def _counts_of(stats: dict[str, dict]) -> dict[str, int]:
    return {model: int(row.get("count", 0)) for model, row in stats.items()}


def _neurons_of(stats: dict[str, dict]) -> dict[str, float]:
    return {model: float(row.get("neurons", 0.0)) for model, row in stats.items()}


def _cf_counts(ai_base: str) -> dict[str, int]:
    """모델별 <호출 수>만 뽑는다. 사후 대조가 쓴다."""
    return _counts_of(_cf_stats(ai_base))


# 워밍업 질문. 코퍼스 어디에도 없는 낱말로 짓는다.
#
# 🔴 이유는 <진짜 CF 였을 때의 비용>이다. 이 질문은 어떤 청크와도 멀어
#    answerable_max_distance 게이트에 걸리므로, 진짜 CF 를 보고 있었다면 임베딩 1회
#    (약 0.024 뉴런, 하루 한도 10,000 의 0.0002%)에서 멈춘다. 게이트가 어쩌다 통과해
#    생성까지 가더라도 1건은 약 25 뉴런, 0.25% 다. 어느 쪽이든 12분 실행이 날려버리는
#    하루치와는 비교가 안 된다.
#    반대로 가짜 CF 는 <진짜 청크 벡터>를 돌려주므로 거리가 0 이라 게이트를 통과하고
#    embed·rerank·generate 를 다 태운다. 즉 이 한 건으로 세 모델을 한꺼번에 검사한다.
WARMUP_QUESTION = "부하테스트 사전 점검용 질문 zzqq (코퍼스에 없는 말입니다)"


def judge_fake_cf(before: dict[str, dict], after: dict[str, dict]) -> tuple[bool, str]:
    """워밍업 전후의 cf-stats 로 <요청을 처리하는 프로세스>가 가짜 CF 를 보는지 판정한다.

    왜 뉴런인가
    ─────────────────────────────────────────────────────────────────────
    가짜 서버는 뉴런을 0 으로 준다(loadtest/fake_cf.py). 진짜 Cloudflare 는 호출마다
    0 이 아닌 값을 준다(cf._record_neurons 의 세 경로 중 하나로 반드시 들어온다).
    그리고 이 숫자는 <드라이버가 아니라 uvicorn 이 실제로 받은 응답>에서 나온다.
    환경변수는 그것을 말해주지 못한다: 드라이버 셸에 가짜 값이 있어도 uvicorn 이 진짜
    Cloudflare 를 보고 있을 수 있고, 그게 위험한 방향의 오탐이다.

    🔴 세 결과를 <세 값으로> 가른다. 뭉치면 원인이 다른 사실이 같은 실패가 된다.
       ① 호출이 안 늘었다  → 판정 불가(가짜라는 뜻이 아니다). 그래도 중단한다,
                             모르는 채로 12분을 돌릴 수는 없다.
       ② 뉴런이 늘었다    → 진짜 CF 다. 중단.
       ③ 호출만 늘었다    → 가짜 CF 다. 진행.
    """
    b_count, a_count = _counts_of(before), _counts_of(after)
    b_neuron, a_neuron = _neurons_of(before), _neurons_of(after)
    models = set(a_count) | set(b_count)

    called = {m: a_count.get(m, 0) - b_count.get(m, 0) for m in models}
    called = {m: d for m, d in called.items() if d > 0}
    if not called:
        return False, (
            "중단: 워밍업 요청이 Cloudflare 호출을 하나도 늘리지 않았다. "
            "가짜/진짜를 <판정하지 못한> 것이지 가짜라는 뜻이 아니다. "
            "ai-service 가 그 주소에 떠 있는지, 봇에 임베딩된 청크가 있는지 확인할 것."
        )

    burned = {
        m: round(a_neuron.get(m, 0.0) - b_neuron.get(m, 0.0), 6)
        for m in called
        if a_neuron.get(m, 0.0) - b_neuron.get(m, 0.0) > 0
    }
    if burned:
        return False, (
            f"중단: 요청을 처리하는 ai-service 가 <진짜 Cloudflare> 를 보고 있다. "
            f"워밍업 1건에 뉴런이 늘었다({burned}). 이대로 12분을 돌리면 하루 한도"
            f"(10,000 뉴런)가 날아가고 24~33시간 기다려야 한다. "
            f"가짜 서버를 띄우고(cd ai-service && .venv/bin/python -m loadtest.fake_cf) "
            f"CF_BASE_URL=http://127.0.0.1:9001 로 uvicorn 을 <다시> 띄운 뒤 이 명령을 다시 실행할 것."
        )

    return True, f"OK   가짜 CF 확인: 워밍업 호출 {called}, 뉴런 증가 0"


def _assert_fake_cf(ai_base: str, bot_id: str) -> None:
    """측정을 시작하기 <전에> 실제로 도는 ai-service 를 상대로 확인한다.

    ⚠️ 사후 대조가 아니라 여기여야 한다. 다 돌리고 나서 알아봐야 뉴런은 이미 탔다.
    """
    before = _cf_stats(ai_base)
    try:
        # ⚠️ 200 이 아니어도 된다. 게이트에 걸리면 fallback(200)이고, 생성이 잘리면 503 이다.
        #    둘 다 CF 호출은 이미 일어났으므로 판정 재료로는 충분하다.
        #    막힌 것은 호출 수가 안 늘어난 경우이고 그건 judge_fake_cf 가 ①로 잡는다.
        httpx.post(
            f"{ai_base}/internal/chat",
            json={"bot_id": bot_id, "message": WARMUP_QUESTION, "session_id": "s2-guard"},
            timeout=120.0,
        )
    except httpx.HTTPError as e:
        raise SystemExit(f"중단: 워밍업 요청이 실패했다 ({e}). ai-service 가 {ai_base} 에 떠 있는가?")

    ok, message = judge_fake_cf(before, _cf_stats(ai_base))
    print(message)
    if not ok:
        raise SystemExit(1)


def _pick_bot(bots: list[dict]) -> dict:
    """봇을 <규칙으로> 고른다. 사람이 고르면 다음 실행에서 다른 봇을 고를 수 있다.

    🔴 문서가 가장 많은 봇을 쓴다. 부하테스트가 재려는 것은 <실제 코퍼스를 가진 봇>의
       검색·생성 경로이고, 문서 0건 봇을 고르면 게이트에서 막혀 전부 fallback 이 난다.
       동점이면 먼저 만들어진 쪽 — 규칙에 임의성이 남으면 재현이 안 된다.
    """
    if not bots:
        raise SystemExit("중단: 이 계정에 봇이 없다.")
    return sorted(bots, key=lambda b: (-b["documentCount"], b["createdAt"]))[0]


def _corpus(bot_id: str) -> dict:
    """코퍼스 크기. API 가 아니라 DB 에서 직접 센다 — 청크 수는 API 가 안 준다."""
    from app.db import cursor

    with cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM documents WHERE bot_id=%s AND status='ready'", (bot_id,)
        )
        docs = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM chunks WHERE bot_id=%s", (bot_id,))
        chunks = cur.fetchone()[0]
    return {"documents_ready": docs, "chunks": chunks}


def _settings_snapshot() -> dict:
    from app.config import get_settings

    s = get_settings()
    return {
        "reranker_enabled": s.reranker_enabled,
        "hybrid_enabled": s.hybrid_enabled,
        "answerable_max_distance": s.answerable_max_distance,
        "max_distance": s.max_distance,
        "top_k": s.top_k,
        "chat_model": s.chat_model,
        "embedding_model": s.embedding_model,
        "reranker_model": s.reranker_model,
        # 🔴 이 값들은 <드라이버 프로세스>가 읽은 것이지 요청을 처리한 uvicorn 의 것이 아니다.
        #    둘이 다른 환경변수로 떠 있으면 이 파일은 거짓 조건을 남긴다.
        #    특히 cf_base_url: 이건 <기록용>이지 판정 근거가 아니다.
        #    uvicorn 이 무엇을 보는지는 judge_fake_cf 가 뉴런으로 판정한다.
        "cf_base_url": s.cf_base_url,
    }


def cmd_before(args) -> int:
    from loadtest.fake_cf import LATENCY_MS

    settings = _settings_snapshot()

    # 🔴 이 값으로 <막지> 않는다. 예전에는 여기서 중단시켰는데, 그 검사는 드라이버
    #    프로세스의 환경변수만 봐서 양쪽으로 다 틀렸다:
    #      · 드라이버만 가짜 값 → 통과시킨다. uvicorn 이 진짜 CF 여도 통과한다(위험한 오탐).
    #      · 드라이버만 진짜 값 → 중단시킨다. uvicorn 이 가짜여도 중단한다(2026-09-10 실제로 겪었다).
    #    진짜 판정은 아래 _assert_fake_cf 가 <도는 프로세스>를 상대로 한다.
    #    값을 계속 찍는 이유는 두 프로세스의 설정이 어긋났다는 <단서>로는 쓸모가 있어서다.
    if "cloudflare.com" in settings["cf_base_url"]:
        print(f"경고: 이 셸의 CF_BASE_URL 이 진짜 Cloudflare 다 ({settings['cf_base_url']}). "
              f"uvicorn 이 무엇을 보는지는 이 값으로 알 수 없어 아래 워밍업 검사로 판정한다.")

    client = httpx.Client(timeout=60.0)
    resp = client.post(f"{args.api}/api/auth/login",
                       json={"email": args.email, "password": args.password})
    resp.raise_for_status()
    token = resp.json()["token"]

    resp = client.get(f"{args.api}/api/bots", headers={"Authorization": f"Bearer {token}"})
    resp.raise_for_status()
    bot = _pick_bot(resp.json())

    # 🔴 여기서 막는다. k6 를 띄우기 <전>이자 봇을 고른 <뒤>다.
    #    측정이 실제로 두드릴 봇으로 같은 경로를 한 번 태워야 판정에 뜻이 있다.
    _assert_fake_cf(args.ai, bot["id"])

    # 리랭커가 꺼져 있으면 rerank 를 안 부른다. 기대 배수를 여기서 <설정으로부터> 정한다.
    expected = 3 if settings["reranker_enabled"] else 2

    context = {
        "run_id": args.run_id,
        "commit": subprocess.run(["git", "rev-parse", "HEAD"],
                                 capture_output=True, text=True).stdout.strip(),
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "api_base": args.api,
        "ai_base": args.ai,
        "bot": {
            "id": bot["id"],
            "name": bot["name"],
            "document_count": bot["documentCount"],
        },
        "corpus": _corpus(bot["id"]),
        "settings": settings,
        # 가짜 CF 의 고정 지연. S1 실측 p50 이고 이 PR 은 이 값을 바꾸지 않는다.
        "fake_cf_latency_ms": dict(LATENCY_MS),
        "expected_cf_calls_per_request": expected,
        # ⚠️ 워밍업 <뒤>의 값이다. 앞에서 찍으면 워밍업 3건이 사후 대조의 배수에 섞여
        #    "경로를 더 탔다" 로 읽힌다(요청 수에는 안 잡히므로 배수가 위로 튄다).
        "cf_stats_before": _cf_counts(args.ai),
        "stages": [1, 5, 10, 20, 40, 80],
        "hold_seconds": 120,
        "warmup_discard_seconds": 20,
    }

    RESULTS.mkdir(exist_ok=True)
    _context_path(args.run_id).write_text(
        json.dumps(context, ensure_ascii=False, indent=2, default=str)
    )
    print(json.dumps(context, ensure_ascii=False, indent=2, default=str))
    print(f"\n저장: {_context_path(args.run_id)}")
    # 아래 두 줄을 k6 실행 명령에 그대로 넣는다.
    print(f"\nBOT_ID={bot['id']}")
    print(f"RUN_ID={args.run_id}")
    return 0


def cmd_after(args) -> int:
    context = json.loads(_context_path(args.run_id).read_text())
    summary = json.loads(Path(args.k6_summary).read_text())

    def metric_count(key: str) -> int:
        m = summary.get("metrics", {}).get(key) or {}
        return int((m.get("values") or {}).get("count", 0))

    after = _cf_counts(context["ai_base"])
    before = context["cf_stats_before"]
    delta = {model: after.get(model, 0) - before.get(model, 0)
             for model in set(after) | set(before)}
    total_delta = sum(delta.values())

    ok_2xx = metric_count("chat_status{status:200}")
    fallbacks = metric_count("chat_fallback")
    expected = context["expected_cf_calls_per_request"]
    actual_ratio = round(total_delta / ok_2xx, 3) if ok_2xx else None

    verdicts: list[str] = []

    # ① fallback 이 하나라도 있으면 그 실행은 무효다.
    if fallbacks == 0:
        verdicts.append("OK   fallback 0건 — 생성 경로를 탔다")
    else:
        verdicts.append(
            f"무효 fallback {fallbacks}건. 그 요청들은 LLM 을 안 타 0.1초에 끝났고, "
            f"재려던 곡선이 그만큼 아래로 끌려갔다. 질문·게이트 설정을 확인하고 다시 잰다."
        )

    # ② 가짜 CF 호출 수가 요청 수와 맞는가.
    #    🔴 pass/fail 로만 내지 않고 <실제 배수>를 함께 적는다. 기대와 다를 때 그 값이
    #       2 인지 3 인지 0 인지에 따라 원인이 전혀 다르다(리랭커 꺼짐 / 경로 미탐 /
    #       드라이버와 uvicorn 의 설정 불일치). 하나의 FAIL 로 뭉개면 그 구분이 사라진다.
    if ok_2xx == 0:
        verdicts.append("무효 2xx 가 0건이다. 실행이 시작조차 못 했다.")
    elif actual_ratio is None:
        verdicts.append("무효 배수를 계산할 수 없다.")
    elif abs(actual_ratio - expected) <= 0.05:
        verdicts.append(f"OK   가짜 CF 호출 배수 {actual_ratio} ≈ 기대 {expected}")
    else:
        verdicts.append(
            f"무효 가짜 CF 호출 배수가 {actual_ratio} 다 (기대 {expected}). "
            f"모델별 증가분={delta}. 2 면 리랭커가 꺼진 채 돌았고(시작 조건 파일의 "
            f"reranker_enabled 와 대조할 것), 0 에 가까우면 그 경로를 아예 안 탔다."
        )

    result = {
        "run_id": args.run_id,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "cf_stats_before": before,
        "cf_stats_after": after,
        "cf_delta": delta,
        "cf_delta_total": total_delta,
        "requests_2xx": ok_2xx,
        "expected_cf_calls_per_request": expected,
        "actual_cf_calls_per_request": actual_ratio,
        "fallbacks": fallbacks,
        "verdicts": verdicts,
        "valid": all(v.startswith("OK") for v in verdicts),
        # 🔴 "유효" 는 <오염이 없다> 는 뜻이지 <결과가 좋다> 는 뜻이 아니다.
        #    5xx 와 재시작은 여기서 판정하지 않는다 — 그건 S2 가 찾으려는 결과 그 자체이고,
        #    재시작 경계는 Grafana 패널을 눈으로 보고 사람이 표에 옮긴다.
        "valid_means": (
            "오염(fallback·경로 미탐)이 없다는 뜻이다. 5xx·재시작은 여기서 판정하지 않는다."
        ),
    }

    _verdict_path(args.run_id).write_text(
        json.dumps(result, ensure_ascii=False, indent=2)
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n저장: {_verdict_path(args.run_id)}")
    for v in verdicts:
        print(f"  {v}")
    return 0 if result["valid"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="S2 시작 조건 · 사후 대조")
    parser.add_argument("phase", choices=["before", "after"])
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--api", default="http://localhost:8080")
    parser.add_argument("--ai", default="http://localhost:8001")
    parser.add_argument("--email", default="w2check@example.com")
    parser.add_argument("--password")
    parser.add_argument("--k6-summary")
    args = parser.parse_args()

    if args.phase == "before":
        if not args.password:
            print("중단: before 에는 --password 가 필요하다.")
            return 1
        return cmd_before(args)

    if not args.k6_summary:
        print("중단: after 에는 --k6-summary 가 필요하다.")
        return 1
    return cmd_after(args)


if __name__ == "__main__":
    sys.exit(main())
