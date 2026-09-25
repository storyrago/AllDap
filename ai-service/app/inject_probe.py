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

import random
from dataclasses import dataclass

from .eval_cases import Case, SourceRef
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
