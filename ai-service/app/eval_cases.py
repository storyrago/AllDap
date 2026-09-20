"""박제된 평가 결과(`eval_results`)를 <채점자 입력>으로 되돌린다.

이 모듈이 왜 따로 있나
─────────────────────────────────────────────────────────────────────────────
평가를 다시 돌리지 않고 <이미 나온 답변과 근거>로 채점자를 다시 검사하려면,
DB 에 박제된 한 행을 `judge.score(question, ground_truth, sources, answer)` 의
인자로 되돌려야 한다. 그 일 하나만 한다.

🔴 이 파일을 따로 뺀 이유는 <다음 슬라이스> 다. 무관한 청크를 한 건씩 주입해가며
   채점자가 언제 눈이 머는지 보는 탐침도 똑같이 "저장된 케이스를 복원해 다시
   넣는" 일을 한다. 2026-09-18 에 같은 일을 하는 스크립트를 스크래치패드에 두었다가
   세션이 끝나며 잃었고, 그래서 핸드오프에 표를 손으로 옮겨 적어야 했다.

외부 API 를 부르지 않는다. DB 만 읽는다.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from .db import cursor
from .schemas import Id, Source

# 대조에 쓰는 실행들. 11·12·13 = 306청크 · 14·15·16 = 360청크.
# 전부 status='completed' 이고 처리 실패 0건이다(2026-09-20 확인).
DEFAULT_RUN_IDS: list[int] = [11, 12, 13, 14, 15, 16]


@dataclass(frozen=True)
class SourceRef:
    """근거 청크 하나. preview(앞 200자)가 아니라 <전문>을 들고 있다.

    🔴 preview 를 쓰면 안 되는 이유가 실측돼 있다(2026-08-02). 생성 모델은 전문을
       보고 답했는데 채점자가 preview 만 봐서, 250번째 글자에 있던 "HR-310" 을
       못 보고 <맞는 답에 0점>을 줬다. 사람이 채점자보다 덜 보면 이번에는
       <사람 라벨이> 거짓이 된다.
    """

    chunk_id: Id
    document_id: Id
    filename: str
    content: str

    def to_source(self) -> Source:
        """`judge.score` 가 받는 타입으로 바꾼다.

        `judge.score` 는 `fetch_contents` 로 본문을 다시 읽고, 못 찾으면 preview 로
        떨어진다. preview 자리에 전문을 넣어두면 어느 길로 가도 같은 것을 본다.
        score 는 채점에 쓰이지 않으므로 0.0 으로 둔다.
        """
        return Source(
            chunk_id=self.chunk_id,
            document_id=self.document_id,
            filename=self.filename,
            score=0.0,
            preview=self.content,
        )


@dataclass(frozen=True)
class Case:
    """채점자가 판정한 서로 다른 입력 하나."""

    case_id: str
    question_id: Id
    question: str
    ground_truth: str
    generated_answer: str
    sources: tuple[SourceRef, ...]
    seen_in_runs: tuple[int, ...]
    judge_faithfulness: float
    judge_relevancy: float


def chunk_ids_of(retrieved: object) -> list[Id]:
    """`retrieved_chunks`(jsonb)에서 chunk_id 를 <순서대로> 꺼낸다.

    🔴 저장된 값이 문자열이다: {"chunk_id": "270", ...}.
       int 로 바꾸지 않으면 `chunks` 조회가 통째로 비고, 그러면 사람이 근거 없이
       라벨을 매기게 된다. 조용히 비는 것이 가장 나쁜 실패라 여기서 못박는다.
    """
    if isinstance(retrieved, (str, bytes)):
        retrieved = json.loads(retrieved)
    if not isinstance(retrieved, list):
        return []
    out: list[Id] = []
    for e in retrieved:
        if isinstance(e, dict) and "chunk_id" in e:
            out.append(int(e["chunk_id"]))
    return out


def filenames_of(retrieved: object) -> dict[Id, str]:
    """chunk_id → filename. 파일명은 JSON 에 이미 있어 documents 를 다시 안 join 한다."""
    if isinstance(retrieved, (str, bytes)):
        retrieved = json.loads(retrieved)
    if not isinstance(retrieved, list):
        return {}
    return {
        int(e["chunk_id"]): str(e.get("filename", ""))
        for e in retrieved
        if isinstance(e, dict) and "chunk_id" in e
    }


def case_key(question_id: int, answer: str, chunk_ids: list[Id]) -> str:
    """같은 입력을 하나로 묶는 안정 해시 (12자).

    🔴 <순서를 유지한다.> 근거의 순서가 채점자 판단을 바꾼다는 것이 2026-09-18 에
       실측됐다(무관한 청크가 4번째에 끼자 3번째 자리의 정답을 못 봤다).
       정렬해서 묶으면 서로 다른 입력이 한 칸으로 뭉개진다.
    """
    raw = f"{question_id}\x00{answer}\x00{','.join(str(c) for c in chunk_ids)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


class MissingChunk(RuntimeError):
    """근거 청크가 `chunks` 에 없다. 사람이 근거 없이 라벨을 매기는 것을 막는다."""


def load_cases(run_ids: list[int] | None = None) -> list[Case]:
    """`eval_results` 에서 <채점자가 점수를 매긴> 서로 다른 입력을 복원한다.

    제외하는 것 둘 (이유가 서로 다르다):
      · generated_answer IS NULL  → 처리 실패. 측정 자체가 없다
      · faithfulness   IS NULL    → fallback. 채점자가 불리지 않아 대조할 상대가 없다
    """
    ids = list(run_ids or DEFAULT_RUN_IDS)
    with cursor() as cur:
        cur.execute(
            """SELECT r.run_id, r.question_id, q.question, q.ground_truth,
                      r.generated_answer, r.retrieved_chunks,
                      r.faithfulness, r.relevancy
                 FROM eval_results r
                 JOIN eval_questions q ON q.id = r.question_id
                WHERE r.run_id = ANY(%s)
                  AND r.generated_answer IS NOT NULL
                  AND r.faithfulness IS NOT NULL
                ORDER BY r.run_id, r.question_id""",
            (ids,),
        )
        rows = cur.fetchall()

        wanted: set[Id] = set()
        for row in rows:
            wanted.update(chunk_ids_of(row[5]))
        cur.execute(
            "SELECT id, document_id, content FROM chunks WHERE id = ANY(%s)",
            (sorted(wanted),),
        )
        chunks = {r[0]: (r[1], r[2]) for r in cur.fetchall()}

    missing = sorted(wanted - set(chunks))
    if missing:
        raise MissingChunk(
            f"근거 청크 {len(missing)}개가 chunks 에 없습니다: {missing[:10]}"
            " ... 코퍼스를 다시 적재했거나 eval_set load --replace 를 돌린 것입니다."
            " 이 상태로는 사람이 근거 없이 라벨을 매기게 되므로 중단합니다."
        )

    merged: dict[str, dict] = {}
    for run_id, qid, question, gt, answer, retrieved, faith, rel in rows:
        cids = chunk_ids_of(retrieved)
        names = filenames_of(retrieved)
        key = case_key(int(qid), answer, cids)
        if key not in merged:
            merged[key] = {
                "case": Case(
                    case_id=key,
                    question_id=int(qid),
                    question=question,
                    ground_truth=gt,
                    generated_answer=answer,
                    sources=tuple(
                        SourceRef(
                            chunk_id=c,
                            document_id=chunks[c][0],
                            filename=names.get(c, ""),
                            content=chunks[c][1],
                        )
                        for c in cids
                    ),
                    seen_in_runs=(),
                    judge_faithfulness=float(faith),
                    judge_relevancy=float(rel),
                ),
                "runs": [],
            }
        merged[key]["runs"].append(int(run_id))

    out: list[Case] = []
    for key, v in merged.items():
        c: Case = v["case"]
        out.append(
            Case(
                case_id=c.case_id,
                question_id=c.question_id,
                question=c.question,
                ground_truth=c.ground_truth,
                generated_answer=c.generated_answer,
                sources=c.sources,
                seen_in_runs=tuple(sorted(set(v["runs"]))),
                judge_faithfulness=c.judge_faithfulness,
                judge_relevancy=c.judge_relevancy,
            )
        )
    return out
