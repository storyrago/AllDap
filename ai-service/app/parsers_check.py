"""parsers 자체 점검 - <실제 바이너리 파일>로 돈다.

실행:  cd ai-service && .venv/bin/python -m app.parsers_check

chunker_check 와 같은 방식이다(assert 와 `python -m` 만. 외부 호출도 DB 도 없다).
다만 입력이 코드 안의 문자열이 아니라 `testdata/fixtures/` 의 진짜 PDF·DOCX·HWPX 다.

🔴 이 파일이 생긴 이유 - 파서에는 회귀를 잡아줄 것이 아무것도 없었다
────────────────────────────────────────────────────────────────────
"실제 한글 PDF·DOCX 파싱 확인" 은 2026-07-31 에 통과했다고 기록돼 있는데
(`docs/W1-이해노트.md` 의 검증 표), **그때 쓴 파일이 저장소에 없었다.**
PDF·DOCX·HWPX 가 0건이었다(`git ls-files` 로 확인). 수동으로 한 번 열어보고 끝냈기 때문이다.

fallback_e2e_check 가 생긴 이유와 정확히 같다: **측정은 재현할 수 없으면 측정이 아니다.**
파일을 `testdata/fixtures/` 에 박제하고, 그 파일에 무엇이 들어 있어야 하는지를
`testdata/make_fixtures.py` 의 상수로 두고, 여기서 그 상수를 그대로 인용한다.

이 점검이 닫는 축 / 안 닫는 축 (섞어서 말하지 말 것)
────────────────────────────────────────────────────────────────────
  ✅ 파서 단위 (파일 → 텍스트)     여기
  ✅ 재현 가능성                   여기 (파일이 저장소에 있다)
  ✅ 업로드 파이프라인 종단        `app/upload_e2e_check.py` - 여기가 아니다
  ❌ 대용량 문서                   여전히 미검증. 이 파일들은 전부 수 KB 다

🔴 <걸려야 할 것이 걸리는지> 를 실제로 확인했다
────────────────────────────────────────────────────────────────────
이 저장소는 "짜둔 검사가 아무 데서도 안 돌거나, 돌아도 아무것도 못 잡는" 사고를
두 번 냈다(2026-09-08 오픈 리다이렉트, 2026-09-09 Forwarded 점검 명령).
그래서 파서를 일부러 셋 망가뜨려 이 점검이 <빨간불이 되는지> 보고 되돌렸다(2026-09-11):

  · HWPX run 병합 제거      → check_hwpx_merges_runs 가 잡았다
  · DOCX 표 순회 제거       → check_docx_table 이 잡았다
  · PDF 페이지 구분자 제거  → check_pdf 가 잡았다

통과했다는 말은 이 셋이 <실제로> 회귀를 잡는다는 뜻이다.
"""
from __future__ import annotations

import sys
from pathlib import Path

from .parsers import ParseError, detect_type, extract_text, normalize

# 정답지는 생성기에서 그대로 가져온다. 여기에 문자열을 다시 적으면
# 파일과 단언이 따로 놀아 "무엇이 맞는지" 가 두 벌이 된다.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from testdata.make_fixtures import FIXTURES, NAMES, PAGE1, PAGE2, TABLE  # noqa: E402

PDF = FIXTURES / "취업규칙_샘플.pdf"
DOCX = FIXTURES / "취업규칙_샘플.docx"
HWPX = FIXTURES / "취업규칙_샘플.hwpx"


def check_fixtures_exist() -> None:
    """재현 가능성 축을 지키는 가드.

    파일이 사라지면 나머지 점검이 조용히 건너뛰어지는 것이 아니라 <여기서 멈춰야> 한다.
    "돌렸는데 통과했다" 와 "돌릴 대상이 없었다" 는 다른 사실이다.
    """
    missing = [n for n in NAMES if not (FIXTURES / n).exists()]
    assert not missing, f"재현 자산이 없다: {missing} (testdata/make_fixtures.py 로 만들 것)"


# ── PDF ─────────────────────────────────────────────────────────────

def check_pdf() -> None:
    ftype, text = extract_text(PDF.name, PDF.read_bytes())
    assert ftype == "pdf", ftype
    for line in PAGE1 + PAGE2:
        assert line in text, (line, text)
    # 페이지 경계는 빈 줄이 된다(`_parse_pdf` 가 "\n\n" 으로 잇는다).
    # 이게 깨지면 마지막 줄과 다음 페이지 첫 줄이 한 문단으로 붙어 청킹이 흐려진다.
    assert f"{PAGE1[-1]}\n\n{PAGE2[0]}" in text, repr(text)
    # 2페이지짜리라는 사실 자체를 박제한다. 1페이지가 되면 위 단언도 같이 깨진다.
    assert text.count("\n\n") == 1, repr(text)


def check_pdf_corrupt_gives_user_message() -> None:
    """깨진 파일은 스택트레이스가 아니라 <사용자가 읽을 수 있는 한국어>로 실패해야 한다.

    이 경로가 깨지면 업로드가 500 으로 나가고, `_process_document` 의
    `except ParseError` 가 아니라 맨 바깥 `except Exception` 에 걸려
    error_message 가 "처리 중 오류가 발생했습니다: ..." 로 뭉개진다.
    """
    try:
        extract_text("깨진.pdf", b"%PDF-1.4 \x00\x01\x02 not really a pdf")
    except ParseError as e:
        assert "PDF" in str(e), str(e)
    else:
        raise AssertionError("깨진 PDF 가 ParseError 없이 통과했다")


# ── DOCX ────────────────────────────────────────────────────────────

def check_docx() -> None:
    ftype, text = extract_text(DOCX.name, DOCX.read_bytes())
    assert ftype == "docx", ftype
    for line in PAGE1 + PAGE2:
        assert line in text, (line, text)


def check_docx_table() -> None:
    """표를 놓치는 회귀는 <조용히> 난다 - 본문이 멀쩡히 나오므로 글자 수로는 안 보인다."""
    _, text = extract_text(DOCX.name, DOCX.read_bytes())
    for row in TABLE:
        assert " | ".join(row) in text, (row, text)


def check_docx_corrupt_gives_user_message() -> None:
    try:
        extract_text("깨진.docx", b"PK\x03\x04 not really a docx")
    except ParseError as e:
        assert "DOCX" in str(e), str(e)
    else:
        raise AssertionError("깨진 DOCX 가 ParseError 없이 통과했다")


def check_docx_drops_empty_paragraph() -> None:
    """빈 문단이 빈 줄로 남으면 normalize 를 거쳐도 청크 경계가 지저분해진다."""
    _, text = extract_text(DOCX.name, DOCX.read_bytes())
    assert "\n\n" not in text, repr(text)


# ── HWPX ────────────────────────────────────────────────────────────

def check_hwpx() -> None:
    ftype, text = extract_text(HWPX.name, HWPX.read_bytes())
    assert ftype == "hwpx", ftype
    for line in PAGE1 + PAGE2:
        assert line in text, (line, text)


def check_hwpx_merges_runs() -> None:
    """🔴 이 점검이 이 파일에서 가장 중요하다.

    fixture 의 제7조는 <hp:run> 3개로 쪼개져 저장돼 있다. 한글이 서식 경계마다
    run 을 나누기 때문에 실제 문서가 늘 그렇다. 이어 붙이지 않으면
    "제7조 (장비" / " 지원) 입사 시..." 처럼 <문단이 조각난다>.

    조각나도 낱말은 다 남아 있어서 글자 수나 "포함" 단언으로는 안 잡힌다.
    그래서 <한 줄로 나오는가>를 직접 본다.
    """
    _, text = extract_text(HWPX.name, HWPX.read_bytes())
    lines = text.splitlines()
    merged = [ln for ln in lines if ln.startswith("제7조")]
    assert merged == [PAGE2[0]], (merged, lines)


def check_hwpx_bad_zip() -> None:
    try:
        extract_text("깨진.hwpx", b"PK\x03\x04 garbage")
    except ParseError as e:
        assert "HWPX" in str(e), str(e)
    else:
        raise AssertionError("깨진 HWPX 가 ParseError 없이 통과했다")


def check_hwpx_without_section() -> None:
    """zip 은 멀쩡한데 본문이 없는 경우. "손상" 과 다른 사실이라 안내도 달라야 한다."""
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("mimetype", "application/hwp+zip")
    try:
        extract_text("본문없음.hwpx", buf.getvalue())
    except ParseError as e:
        assert "section" in str(e), str(e)
    else:
        raise AssertionError("본문 없는 HWPX 가 ParseError 없이 통과했다")


# ── 형식 판정 · 텍스트 ───────────────────────────────────────────────

def check_hwp_message_tells_what_to_do() -> None:
    """AGENTS.md 규칙: 에러는 "무엇을 어떻게 하면 되는지" 까지 알려줘야 한다.

    구형 .hwp 는 우리가 <영원히> 못 여는 것이 아니라 사용자가 다시 저장하면 되는 것이다.
    그 차이가 문구에 남아 있어야 한다.
    """
    try:
        detect_type("규정.hwp")
    except ParseError as e:
        assert ".hwpx" in str(e), str(e)
    else:
        raise AssertionError(".hwp 가 통과했다")


def check_unsupported_extension() -> None:
    try:
        detect_type("표.xlsx")
    except ParseError as e:
        # 지원 목록을 함께 보여줘야 사용자가 무엇으로 바꿔야 할지 안다.
        assert "pdf" in str(e) and "hwpx" in str(e), str(e)
    else:
        raise AssertionError(".xlsx 가 통과했다")


def check_cp949_text() -> None:
    """한국어 환경에서 메모장으로 저장한 .txt 가 여전히 cp949 로 온다."""
    _, text = extract_text("공지.txt", "제2조 수습기간은 3개월".encode("cp949"))
    assert text == "제2조 수습기간은 3개월", repr(text)


def check_normalize() -> None:
    # \xa0(non-breaking space)는 한글 문서에서 흔하다. 그대로 두면 낱말 검색에서 어긋난다.
    assert normalize("제1조\xa0(목적)") == "제1조 (목적)"
    # 빈 줄 3개 이상은 2개로. 청크 경계 판정이 빈 줄에 기대고 있다.
    assert normalize("가\n\n\n\n나") == "가\n\n나"


# 가드를 맨 앞에 둔다. 파일이 없는데 뒤 점검들이 먼저 터지면
# "파서가 깨졌다" 와 "잴 대상이 없다" 가 같은 모습으로 보인다.
CHECKS = [check_fixtures_exist] + [
    v for k, v in sorted(globals().items())
    if k.startswith("check_") and v is not check_fixtures_exist
]


def main() -> None:
    for fn in CHECKS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\nparsers_check: {len(CHECKS)}개 통과")


if __name__ == "__main__":
    main()
