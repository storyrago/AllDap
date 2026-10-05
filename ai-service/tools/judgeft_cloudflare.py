"""M1(Cloudflare)으로 새 시험지를 채점한다. 실행 번호(1, 2, 3)를 받는다(스펙 8-1절).

실행:
    cd ai-service
    $PY -m tools.judge5_cloudflare --smoke              # 연결과 오늘의 한도 확인(v2 도구 그대로)
    $PY -m tools.judgeft_cloudflare --run 1 [--limit 10]

v2 의 judge5_cloudflare 는 실행 번호가 1 로 고정돼 있다. 그 파일을 고치지 않고 호출, 결과 줄, 이어 하기 함수를
가져다 쓴다. 학습 전 관문 (a) 와 (b) 를 모두 통과하기 전에는 돌지 않는다. 관문에서 끝나면 뉴런을 쓰지 않기 위해서다
(스펙 8-1절). (b) 에서 메모리가 모자라 사용자가 새 실험으로 돌리면 이 실험의 M1 결과는 쓰이지 않는다.
"""
from __future__ import annotations

import argparse
import json
import sys

from app import cf

from .judge5 import MODELS, sha256_file
from .judge5_cloudflare import MODEL_KEY, _call, _log_failure, done_ids, foreign_lines, result_line
from .judgeft_files import CASES, CASES_SHA, GATE_A, GATE_B, read_json, read_jsonl, result_path


def gate_passed() -> bool:
    """관문 (a) 는 pass, 관문 (b) 는 loss 가 숫자였는가(finite). (b) 가 메모리 부족이면 gate_b.json 자체가 없다."""
    a = GATE_A.exists() and bool(read_json(GATE_A).get("pass"))
    b = GATE_B.exists() and bool(read_json(GATE_B).get("finite"))
    return a and b


def run(n: int, limit: int | None) -> int:
    if not gate_passed():
        print("학습 전 관문 (a), (b) 를 모두 통과하지 않았습니다(gate_a.json, gate_b.json). "
              "M1 은 두 관문을 통과한 뒤에 돌립니다(스펙 8-1절, 계획 E17).")
        return 1
    actual = sha256_file(CASES)
    if actual != CASES_SHA.read_text(encoding="utf-8").split()[0]:
        print("새 시험지의 해시가 cases.sha256 과 다릅니다. 동결 커밋의 시험지인지 확인하세요.")
        return 1
    out = result_path("new", "M1", n)
    failures = out.with_name(f"M1_run{n}_failures.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    if foreign_lines(out, actual):
        print(f"{out.name} 에 다른 시험지로 채점한 줄이 있습니다. 섞이지 않게 멈춥니다(옮기고 다시 하세요).")
        return 1
    rows = read_jsonl(CASES)
    done = done_ids(out)
    failed = 0
    for r in [r for r in rows if r["case_id"] not in done][:limit]:
        try:
            text, finish = _call(r["messages"])
        except Exception as e:  # noqa: BLE001 - 한 건의 호출 실패가 나머지를 막지 않게 한다
            failed += 1
            _log_failure(failures, r["case_id"], "exception", f"{type(e).__name__}: {e}", None)
            continue
        if not text.strip():
            failed += 1     # 빈 응답은 API 쪽 이상이라 결과로 쓰지 않는다(v2 와 같다)
            _log_failure(failures, r["case_id"], "empty", "", finish)
            continue
        line = result_line(r["case_id"], MODEL_KEY, MODELS[MODEL_KEY], "cloudflare", n, text, finish, actual,
                           r.get("domain"))
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    total = len(done_ids(out))
    print(f"{out.name}: {total}/{len(rows)}건. 이번 호출 실패 {failed}건. 뉴런 {cf.neurons_used()}")
    return 0 if total == len(rows) else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="M1 으로 새 시험지를 채점한다")
    p.add_argument("--run", type=int, choices=(1, 2, 3), required=True)
    p.add_argument("--limit", type=int, default=None)
    args = p.parse_args(argv)
    return run(args.run, args.limit)


if __name__ == "__main__":
    sys.exit(main())
