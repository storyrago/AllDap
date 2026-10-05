"""질문마다 실제 검색으로 근거 청크 전문을 뽑는다(스펙 3-4절, v2 스펙 2-3절).

실행:
    cd ai-service
    $PY -m tools.judgeft_search --bot travel=13 --bot telecom=14 [--limit N]

검색 한 건의 일(임베딩, 검색, 전문 다시 읽기, 리랭커와 키워드 검색 실패 감지, 빈 결과의 원인)은 v2 의
judge5v2_search.search_one 을 그대로 쓴다. 이 파일은 경로, 분야, 봇 번호 확인만 다르다. 같은 검색 규칙을
두 번 적으면 한쪽만 고쳐지기 때문이다.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter

from app import cf

from .judgeft_files import (
    BOTS, PROTECTED_BOTS, QUESTIONS, RETRIEVED, V2_BOTS, append_jsonl, fields_doc, read_json, read_jsonl,
)
from .judge5v2_search import nondefault_settings, search_one, search_settings, settings_conflicts, settled_qids


def protected_bots() -> frozenset[int]:
    """건드리지 않는 봇: 데모 봇, 리랭커 실험 봇, v2 의 봇 넷(스펙 3-4절)."""
    v2 = set(read_json(V2_BOTS).values()) if V2_BOTS.exists() else set()
    return PROTECTED_BOTS | frozenset(v2)


def parse_bots(items: list[str], fields: list[str], protected: frozenset[int]) -> dict[str, int]:
    """--bot travel=13 꼴을 {"travel": 13} 으로 바꾼다. 열지 않은 분야, 막은 봇, 겹친 분야와 번호를 거절한다."""
    out: dict[str, int] = {}
    for item in items:
        field, _, num = item.partition("=")   # partition 은 첫 "=" 에서 셋으로 자른다
        if field not in fields or not num.isdigit():
            raise SystemExit(f"--bot 은 분야=번호 꼴입니다. 열린 분야는 {', '.join(fields)}. 받은 값: {item}")
        bot_id = int(num)
        if bot_id in protected:
            raise SystemExit(f"봇 {bot_id}번은 이 실험에서 쓰지 않습니다(데모, 리랭커 실험, v2 의 봇). "
                             f"testdata/judgeft/bots.json 의 번호를 주세요.")
        if field in out or bot_id in out.values():
            raise SystemExit(f"--bot 에 같은 분야나 같은 번호가 두 번 있습니다: {item}")
        out[field] = bot_id
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="파인튜닝 실험의 질문마다 근거 청크 전문을 뽑는다")
    p.add_argument("--bot", action="append", required=True, help="분야=봇 번호. 분야마다 한 번씩")
    p.add_argument("--limit", type=int, default=None, help="이번 실행에서 검색할 최대 질문 수")
    args = p.parse_args(argv)
    doc = fields_doc()
    bots = parse_bots(args.bot, doc["test"] + doc["train"], protected_bots())
    if not BOTS.exists():
        print("testdata/judgeft/bots.json 이 없습니다. 계획 E2 가 봇을 만들고 남기는 파일입니다.")
        return 1
    recorded = read_json(BOTS)
    # := 는 값을 이름에 담으면서 그 값으로 바로 if 를 판단한다(파이썬 3.8 의 대입식). 계산을 한 번만 하고 결과를 아래에서 다시 쓴다.
    if wrong := [f"{f}={n}(기록은 {recorded.get(f)})" for f, n in bots.items() if recorded.get(f) != n]:
        print(f"--bot 이 bots.json 과 다릅니다: {', '.join(wrong)}")
        return 1
    settings = search_settings()
    # 이 실험은 기본 설정만 쓴다. v2 처럼 --allow-nondefault 를 두지 않는다(쓸 일이 없는 문을 열어 두지 않는다).
    if diff := nondefault_settings(settings):
        print("검색 설정이 config.py 의 기본값과 다릅니다. 셸의 환경변수나 .env 를 확인하세요:")
        for k, d in diff.items():
            print(f"  - {k}: 기본값 {d['default']!r}, 지금 {d['actual']!r}")
        return 1
    questions = read_jsonl(QUESTIONS)
    if dup := [k for k, n in Counter(q["qid"] for q in questions).items() if n > 1]:
        print(f"questions.jsonl 에 같은 qid 가 두 번 있습니다: {dup[:5]}")
        return 1
    existing = read_jsonl(RETRIEVED)
    if conflicts := settings_conflicts(existing, settings):
        print(f"retrieved.jsonl 에 지금과 다른 검색 설정의 줄이 {len(conflicts)}개 있습니다. 멈춥니다: {conflicts[:3]}")
        return 1
    done = settled_qids(existing)
    todo = [q for q in questions if q["domain"] in bots and q["qid"] not in done][: args.limit]
    counts: Counter = Counter()
    for q in todo:
        row = search_one(bots[q["domain"]], q["question"])
        append_jsonl(RETRIEVED, {"qid": q["qid"], "domain": q["domain"], "bot_id": bots[q["domain"]],
                                 "settings": settings, **row})
        counts[(q["domain"], row["drop_reason"] or "ok")] += 1
    for (field, reason), n in sorted(counts.items()):
        print(f"{field}: {reason} {n}")
    print(f"이번 실행의 뉴런: {cf.neurons_used()}")
    rows = read_jsonl(RETRIEVED)
    tried, done = {r["qid"] for r in rows}, settled_qids(rows)
    mine = [q["qid"] for q in questions if q["domain"] in bots]
    if failed := sum(1 for qid in mine if qid in tried and qid not in done):
        print(f"호출 실패로 버린 질문 {failed}개. 같은 명령을 다시 실행하면 그 질문만 다시 검색합니다(v2 스펙 2-3절).")
    if never := sum(1 for qid in mine if qid not in tried):
        print(f"아직 검색하지 않은 질문 {never}개. 같은 명령을 다시 실행하면 이어서 합니다.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
