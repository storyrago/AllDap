"""S1: 가짜 서버에 넣을 지연값을 <추측하지 않고> 진짜 LLM 으로 실측한다.

실행:
    cd ai-service && .venv/bin/python -m loadtest.s1_baseline \
        --email you@example.com --password '...' \
        --bot-id 628d2785-a128-486c-a1ac-556f19f06de3

🔴 하루 한도의 94% 를 태운다. 다른 측정이 없는 날에 돌릴 것.

왜 350건인가 — 그리고 왜 <비용은 추정하지 않는가>
─────────────────────────────────────────────────────────────────────────────
🔴 실행 <뒤>의 비용은 추정하지 않는다. Cloudflare 가 호출마다 정확한 뉴런을
돌려주므로(AGENTS.md "회당 비용" 절), 실행이 끝나면 실측 합계가 결과 파일의
neurons_measured 에 그대로 남는다. 대시보드를 읽을 필요도 곱셈을 할 필요도 없다.
⚠️ 단 <새 실행부터>다. results/ 에 남아 있는 파일 3개는 이 필드가 생기기 전에 저장돼
   neurons_estimated 하나만 갖고, 그 값은 실측이 아니라 상수 25.08 시점의 추정이다
   (아래 result 조립부 주석 참고).

추정이 필요한 자리는 하나뿐이다 — 실행 <전>에 걸어야 하는 상한 검사(MAX_REQUESTS).
그런데 그 추정은 세 번 연속 <아래로> 빗나갔다:

    계획서 24.64 → 예행 1회 25.08 → 예행 누적 25.24 → 본 실행 328건 실측 25.43

그래서 상한에 쓰는 값은 최신 실측을 그대로 박지 않고 <조금 크게> 잡는다(26.0).
크게 잡으면 여유가 남을 뿐이지만, 작게 잡으면 한도를 태우고 24~33시간을 기다린다.
손해가 대칭이 아니므로 <큰 쪽으로 틀린다.>

350건 × 26.0 = 9,100. 예행 2회(약 250)를 빼면 여유가 약 650 남는다.
380건이면 9,880 이라 예행을 빼고 나면 재시도 한 번에 한도가 닿는다.
(실측으로 되짚으면 본 실행 327건이 실제로 쓴 것은 8,340 이다. 상한은 그보다
 넉넉해야 하는 값이지 맞혀야 하는 값이 아니다.)

남기는 이유 둘:
  ① 한도를 완전히 태우면 <언제 풀리는지 모른다.> 실측상 대시보드가 0/10k 로
     리셋돼도 차단은 안 풀렸고, 실제로는 소진 시각에서 약 24~33시간 뒤였다.
  ② 스크립트 버그를 나중에 발견해도 남은 여유로 최소한 확인은 할 수 있다.

🔴 부분 측정을 정상 측정처럼 남기지 않는다
─────────────────────────────────────────────────────────────────────────────
이 저장소는 평가 16문항이 전부 429 로 죽었는데 실행이 completed 로 남아
<그 실행을 유효한 측정으로 착각한> 적이 있다.
그래서 429·503·비200 이 하나라도 나오면 <즉시 멈추고> 결과 파일에
"aborted_at" 을 적는다. 끝까지 돈 것처럼 보이는 파일을 만들지 않는다.

p99 의 한계 (리포트에 그대로 적을 것)
─────────────────────────────────────────────────────────────────────────────
350건이면 p99 는 상위 약 4건이 결정한다. 100건이면 최악 1건이 곧 p99 라 우연이
지표가 된다. 튼튼하려면 1,000건 이상인데 그건 이틀 반 치 한도라 못 한다.
p50·p95 는 350건이면 충분하고, <S1 이 실제로 하는 일에 쓰이는 것은 p50 이다.>
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path

import httpx

# 근거가 <있는> 질문들. 게이트를 통과해 생성까지 태워야 지연을 잴 수 있다.
# 근거 없는 질문을 섞으면 그 요청은 LLM 을 안 부르고 0.1초에 끝나 p50 을 끌어내린다.
#
# 🔴 손으로 적지 말고 <eval_questions 테이블의 원문 그대로> 쓴다.
#    처음에는 손으로 적었고 5건 예행에서 2건이 fallback 났다. 회귀가 아니라
#    <다른 질문을 던진 것>이었다. AGENTS.md 가 "1.000, 3회 일관" 으로 기록한 것은
#    저 테이블의 문항이고, 우리가 적은 것과는 16건 중 완전 일치가 0건이었다.
#    예: 테이블은 "정규직으로 <새로 들어온 직원의> 시용 기간" 인데 우리는 "정규직의"
#    뿐이라, distractor(인턴 지침)와 구분되는 신호가 빠져 NO_ANSWER 가 났다.
#    테이블 문항은 문서 어휘를 <일부러 피한> 패러프레이즈다("법인카드" → "플라스틱 카드").
#    직설적으로 바꿔 적으면 그 성질이 사라져 다른 것을 재게 된다.
#
# 아래 5개는 전부 AGENTS.md 가 현재 기본값(리랭커 ON + 하이브리드 ON)에서
# 1.000 · 3회 일관으로 기록한 문항이다.
QUESTIONS = [
    "정규직으로 새로 들어온 직원의 시용 기간은 얼마나 되나요?",
    "정규직의 업무용 컴퓨터를 바꿀 수 있는 주기는 얼마나 되나요?",
    "정규직이 결혼할 때 쉴 수 있는 날이 며칠인가요?",
    "정규직 기준으로 회사의 플라스틱 카드는 어떤 직급부터 쓸 수 있나요?",
    "정규직이 쌍둥이를 낳았을 때 아빠가 쓸 수 있는 휴가는 며칠인가요?",
]

# ⚠️ 일부러 뺀 문항 둘: "재택 주 2회" 와 "기간제 연차" 는 현재 기본값에서
#    <fallback 이 정상>이다. 리랭커가 정답 청크를 밀어내는, AGENTS.md 가 알고 남긴
#    실패 2건이라 베이스라인에 넣으면 회귀로 오독된다.

# 🔴 "출산 전후 휴가는 며칠인가요?" 를 넣었다가 뺐다. 코퍼스에 <정답이 없다>:
#    07_경조사_지원규정 이 "본인 출산은 법정 출산휴가에 따르며" 라고만 적고 일수가 없고,
#    숫자가 있는 것은 전부 배우자 출산휴가인데 대상별로 값이 갈린다(10일·5일·12일).
#    거기에 질문에 대상 수식어가 없어 "정규직 결혼 휴가" 가 top5 전부 distractor 로
#    fallback 났던 것과 같은 구조다.
#    질문 5개를 순환하므로 이 하나가 380건 중 76건(20%)이고, fallback 은 LLM 을 안 타
#    0.1~0.2초에 끝나므로 <재려던 p50 이 통째로 끌려 내려간다.>

# 🔴 이 상수는 <실행 전 상한 검사에만> 쓴다. 결과 파일의 비용 숫자는 여기서 곱하지 않고
#    Cloudflare 가 준 실측(per_model[*].neurons)을 합해서 쓴다 — 위 docstring 참고.
#    값을 최신 실측(25.43)이 아니라 26.0 으로 두는 이유는 추정이 세 번 연속 아래로
#    빗나갔고, 틀렸을 때의 손해가 대칭이 아니기 때문이다(크면 여유가 남고, 작으면
#    한도를 태워 24~33시간 대기). 여유를 더 두고 싶으면 이 값을 깎지 말고
#    MAX_REQUESTS 를 낮출 것 — 상수를 깎으면 <상한이 지키려던 것>이 무너진다.
MAX_REQUESTS = 350               # 예산 상한. 코드로 강제한다.
NEURONS_BUDGET_PER_REQUEST = 26.0  # 예산용 <보수적> 추정치. 실측은 25.43 (2026-09-10, 328건)


def _pct(values: list[float], p: float) -> float:
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, int(-(-len(ordered) * p // 100)) - 1))
    return ordered[idx]


def _conditions(args) -> dict:
    """시작 조건. <이게 없으면 숫자가 나중에 쓸모없어진다.>

    "그때 뭘로 쟀지" 를 못 답하는 측정은 재현할 수 없고, 재현할 수 없으면 측정이 아니다.
    """
    from app.config import get_settings

    s = get_settings()
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    return {
        "commit": sha,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "api_base": args.api,
        "bot_id": args.bot_id,
        "requests_planned": args.count,
        "settings": {
            "chat_model": s.chat_model,
            "embedding_model": s.embedding_model,
            "reranker_model": s.reranker_model,
            "reranker_enabled": s.reranker_enabled,
            "hybrid_enabled": s.hybrid_enabled,
            "max_distance": s.max_distance,
            "answerable_max_distance": s.answerable_max_distance,
            "top_k": s.top_k,
            "chat_temperature": s.chat_temperature,
            # 🔴 이 값들은 <드라이버 프로세스>가 읽은 것이지 요청을 처리한 uvicorn 의
            #    것이 아니다. 둘이 다른 환경변수로 떠 있으면 이 파일은 거짓 조건을 남긴다.
            #    하필 이 PR 이 다루는 것이 CF_BASE_URL 이라(가짜 서버를 띄웠던 셸에서
            #    uvicorn 을 재시작하면 그대로 남는다) 사후 대조가 되게 함께 적는다.
            #    진짜 주소가 아니면 그 측정은 가짜 서버를 잰 것이다.
            "cf_base_url": s.cf_base_url,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="S1 지연 기준선(진짜 LLM)")
    parser.add_argument("--api", default="http://localhost:8080")
    parser.add_argument("--ai", default="http://localhost:8001")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--bot-id", required=True)
    parser.add_argument("--count", type=int, default=MAX_REQUESTS)
    args = parser.parse_args()

    if args.count > MAX_REQUESTS:
        print(f"중단: --count 상한은 {MAX_REQUESTS} 입니다 "
              f"(하루 한도의 94%). 더 쓰면 언제 풀리는지 알 수 없어집니다.")
        return 1

    conditions = _conditions(args)
    client = httpx.Client(timeout=180.0)

    # 로그인 1회. 토큰을 재사용한다(로그인에도 분당 제한이 있다).
    resp = client.post(f"{args.api}/api/auth/login",
                       json={"email": args.email, "password": args.password})
    resp.raise_for_status()
    token = resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    latencies: list[float] = []
    # fallback 은 개수만으로는 못 고친다. <어느 질문이> 걸렸는지 알아야
    # 그 질문을 바꿀 수 있다. 특히 "법인카드" 문항은 d1=0.4026 으로 16문항 중
    # 게이트(answerable_max_distance=0.44)에 가장 가까워 여유가 0.037 뿐이다.
    fallback_questions: dict[str, int] = {}
    aborted_at: str | None = None

    for i in range(args.count):
        question = QUESTIONS[i % len(QUESTIONS)]
        started = time.perf_counter()
        r = client.post(
            f"{args.api}/api/bots/{args.bot_id}/chat",
            headers=headers,
            json={"message": question, "sessionId": f"s1-{i}"},
        )
        elapsed = (time.perf_counter() - started) * 1000

        if r.status_code != 200:
            # 🔴 여기서 계속 돌면 <부분 측정이 정상 측정처럼> 남는다.
            aborted_at = f"{i}건째에서 HTTP {r.status_code}: {r.text[:200]}"
            print(f"\n중단: {aborted_at}")
            break

        latencies.append(elapsed)
        if r.json().get("isFallback"):
            fallback_questions[question] = fallback_questions.get(question, 0) + 1
        if (i + 1) % 20 == 0:
            print(f"  {i + 1}/{args.count}  p50={_pct(latencies, 50):.0f}ms")

    # 모델별 지연은 Python 프로세스 안에서만 알 수 있다.
    # 🔴 여기서 예외가 나면 아래 write_text 에 <도달하지 못한다.> latencies 는 메모리에만
    #    있으므로 380건(9,363 뉴런, 다시 돌리려면 24~33시간)이 파일 한 줄 없이 사라진다.
    #    포트 오타·uvicorn 사망·비-JSON 응답이면 충분하다.
    #    이 스크립트가 막으려는 것은 "부분 측정을 정상 측정처럼 남기는 것" 인데,
    #    안전망이 없으면 <정상 측정을 아예 안 남기는> 정반대 사고가 난다.
    cf_stats: dict | None = None
    cf_stats_error: str | None = None
    try:
        cf_resp = client.get(f"{args.ai}/internal/debug/cf-stats")
        cf_resp.raise_for_status()
        cf_stats = cf_resp.json()
    except Exception as exc:
        cf_stats_error = f"{type(exc).__name__}: {exc}"
        print(f"\n경고: cf-stats 를 못 읽었습니다 ({cf_stats_error}). "
              f"모델별 지연은 비지만 종단 측정은 아래에 저장합니다.")

    # 🔴 비용은 <곱하지 않고 읽는다.> Cloudflare 응답이 호출당 뉴런을 주고, 그 합계가
    #    per_model 에 이미 들어 있다. 곱셈은 세 번 연속 아래로 빗나갔다(24.64→25.08→
    #    25.24→실측 25.43). AGENTS.md 가 리랭커 비용을 "수십 뉴런일 것" 이라 추정했다가
    #    실측 13.6 을 보고 남긴 교훈과 같은 자리다.
    #
    # ⚠️ cf-stats 를 못 읽으면 실측이 <없다.> 그때 0 을 적으면 "안 썼다" 와 "재지 못했다"
    #    가 뭉개진다. None 으로 두고(= per_model_error 가 이유를 말한다) 예산 추정치는
    #    neurons_budgeted 로 따로 남긴다. 이름을 갈라야 둘을 섞어 읽지 않는다.
    measured_neurons: float | None = None
    measured_count = 0
    if cf_stats:
        measured_neurons = round(
            sum(float(m.get("neurons", 0.0)) for m in cf_stats.values()), 2
        )
        measured_count = max((int(m.get("count", 0)) for m in cf_stats.values()), default=0)

    result = {
        "conditions": conditions,
        "aborted_at": aborted_at,
        "requests_ok": len(latencies),
        # ⚠️ 2026-09-10 <이전>에 저장된 결과 파일 3개(S1-2026-09-10.json, -dryrun1, -dryrun2)
        #    에는 이 두 필드 대신 neurons_estimated 하나만 있다. 그건 측정 기록이라
        #    고치지 않았다. 옛 파일의 neurons_estimated 는 지금의 neurons_budgeted 에
        #    해당하고, 상수가 25.08 이던 시점의 값이다(실측보다 1.7% 낮다).
        "neurons_measured": measured_neurons,
        # 건당 실측. 다음 실행의 예산 상수를 <추측하지 않고> 여기서 되짚으라고 남긴다.
        "neurons_per_request_measured": (
            round(measured_neurons / measured_count, 2)
            if measured_neurons is not None and measured_count else None
        ),
        # 실행 전 상한 검사가 <가정했던> 값. 실측과 나란히 둬야 가정이 얼마나 빗나갔는지 보인다.
        "neurons_budgeted": round(len(latencies) * NEURONS_BUDGET_PER_REQUEST, 1),
        # 🔴 fallback 이 0 이 아니면 그 요청들은 LLM 을 안 탔다 = 측정이 오염됐다.
        "fallbacks": sum(fallback_questions.values()),
        "fallback_questions": fallback_questions,
        "end_to_end_ms": {
            "p50": round(_pct(latencies, 50)),
            "p95": round(_pct(latencies, 95)),
            "p99": round(_pct(latencies, 99)),
        } if latencies else None,
        "per_model": cf_stats,
        # per_model 이 null 이면 <재지 못한 것>이지 0 이 아니다. 둘을 뭉개지 않는다.
        "per_model_error": cf_stats_error,
        # 숫자를 박아두면 --count 를 바꾼 순간 <파일이 거짓말을 한다.> 실제 표본으로 쓴다.
        "p99_caveat": (
            f"표본 {len(latencies)}건이라 p99 는 상위 약 "
            f"{max(1, round(len(latencies) * 0.01))}건이 결정한다. p50·p95 만 신뢰한다."
        ),
        # 🔴 per_model 은 uvicorn 프로세스 수명 동안의 <누적>이다. 이 실행분만이 아니다.
        #    count 가 requests_ok 와 다르면 이전 실행이 섞인 것이다. 뭉개지 말고 드러낸다.
        "per_model_note": (
            "per_model 은 uvicorn 프로세스 누적치다. "
            "count 가 requests_ok 와 다르면 이전 실행분이 포함된 것이다. "
            "neurons_measured 도 같은 누적치이므로, count 가 requests_ok 와 같을 때만 "
            "이 실행분과 정확히 같다."
        ),
    }

    out = Path(__file__).parent / "results" / f"S1-{datetime.now():%Y-%m-%d}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n저장: {out}")
    return 1 if aborted_at else 0


if __name__ == "__main__":
    raise SystemExit(main())
