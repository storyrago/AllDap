"""무관한 청크 주입 탐침 (2026-09-26).

설계: docs/superpowers/specs/2026-09-26-inject-probe-design.md

무엇을 재나
─────────────────────────────────────────────────────────────────────────────
2026-09-18 에 q3 한 문항에서, 답변을 고정한 채 근거에 무관한 청크 하나가 끼자
채점자 충실성이 1.0 에서 0.0 으로 떨어졌다. 정답 청크는 그대로 3번째에 있었다.
이 도구는 그것이 일반적인지, 그리고 채점자가 <장수>에 약한지
<헷갈리게 비슷한 내용>에 약한지를 가른다.

  base          원래 근거 5장 그대로 (지금 다시 채점해도 1.0 인가)
  near+1/2/4    끝에 <질문과 벡터 거리가 가까운> 청크를 1·2·4장
  far+1/2/4     끝에 <거리 순위 아래쪽 절반>의 청크를 1·2·4장 (대조군)
  near+1@front  near 1장을 맨 앞에 (자리가 중요한가)

🔴 답변은 끝까지 글자 하나 안 바뀐다. 대상은 사람도 채점자도 1.0 을 준 케이스뿐이라,
   주입 뒤 점수가 떨어지면 정의상 채점자 실수다.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from dataclasses import dataclass

from .config import get_settings
from .db import cursor
from .eval_cases import DEFAULT_RUN_IDS, Case, SourceRef, load_cases
from .judge import Scores, score
from .judge_agreement import DEFAULT_PATH as LABELS_PATH
from .judge_agreement import read_labels
from .retriever import embed_one
from .schemas import Id

# 튜플(tuple)로 둔 이유: 리스트와 달리 바꿀 수 없어서, 어딘가에서 실수로
# append 해 조건 목록이 늘어나는 일이 원천적으로 막힌다.
CONDITIONS: tuple[str, ...] = (
    "base",
    "near+1", "near+2", "near+4",
    "far+1", "far+2", "far+4",
    "near+1@front",
)
INJECT_MAX = 4
_STEPS = (1, 2, 4)
DEFAULT_RESULTS = "testdata/inject_probe_results.jsonl"
# 연달아 이만큼 실패하면 멈춘다. 하루 한도(429)에 걸리면 이후 호출이 전부 실패하는데,
# 계속 돌면 남은 수백 건이 전부 null 줄로 쌓여 파일만 지저분해진다.
_STOP_AFTER_FAILURES = 3


# frozen=True: 만든 뒤 필드를 못 바꾸는 불변 객체. 같은 값이면 == 로 같다고 나오고
# set 에도 넣을 수 있다. 점검에서 "같은 씨앗 → 같은 결과" 를 == 로 비교하는 근거다.
@dataclass(frozen=True)
class Candidate:
    """주입 후보 청크 하나. distance 는 <그 질문>과의 벡터 거리다."""

    chunk_id: Id
    document_id: Id
    filename: str
    content: str
    distance: float

    def to_ref(self) -> SourceRef:
        """채점자 입력 타입으로 바꾼다. 거리는 채점에 안 쓰이므로 버린다."""
        return SourceRef(
            chunk_id=self.chunk_id,
            document_id=self.document_id,
            filename=self.filename,
            content=self.content,
        )


def select_targets(cases: list[Case], labels: dict[str, dict]) -> list[Case]:
    """사람 1.0 · 채점자 1.0 인 케이스만 남긴다.

    출발점이 0.5 나 0.0 이면 "주입 때문에 떨어졌다" 와 "원래 틀린 답을 뒤늦게 잡았다" 를
    가를 수 없다. 둘 다 1.0 이어야 떨어진 것이 곧 채점자 실수다.
    """
    out: list[Case] = []
    for c in cases:
        rec = labels.get(c.case_id)
        if rec is None or rec.get("label") is None:
            continue
        if float(rec["label"]) == 1.0 and c.judge_faithfulness == 1.0:
            out.append(c)
    return out


def _eligible(ranked: list[Candidate], exclude_ids: set[Id], exclude_docs: set[Id]) -> list[Candidate]:
    """원래 근거와 정답 문서를 뺀다. 정답 문서가 섞이면 <답을 뒷받침하는> 종이가 된다."""
    return [r for r in ranked if r.chunk_id not in exclude_ids and r.document_id not in exclude_docs]


def pick_near(
    ranked: list[Candidate],
    exclude_ids: set[Id],
    exclude_docs: set[Id],
    max_distance: float,
    n: int = INJECT_MAX,
) -> list[Candidate]:
    """비슷한 동네: 거리가 가까운 순으로, 거리 컷 안에 드는 것만 최대 n 장.

    `ranked` 는 거리 오름차순이어야 한다. 컷 밖 청크는 실제 서비스에서 근거에
    절대 들어오지 않으므로 현실성이 없다. `<=` 인 이유는 retriever.search 가
    `distance > max_distance` 만 버리기 때문이다(같은 경계를 써야 한다).
    """
    pool = [r for r in _eligible(ranked, exclude_ids, exclude_docs) if r.distance <= max_distance]
    return pool[:n]


def pick_far(
    ranked: list[Candidate],
    exclude_ids: set[Id],
    exclude_docs: set[Id],
    seed: int,
    n: int = INJECT_MAX,
) -> list[Candidate]:
    """딴 얘기: 거리 순위 아래쪽 절반에서 무작위 n 장.

    random.Random(seed) 는 전역 난수와 분리된 <자기만의> 난수 생성기다.
    씨앗을 question_id 로 고정하면 다시 돌려도 같은 청크가 나온다.
    sample 은 중복 없이 뽑고 뽑힌 순서를 돌려준다. 그 순서대로 +1 · +2 · +4 에 쌓는다.
    """
    bottom = ranked[len(ranked) // 2:]
    pool = _eligible(bottom, exclude_ids, exclude_docs)
    return random.Random(seed).sample(pool, min(n, len(pool)))


def build_conditions(
    original: tuple[SourceRef, ...],
    near: list[Candidate],
    far: list[Candidate],
) -> dict[str, tuple[tuple[SourceRef, ...], tuple[Candidate, ...]]]:
    """조건 이름 → (채점자에게 줄 근거, 주입한 청크).

    🔴 더하기이지 바꿔 끼우기가 아니다. 원래 근거는 하나도 빠지지 않고 순서도 그대로다.
       바꿔 끼우면 "엉뚱한 종이가 들어와서" 와 "원래 종이가 빠져서" 가 섞인다.
    k 장이 안 차는 조건은 만들지 않는다. 3장짜리를 +4 라고 부르면 표가 거짓말을 한다.
    """
    base = tuple(original)
    out: dict[str, tuple[tuple[SourceRef, ...], tuple[Candidate, ...]]] = {"base": (base, ())}
    for kind, picks in (("near", near), ("far", far)):
        for k in _STEPS:
            if len(picks) >= k:
                injected = tuple(picks[:k])
                out[f"{kind}+{k}"] = (base + tuple(c.to_ref() for c in injected), injected)
    if near:
        first = near[0]
        out["near+1@front"] = ((first.to_ref(),) + base, (first,))
    return out


# ── 결과 파일 ────────────────────────────────────────────────────────────────
# JSON Lines(.jsonl): 한 줄에 JSON 하나. 통째로 다시 쓰는 JSON 과 달리 <끝에 붙이기만>
# 하면 되므로, 한 건 채점할 때마다 바로 저장할 수 있고 중간에 죽어도 앞의 줄은 멀쩡하다.


def make_record(case: Case, condition: str, injected: tuple[Candidate, ...], scores: Scores | None) -> dict:
    """채점 한 번을 한 줄로. 🔴 실패는 null 이지 0.0 이 아니다."""
    return {
        "case_id": case.case_id,
        "question_id": case.question_id,
        "condition": condition,
        "injected": [
            {"chunk_id": c.chunk_id, "filename": c.filename, "distance": round(c.distance, 4)}
            for c in injected
        ],
        "faithfulness": None if scores is None else scores.faithfulness,
        "relevancy": None if scores is None else scores.relevancy,
        "reason": "" if scores is None else scores.reason,
        # 사람이 채운다: 무관 / 모순 / 뒷받침. run 은 이 칸을 쓰기만 하고 다시 건드리지 않는다.
        "review": None,
    }


def read_results(path: str) -> list[dict]:
    """파일이 없으면 빈 목록. 빈 줄은 건너뛴다(사람이 손으로 고치다 남길 수 있다)."""
    if not os.path.exists(path):
        return []
    out: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def latest(records: list[dict]) -> dict[tuple[str, str], dict]:
    """(case_id, condition) 마다 <마지막> 줄. 실패 뒤 재시도가 성공하면 그것이 남는다."""
    out: dict[tuple[str, str], dict] = {}
    for r in records:
        out[(r["case_id"], r["condition"])] = r
    return out


def done_keys(records: list[dict]) -> set[tuple[str, str]]:
    """이미 <성공한> 키. 실패(null)는 넣지 않아 다음 실행이 다시 부른다."""
    return {k for k, r in latest(records).items() if r["faithfulness"] is not None}


# ── DB · 외부 API ────────────────────────────────────────────────────────────


def _gold_documents(question_ids: list[int]) -> dict[int, Id]:
    """question_id → 정답 청크가 속한 문서. source_chunk_id 가 NULL 이면 빠진다."""
    with cursor() as cur:
        cur.execute(
            """SELECT q.id, c.document_id
                 FROM eval_questions q JOIN chunks c ON c.id = q.source_chunk_id
                WHERE q.id = ANY(%s)""",
            (question_ids,),
        )
        return {int(qid): doc for qid, doc in cur.fetchall()}


def _ranked(bot_id: Id, question: str) -> list[Candidate]:
    """그 봇의 <전체> 청크를 질문과의 벡터 거리 오름차순으로.

    `<=>` 는 pgvector 의 코사인 거리 연산자다. retriever.search 와 같은 거리라
    max_distance 컷을 그대로 댈 수 있다. 임베딩은 질문당 1회라 비용은 무시할 수준이다.
    """
    qvec = embed_one(question)
    with cursor() as cur:
        cur.execute(
            """SELECT c.id, c.document_id, d.filename, c.content,
                      c.embedding <=> %s::vector AS distance
                 FROM chunks c JOIN documents d ON d.id = c.document_id
                WHERE c.bot_id = %s AND c.embedding IS NOT NULL
                ORDER BY distance""",
            (qvec, bot_id),
        )
        return [Candidate(r[0], r[1], r[2], r[3], float(r[4])) for r in cur.fetchall()]


def run(bot_id: Id, results_path: str, labels_path: str, limit: int | None) -> int:
    """대상 케이스마다 조건을 조립해 채점하고, 한 번마다 즉시 한 줄 붙인다."""
    s = get_settings()
    targets = select_targets(load_cases(DEFAULT_RUN_IDS), read_labels(labels_path))
    if limit is not None:
        targets = targets[:limit]
    gold = _gold_documents(sorted({c.question_id for c in targets}))
    done = done_keys(read_results(results_path))
    print(f"대상 {len(targets)}건 · 이미 끝난 채점 {len(done)}회")

    failures = 0
    calls = 0
    # "a" 모드: 파일 끝에 붙인다. 기존 줄(사람이 적은 review 포함)은 건드리지 않는다.
    with open(results_path, "a", encoding="utf-8") as out:
        for i, case in enumerate(targets, 1):
            exclude_ids = {src.chunk_id for src in case.sources}
            exclude_docs = {gold[case.question_id]} if case.question_id in gold else set()
            ranked = _ranked(bot_id, case.question)
            near = pick_near(ranked, exclude_ids, exclude_docs, s.max_distance)
            far = pick_far(ranked, exclude_ids, exclude_docs, seed=case.question_id)
            conds = build_conditions(case.sources, near, far)
            if len(near) < INJECT_MAX:
                print(f"  ⚠️ q{case.question_id} ({case.case_id}) near 가 {len(near)}장뿐이라 일부 조건을 건너뜁니다")
            for name in CONDITIONS:
                if name not in conds or (case.case_id, name) in done:
                    continue
                sources, injected = conds[name]
                result = score(
                    case.question, case.ground_truth,
                    [src.to_source() for src in sources], case.generated_answer,
                )
                calls += 1
                out.write(json.dumps(make_record(case, name, injected, result), ensure_ascii=False) + "\n")
                # flush: 버퍼에 쌓아두지 말고 지금 디스크로. 이게 없으면 죽을 때 마지막 몇 줄이 사라진다.
                out.flush()
                failures = failures + 1 if result is None else 0
                if failures >= _STOP_AFTER_FAILURES:
                    print(f"❌ 채점이 {failures}번 연달아 실패해 멈춥니다(하루 한도일 가능성이 큽니다)."
                          " 한도가 풀린 뒤 같은 명령을 다시 돌리면 이어서 합니다.", file=sys.stderr)
                    return 1
            print(f"  [{i}/{len(targets)}] q{case.question_id} 끝")
    print(f"채점 {calls}회. 결과: {results_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="무관한 청크를 주입해 채점자를 다시 부른다")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="채점한다 (외부 API 를 부른다. 이어 돌리기 가능)")
    r.add_argument("--bot-id", type=int, required=True)
    r.add_argument("--results", default=DEFAULT_RESULTS)
    r.add_argument("--labels", default=LABELS_PATH)
    r.add_argument("--limit", type=int, default=None, help="앞에서 N건만 (시험 삼아 돌릴 때)")
    args = p.parse_args(argv)
    if args.cmd == "run":
        return run(args.bot_id, args.results, args.labels, args.limit)
    return 0


if __name__ == "__main__":
    from .db import close_pool
    try:
        sys.exit(main())
    finally:
        close_pool()
