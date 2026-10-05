"""학습 전 M3 와 학습 후 M3 가 같은 입력에 같은 출력을 내는지 확인하고, 모델마다 몇 번 돌린 결과를 쓸지 정한다(스펙 8-1절).

실행:
    cd ai-service
    $PY -m tools.judgeft_determinism pre     # 동결 시험지. 계획 E12
    $PY -m tools.judgeft_determinism post    # 새 시험지. 계획 E16

출력이 달라졌을 때 생성이 실행마다 다른 것인지, 환경(라이브러리 판)이 바뀌어 다른 것인지를 가른다.
판이 v2 와 다르면 v2 의 결과와 대조하지 않는다. 대조하면 두 원인이 하나로 섞인다.
판이 같은데 v2 와 다르면 새 환경에서 한 번 더 채점해(run2) run1 과 대조한다. v2 와 이 실험은 노트북 코드가 다르고
v2 는 accelerate 판을 적지 않았으므로, 판이 같다는 것만으로 같은 환경이라고 말할 수 없기 때문이다.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .judge5 import RULES_V2, parse_result
from .judgeft_files import DETERMINISM, V2_ENV, V2_RESULTS_DIR, read_json, read_jsonl, result_path, write_json

ENV_KEYS = ("gpu", "torch", "transformers", "bitsandbytes")   # v2 의 env.json 에 있는 값(스펙 8-1절). GPU 가 다르면 연산이 다르다


def env_path(results: Path) -> Path:
    """결과 파일 옆의 환경 기록. 채점 노트북이 M3pre_run1.jsonl 옆에 M3pre_run1.env.json 을 쓴다."""
    return results.with_suffix(".env.json")


def env_diff(env: dict, ref: dict) -> dict[str, dict]:
    return {k: {"v2": ref.get(k), "now": env.get(k)} for k in ENV_KEYS if env.get(k) != ref.get(k)}


def compare_runs(a: list[dict], b: list[dict]) -> dict:
    """두 실행을 문항마다 대조한다. 읽은 점수와 출력 본문이 모두 같아야 같다고 센다. 문항 집합이 다르면 멈춘다."""
    def key(rows):
        return {r["case_id"]: (parse_result(r["output"], r.get("finish"), rules=RULES_V2), r["output"]) for r in rows}
    ka, kb = key(a), key(b)
    if set(ka) != set(kb):
        raise SystemExit(f"두 실행의 문항이 다릅니다({len(ka)}개와 {len(kb)}개). 빠진 문항을 마저 채점한 뒤 다시 하세요.")
    diff = sorted(c for c in ka if ka[c] != kb[c])
    return {"same": len(ka) - len(diff), "diff": len(diff), "diff_ids": diff}


def decide_pre_from(run1: list[dict], v2: list[dict], run2: list[dict] | None, d: dict) -> dict:
    """결정성 판정의 본체(파일을 읽지 않아 점검할 수 있다). run2 는 새 환경의 둘째 실행이고 아직 없으면 None 이다.

    use_v2 는 학습 전 M3 의 동결 시험지 값에 v2 의 run1 을 쓰는가다. v2 와 판이 같고 줄마다 같을 때만 쓴다.
    """
    out: dict = {"env_same": not d, "env_diff": d}
    if not d:
        c = compare_runs(run1, v2)
        out["vs_v2"] = {k: c[k] for k in ("same", "diff")}
        if c["diff"] == 0:
            return {**out, "compared": ["frozen M3pre_run1", "v2 M3_run1"], **c, "use_v2": True, "runs": 1}
        why = (f"판은 v2 와 같은데 v2 의 run1 과 {c['diff']}줄이 다릅니다. 생성이 실행마다 다른지, 노트북 코드나 "
               "accelerate 판(v2 는 적지 않았다)이 달라서인지 가르려고 새 환경에서 한 번 더 채점합니다")
    else:
        why = f"환경의 판이 v2 와 다릅니다({d}). v2 결과를 섞지 않고 새 환경에서 한 번 더 채점합니다"
    if run2 is None:
        raise SystemExit(why + "(계획 E12 Step 3). frozen/M3pre_run2.jsonl 을 만든 뒤 다시 하세요.")
    c = compare_runs(run1, run2)
    # 새 환경의 두 실행이 같으면 생성은 결정적이고, v2 와의 차이는 환경이나 코드의 차이다. 그래도 v2 의 값은 섞지 않는다.
    return {**out, "compared": ["frozen M3pre_run1", "frozen M3pre_run2"], **c, "use_v2": False,
            "runs": 1 if c["diff"] == 0 else 3}


def decide_pre() -> dict:
    run1 = result_path("frozen", "M3pre", 1)
    run2 = result_path("frozen", "M3pre", 2)
    d = env_diff(read_json(env_path(run1)), read_json(V2_ENV))
    return decide_pre_from(read_jsonl(run1), read_jsonl(V2_RESULTS_DIR / "M3_run1.jsonl"),
                           read_jsonl(run2) if run2.exists() else None, d)


def decide_post() -> dict:
    c = compare_runs(read_jsonl(result_path("new", "M3ft", 1)), read_jsonl(result_path("new", "M3ft", 2)))
    return {"compared": ["new M3ft_run1", "new M3ft_run2"], **c, "runs": 1 if c["diff"] == 0 else 3}


def runs_for(model: str, sheet: str, det: dict) -> list[Path]:
    """모델과 시험지마다 판정에 쓰는 결과 파일 목록. 첫째가 부호 검정에 쓰는 실행이다(스펙 8-3절)."""
    if model == "M1":
        return [V2_RESULTS_DIR / "M1_run1.jsonl"] if sheet == "frozen" else [result_path("new", "M1", n) for n in (1, 2, 3)]
    if model == "M3pre":
        pre = det["pre"]
        if sheet == "new":
            return [result_path("new", "M3pre", n) for n in range(1, pre["runs"] + 1)]
        if pre["use_v2"]:
            mine = [result_path("frozen", "M3pre", n) for n in (1, 2)]
            return [V2_RESULTS_DIR / "M3_run1.jsonl"] + (mine if pre["runs"] == 3 else [])
        return [result_path("frozen", "M3pre", n) for n in range(1, pre["runs"] + 1)]
    post = det["post"]
    return [result_path(sheet, "M3ft", n) for n in range(1, post["runs"] + 1)]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="결정성을 확인하고 쓸 실행 수를 정한다")
    p.add_argument("which", choices=("pre", "post"))
    args = p.parse_args(argv)
    doc = read_json(DETERMINISM) if DETERMINISM.exists() else {}
    doc[args.which] = decide_pre() if args.which == "pre" else decide_post()
    write_json(DETERMINISM, doc)
    r = doc[args.which]
    print(f"{args.which}: {r['compared'][0]} 와 {r['compared'][1]} 를 대조. 같은 문항 {r['same']}, 다른 문항 {r['diff']}. "
          f"쓸 실행 수 {r['runs']}")
    if args.which == "pre" and r["env_diff"]:
        print(f"환경의 판이 v2 와 다릅니다: {r['env_diff']}. v2 의 결과는 쓰지 않습니다.")
    elif args.which == "pre" and not r["use_v2"]:
        print(f"판은 v2 와 같지만 v2 의 run1 과 {r['vs_v2']['diff']}줄이 달라 v2 의 결과는 쓰지 않습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
