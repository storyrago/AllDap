"""tools.judge5v2_search 의 점검. DB 도 외부 API 도 쓰지 않는다(가짜 함수를 넣는다).

실행:  cd ai-service && python -m tools.judge5v2_search_check

이 도구가 틀리면 시험지에 서비스와 다른 근거가 들어간다. 앞 200자만 담기거나, 리랭커가 실패한 순서가
리랭커를 켠 설정으로 적히거나, 임베딩을 두 번 불러 뉴런을 두 배로 쓴다. 셋 다 결과 숫자로는 드러나지 않는다.
"""
from __future__ import annotations

import logging

from app import retriever
from app.schemas import Source

from .judge5v2_search import (
    SETTING_KEYS, check_bots_file, drop_reason, nondefault_settings, parse_bots, search_one, search_settings,
    settings_conflicts, settled_qids, warning_reason,
)


def _src(cid: int) -> Source:
    return Source(chunk_id=cid, document_id=1, filename=f"{cid}.md", score=0.9, preview="앞 200자")


def _fakes(sources: list[Source], warn: str | None = None, d1: float | None = 0.2,
           contents: dict | None = None) -> tuple[dict, dict]:
    calls = {"embed": 0}

    def embed(q: str) -> list[float]:
        calls["embed"] += 1
        return [0.5]

    def search(bot_id: int, q: str) -> list[Source]:
        # 실제 search 처럼 모듈의 embed_one 을 부른다. 바꿔 끼운 함수가 미리 만든 벡터를 돌려줘야 한다.
        assert retriever.embed_one(q) == [0.5]
        if warn:
            logging.getLogger("app.retriever").warning(warn)
        return sources

    def fetch(ids: list[int]) -> dict:
        return contents if contents is not None else {i: f"전문 {i}" for i in ids}

    return calls, {"embed": embed, "search": search, "fetch": fetch, "top1": lambda bot_id, vec: d1}


def check_search_one_returns_full_content() -> None:
    """시험지에는 앞 200자가 아니라 전문이 들어간다(스펙 2-3절)."""
    calls, f = _fakes([_src(1), _src(2)])
    row = search_one(9, "질문", **f)
    assert row["status"] == "ok" and row["drop_reason"] is None
    assert [s["content"] for s in row["sources"]] == ["전문 1", "전문 2"]
    assert [s["filename"] for s in row["sources"]] == ["1.md", "2.md"]
    assert calls["embed"] == 1          # 임베딩은 한 번만 부른다


def check_search_one_restores_embed_one() -> None:
    """embed_one 을 바꿔 끼운 것이 검색 뒤에 남으면 다음 질문이 앞 질문의 벡터로 검색된다."""
    original = retriever.embed_one
    _, f = _fakes([_src(1)])
    search_one(9, "질문", **f)
    assert retriever.embed_one is original


def check_rerank_failure_drops_question() -> None:
    _, f = _fakes([_src(1), _src(2)], warn="리랭킹 실패(원래 순서 유지) provider=cloudflare: HTTPError: 500")
    row = search_one(9, "질문", **f)
    assert row["status"] == "dropped" and row["drop_reason"] == "rerank_failed"
    assert row["warnings"] and row["sources"]   # 근거는 남겨 둔다. 왜 뺐는지 나중에 볼 수 있게


def check_keyword_failure_drops_question() -> None:
    _, f = _fakes([_src(1), _src(2)], warn="키워드 검색 실패(벡터 결과만 사용): OperationalError: x")
    assert search_one(9, "질문", **f)["drop_reason"] == "keyword_failed"


def check_empty_result_reasons() -> None:
    """빈 결과의 원인을 둘로 가른다(스펙 2-3절). 청크가 아예 없으면 원인이 아니라 준비 실수라서 멈춘다."""
    assert drop_reason(0, 0.99, 0.44) == "answerable"
    assert drop_reason(0, 0.30, 0.44) == "max_distance"
    assert drop_reason(2, 0.99, 0.44) is None
    try:
        drop_reason(0, None, 0.44)
    except RuntimeError:
        return
    raise AssertionError("청크가 없는 봇은 멈춰야 한다")


def check_missing_content_is_an_error() -> None:
    """검색이 돌려준 청크의 본문을 못 읽으면 앞 200자로 대신하지 않고 멈춘다."""
    _, f = _fakes([_src(1)], contents={})
    try:
        search_one(9, "질문", **f)
    except RuntimeError:
        return
    raise AssertionError("본문이 없으면 멈춰야 한다")


def check_parse_bots_refuses_protected() -> None:
    assert parse_bots(["hr=12", "shop=13"]) == {"hr": 12, "shop": 13}
    for bad in (["hr=1"], ["hr=7"], ["hr=8"], ["sales=12"], ["hr=x"]):
        try:
            parse_bots(bad)
        except SystemExit:
            continue
        raise AssertionError(bad)


def check_parse_bots_refuses_duplicates() -> None:
    """같은 분야를 두 번, 같은 번호를 두 분야에 주면 거절한다. answerable 판정은 다시 검색하지 않아 굳기 때문이다."""
    for bad in (["hr=12", "hr=13"], ["hr=12", "shop=12"]):
        try:
            parse_bots(bad)
        except SystemExit:
            continue
        raise AssertionError(bad)


def check_bots_file_must_match() -> None:
    recorded = {"hr": 12, "shop": 13, "manual": 14, "finance": 15}
    check_bots_file({"hr": 12, "shop": 13}, recorded)                    # 일부 분야만 줘도 된다
    for bad in ({"hr": 13}, {"shop": 12}, {"hr": 12, "manual": 99}):
        try:
            check_bots_file(bad, recorded)
        except SystemExit:
            continue
        raise AssertionError(bad)


def check_nondefault_settings_compares_with_config_defaults() -> None:
    """기준은 config.py 의 기본값이다. 셸에 남은 RERANKER_PROVIDER=local_int8 같은 값을 잡아야 한다."""
    from app.config import Settings
    defaults = {k: Settings.model_fields[k].get_default(call_default_factory=True) for k in SETTING_KEYS}
    # 스펙 2-3절이 글로 정한 값을 직접 못박는다. config.py 의 기본값이 바뀌면 위 비교는 따라 바뀌지만 이 줄은 실패한다.
    assert defaults["hybrid_enabled"] is True and defaults["reranker_enabled"] is True
    assert defaults["reranker_provider"] == "cloudflare"
    assert nondefault_settings(defaults) == {}
    changed = dict(defaults, reranker_provider="local_int8", top_k=8)
    assert nondefault_settings(changed) == {
        "reranker_provider": {"default": "cloudflare", "actual": "local_int8"},
        "top_k": {"default": defaults["top_k"], "actual": 8},
    }


def check_settings_conflicts_refuses_mixed_runs() -> None:
    """--allow-nondefault 로 뽑은 줄이 있으면 기본 설정으로 다시 돌릴 때 멈춘다. 같은 설정이면 통과한다."""
    now = search_settings()
    same = [{"qid": "a", "settings": dict(now)}, {"qid": "b", "settings": dict(now)}]
    assert settings_conflicts(same, now) == []
    mixed = same + [{"qid": "c", "settings": dict(now, reranker_provider="local_int8")}]
    got = settings_conflicts(mixed, now)
    assert len(got) == 1 and got[0].startswith("c: reranker_provider('local_int8' -> ")
    assert settings_conflicts([{"qid": "d", "settings": {}}], now)       # 설정이 비어 있는 줄도 다른 설정이다


def check_warning_reason_prefers_rerank() -> None:
    assert warning_reason([]) is None
    assert warning_reason(["키워드 검색 실패(...)", "리랭킹 실패(...)"]) == "rerank_failed"


def check_settled_qids_retries_call_failures() -> None:
    """호출 실패로 버린 질문은 끝난 것으로 보지 않는다(계획 형식 2). 다시 검색해 성공하면 마지막 줄이 판정이다."""
    def row(qid: str, reason: str | None) -> dict:
        return {"qid": qid, "status": "ok" if reason is None else "dropped", "drop_reason": reason}

    rows = [row("a", None), row("b", "answerable"), row("c", "max_distance"),
            row("d", "rerank_failed"), row("e", "keyword_failed"), row("f", "rerank_failed"), row("f", None)]
    assert settled_qids(rows) == {"a", "b", "c", "f"}


CHECKS = [
    check_search_one_returns_full_content,
    check_search_one_restores_embed_one,
    check_rerank_failure_drops_question,
    check_keyword_failure_drops_question,
    check_empty_result_reasons,
    check_missing_content_is_an_error,
    check_parse_bots_refuses_protected,
    check_parse_bots_refuses_duplicates,
    check_bots_file_must_match,
    check_nondefault_settings_compares_with_config_defaults,
    check_settings_conflicts_refuses_mixed_runs,
    check_warning_reason_prefers_rerank,
    check_settled_qids_retries_call_failures,
]


def main() -> None:
    for fn in CHECKS:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(CHECKS)}가지 전부 통과.")


if __name__ == "__main__":
    main()
