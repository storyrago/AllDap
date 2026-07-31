"""텍스트를 검색 단위(청크)로 자른다.

전략: 문단(빈 줄) 경계를 최대한 지키면서 목표 길이에 맞춰 묶고,
청크 사이에 약간의 겹침(overlap)을 둬서 경계에서 문맥이 끊기는 걸 줄인다.

※ W4에서 청킹 전략을 바꿔가며 평가 점수를 비교할 예정이므로,
   파라미터는 반드시 바깥에서 주입받도록 열어둔다.
"""
from __future__ import annotations

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


def chunk_text(
    text: str,
    *,
    size: int = 500,
    overlap: int = 50,
) -> list[Chunk]:
    if size <= 0:
        raise ValueError("size는 1 이상이어야 합니다.")
    if not 0 <= overlap < size:
        raise ValueError("overlap은 0 이상 size 미만이어야 합니다.")

    pieces: list[str] = []
    for para in _split_paragraphs(text):
        pieces.extend(_split_long(para, size))

    chunks: list[Chunk] = []
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

    return [
        Chunk(index=i, content=c, meta={"char_len": len(c)})
        for i, c in enumerate(chunks)
    ]
