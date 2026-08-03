"""chunker 자체 점검.

실행:  cd ai-service && .venv/bin/python -m app.chunker_check

evaluator_check.py 와 같은 방식이다 — assert 와 `python -m` 만 쓴다.
외부 호출도 DB 도 없어서 pytest 없이 바로 돌아간다.

여기서 지키는 것: <청크 하나에 주제 하나>.
이게 깨지면 임베딩이 여러 주제의 평균이 되어 어느 질문에도 잘 안 걸린다.
실제로 2026-08-03 평가에서 그 일이 났다 — 478자 청크에 조항 4개가 들어가
답이 문서에 있는데도 검색 5위 안에 못 들어와 fallback 이 났다.
"""
from __future__ import annotations

from .chunker import chunk_text

# 실제 코퍼스와 같은 모양: 제목과 본문 사이에 <빈 줄이 없다>.
# 이게 핵심이다. 빈 줄이 있었다면 예전 문단 분할로도 잘렸을 것이다.
REGULATION = """# 취업규칙
## 제4조 식대 및 교통비
식대는 월 15만원을 급여와 함께 지급한다. 교통비는 지급하지 않는다.
## 제5조 교육비 지원
직무 관련 도서는 연간 50만원 한도로 전액 지원한다.
## 제6조 장비 지원
입사 시 노트북과 모니터 1대를 지급한다. 노트북 교체 주기는 3년이다.
"""


def check_heading_split() -> None:
    chunks = chunk_text(REGULATION, size=500, overlap=50, split_headings=True)
    # 제목이 4개(H1 1 + H2 3)이므로 청크도 4개여야 한다.
    assert len(chunks) == 4, [c.content for c in chunks]
    # 어느 청크도 제목 경계를 넘지 않는다 = 청크마다 <제목 줄>이 정확히 하나.
    for c in chunks:
        headings = [ln for ln in c.content.splitlines() if ln.lstrip().startswith("#")]
        assert len(headings) == 1, (headings, c.content)
    # 제목이 본문과 함께 남아 있어야 한다. 떼면 그 청크가 무슨 주제인지 잃는다.
    장비 = [c for c in chunks if "노트북" in c.content]
    assert len(장비) == 1, 장비
    assert 장비[0].content.startswith("## 제6조 장비 지원"), 장비[0].content
    # 다른 조항이 섞여 들어오면 안 된다 — 이게 원래 버그였다.
    assert "식대" not in 장비[0].content, 장비[0].content
    assert "도서" not in 장비[0].content, 장비[0].content


def check_legacy_behavior() -> None:
    """끄면 예전 동작 그대로. before/after 비교를 재현할 수 있어야 한다."""
    chunks = chunk_text(REGULATION, size=500, overlap=50, split_headings=False)
    assert len(chunks) == 1, [c.content for c in chunks]
    # 예전에는 조항 넷이 한 청크에 뭉쳤다는 사실 자체를 박제해둔다.
    assert "식대" in chunks[0].content and "노트북" in chunks[0].content


def check_long_section_still_splits() -> None:
    """절 하나가 size 를 넘으면 그 안에서는 여전히 쪼개진다.
    제목 분할이 길이 상한을 무력화하면 안 된다."""
    long_body = "## 긴 조항\n" + ("가나다라마바사아자차. " * 80)
    chunks = chunk_text(long_body, size=200, overlap=20, split_headings=True)
    assert len(chunks) > 1, len(chunks)
    assert all(len(c.content) <= 200 + 20 for c in chunks), [len(c.content) for c in chunks]


def check_no_heading_document() -> None:
    """제목이 없는 문서(txt 등)도 깨지지 않는다."""
    plain = "첫 문단입니다.\n\n둘째 문단입니다."
    chunks = chunk_text(plain, size=500, overlap=50, split_headings=True)
    assert len(chunks) == 1, [c.content for c in chunks]
    assert "첫 문단" in chunks[0].content and "둘째 문단" in chunks[0].content


def check_index_is_sequential() -> None:
    """절이 여러 개여도 index 는 문서 전체 기준으로 0,1,2… 로 이어져야 한다.
    절마다 0 부터 다시 시작하면 chunk_index 가 중복돼 순서가 무너진다."""
    chunks = chunk_text(REGULATION, size=500, overlap=50, split_headings=True)
    assert [c.index for c in chunks] == list(range(len(chunks))), [c.index for c in chunks]


def main() -> None:
    checks = [
        check_heading_split,
        check_legacy_behavior,
        check_long_section_still_splits,
        check_no_heading_document,
        check_index_is_sequential,
    ]
    for fn in checks:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(checks)}가지 전부 통과.")


if __name__ == "__main__":
    main()
