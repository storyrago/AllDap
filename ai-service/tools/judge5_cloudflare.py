"""M1(지금 서비스의 채점 모델, Cloudflare)으로 시험지를 채점한다.

실행:
    cd ai-service
    .venv/bin/python -m tools.judge5_cloudflare --smoke   # 가짜 사례 하나로 연결만 확인(44건을 쓰지 않는다)
    .venv/bin/python -m tools.judge5_cloudflare           # 시험지 44건 채점 → testdata/judge5/results/M1_run1.jsonl
    .venv/bin/python -m tools.judge5_cloudflare --cases testdata/judge5v2/cases.jsonl --results-dir testdata/judge5v2/results

점수는 여기서 읽지 않는다. 출력 원문만 저장하고 점수는 tools.judge5_report 가
judge5.parse_result 하나로 읽는다. 코랩 결과와 같은 규칙으로 읽기 위해서다.

이어 하기: 이미 결과 파일에 있는 사례는 건너뛴다. 호출이 실패한 사례는 결과 파일에 쓰지 않으므로
다시 실행하면 그 사례만 다시 부른다. 실패를 결과 줄로 남기지 않는 이유: "호출 실패" 와
"모델이 양식을 안 지켜 못 읽음" 은 다른 사실이다. 앞의 것은 다시 부르면 풀리고, 뒤의 것은 결과다.
빈 응답(cf.text_of 가 "" 를 돌려준 경우)도 같은 이유로 호출 실패로 센다.
호출 실패는 결과 파일이 아니라 results/M1_failures.jsonl 에 따로 남긴다. 특정 사례가 계속 실패하면
콘솔 출력만으로는 몇 번, 왜 실패했는지가 사라지기 때문이다.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from app import cf

from .judge5 import MAX_NEW_TOKENS, MODELS, parse_result, sha256_file, smoke_messages
from .judge5_export import CASES, RESULTS_DIR

MODEL_KEY = "M1"
RUN = 1


def sha_path(cases: Path) -> Path:
    """시험지 해시 파일의 자리. 시험지와 같은 폴더의 cases.sha256 이다(앞 실험과 v2 모두).
    with_suffix 는 확장자만 바꾼다: cases.jsonl 이 cases.sha256 이 된다."""
    return cases.with_suffix(".sha256")


def result_line(case_id: str, model: str, repo: str, revision: str, run: int,
                output: str, finish: str | None, cases_sha256: str, domain: str | None = None) -> dict:
    """결과 파일 한 줄. 코랩 노트북도 같은 키로 쓴다(계획 파일 구조 절)."""
    line = {"case_id": case_id, "model": model, "repo": repo, "revision": revision, "run": run,
            "output": output, "finish": finish, "cases_sha256": cases_sha256}
    if domain is not None:
        # v2 시험지는 문항마다 분야를 적는다(v2 스펙 8-3절). 앞 실험의 줄 모양은 그대로 두려고 있을 때만 넣는다.
        line["domain"] = domain
    return line


def done_ids(path: Path) -> set[str]:
    """결과 파일에 이미 있는 사례 번호. 파일이 없으면 빈 집합."""
    if not path.exists():
        return set()
    return {json.loads(line)["case_id"] for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


def foreign_lines(path: Path, cases_sha256: str) -> int:
    """결과 파일에서 지금 시험지와 다른 시험지로 채점한 줄의 수.

    이어 하기는 case_id 만 보므로, 시험지를 다시 만든 뒤 실행하면 옛 줄은 건너뛰고 새 줄만 덧붙여
    한 파일에 두 시험지가 섞인다. 그걸 부르기 전에 막아 뉴런을 아낀다.
    """
    if not path.exists():
        return 0
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return sum(1 for r in rows if r.get("cases_sha256") != cases_sha256)


def _log_failure(path: Path, case_id: str, kind: str, detail: str, finish: str | None) -> None:
    # 실패 기록은 결과 파일과 다른 파일이다. 보고서가 결과로 세지 않게 하려는 것이다.
    line = {"case_id": case_id, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "kind": kind, "detail": detail, "finish": finish}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")


def _call(messages: list[dict]) -> tuple[str, str | None]:
    result = cf.run(MODELS[MODEL_KEY], {
        "messages": messages,
        "max_tokens": MAX_NEW_TOKENS,
        "temperature": 0,   # 채점은 같은 입력에 같은 점수여야 한다(스펙 §3-3)
    })
    return cf.text_of(result), cf.finish_reason(result)


def smoke() -> int:
    """44건이 아닌 가짜 사례로 연결과 양식만 본다. 순서 규칙(스펙 §4-1) 때문에 따로 둔다."""
    # 가짜 사례는 judge5.SMOKE_CASE 한 곳에 있다. 코랩 노트북도 같은 사례로 모델마다 먼저 확인한다.
    text, finish = _call(smoke_messages())
    print(text)
    print(f"\nfinish={finish}  읽은 결과={parse_result(text)}  뉴런={cf.neurons_used()}")
    return 0


def run_all(limit: int | None, cases: Path = CASES, results_dir: Path = RESULTS_DIR) -> int:
    expected = sha_path(cases).read_text(encoding="utf-8").split()[0]
    actual = sha256_file(cases)
    if actual != expected:
        print(f"시험지 해시가 다릅니다: 파일 {actual} / 기록 {expected}. "
              f"시험지를 만든 도구(tools.judge5_export cases 또는 tools.judge5v2_export final)를 다시 실행하세요.")
        return 1
    results_dir.mkdir(parents=True, exist_ok=True)
    out = results_dir / f"{MODEL_KEY}_run{RUN}.jsonl"
    failures = results_dir / f"{MODEL_KEY}_failures.jsonl"
    stale = foreign_lines(out, actual)
    if stale:
        print(f"{out.name} 에 다른 시험지로 채점한 줄이 {stale}건 있습니다. 섞이지 않게 멈춥니다.")
        print(f"그 파일을 다른 이름으로 옮긴 뒤 다시 실행하세요(지우지 말고 옮기세요. 뉴런을 들인 결과입니다).")
        return 1
    done = done_ids(out)
    rows = [json.loads(line) for line in cases.read_text(encoding="utf-8").splitlines() if line.strip()]
    todo = [r for r in rows if r["case_id"] not in done][:limit]
    failed = 0
    for r in todo:
        try:
            text, finish = _call(r["messages"])
        except Exception as e:  # noqa: BLE001 - 한 건의 호출 실패가 나머지를 막지 않게 한다
            failed += 1
            print(f"호출 실패 {r['case_id']}: {type(e).__name__}: {e}")
            _log_failure(failures, r["case_id"], "exception", f"{type(e).__name__}: {e}", None)
            continue
        if not text.strip():
            # cf.text_of 는 응답의 두 모양이 모두 비었을 때 "" 를 돌려준다. 그건 모델이 양식을 어긴 것이
            # 아니라 API 쪽 이상이라(2026-08-02 에 한쪽이 빈 응답을 실제로 받았다) 호출 실패로 센다.
            # 결과 줄로 쓰면 보고서가 "못 읽음(missing)" 으로 세어 §4-4 의 못 읽음 0건 기준을 흔든다.
            failed += 1
            print(f"빈 응답 {r['case_id']}: finish={finish}. 결과로 쓰지 않고 다음 실행에서 다시 부른다.")
            _log_failure(failures, r["case_id"], "empty", "", finish)
            continue
        line = result_line(r["case_id"], MODEL_KEY, MODELS[MODEL_KEY], "cloudflare", RUN, text, finish, actual,
                           r.get("domain"))
        # "a" 는 이어 쓰기 모드다. 한 줄씩 바로 써 두면 중간에 멈춰도 그때까지의 결과가 남는다.
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    total = len(done_ids(out))
    print(f"{out.name}: {total}/{len(rows)}건. 이번 호출 실패 {failed}건. 뉴런 {cf.neurons_used()}")
    if total < len(rows):
        print("빠진 사례가 있습니다. 같은 명령을 다시 실행하면 빠진 사례만 부릅니다.")
        return 1
    return 0


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="M1(Cloudflare)으로 시험지를 채점한다")
    p.add_argument("--smoke", action="store_true", help="가짜 사례 하나로 연결만 확인한다")
    p.add_argument("--limit", type=int, default=None, help="이번 실행에서 부를 최대 사례 수")
    # 기본값을 앞 실험 경로로 두는 이유: 앞 실험을 같은 명령으로 다시 돌릴 수 있어야 한다(v2 스펙 8-3절).
    p.add_argument("--cases", type=Path, default=CASES, help="시험지 파일. 해시 파일은 같은 폴더의 cases.sha256")
    p.add_argument("--results-dir", type=Path, default=RESULTS_DIR, help="결과를 쓸 폴더")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return smoke() if args.smoke else run_all(args.limit, args.cases, args.results_dir)


if __name__ == "__main__":
    sys.exit(main())
