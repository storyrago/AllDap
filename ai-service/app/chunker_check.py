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


def check_line_without_period_is_still_split() -> None:
    """🔴 마침표가 <없는> 긴 줄도 size 를 넘지 않아야 한다.

    _split_sentences 가 `line.split(".")` 로만 자르기 때문에, 마침표가 없으면
    조각이 하나뿐이라 <길이 상한이 전혀 적용되지 않았다.> 실측(2026-09-03):
        "## 긴 표\\n" + "가나다라마바사아자차"*300, size=500  →  청크 길이 [6, 3008]

    3008자 청크는 이 모듈의 존재 이유("청크 하나에 주제 하나")가 정면으로 무너진 것이다.
    2026-08-03 에 478자 청크에 조항 4개가 들어가 fallback 이 났던 것과 <같은 실패 모드>이고
    규모가 6배다.

    ⚠️ 바로 위 check_long_section_still_splits 는 이걸 못 잡는다 —
       그 지문("가나다라마바사아자차. " * 80)은 <마침표를 갖고 있다.>

    현실적인 입력: PDF·HWPX 표 한 행, 마침표 없이 개행·중점으로만 나열된 조항.
    parsers._parse_docx 가 표를 " | " 로 이어 붙인 줄이 정확히 이 모양이다.
    """
    no_period = "## 긴 표\n" + ("가나다라마바사아자차" * 300)
    chunks = chunk_text(no_period, size=500, overlap=50, split_headings=True)
    lengths = [len(c.content) for c in chunks]
    # +1: _pack 이 "꼬리(overlap) + '\n' + 다음 조각" 으로 새 buf 를 시작하므로,
    # 강제분할로 조각이 정확히 size 자가 되면 그 개행 한 글자만큼 상한을 넘는다.
    assert all(n <= 500 + 50 + 1 for n in lengths), lengths


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


def check_idempotent() -> None:
    """청킹은 <몇 번을 돌려도 같은 결과>여야 한다.

    🔴 이게 깨져서 실제로 코퍼스가 망가졌다 (2026-08-03).
       예전 _split_long 이 개행을 공백으로 바꿔, 두 번째 청킹 때 제목을 못 찾아
       조항이 도로 뭉쳤다. 재청킹이 <조용히 반쪽만> 동작했다.
       청크를 이어 붙여 다시 자르는 rechunk 가 있는 한 이 성질이 필수다.
    """
    once = chunk_text(REGULATION, size=500, overlap=50, split_headings=True)
    restored = "\n".join(c.content for c in once)
    twice = chunk_text(restored, size=500, overlap=50, split_headings=True)
    assert [c.content for c in once] == [c.content for c in twice], (
        [c.content for c in once],
        [c.content for c in twice],
    )


def check_inline_heading_is_recovered() -> None:
    """줄 중간으로 밀려난 제목도 절 경계로 인정한다.

    옛 청커가 개행을 지워버린 텍스트가 DB 에 남아 있어서, 그걸 다시 자를 때
    필요하다. 이게 없으면 이미 저장된 문서는 영원히 안 쪼개진다.
    """
    damaged = "## 제4조 식대 식대는 월 15만원이다. ## 제5조 교육비 도서는 연 50만원이다."
    chunks = chunk_text(damaged, size=500, overlap=50, split_headings=True)
    assert len(chunks) == 2, [c.content for c in chunks]
    assert chunks[1].content.startswith("## 제5조"), chunks[1].content


def check_newlines_survive_long_paragraph() -> None:
    """긴 문단을 쪼개도 줄 구조가 살아남아야 한다 (위 멱등성의 뿌리)."""
    long_doc = "## 긴 절\n" + ("가나다라마바사아자차카타파하. " * 40) + "\n## 다음 절\n짧다."
    chunks = chunk_text(long_doc, size=200, overlap=20, split_headings=True)
    assert any(c.content.startswith("## 다음 절") for c in chunks), [c.content for c in chunks]


def main() -> None:
    checks = [
        check_heading_split,
        check_legacy_behavior,
        check_long_section_still_splits,
        check_line_without_period_is_still_split,
        check_no_heading_document,
        check_index_is_sequential,
        check_idempotent,
        check_inline_heading_is_recovered,
        check_newlines_survive_long_paragraph,
    ]
    for fn in checks:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(checks)}가지 전부 통과.")


if __name__ == "__main__":
    main()
