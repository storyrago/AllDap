"""변경 기록과 문장 틀로 모범 답안을 만든다(스펙 4-3절, 4-5절).

모범 답안은 판단 이유와 끝의 `So the overall score is n. [RESULT] n` 이다. 이유는 사람이나 다른 AI 가 쓰지 않고
변경 기록(무엇을 무엇으로 바꿨는지)에서 정해진 틀로 만든다. 그래서 이유와 정답 점수가 어긋나지 않는다.

문장 틀 파일(testdata/judgeft/templates.json)에는 빈칸만 있고 값이 없다. 근거의 값과 대상은 이 모듈이
변경 기록에서 채운다. 틀 파일에 한글이 있으면 어떤 문항의 값이 틀에 들어간 것이므로 점검이 막는다(스펙 5-3절).
외부 API 도 DB 도 부르지 않는다.
"""
from __future__ import annotations

import random
import re
import string

from .judgeft_files import SEED, TABLE_SCORE, TEMPLATES, read_json, value_in

# 틀 묶음마다 쓸 수 있는 빈칸과 반드시 있어야 하는 빈칸(스펙 4-5절의 "유형마다 담는 판단" 표).
SLOTS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "five_target": (frozenset({"target", "evidence"}), frozenset({"target", "evidence"})),
    "five_plain": (frozenset({"evidence"}), frozenset({"evidence"})),
    "four": (frozenset({"evidence", "added"}), frozenset({"evidence", "added"})),
    "three": (frozenset({"evidence", "added"}), frozenset({"evidence", "added"})),
    "two": (frozenset({"evidence", "added"}), frozenset({"evidence", "added"})),
    "six_target": (frozenset({"target", "evidence", "value"}), frozenset({"target", "evidence", "value"})),
    "six_plain": (frozenset({"evidence", "value"}), frozenset({"evidence", "value"})),
    "seven": (frozenset({"gist"}), frozenset({"gist"})),
    "eight": (frozenset({"target", "evidence", "value", "other_target", "other_evidence"}),
              frozenset({"target", "evidence", "value", "other_target", "other_evidence"})),
}
MIN_TEMPLATES = 3      # 스펙 4-5절: 유형마다 세 개 이상
HANGUL = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ]")


def template_problems(templates: dict) -> list[str]:
    """문장 틀 파일이 규칙대로인가. 문제 목록(빈 목록이면 통과)."""
    out = []
    if set(templates) != set(SLOTS):
        out.append(f"틀 묶음의 이름이 다르다: 있어야 할 것 {sorted(SLOTS)}, 있는 것 {sorted(templates)}")
    for key, texts in templates.items():
        allowed, required = SLOTS.get(key, (frozenset(), frozenset()))
        if len(texts) < MIN_TEMPLATES:
            out.append(f"{key}: 틀이 {len(texts)}개다. {MIN_TEMPLATES}개 이상 둔다")
        for i, text in enumerate(texts):
            # string.Formatter().parse 는 "{a} 와 {b}" 를 (앞 글자, 빈칸 이름, ...) 조각으로 나눈다.
            names = {name for _, name, _, _ in string.Formatter().parse(text) if name is not None}
            if names - allowed or required - names:
                out.append(f"{key}[{i}]: 빈칸 {sorted(names)} 가 규칙과 다르다(필요 {sorted(required)})")
            if HANGUL.search(text):
                out.append(f"{key}[{i}]: 틀에 한글이 있다. 값은 변경 기록에서 채운다(스펙 5-3절)")
            if "[RESULT]" in text or "overall score" in text:
                out.append(f"{key}[{i}]: 끝맺음은 이 모듈이 붙인다. 틀에 적지 않는다")
    return out


def group_for(t: int, has_target: bool) -> str:
    """유형 번호(짝 문항은 1)에서 틀 묶음 이름을 정한다. 대상이 없는 질문은 대상 문장이 없는 묶음을 쓴다."""
    if t in (1, 2):
        return "five_target" if has_target else "five_plain"
    if t == 6:
        return "six_target" if has_target else "six_plain"
    return {3: "four", 4: "three", 5: "two", 7: "seven", 8: "eight"}[t]


def _quote_list(items: list[dict]) -> str:
    """근거 인용 목록을 '"원문" ([근거 2]); "원문" ([근거 3])' 꼴로 쓴다. 근거 머리표는 지시문의 [근거 i] 와 같다."""
    return "; ".join(f"\"{e['quote']}\" ([근거 {e['source']}])" for e in items)


def record_problems(t: int, rec: dict, question: dict, sources: list[dict]) -> list[str]:
    """변경 기록이 모범 답안을 만들 만큼 갖춰졌고 근거와 글자로 맞는가(스펙 5-2절 확인 1). sources 는 근거 청크 목록."""
    out = []
    ev = rec.get("evidence") or []
    if t != 7 and not ev:
        out.append("evidence(근거 주장)가 비었다")
    quotes = list(ev) + ([rec["other"]] if t == 8 and isinstance(rec.get("other"), dict) else [])
    for e in quotes:
        i = e.get("source")
        # type(i) is int: bool 을 막는다. 근거 번호는 지시문과 같이 1 부터 센다.
        if type(i) is not int or not 1 <= i <= len(sources):
            out.append(f"근거 번호 {i!r} 가 근거 청크 범위(1~{len(sources)}) 밖이다")
        elif not e.get("quote") or e["quote"] not in sources[i - 1]["content"]:
            out.append(f"인용 {e.get('quote')!r} 가 [근거 {i}] 에 글자 그대로 있지 않다")
    if t in (1, 2, 6, 8) and rec.get("target") is not None and not isinstance(rec["target"], str):
        out.append("target 은 글자이거나 null 이다")
    if t == 8:
        c = question.get("contrast") or {}
        other = rec.get("other") or {}
        if rec.get("target") != (c.get("asked") or {}).get("target"):
            out.append("⑧ 의 target 이 질문의 대상(contrast.asked.target)과 다르다")
        # 첫째 인용은 질문 대상의 값이다. ⑧ 의 모범 답안은 이것만, 짝 문항의 모범 답안은 전부를 인용한다.
        asked_value = (c.get("asked") or {}).get("value")
        if ev and not (isinstance(ev[0].get("quote"), str) and asked_value and value_in(asked_value, ev[0]["quote"])):
            out.append("⑧ 의 evidence 첫째는 질문 대상의 값(contrast.asked.value)이 적힌 구절이다")
        # 짝 문항의 5점 모범 답안은 "모든 주장이 근거에 있다" 고 쓰므로, 인용이 멀쩡한 답변의 주장마다 있어야 한다(스펙 4-3절).
        if type(question.get("claims")) is int and len(ev) != question["claims"]:
            out.append(f"⑧ 의 evidence 는 멀쩡한 답변의 주장마다 하나씩, {question['claims']}개 적는다(지금 {len(ev)}개)")
        if other.get("target") != (c.get("other") or {}).get("target"):
            out.append("⑧ 의 other.target 이 contrast.other.target 과 다르다")
    if t in (3, 4, 5) and not rec.get("added"):
        out.append("③, ④, ⑤ 는 added(더하거나 바꾼 주장)를 적는다")
    if t == 7 and not rec.get("gist"):
        out.append("⑦ 은 gist(지어낸 답변의 요지)를 적는다")
    return out


def render(t: int, rec: dict, question: dict, item_id: str, templates: dict, seed: int = SEED) -> str:
    """모범 답안 하나. t 는 유형(짝 문항은 1), item_id 는 문항 id 다. 틀은 random.Random(f"{seed}:{item_id}") 로 고른다.

    문항 id 로 고르는 이유: 같은 입력이면 다시 만들어도 같은 틀이 나와야 학습 데이터의 해시가 재현된다.
    """
    group = group_for(t, rec.get("target") is not None)
    text = random.Random(f"{seed}:{item_id}").choice(templates[group])
    c = question.get("contrast") or {}
    values = {
        "target": rec.get("target"),
        # ⑧ 은 질문 대상의 값(첫째 인용)만 인용한다. 나머지 인용은 짝 문항이 쓴다.
        "evidence": _quote_list((rec.get("evidence") or [])[:1] if t == 8 else rec.get("evidence") or []),
        "value": rec.get("new_value") if t == 6 else (c.get("other") or {}).get("value"),
        "other_target": (rec.get("other") or {}).get("target"),
        "other_evidence": _quote_list([rec["other"]]) if rec.get("other") else None,
        "added": ", ".join(f"\"{a}\"" for a in rec.get("added") or []),
        "gist": f"\"{rec.get('gist')}\"",
    }
    score = TABLE_SCORE[t]
    # format(**values): 틀의 {이름} 자리에 같은 이름의 값을 넣는다. 틀에 없는 이름은 쓰이지 않는다.
    return f"{text.format(**values)} So the overall score is {score}. [RESULT] {score}"


def load_templates() -> dict:
    return read_json(TEMPLATES)
