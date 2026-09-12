"""S2 재측정용 <단계별 관측기>. 사다리를 도는 동안 몇 초마다 지표를 찍어 JSONL 로 남긴다.

실행:
    # k6 를 백그라운드로 띄운 <직후> 그 pid 를 넘겨 함께 돌린다.
    cd ai-service && .venv/bin/python -m loadtest.s2_probe sample \\
        --run-id 2026-09-12-1 --k6-pid 12345 --duration 900

    # 끝난 뒤 단계별로 접는다.
    cd ai-service && .venv/bin/python -m loadtest.s2_probe fold \\
        --run-id 2026-09-12-1

왜 이 파일이 있는가
─────────────────────────────────────────────────────────────────────────────
before(2026-09-10)는 80 VU 지점 <한 번>만 손으로 긁었다. 스레드 상한을 80 으로 올린
뒤에는 그것으로 부족하다. 설계서(specs/2026-09-12-loadtest-pr5-remeasure-design.md §3
"유효성 장치")가 단계마다 찍으라고 정한 것이 셋 있고, 각각 <뭉개지는 서로 다른 사실>이
있어서다:

① `alldap_ai_circuit_state`
   풀이 마르면 30초 대기 → PoolTimeout → 500 → Spring 이 Python 5xx 를 서킷 실패로
   세어 5건에 30초 차단 → 처리량이 <갑자기 0> 으로 떨어진다.
   🔴 그건 "천장에 닿았다" 가 아니라 "차단됐다" 다. 이 값이 없으면 리포트가
      "160 VU 에서 처리량이 무너졌다" 라고 <틀리게> 쓴다.

② `alldap_db_pool_requests_waiting`
   30초짜리 PoolTimeout 대기는 15초 스크레이프 두 번 <사이에> 통째로 들어갈 수 있다.
   포화가 있었는데 그래프에 안 남는 판이 가능하다. 그래서 더 촘촘히 직접 찍는다.

③ k6 프로세스 CPU
   160 VU 는 k6 가 <같은 기계>에서 도는 부하원이다. k6 가 CPU 를 먹으면 지연이 서버
   탓인지 측정기 탓인지 못 가른다. 설계서는 이걸 폐기 조건이 아니라 <그 단계를 참고로만
   쓰는> 사유로 뒀다 - 폐기하면 측정기 문제로 서버 숫자를 전부 버리게 된다.

🔴 읽지 못한 것과 값이 0 인 것을 가른다. 시계열이 없으면 null 로 적고, 값이 NaN·Inf 면
   promtext.MetricUnreadable 이 그 자리에서 멈춘다. 스크레이프 자체가 실패하면
   그 표본에 error 를 적고 <계속 돈다> - 한 번의 네트워크 실패로 15분짜리 판을 버릴 수는
   없지만, 몇 번 실패했는지는 fold 가 세어 보고한다.

⚠️ 이 관측기는 <판정하지 않는다.> 값을 모으기만 하고, 무엇이 새 벽인지는 사람이
   실행 전에 못박은 기준(PRE-*-criteria.md)에 대본다. 이 저장소가 여덟 번 낸 부류를
   막으려는 자리라, 관측기가 스스로 결론을 내면 그 자리가 다시 흐려진다.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

from .promtext import parse_prom_counter

RESULTS = Path(__file__).parent / "results"

# 사다리. s2_breakpoint.js 의 STAGES·HOLD_S 와 <같아야> 표본이 올바른 단계로 접힌다.
# 🔴 여기 값을 고치면 저기도 고칠 것. 두 곳에 있는 이유는 k6 가 JS 이고 이쪽이 파이썬이라
#    한쪽을 import 할 수 없어서다. fold 가 표본 수를 함께 적으므로, 어긋나면 단계별
#    표본 수가 눈에 띄게 치우쳐 드러난다.
STAGES = [1, 5, 10, 20, 40, 80, 160]
HOLD_S = 120
WARMUP_DISCARD_S = 20

# Python(:8001 /internal/metrics) 에서 읽는 게이지들.
PY_GAUGES = [
    "alldap_anyio_threads_borrowed",
    "alldap_anyio_threads_total",
    "alldap_chat_inflight",
    "alldap_db_pool_size",
    "alldap_db_pool_max",
    "alldap_db_pool_available",
    "alldap_db_pool_requests_waiting",
    "alldap_db_pool_open",
]

# Spring(:8081 /actuator/prometheus) 에서 읽는 것들. 라벨이 필요한 것은 튜플로 둔다.
SPRING_GAUGES: list[tuple[str, dict[str, str]]] = [
    ("alldap_ai_circuit_state", {}),
    ("tomcat_threads_busy_threads", {"name": "http-nio-8080"}),
    ("tomcat_threads_config_max_threads", {"name": "http-nio-8080"}),
    ("hikaricp_connections_pending", {}),
    ("hikaricp_connections_active", {}),
    ("process_start_time_seconds", {}),
    ("jvm_memory_used_bytes", {"area": "heap", "id": "G1 Old Gen"}),
    ("jvm_gc_pause_seconds_sum", {}),
    ("jvm_gc_pause_seconds_count", {}),
]


def _jsonl_path(run_id: str) -> Path:
    return RESULTS / f"S2-{run_id}-probe.jsonl"


def _fold_path(run_id: str) -> Path:
    return RESULTS / f"S2-{run_id}-probe-folded.json"


def _scrape(url: str) -> str:
    resp = httpx.get(url, timeout=5.0)
    resp.raise_for_status()
    return resp.text


def _k6_cpu(pid: int | None) -> float | None:
    """k6 프로세스의 순간 CPU 사용률(%). 코어 하나가 100 이므로 멀티코어에서는 100 을 넘는다.

    🔴 pid 가 없으면 None 이다. 0.0 으로 두면 "k6 가 놀고 있었다" 로 읽히는데,
       실제로는 <재지 않았다> 이다.
    """
    if pid is None:
        return None
    try:
        out = subprocess.run(
            ["ps", "-o", "%cpu=", "-p", str(pid)],
            capture_output=True, text=True, timeout=5,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    text = out.stdout.strip()
    if not text:
        return None       # 프로세스가 이미 끝났다
    try:
        return float(text.split()[0])
    except (ValueError, IndexError):
        return None


def _stage_of(elapsed_s: float) -> tuple[int | None, bool]:
    """경과 초 → (그때의 VU 단계, 판정 구간인가).

    k6 의 각 시나리오는 startTime = i*HOLD_S 로 <절대 시각>에 시작한다(s2_breakpoint.js).
    그래서 경과 초만으로 단계를 되짚을 수 있다.
    앞 WARMUP_DISCARD_S 초는 k6 집계에서 버리는 구간이라 여기서도 같은 경계로 가른다 -
    다른 경계를 쓰면 "그 단계의 지연" 과 "그 단계의 내부 지표" 가 다른 구간을 말하게 된다.
    """
    if elapsed_s < 0:
        return None, False
    idx = int(elapsed_s // HOLD_S)
    if idx >= len(STAGES):
        return None, False
    within = elapsed_s - idx * HOLD_S
    return STAGES[idx], within >= WARMUP_DISCARD_S


def cmd_sample(args) -> int:
    RESULTS.mkdir(exist_ok=True)
    path = _jsonl_path(args.run_id)
    start = time.time()
    started_at = datetime.now().isoformat(timespec="seconds")
    print(f"관측 시작 {started_at}  interval={args.interval}s  duration={args.duration}s")
    print(f"기록: {path}")

    with path.open("w") as fh:
        fh.write(json.dumps({
            "kind": "header",
            "run_id": args.run_id,
            "started_at": started_at,
            "started_monotonic_epoch": start,
            "interval_s": args.interval,
            "duration_s": args.duration,
            "k6_pid": args.k6_pid,
            "stages": STAGES,
            "hold_seconds": HOLD_S,
            "warmup_discard_seconds": WARMUP_DISCARD_S,
            "ai_metrics": args.ai_metrics,
            "spring_metrics": args.spring_metrics,
        }, ensure_ascii=False) + "\n")
        fh.flush()

        while True:
            now = time.time()
            elapsed = now - start
            if elapsed > args.duration:
                break
            stage, measuring = _stage_of(elapsed)
            row: dict = {
                "kind": "sample",
                "at": datetime.now().isoformat(timespec="seconds"),
                "elapsed_s": round(elapsed, 1),
                "stage": stage,
                "phase": "measure" if measuring else "warmup",
                "k6_cpu_percent": _k6_cpu(args.k6_pid),
            }
            for label, url, names in (
                ("py", args.ai_metrics, [(n, {}) for n in PY_GAUGES]),
                ("spring", args.spring_metrics, SPRING_GAUGES),
            ):
                try:
                    text = _scrape(url)
                except httpx.HTTPError as e:
                    row[f"{label}_error"] = str(e)
                    continue
                for name, labels in names:
                    # 🔴 값을 못 읽으면(NaN·Inf) parse_prom_counter 가 예외를 던지고
                    #    이 판은 그 자리에서 멈춘다. 그것이 의도다 - 계측이 죽은 채로
                    #    15분을 도는 것이 가장 나쁘다.
                    row[name] = parse_prom_counter(text, name, labels)
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()

            # 프로세스가 사라졌으면 k6 가 끝난 것이다. 마지막 표본까지 남기고 멈춘다.
            if args.k6_pid is not None and _k6_cpu(args.k6_pid) is None and elapsed > 30:
                print(f"k6(pid {args.k6_pid}) 가 보이지 않는다. 관측을 마친다 (경과 {elapsed:.0f}s)")
                break

            time.sleep(max(0.0, args.interval - (time.time() - now)))

    print(f"저장: {path}")
    return 0


def _agg(values: list[float | None]) -> dict:
    """None 을 <섞지 않고> 센다. null 이 몇 번이었는지가 곧 '계측이 있었는가' 다."""
    present = [v for v in values if v is not None]
    return {
        "n": len(values),
        "n_null": len(values) - len(present),
        "min": min(present) if present else None,
        "max": max(present) if present else None,
        "last": present[-1] if present else None,
        "mean": round(sum(present) / len(present), 3) if present else None,
    }


def cmd_fold(args) -> int:
    path = _jsonl_path(args.run_id)
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    header = next((r for r in rows if r.get("kind") == "header"), {})
    samples = [r for r in rows if r.get("kind") == "sample"]

    scrape_errors = {
        "py": sum(1 for r in samples if "py_error" in r),
        "spring": sum(1 for r in samples if "spring_error" in r),
    }

    tracked = PY_GAUGES + [n for n, _ in SPRING_GAUGES] + ["k6_cpu_percent"]
    by_stage: dict[str, dict] = {}
    for stage in STAGES:
        # 🔴 판정 구간(앞 20초를 버린 뒤)만 접는다. k6 표와 같은 구간이어야 한 표에 올릴 수 있다.
        rows_m = [r for r in samples if r.get("stage") == stage and r.get("phase") == "measure"]
        if not rows_m:
            by_stage[str(stage)] = {"samples": 0}
            continue
        entry: dict = {"samples": len(rows_m)}
        for name in tracked:
            entry[name] = _agg([r.get(name) for r in rows_m])
        by_stage[str(stage)] = entry

    # 재시작 판정. process_start_time_seconds 가 하나라도 다르면 Spring 이 다시 떴다.
    starts = sorted({r["process_start_time_seconds"] for r in samples
                     if r.get("process_start_time_seconds") is not None})
    result = {
        "run_id": args.run_id,
        "header": header,
        "folded_at": datetime.now().isoformat(timespec="seconds"),
        "total_samples": len(samples),
        "scrape_errors": scrape_errors,
        "spring_process_start_times": starts,
        "spring_restarted": len(starts) > 1,
        "by_stage": by_stage,
    }
    _fold_path(args.run_id).write_text(json.dumps(result, ensure_ascii=False, indent=2))

    # 사람이 먼저 보는 표. 판정에 쓰는 셋을 앞에 둔다.
    print(f"표본 {len(samples)}개 · 스크레이프 실패 py={scrape_errors['py']} "
          f"spring={scrape_errors['spring']} · Spring 재시작={result['spring_restarted']}")
    print("")
    print("VU    표본  circuit(max)  waiting(max)  borrowed(max)  tomcat_busy(max)  k6cpu%(max)")
    for stage in STAGES:
        e = by_stage[str(stage)]
        if not e.get("samples"):
            print(f"{stage:>4}  (표본 없음)")
            continue
        def m(k):
            v = e.get(k, {}).get("max")
            return "-" if v is None else f"{v:g}"
        print(f"{stage:>4}  {e['samples']:>4}  {m('alldap_ai_circuit_state'):>12}  "
              f"{m('alldap_db_pool_requests_waiting'):>12}  "
              f"{m('alldap_anyio_threads_borrowed'):>13}  "
              f"{m('tomcat_threads_busy_threads'):>16}  {m('k6_cpu_percent'):>11}")
    print(f"\n저장: {_fold_path(args.run_id)}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="S2 단계별 내부 지표 관측")
    sub = p.add_subparsers(dest="phase", required=True)

    s = sub.add_parser("sample", help="사다리를 도는 동안 지표를 찍는다")
    s.add_argument("--run-id", required=True)
    s.add_argument("--k6-pid", type=int, default=None)
    s.add_argument("--interval", type=float, default=5.0)
    s.add_argument("--duration", type=float, default=len(STAGES) * HOLD_S + 90)
    s.add_argument("--ai-metrics", default="http://localhost:8001/internal/metrics")
    s.add_argument("--spring-metrics", default="http://localhost:8081/actuator/prometheus")
    s.set_defaults(func=cmd_sample)

    f = sub.add_parser("fold", help="단계별로 접는다")
    f.add_argument("--run-id", required=True)
    f.set_defaults(func=cmd_fold)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
