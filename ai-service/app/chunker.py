"""텍스트를 검색 단위(청크)로 자른다.

전략: <제목 경계를 절대 넘지 않고>, 그 안에서 문단(빈 줄) 경계를 지키며
목표 길이에 맞춰 묶는다. 같은 절 안에서만 약간의 겹침(overlap)을 둬서
경계에서 문맥이 끊기는 걸 줄인다.

🔴 제목 경계 분할은 W4 평가에서 <실측으로> 필요해진 것이다 (2026-08-03).
   원래는 빈 줄만 문단 경계로 봤는데, 실제 규정 문서는 제목과 본문 사이에
   빈 줄이 없다:

       ## 제4조 식대 및 교통비
       식대는 월 15만원을 ...
       ## 제5조 교육비 지원
       ...

   그래서 문서 전체가 <한 문단>으로 잡혀 500자씩 기계적으로 묶였고,
   478자 청크 하나에 조항 4개(식대·교육비·장비·건강검진)가 들어갔다.
   그 청크의 임베딩은 네 주제의 평균이 되어 "노트북 교체 주기" 같은
   구체적 질문에 걸리지 않는다 — 실제로 답이 문서에 있는데도 검색 5위 안에
   그 문서가 아예 안 들어와 fallback 이 났다.

   교훈: <임베딩 하나가 대표할 수 있는 것은 주제 하나다.>
   한 청크에 주제를 여럿 담으면 그 벡터는 어느 쪽도 잘 대표하지 못한다.

※ `split_headings=False` 로 두면 예전 동작 그대로다. before/after 비교를
   재현할 수 있어야 하므로 지우지 말 것.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Chunk:
    index: int
    content: str
    meta: dict


def _split_paragraphs(text: str) -> list[str]:
    parts = [p.strip() for p in text.split("\n\n")]
    return [p for p in parts if p]


def _split_long(paragraph: str, size: int) -> list[str]:
    """한 문단이 목표 크기보다 훨씬 길면 문장 단위로 쪼갠다."""
    if len(paragraph) <= size:
        return [paragraph]

    out, buf = [], ""
    # 한국어/영어 문장 끝을 대략적으로 잡는다
    for sentence in paragraph.replace("。", ".").split("."):
        s = sentence.strip()
        if not s:
            continue
        s += "."
        if len(buf) + len(s) > size and buf:
            out.append(buf.strip())
            buf = s
        else:
            buf += " " + s
    if buf.strip():
        out.append(buf.strip())
    return out or [paragraph[:size]]


# 마크다운 제목 줄(`#` ~ `######` + 공백 + 내용). 빈 줄이 없어도 여기서 자른다.
_HEADING = re.compile(r"^#{1,6}[ \t]+\S", re.M)


def _split_sections(text: str) -> list[str]:
    """제목 줄 <앞>에서 통째로 자른다. 제목은 뒤따르는 절에 붙는다.

    제목을 절 안에 남기는 이유: "## 제6조 장비 지원" 자체가 그 절이 무슨 얘기인지
    말해주는 가장 강한 신호다. 떼어내면 임베딩이 주제를 잃는다.
    """
    starts = [m.start() for m in _HEADING.finditer(text)]
    if not starts:
        return [text]
    if starts[0] != 0:
        starts.insert(0, 0)  # 첫 제목 앞의 머리말도 하나의 절로 살린다
    bounds = starts + [len(text)]
    out = []
    for a, b in zip(bounds, bounds[1:]):
        piece = text[a:b].strip()
        if piece:
            out.append(piece)
    return out


def _pack(pieces: list[str], size: int, overlap: int) -> list[str]:
    """조각들을 size 를 넘지 않게 묶는다. 겹침은 <이 묶음 안에서만> 준다."""
    chunks: list[str] = []
    buf = ""
    for piece in pieces:
        candidate = f"{buf}\n{piece}".strip() if buf else piece
        if len(candidate) > size and buf:
            chunks.append(buf)
            # 앞 청크의 꼬리를 겹쳐서 시작
            tail = buf[-overlap:] if overlap else ""
            buf = f"{tail}\n{piece}".strip() if tail else piece
        else:
            buf = candidate
    if buf.strip():
        chunks.append(buf.strip())
    return chunks


def chunk_text(
    text: str,
    *,
    size: int = 500,
    overlap: int = 50,
    split_headings: bool = True,
) -> list[Chunk]:
    if size <= 0:
        raise ValueError("size는 1 이상이어야 합니다.")
    if not 0 <= overlap < size:
        raise ValueError("overlap은 0 이상 size 미만이어야 합니다.")

    # 절 경계를 먼저 세운다. 이 경계는 <절대> 넘지 않는다 —
    # 넘는 순간 한 벡터가 주제 둘을 대표하게 되고, 그러면 어느 쪽도 못 찾는다.
    sections = _split_sections(text) if split_headings else [text]

    chunks: list[str] = []
    for section in sections:
        pieces: list[str] = []
        for para in _split_paragraphs(section):
            pieces.extend(_split_long(para, size))
        chunks.extend(_pack(pieces, size, overlap))

    return [
        Chunk(index=i, content=c, meta={"char_len": len(c)})
        for i, c in enumerate(chunks)
    ]
