"""A(cloudflare) · B(local) · C(local_int8) 실행을 <읽어서> 표로 뽑는다.

    cd ai-service && .venv/bin/python -m app.rerank_compare --bot-id 1

🔴 새로 재는 것이 없다. 이미 저장된 eval_runs · eval_results 를 읽을 뿐이다.
   "새 평가 도구를 만들지 않는다" 는 설계문서 §4-1 을 지키는 것이다.

🔴 status='completed' 인 실행만 본다. 이유가 둘이다.
   ① partial 은 <분모가 달라> 애초에 비교할 수 없다.
   ② 무엇보다 채점 실패가 섞이면 "fallback 했다" 와 "재지 못했다" 를 SQL 로 가를 수 없다
      (둘 다 faithfulness IS NULL 이다). completed 는 judge_failed=0 이 보장되므로
      그 안에서만 아래 해석이 <확정적>이다:
          generated_answer IS NOT NULL AND faithfulness IS NULL  ->  fallback
          generated_answer IS NULL                               ->  처리 실패(있으면 completed 가 아니다)

왜 평균만 보지 않는가
─────────────────────────────────────────────────────────────────────────────
기본값을 정할 때 결정적이었던 것은 평균(0.875)이 아니라 <회당 오답 0건> 이었다.
그리고 응답률이 네 설정 모두 0.875 로 같은데 내용물이 전부 다른 것을 네 번 겪었다.
그래서 회당 오답 · 완전오답 · fallback 과 문항별 표를 함께 찍는다.
"""
from __future__ import annotations

import argparse

from .db import cursor

_RUNS_SQL = """
SELECT r.id,
       r.config->>'reranker_provider' AS provider,
       r.avg_faithfulness, r.avg_relevancy, r.answered_rate,
       r.question_count, r.scored_count
  FROM eval_runs r
 WHERE r.bot_id = %s AND r.status = 'completed'
 ORDER BY r.id
"""

_RESULTS_SQL = """
SELECT r.config->>'reranker_provider' AS provider,
       q.question,
       e.faithfulness,
       (e.generated_answer IS NOT NULL AND e.faithfulness IS NULL) AS is_fallback
  FROM eval_results e
  JOIN eval_runs r ON r.id = e.run_id
  JOIN eval_questions q ON q.id = e.question_id
 WHERE r.bot_id = %s AND r.status = 'completed'
 ORDER BY q.id, r.id
"""

# 오염 점검. 올바른 지표는 scored_count 가 아니라 <generated_answer IS NULL 행의 존재> 다.
# scored_count 는 fallback 이 많으면 자연히 작아지는데 그것은 정상 측정이다(AGENTS.md 2026-08-13).
_CONTAMINATION_SQL = """
SELECT e.run_id, count(*)
  FROM eval_results e
  JOIN eval_runs r ON r.id = e.run_id
 WHERE r.bot_id = %s AND r.status = 'completed' AND e.generated_answer IS NULL
 GROUP BY e.run_id
 ORDER BY e.run_id
"""

UNRECORDED = "(박제 없음)"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bot-id", type=int, required=True)
    args = parser.parse_args()

    with cursor() as cur:
        cur.execute(_RUNS_SQL, (args.bot_id,))
        runs = cur.fetchall()
        cur.execute(_RESULTS_SQL, (args.bot_id,))
        results = cur.fetchall()
        cur.execute(_CONTAMINATION_SQL, (args.bot_id,))
        contaminated = cur.fetchall()

    print("실행 목록 (run_id · 박제된 reranker_provider)")
    for row in runs:
        print(f"  {row[0]:>5}  {row[1] or UNRECORDED}")

    if contaminated:
        # completed 인데 처리 실패 행이 있다면 전제가 깨진 것이다. 조용히 지나가면 안 된다.
        print("\n🔴 오염 의심: completed 인데 generated_answer IS NULL 인 행이 있다")
        for run_id, count in contaminated:
            print(f"  run {run_id}: {count}건")

    by_provider: dict[str, list[tuple]] = {}
    for row in runs:
        by_provider.setdefault(row[1] or UNRECORDED, []).append(row)

    print("\n설정             회수  전체충실성(회차별)              폭      관련성  응답률")
    for provider, rows in by_provider.items():
        # 전체 충실성 = avg × scored / total. 생존 편향에 넘어가지 않는 유일한 값이다.
        overalls = [
            float(r[2]) * int(r[6]) / int(r[5])
            for r in rows
            if r[2] is not None and r[5]
        ]
        rel = [float(r[3]) for r in rows if r[3] is not None]
        ans = [float(r[4]) for r in rows if r[4] is not None]
        spread = (max(overalls) - min(overalls)) if overalls else 0.0
        print(
            f"{provider:<16} {len(rows):>3}  "
            f"{[round(o, 3) for o in overalls]!s:<28} "
            f"{spread:.3f}  "
            f"{(sum(rel) / len(rel) if rel else 0):.3f}  "
            f"{(sum(ans) / len(ans) if ans else 0):.3f}"
        )
    # ⚠️ 설정 간 차이가 0.032 보다 작으면 <구별되지 않는다> 로 읽는다(AGENTS.md 의 편차 규칙).

    print("\n회당 오답 · 완전오답 · fallback (기본값을 정할 때 결정적이었던 지표)")
    acc: dict[str, list[int]] = {}
    for provider, _question, faith, is_fallback in results:
        key = provider or UNRECORDED
        cells = acc.setdefault(key, [0, 0, 0])  # 오답 · 완전오답 · fallback
        if is_fallback:
            cells[2] += 1
        elif faith is not None:
            if float(faith) < 1.0:
                cells[0] += 1
            if float(faith) == 0.0:
                cells[1] += 1
    for provider, (wrong, zero, fallback) in acc.items():
        n = len(by_provider.get(provider, [])) or 1
        print(
            f"{provider:<16} 오답 {wrong / n:.2f} · 완전오답 {zero / n:.2f} · "
            f"fallback {fallback / n:.2f}   (실행 {n}회)"
        )

    print("\n문항별 (평균이 같아도 내용물이 다른 것을 네 번 겪었다)")
    per_question: dict[str, dict[str, list[str]]] = {}
    for provider, question, faith, is_fallback in results:
        cell = "fb" if is_fallback else ("-" if faith is None else f"{float(faith):.3f}")
        per_question.setdefault(question, {}).setdefault(provider or UNRECORDED, []).append(cell)
    for question, cells in per_question.items():
        joined = "   ".join(f"{p}={'/'.join(v)}" for p, v in cells.items())
        print(f"  {question[:28]:<30} {joined}")


if __name__ == "__main__":
    main()
