# 부하테스트 PR 2: 가짜 CF 서버 + S1 지연 기준선

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 진짜 LLM 을 태우지 않고도 채팅 경로 전체를 부하로 때릴 수 있게 만들고(가짜 CF 서버), 그 가짜 서버에 넣을 지연값을 <추측하지 않고> 진짜 LLM 380건으로 실측한다(S1).

**Architecture:** Cloudflare 호출의 기저 URL(`cf_base_url`)만 설정으로 빼고 기본값은 진짜 주소로 둔다. 부하테스트 때만 그 값을 로컬 가짜 서버(:9001)로 돌린다. "가짜 응답을 내는 플래그" 를 코드에 심지 않으므로, 운영에서 이 값이 잘못 들어가면 조용히 가짜 답변을 내보내는 대신 **Cloudflare 에 못 붙어 시끄럽게 실패한다.** 현업에서 WireMock 으로 하는 것과 같은 방식이다.

**Tech Stack:** Python 3.13 / FastAPI / httpx / 표준 라이브러리 `http.server` (가짜 서버에 새 의존성 없음) / psycopg (가짜 서버가 DB 에서 진짜 벡터 1개를 읽는다)

## Global Constraints

- **`cf_base_url` 의 기본값은 진짜 주소** `https://api.cloudflare.com/client/v4` 다. 기본값을 가짜로 두는 순간 운영 사고다.
- 가짜 서버는 **`ai-service/loadtest/` 아래**에만 둔다. `app/` 에는 가짜 응답 코드를 한 줄도 넣지 않는다.
- 가짜 서버는 **새 의존성을 쓰지 않는다.** 표준 라이브러리 + 이미 있는 `app.db` / `app.config` 재사용.
- 진짜 LLM 을 쓰는 것은 **Task 4(S1) 하나뿐**이다. Task 1~3 은 뉴런을 0 쓴다.
- **S1 예산 상한 380건 = 9,363 뉴런(하루 한도의 94%).** 스크립트가 이 상한을 코드로 강제한다.
- 주석·문서·커밋 메시지는 한국어. **em dash 금지** (쉼표·콜론·괄호로 대체).
- 커밋 메시지 형식: `<타입>: <한국어 요약>` (feat / fix / refactor / test / docs / chore).
- 브랜치: `feat/loadtest-fake-cf`. PR 로 간다(설명이 필요한 변경).
- PR 1(`feat/loadtest-observability`)이 **머지된 뒤에** 시작한다. 스택 브랜치를 만들지 않는다(AGENTS.md 2026-09-08 교훈).

---

## File Structure

| 파일 | 책임 |
|---|---|
| `ai-service/app/config.py` | `cf_base_url` 1줄 추가 |
| `ai-service/app/cf.py` | URL 조립에 그 값을 쓴다 + **호출당 지연을 모델별로 기록** |
| `ai-service/app/main.py` | `GET /internal/debug/cf-stats` — 모델별 호출수·뉴런·p50/p95/p99 |
| `ai-service/.env.example` | `CF_BASE_URL` 주석 (기본값이 진짜 주소라는 것을 적는다) |
| `ai-service/loadtest/fake_cf.py` | 가짜 CF 서버. 자는 시간·고정 응답·호출 카운터 |
| `ai-service/loadtest/fake_cf_check.py` | 자체 점검. 가짜 응답이 `app/` 의 파서를 실제로 통과하는지 |
| `ai-service/loadtest/s1_baseline.py` | S1 드라이버. 380건 상한 + 429 즉시 중단 + 시작 조건 기록 |
| `ai-service/loadtest/results/S1-<날짜>.json` | S1 결과물(시작 조건 + 수치). 커밋한다 |
| `.github/workflows/ci.yml` | `compileall` 대상에 `loadtest` 추가 |

**Task 를 나눈 기준.** Task 1 은 가짜 서버 없이 검증할 수 없고(설정만 바꿔서는 확인할 대상이 없다), Task 2 는 Task 1 없이 붙일 곳이 없다. 그래서 **"URL 설정 + 가짜 서버 + 자체 점검"이 한 덩어리(Task 1)** 다. Task 2(계측)는 S1 이 필요로 하는 것이고 가짜 서버로 검증되므로 따로 뗀다. Task 3 은 하루 한도를 태우는 되돌릴 수 없는 작업이라, 앞의 둘이 전부 초록불이 된 뒤에만 시작한다.

---

## Task 1: `cf_base_url` + 가짜 CF 서버

**Files:**
- Modify: `ai-service/app/config.py` (Cloudflare 설정 근처)
- Modify: `ai-service/app/cf.py` (`run()` 의 URL 조립 1줄)
- Modify: `ai-service/.env.example`
- Create: `ai-service/loadtest/fake_cf.py`
- Test: `ai-service/loadtest/fake_cf_check.py`
- Modify: `.github/workflows/ci.yml` (`compileall -q app loadtest`)

**Interfaces:**
- Produces:
  - 설정 `Settings.cf_base_url: str` (환경변수 `CF_BASE_URL`)
  - 가짜 서버 실행: `cd ai-service && .venv/bin/python -m loadtest.fake_cf [--port 9001] [--vector db|blocked|unit]`
  - 가짜 서버 `GET /stats` → `{"counts": {"<model>": n, ...}, "vector": "db"}`
  - Task 2·3 이 둘 다 이 서버 위에서 돈다.

- [ ] **Step 1: 브랜치를 딴다**

```bash
git checkout main && git pull
git checkout -b feat/loadtest-fake-cf
```

- [ ] **Step 2: 실패하는 자체 점검을 쓴다**

`ai-service/loadtest/fake_cf_check.py` 를 새로 만든다.

이 점검이 재는 것은 "서버가 200 을 준다" 가 아니라 **"가짜 응답이 `app/` 의 진짜 파서를 통과하는가"** 다. 응답 모양이 조금만 달라도 `cf.text_of` 가 빈 문자열을 돌려주고, 그러면 `generator.generate` 가 `GenerationFailed` 를 던져 **부하테스트 전체가 503 을 재게 된다.**

```python
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

import os
import threading

# ⚠️ get_settings 는 lru_cache 라 <처음 읽는 순간> 값이 굳는다.
#    그래서 app.* 을 import 하기 <전에> 환경변수를 세팅한다.
os.environ["CF_BASE_URL"] = "http://127.0.0.1:9101"
os.environ.setdefault("CF_ACCOUNT_ID", "fake")
os.environ.setdefault("CF_API_TOKEN", "fake")

from app import cf                      # noqa: E402
from app.config import get_settings     # noqa: E402
from app.generator import FALLBACK_TOKEN  # noqa: E402
from loadtest import fake_cf            # noqa: E402


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

    server.shutdown()
    print(f"\n{'실패 ' + ', '.join(failures) if failures else '전부 통과'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: 점검을 돌려 실패를 확인한다**

```bash
cd ai-service && .venv/bin/python -m loadtest.fake_cf_check
```

기대: `ModuleNotFoundError: No module named 'loadtest.fake_cf'`

- [ ] **Step 4: `cf_base_url` 설정을 추가한다**

`ai-service/app/config.py` 의 `cf_account_id` / `cf_api_token` 바로 아래에 넣는다.

```python
    # ⚠️ 기본값은 <진짜 주소>다. 부하테스트에서만 로컬 가짜 서버로 돌린다.
    #
    # 왜 "가짜 응답을 내는 플래그" 가 아니라 URL 인가
    # ─────────────────────────────────────────────────────────────────
    # 플래그를 코드에 심으면, 운영에서 그게 켜졌을 때 <조용히 가짜 답변>이 나간다.
    # URL 이면 운영에 잘못 들어갔을 때 Cloudflare 에 못 붙어 <시끄럽게 실패>한다.
    # 조용한 실패와 시끄러운 실패 중 고를 수 있다면 항상 시끄러운 쪽이다
    # (config._check_prod 가 같은 논리로 짜여 있다).
    # 현업에서 WireMock 으로 외부 API 를 갈아끼우는 것과 같은 방식이다.
    cf_base_url: str = "https://api.cloudflare.com/client/v4"
```

- [ ] **Step 5: `cf.py` 가 그 값을 쓰게 한다**

`ai-service/app/cf.py` 의 `run()` 안, `url = ...` 한 줄을 바꾼다.

```python
    url = f"{s.cf_base_url}/accounts/{s.cf_account_id}/ai/run/{model}"
```

- [ ] **Step 6: `.env.example` 에 적는다**

`CF_ACCOUNT_ID` / `CF_API_TOKEN` 아래에 붙인다.

```
# 부하테스트에서만 쓴다. 비워두면 진짜 Cloudflare 로 간다.
# 가짜 서버: cd ai-service && .venv/bin/python -m loadtest.fake_cf
# CF_BASE_URL=http://127.0.0.1:9001
```

- [ ] **Step 7: 가짜 CF 서버를 만든다**

`ai-service/loadtest/fake_cf.py`.

```python
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

# 🔴 이 값들은 <아직 실측이 아니다.> S1(Task 3)이 재서 여기를 덮어쓴다.
#    자리표시자인 채로 S2 를 돌리면 그 수치는 아무 의미가 없다.
LATENCY_MS = {"embed": 120, "rerank": 250, "generate": 1200}

# 가짜 답변. 짧고, NO_ANSWER 를 포함하지 않는다(포함하면 전부 fallback 이 된다).
ANSWER = "부하테스트용 고정 답변입니다."

_counts: Counter[str] = Counter()
_lock = threading.Lock()
_vector: list[float] = []


def counts() -> Counter[str]:
    """모델별 호출 횟수. <실행 전후로 비교>해서 그 경로를 실제로 탔는지 본다.

    0 이면 그 경로를 안 탄 것이므로 그 측정은 무효다.
    """
    with _lock:
        return _counts.copy()


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
            self._send(200, {"counts": dict(counts()), "latency_ms": LATENCY_MS})
        else:
            self._send(404, {"success": False, "errors": ["없는 경로"]})

    def do_POST(self) -> None:
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
            kind, result = "embed", self._embedding(payload, s.embedding_dim)
        elif model == s.reranker_model:
            kind, result = "rerank", self._rerank(payload)
        else:
            kind, result = "generate", self._generate()

        time.sleep(LATENCY_MS[kind] / 1000)
        self._send(200, {"success": True, "result": result})

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
        return {"response": [{"id": i, "score": 1.0 - i * 0.01} for i in range(n)]}

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
    global _vector
    _vector = _load_vector(vector_mode)
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
```

- [ ] **Step 8: 점검을 돌려 통과를 확인한다**

```bash
cd ai-service && .venv/bin/python -m loadtest.fake_cf_check
```

기대: 7줄 전부 `OK`, 마지막 줄 `전부 통과`, 종료코드 0.

- [ ] **Step 9: CI 가 `loadtest` 도 컴파일하게 한다**

`.github/workflows/ci.yml` 의 마지막 단계를 바꾼다.

```yaml
      - name: 문법 검사 (컴파일 가능 여부만)
        run: python -m compileall -q app loadtest
```

- [ ] **Step 10: 실제 채팅이 가짜 서버로 도는지 종단 확인**

두 창을 띄운다.

```bash
# 창 1
cd ai-service && .venv/bin/python -m loadtest.fake_cf

# 창 2
cd ai-service && CF_BASE_URL=http://127.0.0.1:9001 .venv/bin/uvicorn app.main:app --port 8001
```

```bash
curl -s localhost:8001/internal/chat -H 'Content-Type: application/json' \
  -d '{"bot_id":"628d2785-a128-486c-a1ac-556f19f06de3","message":"연차는 며칠인가요?"}' | head -c 400
curl -s localhost:9001/stats
```

기대:
- 답변이 `부하테스트용 고정 답변입니다.`
- **`is_fallback` 이 `false`** (게이트를 통과했다는 증거. `true` 면 벡터가 잘못 실린 것이라 측정이 무효다)
- `/stats` 의 counts 에 임베딩·리랭커·생성 **셋 다** 1 이상

- [ ] **Step 11: 커밋**

```bash
git add ai-service/app/config.py ai-service/app/cf.py ai-service/.env.example \
        ai-service/loadtest .github/workflows/ci.yml
git commit -m "feat: 가짜 Cloudflare 서버를 붙여 LLM 없이 채팅 경로를 부하로 때릴 수 있게 한다"
```

---

## Task 2: 모델별 지연 계측 + `/internal/debug/cf-stats`

**Files:**
- Modify: `ai-service/app/cf.py` (`run()` + 누적 dict)
- Modify: `ai-service/app/main.py` (엔드포인트 1개)
- Test: `ai-service/loadtest/fake_cf_check.py` (케이스 추가)

**Interfaces:**
- Consumes: Task 1 의 가짜 서버(지연이 알려진 값이라 계측이 맞는지 검증할 수 있다)
- Produces:
  - `cf.latency_percentiles() -> dict[str, dict]` — 모델별 `{"count", "p50", "p95", "p99"}` (ms)
  - `GET /internal/debug/cf-stats` → `{"<model>": {"count": n, "neurons": x, "p50": .., "p95": .., "p99": ..}}`
  - Task 3(S1) 이 이 엔드포인트에서 **모델별 p50** 을 읽어 `fake_cf.LATENCY_MS` 에 넣는다.

**왜 필요한가.** S1 이 얻어야 하는 것은 "채팅 한 번이 몇 초" 가 아니라 **모델별 지연**이다. 가짜 서버는 임베딩·리랭커·생성을 각각 다른 시간만큼 자야 하는데, 채팅 전체 시간만 알면 그 셋으로 나눌 방법이 없다. 프로세스 안에서만 알 수 있는 값이라 밖으로 꺼내는 문이 필요하다.

- [ ] **Step 1: 실패하는 점검을 추가한다**

`ai-service/loadtest/fake_cf_check.py` 의 `main()` 안, ④ 카운터 검사 **아래**에 붙인다.

```python
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
```

- [ ] **Step 2: 돌려서 실패를 확인한다**

```bash
cd ai-service && .venv/bin/python -m loadtest.fake_cf_check
```

기대: `AttributeError: module 'app.cf' has no attribute 'latency_percentiles'`

- [ ] **Step 3: `cf.py` 에 지연 기록을 붙인다**

`run()` 의 POST 를 감싼다.

```python
    started = time.perf_counter()
    resp = _client().post(url, json=payload)
    _latencies.setdefault(model, []).append((time.perf_counter() - started) * 1000)
```

파일 맨 위에 `import time` 을 추가하고, `_neurons` 선언 아래에 붙인다.

```python
# ── 지연(ms) 집계 ──────────────────────────────────────────────────────
#
# 왜 뉴런과 <따로> 두나: 뉴런은 실패한 호출에 없지만 지연은 실패한 호출에도 있다.
# 한 dict 에 뭉치면 "느렸다" 와 "비쌌다" 가 같은 자리에 섞인다.
#
# ⚠️ 누적은 <프로세스 수명 동안> 쌓인다. 리셋 함수를 두지 않은 것은 일부러다 —
#    "리셋했나?" 를 사람이 기억해야 하는 순간 그 측정은 못 믿는다.
#    측정 구간의 시작은 <프로세스를 다시 띄우는 것>으로 만든다(s1_baseline 이 그렇게 한다).
#
# ⚠️ 스레드 안전하지 않다. _neurons 와 같은 이유이고 같은 한계다(측정용 근사치).
_latencies: dict[str, list[float]] = {}


def latency_percentiles() -> dict[str, dict[str, float]]:
    """모델별 호출 수와 p50/p95/p99(ms).

    ⚠️ 평균을 안 준다. 평균은 느린 꼬리를 감춘다 —
       이 저장소는 avg_faithfulness 로 이미 한 번 데였다(생존 편향).
    """
    out: dict[str, dict[str, float]] = {}
    for model, values in _latencies.items():
        ordered = sorted(values)
        def pct(p: float) -> float:
            # nearest-rank. 표본이 적을 때 보간이 <있지도 않은 값>을 만들지 않는다.
            idx = max(0, min(len(ordered) - 1, int(-(-len(ordered) * p // 100)) - 1))
            return ordered[idx]
        out[model] = {
            "count": len(ordered),
            "p50": pct(50),
            "p95": pct(95),
            "p99": pct(99),
        }
    return out
```

- [ ] **Step 4: 점검 통과를 확인한다**

```bash
cd ai-service && .venv/bin/python -m loadtest.fake_cf_check
```

기대: `⑤ 생성 p50 계측` 포함 전부 `OK`.

- [ ] **Step 5: 엔드포인트를 붙인다**

`ai-service/app/main.py` 의 `/health` 아래에 넣는다.

```python
@app.get("/internal/debug/cf-stats")
def cf_stats() -> dict:
    """모델별 Cloudflare 호출 수·뉴런·지연 백분위. 부하테스트 S1 이 읽는다.

    🔴 이 값은 <이 프로세스가 시작된 뒤>의 누적이다. 측정 구간을 나누려면
       프로세스를 다시 띄운다. 리셋 API 를 안 두는 이유는 cf._latencies 주석에 있다.

    ⚠️ /internal/* 이라 인증이 없다. 여기서 나가는 것은 숫자뿐이고 문서 내용도
       봇 정보도 없지만, 그래도 <노출되지 않는다>는 전제 위에 있다
       (compose 가 ai-service 에 ports: 를 쓰지 않는다).
    """
    neurons = cf.neurons_used()
    stats = cf.latency_percentiles()
    for model, row in stats.items():
        row["neurons"] = neurons.get(model, 0.0)
    return stats
```

`from . import cf` 가 이미 있는지 확인하고 없으면 추가한다.

- [ ] **Step 6: 실제로 열리는지 확인한다**

Task 1 Step 10 의 두 창을 그대로 두고 채팅을 몇 번 더 부른 뒤:

```bash
curl -s localhost:8001/internal/debug/cf-stats
```

기대: 모델 3개(임베딩·리랭커·생성)가 각각 `count`·`p50`·`p95`·`p99`·`neurons`(가짜라 0.0)를 가진다.

- [ ] **Step 7: 커밋**

```bash
git add ai-service/app/cf.py ai-service/app/main.py ai-service/loadtest/fake_cf_check.py
git commit -m "feat: Cloudflare 호출 지연을 모델별로 재고 cf-stats 로 꺼낸다"
```

---

## Task 3: S1 지연 기준선 (진짜 LLM 380건)

**Files:**
- Create: `ai-service/loadtest/s1_baseline.py`
- Create: `ai-service/loadtest/results/S1-<날짜>.json` (스크립트가 쓴다. 커밋한다)
- Modify: `ai-service/loadtest/fake_cf.py` (`LATENCY_MS` 를 실측값으로)

**Interfaces:**
- Consumes: Task 2 의 `GET /internal/debug/cf-stats`
- Produces: `fake_cf.LATENCY_MS` 의 **실측값**. PR 3(S2)의 모든 수치가 이 값 위에 선다.

🔴 **이 Task 는 하루 한도의 94% 를 태운다. 되돌릴 수 없다.** Task 1·2 가 전부 초록불이고, 그날 다른 측정(평가 실행·재임베딩)이 없을 때만 시작한다.

- [ ] **Step 1: 드라이버를 쓴다**

`ai-service/loadtest/s1_baseline.py`.

```python
"""S1 — 가짜 서버에 넣을 지연값을 <추측하지 않고> 진짜 LLM 으로 실측한다.

실행:
    cd ai-service && .venv/bin/python -m loadtest.s1_baseline \
        --email you@example.com --password '...' \
        --bot-id 628d2785-a128-486c-a1ac-556f19f06de3

🔴 하루 한도의 94% 를 태운다. 다른 측정이 없는 날에 돌릴 것.

왜 380건인가
─────────────────────────────────────────────────────────────────────────────
근거 있는 질문 1건 = 24.64 뉴런(생성 23.77 + 리랭커 0.85 + 임베딩 0.025).
상한은 10,000 / 24.64 = 406건. 380 을 쓰고 약 640 뉴런(26건)을 남긴다.

남기는 이유 둘:
  ① 한도를 완전히 태우면 <언제 풀리는지 모른다.> 실측상 대시보드가 0/10k 로
     리셋돼도 차단은 안 풀렸고, 실제로는 소진 시각에서 약 24~33시간 뒤였다.
  ② 스크립트 버그를 나중에 발견해도 남은 26건으로 최소한 확인은 할 수 있다.

🔴 부분 측정을 정상 측정처럼 남기지 않는다
─────────────────────────────────────────────────────────────────────────────
이 저장소는 평가 16문항이 전부 429 로 죽었는데 실행이 completed 로 남아
<그 실행을 유효한 측정으로 착각한> 적이 있다.
그래서 429·503·비200 이 하나라도 나오면 <즉시 멈추고> 결과 파일에
"aborted_at" 을 적는다. 끝까지 돈 것처럼 보이는 파일을 만들지 않는다.

p99 의 한계 (리포트에 그대로 적을 것)
─────────────────────────────────────────────────────────────────────────────
380건이면 p99 는 상위 약 4건이 결정한다. 100건이면 최악 1건이 곧 p99 라 우연이
지표가 된다. 튼튼하려면 1,000건 이상인데 그건 이틀 반 치 한도라 못 한다.
p50·p95 는 380건이면 충분하고, <S1 이 실제로 하는 일에 쓰이는 것은 p50 이다.>
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
QUESTIONS = [
    "정규직의 연차 휴가는 며칠인가요?",
    "정규직의 시용 기간은 얼마인가요?",
    "정규직의 업무용 컴퓨터 교체 주기는 어떻게 되나요?",
    "법인카드는 어느 직급부터 쓸 수 있나요?",
    "출산 전후 휴가는 며칠인가요?",
]

MAX_REQUESTS = 380          # 예산 상한. 코드로 강제한다.
NEURONS_PER_REQUEST = 24.64


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
    fallbacks = 0
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
            fallbacks += 1
        if (i + 1) % 20 == 0:
            print(f"  {i + 1}/{args.count}  p50={_pct(latencies, 50):.0f}ms")

    # 모델별 지연은 Python 프로세스 안에서만 알 수 있다.
    cf_stats = client.get(f"{args.ai}/internal/debug/cf-stats").json()

    result = {
        "conditions": conditions,
        "aborted_at": aborted_at,
        "requests_ok": len(latencies),
        "neurons_estimated": round(len(latencies) * NEURONS_PER_REQUEST, 1),
        # 🔴 fallback 이 0 이 아니면 그 요청들은 LLM 을 안 탔다 = 측정이 오염됐다.
        "fallbacks": fallbacks,
        "end_to_end_ms": {
            "p50": round(_pct(latencies, 50)),
            "p95": round(_pct(latencies, 95)),
            "p99": round(_pct(latencies, 99)),
        } if latencies else None,
        "per_model": cf_stats,
        "p99_caveat": "표본 380건이라 p99 는 상위 약 4건이 결정한다. p50·p95 만 신뢰한다.",
    }

    out = Path(__file__).parent / "results" / f"S1-{datetime.now():%Y-%m-%d}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n저장: {out}")
    return 1 if aborted_at else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: 5건으로 예행연습한다 (123 뉴런)**

**전량을 돌리기 전에 반드시 한다.** 로그인 실패·봇 id 오타·필드 이름 오타를 380건 태우고 나서 발견하면 하루를 잃는다.

```bash
docker compose up -d
cd api && ./gradlew bootRun &          # 진짜 CF_BASE_URL 로 (환경변수를 지운 상태)
cd ai-service && .venv/bin/uvicorn app.main:app --port 8001
cd ai-service && .venv/bin/python -m loadtest.s1_baseline \
  --email <계정> --password '<비번>' --bot-id 628d2785-a128-486c-a1ac-556f19f06de3 --count 5
```

기대: `requests_ok: 5`, **`fallbacks: 0`**, `aborted_at: null`, `per_model` 에 모델 3개.

🔴 `fallbacks` 가 0 이 아니면 **거기서 멈춘다.** 그 질문은 근거를 못 찾은 것이라 생성을 안 탔고, 그대로 380건을 돌리면 생성 지연이 아니라 fallback 지연을 재게 된다. `QUESTIONS` 를 코퍼스에 맞게 고친 뒤 다시 5건을 돌린다.

- [ ] **Step 3: Python 을 재시작하고 380건을 돌린다**

누적이 프로세스 수명 동안 쌓이므로, 예행연습 5건이 섞이지 않게 uvicorn 을 껐다 켠다.

```bash
cd ai-service && .venv/bin/python -m loadtest.s1_baseline \
  --email <계정> --password '<비번>' --bot-id 628d2785-a128-486c-a1ac-556f19f06de3
```

약 8~13분 걸린다(1건당 1.2~2초 가정). 중단되면 `aborted_at` 이 파일에 남는다.

- [ ] **Step 4: 실측값을 가짜 서버에 넣는다**

`ai-service/loadtest/fake_cf.py` 의 `LATENCY_MS` 를 결과 파일의 `per_model[*].p50` 으로 바꾸고, 주석의 "아직 실측이 아니다" 를 지운다.

```python
# ✅ S1 실측값(2026-09-XX, results/S1-2026-09-XX.json). p95 가 아니라 <p50> 이다 —
#    가짜 서버가 재현해야 하는 것은 최악이 아니라 <보통>이다. p95 를 넣으면
#    모든 요청이 최악의 시간을 쓰는, 실제로는 없는 세상을 재게 된다.
LATENCY_MS = {"embed": ..., "rerank": ..., "generate": ...}
```

- [ ] **Step 5: 커밋**

```bash
git add ai-service/loadtest/s1_baseline.py ai-service/loadtest/results ai-service/loadtest/fake_cf.py
git commit -m "feat: 진짜 LLM 380건으로 모델별 지연을 재고 가짜 서버 값에 반영한다"
```

---

## Task 4: PR 올리기

- [ ] **Step 1: 푸시하고 PR 을 연다**

```bash
git push -u origin feat/loadtest-fake-cf
gh pr create --title "feat: 가짜 CF 서버 + S1 지연 기준선 (부하테스트 PR 2)" --body "$(cat <<'BODY'
## 무엇을 왜 바꿨나요

부하테스트를 하려면 진짜 LLM 을 못 쓴다. 근거 있는 질문 1건이 **24.64 뉴런**이고
하루 한도 10,000 이면 **406건**이다. 초당 5건으로 2분만 돌려도 600건이라 하루치를 넘긴다.
지속 부하는 원리적으로 불가능하다.

- Cloudflare 기저 URL 을 설정(`cf_base_url`)으로 뺐다. **기본값은 진짜 주소다.**
- 표준 라이브러리만 쓰는 가짜 CF 서버(`loadtest/fake_cf.py`)를 만들었다.
- 모델별 호출 지연을 재서 `GET /internal/debug/cf-stats` 로 꺼낸다.
- 그 값을 진짜 LLM **380건**으로 실측했다(S1).

## 어떻게 해결했나요

**"가짜 응답 플래그" 가 아니라 URL 인 이유.** 플래그를 코드에 심으면 운영에서
켜졌을 때 <조용히 가짜 답변>이 나간다. URL 이면 잘못 들어갔을 때 Cloudflare 에
못 붙어 시끄럽게 실패한다. WireMock 방식과 같다.

**임베딩 벡터를 아무거나 주면 안 된다는 함정.** 무작위 벡터를 주면 DB 청크와의
거리가 무작위라 `answerable_max_distance=0.44` 게이트에 걸려 **LLM 을 아예 안 부른다.**
그러면 재려던 생성 경로를 한 번도 안 타고 "빠르다" 는 거짓 결과가 나온다.
→ 기동할 때 DB 에서 진짜 청크 벡터 하나를 읽어 그대로 돌려준다(거리 0). 뒤집으면
항상 차단된다. **모드 하나로 두 경로를 다 잰다.**

```
$ .venv/bin/python -m loadtest.fake_cf_check
(여기에 실제 실행 결과를 붙일 것)

$ .venv/bin/python -m loadtest.s1_baseline ... --count 380
(여기에 실제 결과 요약을 붙일 것)
```

## 한계 & 트레이드오프

- 🔴 **S1 의 p99 는 못 믿는다.** 380건이면 p99 를 상위 약 4건이 결정한다.
  1,000건 이상이어야 튼튼한데 그건 이틀 반 치 한도다. **p50·p95 만 쓴다.**
- 🔴 **가짜 서버는 "고정 지연" 이다.** 진짜 LLM 은 분포가 있고 가끔 몇 초씩 튄다.
  그 꼬리는 재현되지 않으므로, PR 3 이후의 p99 는 <우리 서버의 포화>만 반영한다.
  LLM 쪽 꼬리는 안 들어 있다.
- 🔴 **뉴런 계산은 AGENTS.md 의 실측(평가 1회 804)에서 채점분을 뺀 값이다.** 결과 파일의
  `neurons_estimated` 는 추정이고, 실제 소모는 `cf-stats` 의 `neurons` 가 정확하다.
- **`cf._latencies` 는 스레드 안전하지 않다.** `_neurons` 와 같은 한계다(측정용 근사치).
  동시 호출이 겹치면 몇 건이 어긋날 수 있다.
- **누적 리셋 API 가 없다.** 측정 구간의 시작은 프로세스 재시작으로 만든다.
  "리셋했나?" 를 사람이 기억해야 하는 순간 그 측정은 못 믿기 때문이다.
- **재보지 않은 것:** 가짜 서버 자체의 처리량 상한. `ThreadingHTTPServer` 라
  동시 수백이면 그쪽이 먼저 막힐 수 있다. PR 3 에서 `/stats` 카운터와 요청 수를
  대조해 확인한다.

## 검토한 대안과 선택 이유

| 대안 | 기각 이유 |
|---|---|
| `mock_llm=true` 같은 플래그를 `app/` 에 심기 | 운영에서 켜지면 조용히 가짜 답변이 나간다. URL 이면 시끄럽게 실패한다 |
| 진짜 LLM 으로 부하테스트 | 하루 406건이 상한. 초당 5건 2분이면 이미 초과한다 |
| 가짜 서버가 무작위 벡터를 반환 | 게이트에 걸려 LLM 을 안 탄다. "빠르다" 는 거짓 결과가 나온다 |
| WireMock / responses 같은 라이브러리 | 별도 프로세스로 띄워야 하고 의존성이 는다. 표준 라이브러리 50줄로 되는 일이다 |
| 채팅 전체 지연만 재고 셋으로 나누기 | 임베딩·리랭커·생성의 비율을 <모른다>. 나누면 그게 가정값이 된다 |
BODY
)"
```

⚠️ `gh pr create` 까지가 이 계획의 끝이다. **CI 결과를 폴링하지 않는다.**

---

## Self-Review

**스펙 대비 커버리지**

| 스펙(PR 2) 항목 | 담당 |
|---|---|
| `cf_base_url` 설정 2줄 (`config.py` + `cf.py:57`) | Task 1 Step 4·5 |
| 가짜 CF 서버, 표준 라이브러리만 | Task 1 Step 7 |
| 기본값은 진짜 주소 = 잘못 들어가면 시끄럽게 실패 | Task 1 Step 4 (주석에 근거) |
| 가짜 서버 ① 모델별로 잔다 | `LATENCY_MS` + `time.sleep` |
| 가짜 서버 ② 모델별 고정 응답(1024차 벡터·짧은 문장·점수 배열) | `_embedding` / `_generate` / `_rerank` |
| 가짜 서버 ③ 호출 횟수를 센다 | `counts()` + `GET /stats` |
| 임베딩 벡터 함정(DB 에서 진짜 벡터를 읽는다) | `_load_vector`, `--vector db` |
| 게이트 경로도 같은 서버로 잰다 | `--vector blocked` |
| S1: 관리자 채팅 380건, 모델별 p50/p95/p99 | Task 3 (+ Task 2 의 `cf-stats`) |
| S1 중단 조건(429·503 즉시 멈춤, "N건에서 중단됨") | `aborted_at` |
| S1 을 늦게 돌린다 / 예행연습 | Task 3 Step 2 |
| 시작 조건 파일(커밋 SHA·설정값·시각) | `_conditions()` |
| p99 표본 한계를 리포트에 적는다 | `p99_caveat` + PR 본문 |
| `isFallback` 을 세서 경로 확인 | `fallbacks` + Task 1 Step 10 |

**스펙에 없는데 넣은 것 2개 (근거)**
- **`cf-stats` 엔드포인트와 지연 계측(Task 2).** 스펙은 S1 이 "모델별 p50/p95/p99" 를
  내놓으라고 하는데, 채팅 전체 시간만으로는 셋을 나눌 방법이 없다. 프로세스 안에서만
  아는 값이라 밖으로 꺼내는 문이 필요하다. **없으면 가짜 서버의 지연값이 결국 가정값이 된다** —
  이 PR 이 존재하는 이유가 그것을 피하는 것이다.
- **`--vector unit` 모드.** 자체 점검이 DB 없이 돌게 한다. DB 를 요구하면 CI 에서도
  개발자 기계에서도 "돌리기 귀찮은 검사" 가 되고, 이 저장소는 **짜둔 검사가 아무 데서도
  안 돌아** 오픈 리다이렉트가 뚫린 적이 있다.

**타입·이름 일관성**: `LATENCY_MS` 의 키(`embed`/`rerank`/`generate`)가 `do_POST` 의 분기와
`fake_cf_check` 의 ⑤ 검사에서 일치한다. `build_server(port, vector_mode)` 시그니처가
`main()` 과 자체 점검 양쪽에서 같다. `cf.latency_percentiles()` 의 반환 모양
(`count`/`p50`/`p95`/`p99`)이 `main.cf_stats` 와 `s1_baseline` 의 `per_model` 읽기에서 일치한다.
포트: 가짜 서버 **9001**(운영용), 자체 점검 **9101**(충돌 방지).

---

## 🔴 사후 정정 (2026-09-11, main 으로 옮기며 덧붙임)

이 계획서는 **구현 전에** 쓴 것이고 PR #101 로 머지됐다. **원문은 고치지 않는다.**
실측 결과는 `../2026-09-10-loadtest-s1-result.md` 에 있다.

### ① 380건이 아니라 350건 상한 · 327건 실측이다

- `s1_baseline.py` 의 `MAX_REQUESTS` 는 **350** 으로 굳었다.
- 실행은 **327건에서 중단**됐다. 327건째가 422 `ANSWER_INCOMPLETE` 였고 드라이버가
  거기서 멈췄다. **계획서가 요구한 중단 장치가 실제로 걸린 것이라 설계대로다** ("끝까지
  돈 것처럼 보이는 부분 측정을 만들지 않는다"). 그 시점에 이미 하루 한도의 86% 를 쓴
  상태라 계속 돌았으면 한도를 넘겼을 것이다.
- 그래서 p99 는 상위 약 4건이 아니라 **약 3건**이 결정한다. 결과 JSON 의
  `p99_caveat` 문구도 그에 맞춰 나갔다. **p50 · p95 만 믿는다는 결론은 그대로다.**

### ② `ANSWER_INCOMPLETE` 의 안내 문구가 반증됐다

계획서는 이 코드를 "재시도로 안 풀리는 실패" 로 전제하고 있었다. 실측은 다르다.
실패한 그 질문을 **같은 실행에서 66번 물어 65번 성공**했다. 문구가
*"같은 질문을 다시 보내도 같은 결과"* 라고 단언하는데 98.5% 는 성공한다.
`generator.generate` 가 잘림과 빈 응답을 같은 `GenerationFailed` 로 던지는 것이
그 아래에 있다. **고치지 않았고 별도 슬라이스다** (S1 결과 문서 §4).

### ③ 가짜 CF 서버는 "50줄" 이 아니라 181줄이다

늘어난 몫은 모드 전환, 호출 카운터, DB 에서 실제 청크 벡터를 읽는 부분이다.
**표준 라이브러리만 쓴다는 조건과 "WireMock 을 안 쓴다" 는 근거는 그대로 유효하다.**

### ④ 계획서가 예상하지 못한 것 둘

- **실행 중 지연이 단조 상승했다** (20건째 p50 1,676ms, 320건째 1,779ms, +6%).
  🔴 다만 이 두 값은 stdout 으로만 보고 결과 파일에 안 남겨 **재확인이 안 된다.**
  드라이버가 중간 스냅샷을 JSON 에 남기게 고칠 것.
- **세션 id 가 실행마다 겹친다** (`s1-0` ~ `s1-N`). 드라이런 2회가 같은 id 를 재사용해
  집계가 66 이 아니라 67 로 샜다. `s1-<시작시각>-<i>` 처럼 유일하게 만들 것.
