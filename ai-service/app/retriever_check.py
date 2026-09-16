"""하이브리드 검색의 자체 점검. `python -m app.retriever_check` 로 돌린다.

DB 도 외부 API 도 부르지 않는다 — 순수 함수(_keywords, _rrf_reorder)만 본다.
검색 품질 자체는 평가 대시보드가 재는 것이고, 여기서 보는 것은
<로직이 의도대로 도는가>뿐이다.
"""
from __future__ import annotations

from . import retriever
from .retriever import _keywords, _rrf_reorder
from .schemas import Source


def _check_keywords() -> None:
    # ① 조사가 떨어져야 벡터가 놓친 청크를 키워드가 잡을 수 있다.
    #    "기간제 근로자가…" 의 정답 문서에는 "기간제 근로자는" 이라고 적혀 있다.
    assert "근로자" in _keywords("기간제 근로자가 쓸 수 있는 휴가는?"), "조사 '가' 가 안 떨어졌다"
    assert "정규직" in _keywords("정규직의 노트북 교체 주기는?"), "조사 '의' 가 안 떨어졌다"
    assert "회사" in _keywords("회사에서 내리는 처벌은?"), "조사 '에서' 가 안 떨어졌다"

    # ② 긴 조사가 먼저 걸려야 한다. "에서" 가 "에" 로 잘리면 "회사에" 가 남는다.
    assert _keywords("사옥에서") == ["사옥"], _keywords("사옥에서")

    # ③ 한 글자는 버린다 — "이", "것" 같은 말이 아무 청크에나 걸려 순위를 망친다.
    assert _keywords("그 것 이 무엇") == ["무엇"], _keywords("그 것 이 무엇")

    # ④ 중복은 한 번만. 같은 낱말이 두 번 나왔다고 점수를 두 배 주면 안 된다.
    assert _keywords("연차 연차 휴가") == ["연차", "휴가"], _keywords("연차 연차 휴가")

    # ⑤ 🐛 조사를 떼서 한 글자가 되면 떼지 않는다.
    #    "휴가" 의 끝 글자가 조사 '가' 라서 "휴" 로 잘리고, 한 글자라 버려졌었다.
    #    이 검사가 그 버그를 잡았다. "평가"·"결과"·"성과"도 같은 함정이다.
    for word in ("휴가", "평가", "결과", "성과", "제도"):
        assert _keywords(word) == [word], f"{word} 가 조사 제거로 망가졌다: {_keywords(word)}"

    # ⑥ 반대로 <과하게> 떼는 것은 무해하다 — LIKE 부분 문자열이라
    #    "성과평"(오절단)도 "성과평가"를 담은 청크에 그대로 걸린다.
    assert _keywords("성과평가는")[0] in "성과평가", _keywords("성과평가는")

    # ⑦ 영문·숫자도 낱말이다 (양식 번호 "HR-101", "GA-310" 같은 것).
    assert "HR" in _keywords("양식 HR-101 은 어디에?")

    # ⑧ 낱말이 하나도 없으면 빈 목록. 호출부가 이걸로 키워드 질의를 건너뛴다.
    assert _keywords("??") == []


def _check_rrf() -> None:
    rows = [(c,) for c in "abcd"]

    # ① 양쪽 목록에 다 있는 문서가 이긴다. b 는 두 목록 모두 상위,
    #    a 는 벡터 1위지만 키워드에는 없다 → 합산 점수로 b 가 앞선다.
    out = _rrf_reorder(rows, ["a", "b", "c"], ["b", "d"], k=1)
    assert [r[0] for r in out][0] == "b", out

    # ② 한쪽에만 있어도 순위는 매겨진다 (빠지지 않는다).
    assert set(r[0] for r in out) == set("abcd")

    # ③ k 가 커지면 순위 간 점수 차가 줄어든다 = 1등을 덜 특별 취급한다.
    #    k=1 에서는 벡터 1위(1/2)가 키워드 2위(1/3)보다 크지만,
    #    k=1000 에서는 둘 다 0.001 근처로 붙어 <양쪽에 등장했는지>가 더 중요해진다.
    small = [r[0] for r in _rrf_reorder(rows, ["a"], ["b", "c", "d"], k=1)]
    assert small[0] == "a", small
    big = [r[0] for r in _rrf_reorder(rows, ["a"], ["b", "c", "d"], k=1000)]
    assert big[0] == "a", big  # 어느 쪽이든 단독 1위는 유지된다

    # ④ 어느 목록에도 없는 문서는 0점이라 맨 뒤로 간다.
    out = _rrf_reorder(rows, ["a"], ["b"], k=60)
    assert [r[0] for r in out][:2] == ["a", "b"], out


def _check_rerank_fusion() -> None:
    """리랭커 융합이 <밀어내기를 실제로 완화하는가.>

    시나리오: 벡터가 1위로 올린 청크 a 를 리랭커가 꼴찌로 민다.
    융합하면 a 는 중간에 남아야 한다 — 그게 이 기능의 존재 이유다.
    """
    ids = list("abcdef")
    prev = ids                      # 벡터/하이브리드가 준 순서
    reranked = list(reversed(ids))  # 리랭커가 정반대로 뒤집었다

    fused = _rrf_reorder(ids, prev, reranked, k=60, key=lambda x: x)

    # ① 모두 대칭이라 아무도 사라지지 않는다.
    assert set(fused) == set(ids), fused

    # ② 🔴 핵심: 벡터 1위였던 a 가 top3 안에 살아남는다.
    #    융합 없이 리랭커 순서를 그대로 쓰면 a 는 꼴찌(6위)라 top5 컷에 잘렸을 것이다.
    assert fused.index("a") < 3, f"밀어내기가 완화되지 않았다: {fused}"

    # ③ 양쪽이 같은 순서면 융합해도 그 순서 그대로다 (합의가 있으면 흔들지 않는다).
    same = _rrf_reorder(ids, prev, prev, k=60, key=lambda x: x)
    assert same == ids, same


def _sources(*chunk_ids: int) -> list[Source]:
    return [
        Source(chunk_id=i, document_id=1, filename=f"{i}.pdf", score=0.9, preview=f"p{i}")
        for i in chunk_ids
    ]


def _check_rerank_survives_provider_failure() -> None:
    """🔴 리랭커가 죽어도 채팅은 살아야 한다. 원래 순서를 그대로 돌려준다.

    로컬 제공자는 Cloudflare 에 없던 실패 모드를 들고 온다(모델 파일 없음 · 의존성 없음 ·
    메모리 부족 · 스레드 고갈). 그래서 <제공자가 무엇이든> 실패가 검색 실패가 되지 않는 것을
    여기서 못박는다. 이건 기존 성질이고, 이 슬라이스가 그것을 깨뜨리지 않았다는 회귀 검사다.
    """
    sources = _sources(1, 2, 3)

    def boom(query: str, texts: list[str]) -> list[int]:
        raise RuntimeError("모델 파일이 없다")

    original_order, original_fetch = retriever._rerank_order, retriever.fetch_contents
    retriever._rerank_order = boom
    retriever.fetch_contents = lambda ids: {}
    try:
        out = retriever._rerank("질문", sources)
    finally:
        retriever._rerank_order = original_order
        retriever.fetch_contents = original_fetch

    assert [s.chunk_id for s in out] == [1, 2, 3], [s.chunk_id for s in out]


def _check_apply_order_keeps_missing_indexes() -> None:
    """응답에 빠진 인덱스가 있어도 청크를 잃지 않는다(기존 성질).

    잃으면 "리랭커가 아래로 내렸다" 와 "제공자가 빠뜨렸다" 가 뭉개진다.
    """
    sources = _sources(1, 2, 3)

    out = retriever._apply_order(sources, [2, 0])  # 인덱스 1 이 응답에서 빠졌다
    assert [s.chunk_id for s in out] == [3, 1, 2], [s.chunk_id for s in out]

    # 범위 밖 인덱스가 와도 터지지 않는다(제공자가 거짓말을 해도 채팅이 죽으면 안 된다).
    out = retriever._apply_order(sources, [9, 1])
    assert [s.chunk_id for s in out] == [2, 1, 3], [s.chunk_id for s in out]


def main() -> None:
    _check_keywords()
    _check_rrf()
    _check_rerank_fusion()
    _check_rerank_survives_provider_failure()
    _check_apply_order_keeps_missing_indexes()
    print("OK — 낱말 추출 8가지 · RRF 4가지 · 리랭커 융합 3가지 · 제공자 실패 2가지 통과")


if __name__ == "__main__":
    main()
