"""벡터가 비어 있는 청크를 다시 임베딩한다.

실행:  cd ai-service && .venv/bin/python -m app.reembed

언제 쓰나
─────────────────────────────────────────────────────────────────────────────
임베딩 모델을 바꿨을 때. 모델이 다르면 벡터 공간이 달라서, 옛 벡터와 새 벡터를
섞어 검색하면 결과가 엉망이 된다. 그래서 마이그레이션이 기존 벡터를 NULL 로 비우고,
이 스크립트가 <청크 본문은 그대로 둔 채> 벡터만 다시 만든다.

문서를 지우고 다시 올려도 되지만, 그러면 파일 원본이 있어야 하고 문서 id 도 바뀐다.
청크 텍스트는 멀쩡하니 벡터만 갈아끼우는 게 맞다.

W4 에서 임베딩 모델 A/B 를 비교할 때도 이걸 쓴다 —
모델 바꾸기 → reembed → 평가 실행, 을 반복한다.
"""
from __future__ import annotations

from . import retriever
from .config import get_settings
from .db import close_pool, cursor


def main() -> None:
    s = get_settings()
    print(f"모델: {s.embedding_model} ({s.embedding_dim}차원)")

    # 벡터가 비어 있는 청크만 고른다. 이미 채워진 걸 다시 부르면 돈과 시간만 쓴다.
    with cursor() as cur:
        cur.execute(
            "SELECT id, content FROM chunks WHERE embedding IS NULL ORDER BY document_id, chunk_index"
        )
        rows = cur.fetchall()

    if not rows:
        print("다시 임베딩할 청크가 없습니다.")
        return

    print(f"대상 청크: {len(rows)}개")

    # ⚠️ 임베딩(외부 호출)을 cursor 블록 <밖>에서 한다.
    #    커넥션 풀이 10개뿐이라 오래 걸리는 호출을 트랜잭션 안에 두면
    #    이 작업과 무관한 채팅·업로드까지 멈춘다. main.py 의 업로드가 같은 구조다.
    vectors = retriever.embed([content for _, content in rows])

    with cursor(commit=True) as cur:
        cur.executemany(
            "UPDATE chunks SET embedding = %s WHERE id = %s",
            # zip 은 두 리스트를 짝지어 준다. embed() 가 순서를 보장하므로
            # rows[i] 의 청크와 vectors[i] 의 벡터가 같은 것이다.
            [(vec, chunk_id) for (chunk_id, _), vec in zip(rows, vectors)],
        )

    with cursor() as cur:
        cur.execute("SELECT count(*) FROM chunks WHERE embedding IS NULL")
        left = cur.fetchone()[0]

    print(f"완료. 남은 미임베딩 청크: {left}개")
    if left:
        # 여기 걸리면 조용히 넘어가면 안 된다 — 그 청크는 영원히 검색되지 않는다.
        raise SystemExit("일부 청크가 임베딩되지 않았습니다. 로그를 확인하세요.")


if __name__ == "__main__":
    try:
        main()
    finally:
        # 커넥션 풀을 닫아준다. 안 닫으면 스크립트가 끝날 때
        # "couldn't stop thread 'pool-1-worker-0'" 경고가 쏟아진다.
        # FastAPI 는 lifespan 에서 close_pool() 을 부르지만(main.py),
        # 이 스크립트는 그 경로를 안 타므로 직접 닫아야 한다.
        # finally 에 두는 이유: 중간에 예외가 나도 반드시 닫히게.
        close_pool()
