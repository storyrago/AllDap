"""OpenAPI 명세와 라우트에 <빈칸>이 없는지 검사한다. DB 도 외부 API 도 없이 돈다.

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

→ 그래서 `summary` 와 설명을 <따로> 요구한다. "둘 중 하나만 있어도 되지 않나" 로
  되돌리지 말 것.

🔴 그 다음, 설명 검사의 <대상>이 명세에서 코드로 옮겨갔다
─────────────────────────────────────────────────────────────────────────────
FastAPI 는 함수 docstring 을 <자동으로> API `description` 에 싣는다. 그래서 코드에
남긴 긴 근거(이모지·코드 서식 포함)가 /docs 화면에 그대로 쏟아져 난잡해졌다.
springdoc 은 Javadoc 을 읽지 않으므로 Spring 화면에는 그런 산문이 없다. 두 화면의
결이 달라진 것이다.

**docstring 을 지우는 것이 아니라 렌더링만 끈다.** 데코레이터에
`description=_NO_DESCRIPTION`(공백 한 칸)을 넘기면 FastAPI 가 docstring 대신
그것을 쓰고, 공백은 `.strip()` 후 빈 문자열이라 명세에서 통째로 빠진다:

    fastapi/routing.py:531-534
        self.description = description or cleandoc(self.endpoint.__doc__ or "")
        self.description = self.description.split("\f")[0].strip()   # ← " " -> ""

코드에는 그대로 남고 명세에서만 사라진다. 그래서 검사도 <보는 곳>을 옮겼다.

    ① "명세에 description 이 있는가" → "함수에 docstring 이 있는가"(`__doc__`)
    ② 그리고 반대로 "명세에 description 이 <없는가>" 를 새로 요구한다.

②를 두는 이유는 `description=` 을 빠뜨려도 <아무 일도 안 일어나기> 때문이다. 화면은
멀쩡히 뜨고 어떤 검사도 안 걸리며, 방금 정리한 난잡함이 조용히 되돌아온다.
⚠️ **②는 설명이 나빠서 막는 것이 아니라 Spring 화면과 결을 맞추려는 것이다.**
   "이 엔드포인트만은 화면에 설명을 넣고 싶다" 가 정말로 생기면, 이 문단을 근거로
   ②를 고치면 된다. 판단이 갈릴 수 있는 자리라 근거를 여기 남긴다.

🔴 그리고 ②가 <실제로> 값을 했다: `\f` 방식은 로컬에서만 동작했다 (2026-09-13)
─────────────────────────────────────────────────────────────────────────────
처음 택한 방식은 위의 `description=` 이 아니라 docstring 맨 앞에 `\f`(form feed)를
넣는 것이었다. FastAPI 가 공식 지원하는 방식이고, 로컬에서 주입 실험을 일곱 번
돌려 "빠뜨리면 걸린다" 까지 확인했다. **그런데 CI 에서 16건이 한꺼번에 실패했다.**

원인은 `inspect.cleandoc` 이 docstring 첫 줄을 정리하는 방식이 파이썬 버전 사이에
달라진 것이다:

    | Python              | cleandoc 후 맨 앞 `\f` | 결과                      |
    | 3.13 (로컬 venv)     | 살아남는다              | FastAPI 가 잘라냄 → 통과   |
    | 3.11 (CI)           | <지워진다>              | 자를 지점이 없음 → 새어나감 |

3.11 은 첫 줄에 `lstrip()`(모든 공백 제거)을 걸고 **파이썬은 `\f` 를 공백으로 친다.**
3.13 은 `lstrip(' ')`(스페이스만)로 바뀌어 `\f` 가 살아남는다.
즉 `\f` 는 **로컬에서만 되는 방식**이었고, 그래서 `description=` 으로 바꿨다.

🔴 **교훈: 검사를 로컬에서만 확인하면 그 검사가 <무엇을 보고 있는지>까지만 알 뿐,
   운영에서 같은 결과가 나오는지는 모른다.** 주입 실험 일곱 번이 전부 초록이었는데
   그게 전부 3.13 에서 본 것이었다. 잡아낸 것은 CI 였다.

🔴 **그리고 이 검사가 살아남은 이유는 <방식이 아니라 결과>를 재기 때문이다.**
   ②는 "`\f` 가 있는가" 를 보지 않는다. `op.get("description")` 이 비었는지를 본다.
   그래서 방식이 `\f` → `description=` 으로 통째로 바뀌었는데도 판정 로직은 한 줄도
   안 고쳤다(고친 것은 안내 문구뿐이다). 다음에 방식이 또 바뀌어도 그대로 유효하다.
   **판정을 방식 쪽으로 되돌리지 말 것.**

무엇을 검사하나
─────────────────────────────────────────────────────────────────────────────
① 모든 엔드포인트 함수에 <알맹이 있는> docstring 이 있다.
   ⚠️ `\f` 와 공백을 걷어낸 뒤 남는 것으로 판정한다. 안 그러면 `\"\"\"\f\"\"\"` 로
      검사를 통과시킬 수 있고, 그건 위에 적은 "걸릴 수 없는 검사" 와 같은 구멍이다.
      (`\f` 는 이제 쓰지 않지만, 옛 방식이 남아도 통과시키지 않으려고 계속 걷어낸다)
② 명세에 `description` 이 없다(= 데코레이터에 `description=_NO_DESCRIPTION` 을 넣었다).
③ `summary` 가 <자동 생성값이 아니다>. 판정은 `함수이름.replace("_", " ").title()`
   과 같은지 보는 것이다. 같으면 아무도 손으로 쓰지 않았다는 뜻이다.
   ⚠️ 이 판정은 명세만 봐서는 할 수 없다. 명세에는 함수 이름이 없다. 그래서
      `app.routes` 의 APIRoute 에서 (경로, 메서드) -> route 를 만들어 짝짓는다.
④ 모든 엔드포인트에 `tags` 가 있고, 그 값이 앱에 선언된 태그 이름 안에 있다.
   오타로 "문서 " 처럼 적으면 Swagger 에 <새 그룹이 조용히 하나 더> 생긴다.
   화면은 멀쩡해 보이는데 분류가 깨진다.
⑤ 선언해놓고 아무도 안 쓰는 태그가 없다. ④의 반대 방향이다. 엔드포인트가 하나도
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


def _route_map() -> dict[tuple[str, str], APIRoute]:
    """(경로, 메서드) -> 라우트. 명세에 없는 것(함수 이름·docstring)을 보려고 만든다."""
    out: dict[tuple[str, str], APIRoute] = {}
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in route.methods:
            out[(route.path, method.upper())] = route
    return out


def _auto_summary(route: APIRoute) -> str:
    """FastAPI 가 <자동으로 만들> summary. 규칙은 generate_operation_summary 와 같다."""
    return route.name.replace("_", " ").title()


def _doc_body(route: APIRoute) -> str:
    """docstring 에서 `\\f` 와 공백을 걷어낸 알맹이."""
    return (route.endpoint.__doc__ or "").replace("\f", "").strip()


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

    routes = _route_map()

    # 짝을 못 찾으면 ①·③ 을 <판정하지 못한 것>이다. 통과가 아니므로 먼저 갈라낸다.
    unpaired = [f"{m} {p}" for p, m, _ in ops if (p, m) not in routes]
    check("모든 엔드포인트를 라우트와 짝지었다", not unpaired)
    for one in unpaired:
        print(f"       라우트를 못 찾아 설명·summary 판정을 못 했다: {one}")
    paired = [(p, m, op, routes[(p, m)]) for p, m, op in ops if (p, m) in routes]

    # ① 함수 docstring 이 있는가. <명세가 아니라 코드>를 본다(`\f` 때문. 위 설명 참고).
    no_doc = [f"{m} {p}" for p, m, _, r in paired if not _doc_body(r)]
    check(f"함수 docstring 이 전부 있다 ({len(paired) - len(no_doc)}/{len(paired)})", not no_doc)
    for one in no_doc:
        print(f"       docstring 이 없거나 알맹이가 없다: {one}")

    # ② 명세에는 description 이 없어야 한다 (= 데코레이터에 description=_NO_DESCRIPTION).
    #    ⚠️ 설명이 나빠서가 아니라 Spring 화면과 결을 맞추려는 것이다. 위 문단 참고.
    #    🔴 판정은 <방식>이 아니라 <결과>를 본다. "`\f` 가 있는가" 가 아니라 "명세의
    #       description 이 비었는가" 다. 그래서 방식이 `\f` 에서 `description=` 으로
    #       바뀌었을 때 이 줄은 한 글자도 안 고쳤고, 오히려 `\f` 가 파이썬 3.11 에서
    #       안 먹는다는 것을 이 줄이 CI 에서 잡아냈다. 방식 쪽으로 되돌리지 말 것.
    rendered = [f"{m} {p}" for p, m, op, _ in paired if (op.get("description") or "").strip()]
    check(f"docstring 이 화면에 안 새어나온다 (설명 노출 {len(rendered)}건)", not rendered)
    for one in rendered:
        print(
            "       데코레이터에 `description=_NO_DESCRIPTION` 을 넣을 것"
            f"(화면이 난잡해진다): {one}"
        )

    # ③ summary 가 자동 생성값이 아닌가.
    #    🔴 "비었는가" 로는 절대 잡히지 않는다. 위 docstring 의 설명 참고.
    auto = [
        f"{m} {p} -> {_auto_summary(r)!r}"
        for p, m, op, r in paired
        if (op.get("summary") or "").strip() == _auto_summary(r)
    ]
    check(f"summary 가 손으로 쓰인 것이다 ({len(paired) - len(auto)}/{len(paired)})", not auto)
    for one in auto:
        print(f"       summary 가 함수 이름에서 자동 생성된 값이다: {one}")

    # ④ 태그. <없는 것>과 <선언 밖의 것>을 따로 센다. 원인이 다르다:
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

    # ⑤ 선언만 되고 아무도 안 쓰는 태그
    used = {tag for _, _, op in ops for tag in op.get("tags", [])}
    unused = [t for t in declared if t not in used]
    check("선언된 태그가 전부 쓰인다", not unused)
    for tag in unused:
        print(f"       아무도 안 쓰는 태그: {tag!r}")

    print(f"\n{'실패 ' + ', '.join(_failures) if _failures else '전부 통과'}")
    return 1 if _failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
