"""`conflicts.judge_pair` 가 모델 응답을 <올바르게 해석하는지> API 호출 없이 검증한다.

실행:
    cd ai-service && .venv/bin/python -m app.conflicts_check

여기서 재는 것은 "모델이 판정을 잘하는가" 가 아니라 <받은 응답을 우리가 올바르게 읽는가> 다.
모델 품질은 실제 문서로 재야 하고(2026-08-05 실측: 심어둔 모순 3/3 탐지, 중복 문서 5쌍 0오탐),
그건 쿼터가 필요하다. 둘을 섞으면 한도가 없는 날 이 검사도 같이 못 돌린다.
(generator_check.py 와 같은 이유·같은 모양이다)

🔴 가장 위험한 건 <모순 아님이 모순으로 뒤집히는> 경우다.
   목록에 헛것이 뜨면 관리자는 화면을 두 번 다시 안 본다.
"""
from __future__ import annotations

from app import cf, conflicts
from app.conflicts import Candidate

_C = Candidate(
    a_id=1,
    b_id=2,
    distance=0.1,
    a_content="노트북 교체 주기는 3년이다.", a_filename="A.md",
    b_content="노트북 교체 주기는 4년이다.", b_filename="B.md",
)


def _reply(content: str) -> dict:
    """Cloudflare 응답 모양 흉내. cf.text_of 가 읽는 형태 그대로."""
    return {"choices": [{"finish_reason": "stop", "message": {"content": content}}]}


def main() -> None:
    real_run = cf.run
    ok = 0

    def case(name: str, raw: str | None, expect) -> None:
        """expect: True=모순 / False=모순아님 / None=판정실패(None 반환)"""
        nonlocal ok
        if raw is None:
            cf.run = lambda m, p: (_ for _ in ()).throw(RuntimeError("호출 실패"))
        else:
            cf.run = lambda m, p, _r=raw: _reply(_r)
        v = conflicts.judge_pair(_C)
        got = None if v is None else v.conflict
        passed = got is expect
        ok += passed
        print(f"  {'✅' if passed else '❌'} {name}\n       → {got!r} (기대 {expect!r})")

    print("conflicts.judge_pair 응답 해석 검사\n")

    case("정상 모순 판정", '{"conflict": true, "topic": "교체 주기", "a_says": "3년", "b_says": "4년"}', True)
    case("정상 모순 아님", '{"conflict": false, "topic": "", "a_says": "", "b_says": ""}', False)
    # 🔴 파이썬에서 bool("false") 는 True 다. 그대로 믿으면 <모순 아님이 모순으로 뒤집힌다.>
    case('문자열 "false" → 모순 아님', '{"conflict": "false", "reason": "같은 내용"}', False)
    case('문자열 "true" → 모순', '{"conflict": "true", "topic": "x", "a_says": "1", "b_says": "2"}', True)
    # 모델이 코드펜스를 씌우는 버릇 (judge._extract_json 재사용)
    case("```json 코드펜스", '```json\n{"conflict": false}\n```', False)
    case("앞뒤 잡소리", '판정 결과입니다: {"conflict": false} 이상입니다.', False)
    # conflict 키가 아예 없으면 <모순 아님>이어야 한다. 없는 것을 있다고 하면 안 된다.
    case("conflict 키 누락", '{"topic": "뭔가"}', False)
    # 🔴 실패는 "모순 아님"이 아니라 <판정하지 못했다>다. 저장하지 않고 넘어가야 한다.
    case("JSON 이 아님 → 판정 실패", "미안하지만 판단할 수 없습니다", None)
    case("호출 실패 → 판정 실패", None, None)

    cf.run = real_run
    print(f"\n{ok}/9 통과")
    if ok != 9:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
