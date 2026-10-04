"""채점 모델 비교 v2 의 검색 도구. 질문마다 근거 청크를 실제 검색으로 뽑는다(스펙 2-3절).

실행:
    cd ai-service
    $PY -m tools.judge5v2_search --bot hr=12 --bot shop=13 --bot manual=14 --bot finance=15

입력은 testdata/judge5v2/questions.jsonl, 출력은 testdata/judge5v2/retrieved.jsonl 이다.
판정이 정해진 질문(ok, answerable, max_distance)은 건너뛴다. 뉴런을 다시 쓰지 않기 위해서다.
호출 실패(rerank_failed, keyword_failed)로 버린 질문은 다시 검색하고, 새 줄을 덧붙인다(계획 형식 2).

서비스 코드(app/)는 고치지 않는다. 대신 세 가지를 바깥에서 한다.
1. 질문 임베딩을 한 번만 만든다. search 안의 embed_one 을 그 벡터를 돌려주는 함수로 잠시 바꾼다.
   가장 가까운 청크의 거리를 따로 재는 데도 같은 벡터를 쓴다. 임베딩을 두 번 부르면 뉴런이 두 배다.
2. 리랭커와 키워드 검색의 실패 경고를 붙잡는다. 둘 다 실패해도 search 는 결과를 돌려주므로,
   경고를 보지 않으면 설정과 다른 순서의 근거가 시험지에 들어간다.
3. search 가 돌려준 앞 200자(preview)가 아니라 fetch_contents 로 전문을 읽는다.

검색 전에 두 가지를 확인하고 다르면 멈춘다.
- 검색 설정이 config.py 의 기본값과 같은가(스펙 2-3절의 "기본 설정 그대로"). 셸에 RERANKER_PROVIDER=local_int8
  같은 값이 남아 있으면 시험지에는 Cloudflare 리랭커로 뽑았다고 적히지만 실제는 다르다. 기본값과 다르게
  돌려야 하면 --allow-nondefault 를 주고, 그때는 결과 줄마다 다른 값을 nondefault 에 남긴다.
- --bot 의 분야와 번호가 testdata/judge5v2/bots.json(E1 이 만든 기록)과 같은가. answerable 로 버린 질문은
  다시 검색하지 않으므로, 분야와 봇을 잘못 짝지은 결과는 다시 돌려도 고쳐지지 않는다.
"""
from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter
from unittest import mock

from app import cf, retriever
from app.config import Settings, get_settings
from app.db import cursor

from .judge5v2_files import (
    BOTS, DOMAINS, PROTECTED_BOTS, QUESTIONS, RETRIEVED, SETTLED_DROPS, append_jsonl, latest_by_qid, read_json,
    read_jsonl,
)

# 시험지에 적을 검색 설정(스펙 2-3절). 검색 결과를 바꾸는 값만 고른다.
# rerank_fusion_k 는 rerank_fusion 이 꺼져 있으면 쓰이지 않는다. 그래도 적는다. 켜면 순서를 바꾸는 값이기 때문이다.
SETTING_KEYS = (
    "top_k", "max_distance", "answerable_max_distance", "reranker_enabled", "reranker_provider",
    "reranker_model", "rerank_candidates", "rerank_fusion", "rerank_fusion_k", "hybrid_enabled",
    "hybrid_candidates", "hybrid_rrf_k", "embedding_model",
)
# app/retriever.py 의 경고 문장 첫머리. 서비스 코드의 문장이 바뀌면 search_check 가 아니라 실제 실행에서만
# 드러나므로, 실행 태스크 E3 이 리랭커 실패 수를 run_log.md 에 적어 둔다.
RERANK_FAIL = "리랭킹 실패"
KEYWORD_FAIL = "키워드 검색 실패"


def search_settings() -> dict:
    s = get_settings()
    return {k: getattr(s, k) for k in SETTING_KEYS}


def nondefault_settings(current: dict) -> dict[str, dict]:
    """current(search_settings 의 결과) 중 config.py 의 기본값과 다른 값. {키: {"default": 기본값, "actual": 실제 값}}.

    기준을 config.py 의 기본값으로 둔 이유: 스펙 2-3절의 "기본 설정" 은 서비스의 기본값이다. .env 가 같은 값을
    다시 적는 것(TOP_K=5 등)은 통과하고, 셸 환경변수든 .env 든 기본값과 다르면 출처와 관계없이 걸린다.
    get_default(call_default_factory=True) 는 Settings 클래스에 적힌 기본값이다(환경변수를 읽기 전의 값).
    .default 대신 쓰는 이유: 기본값을 default_factory(함수)로 적은 필드는 .default 가 빈 표시값이라 늘 다르다고 나온다.
    """
    out = {}
    for k, v in current.items():
        default = Settings.model_fields[k].get_default(call_default_factory=True)
        if v != default:
            out[k] = {"default": default, "actual": v}
    return out


def settings_conflicts(rows: list[dict], current: dict) -> list[str]:
    """이미 있는 검색 줄 중 지금 설정과 다른 설정으로 뽑은 줄. "qid: 키(줄의 값 -> 지금 값)" 목록이다.

    판정이 정해진 질문(settled_qids)은 다시 검색하지 않는다. 그래서 --allow-nondefault 로 끝낸 질문이 있으면
    기본 설정으로 다시 돌려도 그 질문은 건너뛰어져, 한 파일에 서로 다른 설정의 근거가 섞인다. 섞이기 전에 멈춘다.
    """
    out = []
    for r in rows:
        got = r.get("settings") or {}
        keys = [k for k in current if got.get(k) != current[k]]
        if keys:
            out.append(f"{r['qid']}: " + ", ".join(f"{k}({got.get(k)!r} -> {current[k]!r})" for k in keys))
    return out


def check_bots_file(bots: dict[str, int], recorded: dict) -> None:
    """--bot 으로 받은 짝이 bots.json 의 기록과 같은지 본다. 다르면 멈춘다."""
    wrong = [f"{d}={n}(기록은 {recorded.get(d)})" for d, n in bots.items() if recorded.get(d) != n]
    if wrong:
        raise SystemExit(f"--bot 이 testdata/judge5v2/bots.json 과 다릅니다: {', '.join(wrong)}. "
                         f"bots.json 의 번호를 그대로 주세요(계획 E3 Step 1 의 BOTS 변수).")


def drop_reason(n_sources: int, top1: float | None, answerable: float | None) -> str | None:
    """빈 결과의 원인. 결과가 있으면 None 이다(스펙 2-3절).

    search 는 가장 가까운 청크가 answerable 보다 멀면 빈 목록을 돌려준다(근거 유무 판정). 그게 아니면서
    비었다면 모든 청크가 max_distance 컷에 걸린 것이다(검색용 컷).
    """
    if n_sources > 0:
        return None
    if top1 is None:
        raise RuntimeError("봇에 임베딩된 청크가 없습니다. 업로드가 끝났는지(documents.status 가 ready 인지) 확인하세요.")
    if answerable is not None and top1 > answerable:
        return "answerable"
    return "max_distance"


def warning_reason(messages: list[str]) -> str | None:
    if any(m.startswith(RERANK_FAIL) for m in messages):
        return "rerank_failed"
    if any(m.startswith(KEYWORD_FAIL) for m in messages):
        return "keyword_failed"
    return None


class _Catch(logging.Handler):
    """app.retriever 로거의 경고를 모은다. logging.Handler 를 상속하면 로거에 붙여 기록을 받을 수 있다."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())   # getMessage 는 %s 자리에 인자를 채운 문장이다


def top1_distance(bot_id: int, qvec: list[float]) -> float | None:
    """그 봇에서 가장 가까운 청크의 벡터 거리. 빈 결과의 원인을 가르는 데만 쓴다."""
    with cursor() as cur:
        cur.execute(
            "SELECT min(c.embedding <=> %s::vector) FROM chunks c "
            "WHERE c.bot_id = %s AND c.embedding IS NOT NULL",
            (qvec, bot_id),
        )
        v = cur.fetchone()[0]
    return None if v is None else float(v)


def search_one(bot_id: int, question: str, *, embed=None, search=None, fetch=None, top1=None) -> dict:
    """질문 하나를 검색해 형식 2 의 뒷부분(status 부터 sources 까지)을 돌려준다.

    embed, search, fetch, top1 은 점검에서 가짜를 넣으려고 받는다. None 이면 서비스의 함수를 쓴다.
    기본값을 인자 기본값(embed=retriever.embed_one)으로 두지 않는 이유: 그러면 모듈을 불러온 시점의 함수가
    고정돼, 아래에서 embed_one 을 바꿔 끼운 것과 섞일 수 있다.
    """
    embed = embed or retriever.embed_one
    search = search or retriever.search
    fetch = fetch or retriever.fetch_contents
    top1 = top1 or top1_distance
    s = get_settings()

    vec = embed(question)
    catch = _Catch()
    log = logging.getLogger("app.retriever")   # retriever.py 의 _log 와 같은 이름(__name__)이다
    log.addHandler(catch)
    try:
        # mock.patch.object(모듈, 이름, 값): with 블록 안에서만 모듈의 이름을 바꿔 끼우고 끝나면 되돌린다.
        # search 는 안에서 embed_one(query) 를 부르므로, 이렇게 하면 임베딩을 다시 부르지 않는다.
        with mock.patch.object(retriever, "embed_one", lambda _q: vec):
            sources = search(bot_id, question)
    finally:
        log.removeHandler(catch)

    d1 = top1(bot_id, vec)
    reason = warning_reason(catch.messages) or drop_reason(len(sources), d1, s.answerable_max_distance)
    contents = fetch([x.chunk_id for x in sources])
    lost = [x.chunk_id for x in sources if x.chunk_id not in contents]
    if lost:
        raise RuntimeError(f"검색이 돌려준 청크 {lost} 의 본문을 읽지 못했습니다. 검색 도중 문서가 지워졌는지 확인하세요.")
    return {
        "status": "ok" if reason is None else "dropped",
        "drop_reason": reason,
        "top1_distance": d1,
        "warnings": catch.messages,
        "sources": [{"chunk_id": x.chunk_id, "filename": x.filename, "content": contents[x.chunk_id]} for x in sources],
    }


def settled_qids(rows: list[dict]) -> set[str]:
    """판정이 정해진 질문. 질문마다 마지막 줄을 보고, ok 이거나 다시 해도 같은 원인으로 버린 질문만 넣는다."""
    return {r["qid"] for r in latest_by_qid(rows) if r["status"] == "ok" or r["drop_reason"] in SETTLED_DROPS}


def parse_bots(items: list[str]) -> dict[str, int]:
    """--bot hr=12 꼴을 {"hr": 12} 로 바꾼다. 보호한 봇 번호, 같은 분야를 두 번, 같은 번호를 두 분야에 준 것을 거절한다."""
    out: dict[str, int] = {}
    for item in items:
        domain, _, num = item.partition("=")   # partition 은 첫 "=" 에서 셋으로 자른다
        if domain not in DOMAINS or not num.isdigit():
            raise SystemExit(f"--bot 은 분야=번호 꼴입니다(예: hr=12). 분야는 {', '.join(DOMAINS)}. 받은 값: {item}")
        bot_id = int(num)
        if bot_id in PROTECTED_BOTS:
            raise SystemExit(f"봇 {bot_id}번은 이 실험에서 쓰지 않습니다(데모 봇과 리랭커 실험 봇). "
                             f"testdata/judge5v2/bots.json 의 번호를 주세요.")
        if domain in out:
            raise SystemExit(f"--bot 에 분야 {domain} 이 두 번 있습니다. 분야마다 한 번씩 주세요.")
        if bot_id in out.values():
            raise SystemExit(f"봇 {bot_id}번이 두 분야에 있습니다. 분야마다 다른 봇입니다(스펙 2-2절).")
        out[domain] = bot_id
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="질문마다 실제 검색으로 근거 청크 전문을 뽑는다")
    p.add_argument("--bot", action="append", required=True, help="분야=봇 번호. 분야마다 한 번씩")
    p.add_argument("--limit", type=int, default=None, help="이번 실행에서 검색할 최대 질문 수")
    p.add_argument("--allow-nondefault", action="store_true",
                   help="검색 설정이 기본값과 달라도 돌린다. 다른 값은 결과 줄의 nondefault 에 남는다")
    args = p.parse_args(argv)
    bots = parse_bots(args.bot)
    if not BOTS.exists():
        print("testdata/judge5v2/bots.json 이 없습니다. 계획 E1 이 봇을 만들고 남기는 파일입니다. E1 을 먼저 하세요.")
        return 1
    check_bots_file(bots, read_json(BOTS))
    settings = search_settings()
    diff = nondefault_settings(settings)
    if diff and not args.allow_nondefault:
        print("검색 설정이 config.py 의 기본값과 다릅니다(스펙 2-3절은 기본 설정 그대로 검색한다):")
        for k, d in diff.items():
            print(f"  - {k}: 기본값 {d['default']!r}, 지금 {d['actual']!r}")
        print("셸에 남은 환경변수(예: RERANKER_PROVIDER)나 .env 를 확인하세요. "
              "일부러 다르게 돌리려면 --allow-nondefault 를 주고 run_log.md 에 이유를 적으세요.")
        return 1
    if diff:
        print("기본값과 다른 설정으로 돌립니다(--allow-nondefault). 결과 줄마다 nondefault 에 남깁니다: "
              + ", ".join(f"{k}={d['actual']!r}" for k, d in diff.items()))

    questions = read_jsonl(QUESTIONS)
    ids = [q["qid"] for q in questions]
    dup = [k for k, n in Counter(ids).items() if n > 1]
    if dup:
        print(f"questions.jsonl 에 같은 qid 가 두 번 있습니다: {dup[:5]}. 고친 뒤 다시 실행하세요.")
        return 1
    existing = read_jsonl(RETRIEVED)
    if conflicts := settings_conflicts(existing, settings):
        print(f"retrieved.jsonl 에 지금과 다른 검색 설정으로 뽑은 줄이 {len(conflicts)}개 있습니다. 섞이지 않게 멈춥니다:")
        for c in conflicts[:10]:
            print(f"  - {c}")
        print("설정을 그 줄들과 같게 맞추거나, 그 줄들을 다른 이름의 파일로 옮긴 뒤 다시 실행하세요(지우지 말고 옮기세요).")
        return 1
    done = settled_qids(existing)
    todo = [q for q in questions if q["domain"] in bots and q["qid"] not in done][: args.limit]
    # 기본값과 다르게 돌린 실행은 줄마다 표시한다. 나중에 이 줄로 만든 문항이 기본 설정이 아니었음을 알 수 있게.
    extra = {"nondefault": diff} if diff else {}
    counts: Counter = Counter()
    for q in todo:
        row = search_one(bots[q["domain"]], q["question"])
        append_jsonl(RETRIEVED, {"qid": q["qid"], "domain": q["domain"], "bot_id": bots[q["domain"]],
                                 "settings": settings, **extra, **row})
        counts[(q["domain"], row["drop_reason"] or "ok")] += 1
    for (domain, reason), n in sorted(counts.items()):
        print(f"{domain}: {reason} {n}")
    print(f"이번 실행의 뉴런: {cf.neurons_used()}")
    rows = read_jsonl(RETRIEVED)
    tried, done = {r["qid"] for r in rows}, settled_qids(rows)
    mine = [q["qid"] for q in questions if q["domain"] in bots]
    never = sum(1 for qid in mine if qid not in tried)
    failed = sum(1 for qid in mine if qid in tried and qid not in done)
    if failed:
        # 종료 코드를 1 로 하지 않는다. 다시 해도 실패하면 그 줄이 판정이 되기 때문이다(계획 E3 Step 3).
        print(f"호출 실패로 버린 질문 {failed}개. 같은 명령을 다시 실행하면 그 질문만 다시 검색합니다.")
    if never:
        print(f"아직 검색하지 않은 질문 {never}개. 같은 명령을 다시 실행하면 이어서 합니다.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
