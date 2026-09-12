"""생성된 OpenAPI 명세에 <빈칸>이 없는지 검사한다. DB 도 외부 API 도 없이 돈다.

실행:
    cd ai-service && .venv/bin/python -m app.openapi_check

왜 있나
─────────────────────────────────────────────────────────────────────────────
17번째 엔드포인트를 추가하며 설명을 빠뜨려도 파이썬은 잘 돌고, 기존 점검도 전부
초록이고, /docs 화면도 멀쩡히 뜬다. <그 하나만 조용히 껍데기로 남는다.>
실제로 그렇게 뚫려 있었다(16개 중 4개에 설명이 없었고, 그중 둘이 이 서비스의 핵심
경로인 업로드와 채팅이었다). 빠진 것을 채우는 것으로 끝내면 다음에 또 빠진다.
api/ 의 OpenApiCoverageTest 가 Spring 쪽에서 하는 일과 같은 것을 여기서 한다.

🔴 설명 검사를 `summary or description` 으로 두면 <영원히 통과한다>
─────────────────────────────────────────────────────────────────────────────
이 파일의 첫 판이 그렇게 돼 있었고, docstring 을 통째로 지워도 16/16 통과했다.
FastAPI 는 `summary` 를 <항상 자동으로 채우기> 때문이다:

    fastapi/openapi/utils.py: generate_operation_summary()
        if route.summary: return route.summary
        return route.name.replace("_", " ").title()      # ← 함수 이름에서 만든다

즉 `chat` 은 `"Chat"`, `upload_document` 는 `"Upload Document"` 가 되어 `summary`
쪽이 늘 참이고, `or` 의 뒤쪽인 `description` 은 평가되지도 않는다.
**돌기는 도는데 걸릴 수가 없는 검사**였다. 이 저장소가 이미 두 번 겪은 부류
(오픈 리다이렉트 · 배포 rate limit 점검)에서 한 걸음 더 나간 것이다.

→ 그래서 둘을 <따로> 요구한다. "둘 중 하나만 있어도 되지 않나" 로 되돌리지 말 것.

무엇을 검사하나
─────────────────────────────────────────────────────────────────────────────
① `description` 이 비어 있지 않다. 함수 docstring 이 이 자리로 온다.
② `summary` 가 <자동 생성값이 아니다>. 판정은 `함수이름.replace("_", " ").title()`
   과 같은지 보는 것이다. 같으면 아무도 손으로 쓰지 않았다는 뜻이다.
   ⚠️ 이 판정은 명세만 봐서는 할 수 없다. 명세에는 함수 이름이 없다. 그래서
      `app.routes` 의 APIRoute 에서 (경로, 메서드) -> `route.name` 을 만들어 짝짓는다.
      명세 쪽을 읽는 이유는 그것이 <실제로 화면에 그려지는 값>이기 때문이다.
③ 모든 엔드포인트에 `tags` 가 있고, 그 값이 앱에 선언된 태그 이름 안에 있다.
   오타로 "문서 " 처럼 적으면 Swagger 에 <새 그룹이 조용히 하나 더> 생긴다.
   화면은 멀쩡해 보이는데 분류가 깨진다.
④ 선언해놓고 아무도 안 쓰는 태그가 없다. ③의 반대 방향이다. 엔드포인트가 하나도
   안 붙은 태그는 화면에 나오지 않으므로, 설명을 써두고도 안 보이는 상태가 된다.

⚠️ 태그 이름을 여기에 하드코딩하지 않는다. 명세의 tags 절에서 읽어와 대조한다.
   하드코딩하면 사본이 둘이 되고, 이름을 다듬는 순간 이 검사가 거짓으로 실패한다.

⚠️ 빠진 것은 <전부> 나열한다. 하나만 찍으면 고칠 때마다 다시 돌려야 한다.

🔴 한계: 이 검사는 <빈칸만> 본다.
   설명이 맞는 말인지는 검사하지 못한다. summary 에 "문서 목록 조회" 라고 써놓고
   실제로는 삭제하는 코드여도 그대로 통과한다. 맞는 말인지는 사람이 읽어야 한다.
   그래도 두는 이유는, 빈칸은 기계가 확실히 잡을 수 있고 <잡지 않으면 반드시 늘기>
   때문이다.
"""
from __future__ import annotations

from fastapi.routing import APIRoute

from app.main import app

_failures: list[str] = []

# OpenAPI 에서 경로 항목의 키 중 <HTTP 메서드가 아닌> 것들을 걸러내기 위한 목록.
# 걸러내지 않으면 parameters 같은 공용 키를 엔드포인트로 착각해 없는 실패를 만든다.
_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'OK  ' if ok else 'FAIL'} {name} {detail}")
    if not ok:
        _failures.append(name)


def _auto_summaries() -> dict[tuple[str, str], str]:
    """(경로, 메서드) -> FastAPI 가 <자동으로 만들> summary.

    명세에 찍힌 summary 가 이 값과 같으면 아무도 손으로 쓰지 않은 것이다.
    규칙은 fastapi/openapi/utils.py 의 generate_operation_summary 와 같다.
    """
    out: dict[tuple[str, str], str] = {}
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in route.methods:
            out[(route.path, method.upper())] = route.name.replace("_", " ").title()
    return out


def main() -> int:
    print("OpenAPI 명세 빈칸 점검\n")

    spec = app.openapi()
    declared = [t.get("name", "") for t in spec.get("tags", [])]
    print(f"  ..   선언된 태그 {len(declared)}개: {', '.join(declared) or '(없음)'}")

    # (경로, 메서드, 오퍼레이션) 목록을 먼저 펼친다.
    ops: list[tuple[str, str, dict]] = [
        (path, method.upper(), op)
        for path, item in spec.get("paths", {}).items()
        for method, op in item.items()
        if method in _METHODS
    ]
    print(f"  ..   엔드포인트 {len(ops)}개\n")
    check("엔드포인트가 하나 이상 있다", bool(ops))

    auto = _auto_summaries()

    # ① description (docstring 이 오는 자리)
    no_desc = [f"{m} {p}" for p, m, op in ops if not (op.get("description") or "").strip()]
    check(f"description 이 전부 있다 ({len(ops) - len(no_desc)}/{len(ops)})", not no_desc)
    for one in no_desc:
        print(f"       description 없음(함수 docstring 을 쓸 것): {one}")

    # ② summary 가 자동 생성값이 아닌가.
    #    🔴 "비었는가" 로는 절대 잡히지 않는다. 위 docstring 의 설명 참고.
    #    짝을 못 찾은 경우도 실패로 센다. 판정을 <하지 못한 것>이지 통과가 아니다.
    auto_summary: list[str] = []
    unpaired: list[str] = []
    for p, m, op in ops:
        expected = auto.get((p, m))
        if expected is None:
            unpaired.append(f"{m} {p}")
            continue
        if (op.get("summary") or "").strip() == expected:
            auto_summary.append(f"{m} {p} -> {expected!r}")
    check(f"summary 가 손으로 쓰인 것이다 ({len(ops) - len(auto_summary) - len(unpaired)}/{len(ops)})",
          not auto_summary)
    for one in auto_summary:
        print(f"       summary 가 함수 이름에서 자동 생성된 값이다: {one}")
    check("모든 엔드포인트를 라우트와 짝지었다", not unpaired)
    for one in unpaired:
        print(f"       라우트를 못 찾아 summary 판정을 못 했다: {one}")

    # ③ 태그. <없는 것>과 <선언 밖의 것>을 따로 센다. 원인이 다르다:
    #    전자는 빠뜨린 것이고 후자는 오타이거나 선언을 안 한 것이다.
    no_tag = [f"{m} {p}" for p, m, op in ops if not op.get("tags")]
    unknown = [
        (f"{m} {p}", tag) for p, m, op in ops
        for tag in op.get("tags", []) if tag not in declared
    ]
    check(f"태그가 전부 붙어 있다 ({len(ops) - len(no_tag)}/{len(ops)})", not no_tag)
    for one in no_tag:
        print(f"       태그 없음: {one}")
    check("붙은 태그가 전부 선언된 이름이다", not unknown)
    for one, tag in unknown:
        print(f"       선언에 없는 태그: {one} -> {tag!r}")

    # ④ 선언만 되고 아무도 안 쓰는 태그
    used = {tag for _, _, op in ops for tag in op.get("tags", [])}
    unused = [t for t in declared if t not in used]
    check("선언된 태그가 전부 쓰인다", not unused)
    for tag in unused:
        print(f"       아무도 안 쓰는 태그: {tag!r}")

    print(f"\n{'실패 ' + ', '.join(_failures) if _failures else '전부 통과'}")
    return 1 if _failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
