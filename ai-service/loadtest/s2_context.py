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

S2 는 여기에 하나를 더 얹는다 — <경로를 진짜 탔는지>. k6 가 200 을 받았다는 것만으로는
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


def _cf_counts(ai_base: str) -> dict[str, int]:
    """모델별 <호출 수>만 뽑는다. 백분위·뉴런은 이 PR 이 쓰지 않는다."""
    resp = httpx.get(f"{ai_base}/internal/debug/cf-stats", timeout=30.0)
    resp.raise_for_status()
    return {model: int(row.get("count", 0)) for model, row in resp.json().items()}


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
        #    특히 cf_base_url — 가짜 서버를 띄웠던 셸에서 uvicorn 을 재시작하면 그대로 남는다.
        #    진짜 주소면 그 측정은 <진짜 CF 를 태운 것>이고, 하루 한도가 12분에 날아간다.
        "cf_base_url": s.cf_base_url,
    }


def cmd_before(args) -> int:
    from loadtest.fake_cf import LATENCY_MS

    settings = _settings_snapshot()

    # 🔴 가짜 서버를 안 보고 있으면 여기서 멈춘다. 이건 이 PR 에서 <유일하게> 실행 전에
    #    막는 자리다 — 진짜 CF 로 12분을 돌리면 하루 한도가 날아가고 24~33시간 기다린다.
    if "cloudflare.com" in settings["cf_base_url"]:
        print(f"중단: CF_BASE_URL 이 진짜 Cloudflare 다 ({settings['cf_base_url']}). "
              f"가짜 서버(http://127.0.0.1:9001)를 보게 하고 uvicorn 을 다시 띄울 것.")
        return 1

    client = httpx.Client(timeout=60.0)
    resp = client.post(f"{args.api}/api/auth/login",
                       json={"email": args.email, "password": args.password})
    resp.raise_for_status()
    token = resp.json()["token"]

    resp = client.get(f"{args.api}/api/bots", headers={"Authorization": f"Bearer {token}"})
    resp.raise_for_status()
    bot = _pick_bot(resp.json())

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
