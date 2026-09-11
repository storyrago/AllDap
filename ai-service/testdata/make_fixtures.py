"""재현 자산(PDF·DOCX·HWPX) 생성기.

실행:  cd ai-service && .venv/bin/python testdata/make_fixtures.py

🔴 이 스크립트는 <출처 기록>이지 빌드 절차가 아니다.
────────────────────────────────────────────────────────────────────
돌려도 커밋된 바이너리와 <바이트가 같지 않다>. PDF 에는 pymupdf 가 생성 시각을,
DOCX 에는 python-docx 가 코어 속성 타임스탬프를 넣고, zip 엔트리에도 시각이 박힌다.
라이브러리 판이 올라가면 내부 구조까지 달라진다.

그래서 `fixtures/` 의 파일들을 저장소에 <함께 커밋한다>. 생성 스크립트만 두면
"파서가 회귀했다" 와 "생성기가 다른 파일을 냈다" 를 구분할 수 없다.
이 저장소가 반복해 낸 부류다(AGENTS.md 의 "낸 버그" 절 - 서로 다른 사실을 같은 값으로 뭉개기).

그러면 이 스크립트는 왜 두는가: 바이너리만 있으면 <무엇이 들어 있어야 하는지>를
사람이 열어봐야만 알 수 있다. 여기 있는 상수가 그 정답지이고,
`app/parsers_check.py` 의 단언이 그 정답지를 그대로 인용한다.

파일을 다시 만들었으면 `parsers_check` 를 돌려 단언이 여전히 맞는지 볼 것.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"

# ── 본문(세 형식이 공유한다) ──────────────────────────────────────────
# 실제 코퍼스(testdata/corpus/)와 같은 결로 썼다. 조항 번호·숫자가 들어 있어야
# "추출은 됐는데 글자가 깨졌다" 를 단언으로 잡을 수 있다.
#
# 🔴 길이에도 이유가 있다. 두 페이지를 합치면 chunk_size(기본 500자)를 넘는다.
#    넘지 않으면 청크가 1개로 끝나 <청킹이 실제로 돌았는지>를 못 본다.
#    upload_e2e_check 가 "텍스트가 chunk_size 보다 길면 청크도 2개 이상" 을 단언한다.
#
# 🔴 한 줄의 길이에도 이유가 있다. pymupdf 의 insert_text 는 <줄바꿈을 하지 않는다> -
#    페이지 폭을 넘으면 조용히 잘린다. 그래서 각 줄을 폭 안에 들어가게 썼고,
#    make_pdf 가 그것을 빌드 시점에 단언한다(나중에 문장을 늘리다 잘리는 것을 막는다).
#    ⚠️ 대신 <줄바꿈된 PDF> 는 이 자산으로 검증되지 않는다. 실제 PDF 는 문단이
#       여러 줄로 접혀 오고, 추출 결과도 그 줄바꿈을 그대로 갖는다. 별도 축이다.
PAGE1 = [
    "주식회사 올답 취업규칙 (검증용 샘플)",
    "제1조 (목적) 파서 검증용 샘플이며 실제 규정이 아니다.",
    "제2조 (적용 범위) 이 규칙은 정규직 사원에게 적용한다.",
    "제3조 (수습기간) 정규직의 수습기간은 3개월로 한다.",
    "제4조 (근로시간) 1주 소정근로시간은 40시간으로 한다.",
    "제5조 (휴게시간) 근로시간 도중 1시간의 휴게를 부여한다.",
    "제6조 (연차휴가) 1년 근속 시 15일의 연차를 부여한다.",
]
PAGE2 = [
    "제7조 (장비 지원) 입사 시 노트북 1대와 모니터를 지급한다.",
    "제8조 (교체 주기) 업무용 노트북의 교체 주기는 3년으로 한다.",
    "제9조 (재택근무) 정규직은 주 2회까지 재택근무를 할 수 있다.",
    "제10조 (경조휴가) 본인 결혼의 경우 5일을 유급으로 부여한다.",
    "제11조 (교육 지원) 직무 도서는 연 50만원까지 지원한다.",
    "제12조 (건강검진) 연 1회 종합검진 비용을 회사가 부담한다.",
    "제13조 (식대) 식대는 월 15만원을 급여와 함께 지급한다.",
    "제14조 (증명서) 재직증명서는 인사팀에 신청하면 발급한다.",
    "제15조 (시행일) 이 규칙은 2026년 1월 1일부터 시행한다.",
]

# DOCX 의 표. 한 행이 " | " 로 이어져 나와야 한다(parsers._parse_docx).
TABLE = [
    ["구분", "지급 한도", "비고"],
    ["도서구입비", "연 50만원", "직무 관련 도서에 한한다"],
    ["건강검진", "연 1회", "종합검진으로 갈음한다"],
]


def make_pdf(path: Path) -> None:
    """한글 2페이지 PDF.

    fontname="korea" 는 pymupdf 내장 CJK 폰트다. 외부 폰트 파일을 저장소에 넣지
    않아도 되고(라이선스 문제가 없다), 추출도 정상으로 돈다는 것을 확인했다.
    """
    import pymupdf

    doc = pymupdf.open()
    left, fontsize = 60, 12
    for lines in (PAGE1, PAGE2):
        page = doc.new_page()
        usable = page.rect.width - left * 2
        y = 90
        for line in lines:
            # 🔴 insert_text 는 넘치면 잘라낸다. 잘린 PDF 를 커밋하면
            #    "파서가 글자를 잃었다" 로 보인다 - 서로 다른 사실이 같은 모습이 된다.
            width = pymupdf.get_text_length(line, fontname="korea", fontsize=fontsize)
            assert width <= usable, f"페이지 폭 초과({width:.0f}/{usable:.0f}pt): {line}"
            page.insert_text((left, y), line, fontname="korea", fontsize=fontsize)
            y += 28
    # 생성 시각 등 메타데이터를 비운다. 바이트 동일성까지는 못 가지만
    # 차분에 잡음이 덜 섞인다.
    doc.set_metadata({})
    doc.save(str(path), garbage=4, deflate=True)
    doc.close()


def make_docx(path: Path) -> None:
    """본문 문단 + 표 1개.

    표를 넣은 이유: `_parse_docx` 가 문단만 읽고 표를 놓치는 회귀가 <조용히>
    일어난다. 본문은 멀쩡히 나오므로 글자 수로는 안 보인다.
    """
    import docx

    d = docx.Document()
    for line in PAGE1 + PAGE2:
        d.add_paragraph(line)
    d.add_paragraph("")  # 빈 문단: 파서가 걸러내야 한다
    table = d.add_table(rows=0, cols=3)
    for row in TABLE:
        cells = table.add_row().cells
        for cell, value in zip(cells, row):
            cell.text = value
    d.save(str(path))


# ── HWPX ────────────────────────────────────────────────────────────
# 외부 라이브러리 없이 zip + XML 로 직접 만든다. `_parse_hwpx` 가 읽는 것은
# Contents/section*.xml 의 <hp:p> / <hp:t> 뿐이므로 그 최소 골격만 갖춘다.
#
# 🔴 두 번째 문단을 <hp:run> 셋으로 쪼개 넣는다. 이것이 이 파일의 핵심이다.
#    한글이 서식 경계마다 run 을 나누기 때문에, run 을 이어 붙이지 않으면
#    "제3조 (장비" / " 지원) 입사 시" / " 노트북..." 처럼 조각난 문단이 나온다.
#    docs/W1-이해노트.md 의 이해 게이트 4번 항목이 바로 이 이야기다.
_SECTION_TMPL = """<?xml version="1.0" encoding="UTF-8"?>
<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"
        xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">
{paras}
</hs:sec>
"""


def _para(runs: list[str]) -> str:
    inner = "".join(f"<hp:run><hp:t>{r}</hp:t></hp:run>" for r in runs)
    return f"  <hp:p>{inner}</hp:p>"


SECTION0_PARAS = [[line] for line in PAGE1]
SECTION1_PARAS = [
    # 일부러 run 3개로 쪼갠 문단
    [
        "제7조 (장비 지원)",
        " 입사 시 노트북 1대와",
        " 모니터를 지급한다.",
    ],
    *[[line] for line in PAGE2[1:]],
    [""],  # 빈 문단: 파서가 걸러내야 한다
]


def make_hwpx(path: Path) -> None:
    buf = io.BytesIO()
    # date_time 을 고정해 zip 헤더에 생성 시각이 안 박히게 한다.
    # (HWPX 는 우리가 직접 만들므로 여기만은 바이트 재현이 가능하다)
    stamp = (2026, 1, 1, 0, 0, 0)
    entries = {
        "mimetype": "application/hwp+zip",
        "Contents/section0.xml": _SECTION_TMPL.format(
            paras="\n".join(_para(r) for r in SECTION0_PARAS)
        ),
        "Contents/section1.xml": _SECTION_TMPL.format(
            paras="\n".join(_para(r) for r in SECTION1_PARAS)
        ),
    }
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, body in entries.items():
            info = zipfile.ZipInfo(name, date_time=stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, body.encode("utf-8"))
    path.write_bytes(buf.getvalue())


NAMES = {
    "취업규칙_샘플.pdf": make_pdf,
    "취업규칙_샘플.docx": make_docx,
    "취업규칙_샘플.hwpx": make_hwpx,
}


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for name, fn in NAMES.items():
        path = FIXTURES / name
        fn(path)
        print(f"{name}: {path.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
