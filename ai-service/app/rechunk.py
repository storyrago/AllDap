"""이미 올라간 문서를 <다시 청킹>한다. 청킹 전략을 바꿨을 때 쓴다.

실행:
    cd ai-service && .venv/bin/python -m app.rechunk        # 미리보기(기본)
    cd ai-service && .venv/bin/python -m app.rechunk --apply # 실제 적용
    cd ai-service && .venv/bin/python -m app.reembed         # ← 적용 후 반드시

왜 이 스크립트가 필요한가
─────────────────────────────────────────────────────────────────────────────
정석은 <문서를 지우고 다시 올리는 것>이다. 그러면 파싱부터 다시 돌아 원본 그대로
청킹된다. 하지만 그건 **원본 파일이 손에 있을 때** 얘기다. 평가용 코퍼스처럼
파일이 저장소에 없고 DB 에만 남은 경우엔 그 길이 막힌다.
(`documents` 테이블은 파일명·길이 같은 메타만 갖고 원문을 보관하지 않는다)

그래서 이 스크립트는 **청크를 이어 붙여 원문을 복원**한 뒤 다시 자른다.
청킹은 겹침(overlap)을 두므로 그냥 이으면 겹친 부분이 중복된다 —
앞 청크의 꼬리와 뒤 청크의 머리가 겹치는 가장 긴 구간을 찾아 잘라낸다.

⚠️ 복원이 맞는지 <반드시 검산한다.> `documents.char_count` 가 업로드 당시의
   원문 길이라 이것과 비교하면 된다. 오차가 크면 그 문서는 건드리지 않는다 —
   틀린 복원으로 다시 자르면 코퍼스가 조용히 망가진다.

W4 에서의 쓰임
─────────────────────────────────────────────────────────────────────────────
청킹 전략 A/B 비교: 설정 바꾸기 → rechunk --apply → reembed → 평가 실행.
`eval_questions` 는 지워지지 않으므로 <같은 테스트셋으로> 전후를 비교할 수 있다.
(FK 가 ON DELETE SET NULL 이라 출처 링크만 끊긴다. 아래에서 다시 이어준다)
"""
from __future__ import annotations

import sys

from .chunker import chunk_text
from .config import get_settings
from .db import close_pool, cursor

# 겹침 탐색 상한. 설정된 overlap 보다 넉넉히 잡는다 —
# 청킹 당시의 overlap 값이 지금 설정과 다를 수 있기 때문이다.
_MAX_OVERLAP = 200
# 복원 길이가 원문과 이만큼 넘게 차이 나면 손대지 않는다.
# strip() 으로 사라지는 공백 때문에 몇 글자 차이는 정상이다.
_TOLERANCE_RATIO = 0.02
_TOLERANCE_MIN = 20


def _dedup(prev: str, nxt: str) -> str:
    """prev 의 꼬리와 nxt 의 머리가 겹치는 가장 긴 구간을 nxt 에서 잘라낸다."""
    for n in range(min(_MAX_OVERLAP, len(prev), len(nxt)), 0, -1):
        if prev.endswith(nxt[:n]):
            return nxt[n:]
    return nxt


def _restore(chunks: list[str]) -> str:
    text = chunks[0]
    for c in chunks[1:]:
        text += "\n" + _dedup(text, c)
    return text


def _best_new_chunk(ground_truth: str, candidates: list[tuple[str, str]]) -> str | None:
    """기대 답변과 글자가 가장 많이 겹치는 새 청크의 id.

    출처 링크를 다시 잇기 위한 <근사>다. 정확히 복원할 방법은 없다 —
    옛 청크 하나가 새 청크 여럿으로 쪼개졌으므로 어느 쪽이 원본인지는
    질문·답변 내용으로 추정할 수밖에 없다. 못 찾으면 NULL 로 둔다.
    """
    if not ground_truth:
        return None
    best_id, best_score = None, 0
    for cid, content in candidates:
        score = sum(1 for ch in set(ground_truth) if ch in content)
        if score > best_score:
            best_id, best_score = cid, score
    # 절반도 안 겹치면 링크를 잇지 않는다. 틀린 출처는 없는 것만 못하다.
    return best_id if best_score >= len(set(ground_truth)) * 0.5 else None


def main(apply: bool) -> None:
    s = get_settings()
    print(f"청킹 설정: size={s.chunk_size} overlap={s.chunk_overlap} "
          f"split_headings={s.chunk_split_headings}")
    print(f"모드: {'적용' if apply else '미리보기(--apply 를 붙이면 실제로 바꿉니다)'}\n")

    with cursor() as cur:
        cur.execute(
            """SELECT d.id, d.bot_id, d.filename, d.char_count,
                      array_agg(c.content ORDER BY c.chunk_index)
                 FROM documents d JOIN chunks c ON c.document_id = d.id
                GROUP BY d.id, d.bot_id, d.filename, d.char_count
                ORDER BY d.filename"""
        )
        docs = cur.fetchall()

    planned, skipped = [], []
    for doc_id, bot_id, filename, char_count, chunks in docs:
        text = _restore(list(chunks))
        tol = max(_TOLERANCE_MIN, (char_count or len(text)) * _TOLERANCE_RATIO)
        if char_count and abs(len(text) - char_count) > tol:
            skipped.append((filename, char_count, len(text)))
            continue
        new = chunk_text(
            text,
            size=s.chunk_size,
            overlap=s.chunk_overlap,
            split_headings=s.chunk_split_headings,
        )
        planned.append((doc_id, bot_id, filename, len(chunks), new))

    print(f"{'파일':<28} {'기존':>5} {'신규':>5}")
    for _, _, filename, old_n, new in planned:
        print(f"{filename:<28} {old_n:>5} {len(new):>5}")
    old_total = sum(p[3] for p in planned)
    new_total = sum(len(p[4]) for p in planned)
    print(f"\n총 청크: {old_total} → {new_total}")

    if skipped:
        print("\n⚠️ 복원이 원문 길이와 맞지 않아 건드리지 않은 문서:")
        for filename, cc, got in skipped:
            print(f"   {filename}: 원본 {cc}자 / 복원 {got}자")

    if not apply:
        print("\n미리보기입니다. 실제로 바꾸려면 --apply 를 붙이세요.")
        return

    # 출처 링크를 다시 잇기 위해, 끊기기 <전에> 어느 문서였는지 기억해둔다.
    with cursor() as cur:
        cur.execute(
            """SELECT q.id, q.ground_truth, c.document_id
                 FROM eval_questions q JOIN chunks c ON c.id = q.source_chunk_id"""
        )
        question_origin = cur.fetchall()

    with cursor(commit=True) as cur:
        for doc_id, bot_id, _filename, _old_n, new in planned:
            # 벡터는 비운 채로 넣는다. 채우는 것은 reembed 의 일이다 —
            # 임베딩(외부 호출)을 이 트랜잭션 안에서 하면 커넥션 풀이 마른다.
            cur.execute("DELETE FROM chunks WHERE document_id = %s", (doc_id,))
            cur.executemany(
                """INSERT INTO chunks (document_id, bot_id, chunk_index, content, meta)
                   VALUES (%s, %s, %s, %s, '{}'::jsonb)""",
                [(doc_id, bot_id, c.index, c.content) for c in new],
            )
            cur.execute(
                "UPDATE documents SET chunk_count = %s WHERE id = %s",
                (len(new), doc_id),
            )

    # 끊긴 출처 링크를 근사로 다시 잇는다.
    relinked = 0
    with cursor(commit=True) as cur:
        for qid, ground_truth, doc_id in question_origin:
            cur.execute(
                "SELECT id, content FROM chunks WHERE document_id = %s", (doc_id,)
            )
            match = _best_new_chunk(ground_truth or "", cur.fetchall())
            if match:
                cur.execute(
                    "UPDATE eval_questions SET source_chunk_id = %s WHERE id = %s",
                    (match, qid),
                )
                relinked += 1

    print(f"\n적용 완료. 청크 {old_total} → {new_total}")
    print(f"출처 링크 재연결: {relinked}/{len(question_origin)}건")
    print("⚠️ 이제 벡터가 비어 있습니다. 반드시 실행하세요:")
    print("   .venv/bin/python -m app.reembed")


if __name__ == "__main__":
    try:
        main(apply="--apply" in sys.argv)
    finally:
        close_pool()
