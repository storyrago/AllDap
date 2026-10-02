"""app/ 이 tools/ 를 import 하지 않는지 검사한다. DB 도 외부 API 도 없이 돈다.

실행:
    cd ai-service && .venv/bin/python -m tools.import_boundary_check

왜 있나
─────────────────────────────────────────────────────────────────────────────
tools/__init__.py 가 정한 규칙은 "의존 방향은 tools → app 한쪽뿐" 이다. 그런데 운영
이미지는 `ai-service/app` 만 복사한다(Dockerfile). 그래서 app 안의 누가 tools 를
import 하면 <로컬과 CI 에서는 멀쩡히 돌고> 운영 컨테이너에서만 ModuleNotFoundError 로
죽는다. 로컬에는 tools/ 가 늘 옆에 있으니 사람이 알아챌 기회가 없다. 그래서 규칙을
글로 두지 않고 여기서 막는다.

두 가지로 본다 (하나만으로는 구멍이 있다)
─────────────────────────────────────────────────────────────────────────────
① 실제 import: 깨끗한 새 파이썬 프로세스에서 app 의 모든 모듈을 import 한 뒤
   sys.modules 에 tools 로 시작하는 모듈이 있는지 본다.
   - 새 프로세스인 이유: 이 파일 자체가 `python -m tools.import_boundary_check` 로 돌아
     지금 프로세스에는 tools 와 tools.import_boundary_check 가 <이미> 올라와 있다.
     여기서 sys.modules 를 보면 항상 걸린다.
   - app.main 만이 아니라 <전부>인 이유: reembed · rechunk 는 main 이 import 하지 않는
     운영 절차다. main 만 보면 그 둘이 tools 를 불러도 통과한다.
② 소스 훑기(AST): 함수 안에서 늦게 import 하면(`def f(): from tools import x`) ①은
   그 함수가 불리기 전까지 못 본다. 그래서 app/ 의 모든 .py 를 문법 트리로 읽어
   import 문을 위치와 무관하게 전부 센다.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

# 이 파일은 ai-service/tools/ 에 있다. parent 가 tools, 그 parent 가 ai-service 다.
_ROOT = Path(__file__).resolve().parent.parent
_APP = _ROOT / "app"

# 새 프로세스에서 돌릴 코드. app 의 모든 모듈을 import 하고, 올라온 tools* 모듈을 한 줄씩 찍는다.
_PROBE = """
import importlib, pkgutil, sys
import app
for m in pkgutil.walk_packages(app.__path__, "app."):
    importlib.import_module(m.name)
for name in sorted(sys.modules):
    if name == "tools" or name.startswith("tools."):
        print(name)
"""


def _is_tools(module: str | None) -> bool:
    return module is not None and (module == "tools" or module.startswith("tools."))


def runtime_violations() -> list[str]:
    """① 새 프로세스에서 app 전체를 import 하고 올라온 tools* 모듈 이름을 돌려준다."""
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=_ROOT, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        # import 자체가 실패한 것은 "위반 없음" 이 아니다. 둘을 같은 값으로 뭉개지 않는다.
        raise RuntimeError(f"app 모듈을 import 하지 못했습니다:\n{proc.stderr}")
    return [line for line in proc.stdout.splitlines() if line]


def static_violations() -> list[str]:
    """② app/ 의 소스에서 tools 를 가리키는 import 문을 찾아 '파일:줄  문장' 으로 돌려준다."""
    found = []
    for path in sorted(_APP.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                hits = [a.name for a in node.names if _is_tools(a.name)]
            elif isinstance(node, ast.ImportFrom):
                # 상대 import(level > 0)는 app 패키지 안을 가리키므로 tools 일 수 없다.
                hits = [node.module] if node.level == 0 and _is_tools(node.module) else []
            else:
                continue
            for h in hits:
                found.append(f"{path.relative_to(_ROOT)}:{node.lineno}  import {h}")
    return found


def main() -> int:
    print("app → tools import 금지 검사")
    runtime = runtime_violations()
    static = static_violations()

    print(f"  ① 실제 import 후 sys.modules 의 tools 모듈: {len(runtime)}개")
    for name in runtime:
        print(f"     {name}")
    print(f"  ② app/ 소스의 tools import 문: {len(static)}개")
    for line in static:
        print(f"     {line}")

    if runtime or static:
        print("🔴 app 이 tools 를 import 합니다. 운영 이미지에는 tools/ 가 없어 그 자리에서 죽습니다.")
        print("   → 필요한 코드를 app/ 으로 옮기거나, 그 기능을 tools/ 쪽에서 app 을 부르게 바꾸세요.")
        return 1
    print("✅ 통과: app 은 tools 를 import 하지 않습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
