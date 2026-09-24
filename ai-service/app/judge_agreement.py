"""채점자(LLM-as-judge)를 사람 라벨과 대조한다.

실행:
    cd ai-service
    .venv/bin/python -m app.judge_agreement dump     # 블라인드 라벨 파일 내보내기
    #  → testdata/judge_labels.json 의 label 칸을 사람이 0 / 0.5 / 1 로 채운다
    .venv/bin/python -m app.judge_agreement report   # 혼동행렬·방향·왜곡량
    .venv/bin/python -m app.judge_agreement report --reasons  # 불일치분만 채점자 재호출

무엇을 재는가 (두 축을 섞지 말 것)
─────────────────────────────────────────────────────────────────────────────
  정밀도  같은 입력에 같은 점수를 주는가  → 2026-09-18 에 확인됨(두 입력 15회씩, 분산 0)
  정확도  사람이 보기에 맞게 채점하는가  → <이 도구가 재는 것>

🔴 q3 에서 채점자는 <정밀하게 틀렸다>. 10회 내내 일관되게 0.0 을 줬고 그 사유가
   거짓이었다(정답 청크는 근거 3번째에 있었다). 흔들리면 반복 측정으로 걸러지는데
   일관되게 틀리면 안 걸러진다. 그래서 이쪽이 더 나쁘다.

🔴 진짜 위험은 채점자가 1.0 을 준 40건이다
─────────────────────────────────────────────────────────────────────────────
박하게 틀린 것(맞는 답에 0.0)은 눈에 띈다. 숫자가 내려가니 파보게 된다.
<후하게> 틀린 것은 화면에 "잘 되고 있다" 로만 뜨고 DB 어디를 뒤져도 나오지 않는다.
그것을 찾는 유일한 방법이 사람이 그 40건을 직접 읽는 것이고, 그것이 이 도구다.

왜 카파 하나로 결론을 말하지 않나
─────────────────────────────────────────────────────────────────────────────
44건 중 40건이 1.0 이다. 한쪽 값이 91% 를 차지하면 우연 일치 확률이 이미 0.83 쯤이라
카파의 분모가 거의 0 이 된다. 일치율 95% 인데 카파 0.3 이 나온다(카파 역설).
그래서 혼동행렬과 <방향>을 주고, 카파는 주석과 함께 부수적으로만 찍는다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from .db import cursor
from .eval_cases import DEFAULT_RUN_IDS, Case, load_cases

LABELS: tuple[float, float, float] = (0.0, 0.5, 1.0)
DEFAULT_PATH = "testdata/judge_labels.json"

_README = (
    "label 칸에 0 / 0.5 / 1 만 적는다. note 는 선택이다. "
    "채점자 점수는 <일부러> 들어 있지 않다. 보고 매기면 앵커링되어 대조가 성립하지 않는다. "
    "기준: 충실성 = 답변의 모든 주장이 아래 근거에 실제로 적혀 있는가. "
    "1.0 전부 있다 / 0.5 일부만 있다 / 0.0 근거에 없는 내용을 지어냈다. "
    "답이 세상의 상식에 맞는지는 보지 않는다. 사실이더라도 근거에 없으면 깎는다."
)


def confusion(pairs: list[tuple[float, float]]) -> dict[tuple[float, float], int]:
    """3×3 혼동행렬. 🔴 키는 (사람, 채점자) 순서다.

    숫자 하나로 요약하지 않고 표를 통째로 싣는 이유: 44건 중 40건이 한 칸에 몰려
    있어서, 요약 지표는 나머지 4건에 통째로 끌려다닌다. 표는 그 사실을 감추지 않는다.
    """
    m = {(h, j): 0 for h in LABELS for j in LABELS}
    for h, j in pairs:
        m[(h, j)] += 1
    return m


def direction_counts(pairs: list[tuple[float, float]]) -> tuple[int, int, int]:
    """(후함, 박함, 일치). 🔴 후함 = 채점자가 사람보다 <높게> 준 것이다.

    후하면 전체충실성이 실제보다 높게 나오고, 박하면 낮게 나온다.
    둘은 반대 방향의 결론이라 절대 한 값으로 뭉개면 안 된다.
    """
    generous = sum(1 for h, j in pairs if j > h)
    harsh = sum(1 for h, j in pairs if j < h)
    return generous, harsh, len(pairs) - generous - harsh


def overall_faithfulness(scores: list[float], question_count: int) -> float:
    """전체충실성 = avg_faithfulness × scored_count / question_count.

    정리하면 sum(scores) / question_count 다. 이 저장소가 Spring 에서 쓰는 식과
    같아야 채점자 기준 수치와 나란히 놓을 수 있다.
    """
    if question_count <= 0:
        return 0.0
    return sum(scores) / question_count


def linear_weighted_kappa(pairs: list[tuple[float, float]]) -> float:
    """선형 가중 카파. ⚠️ 이 데이터에서는 참고용이다.

    44건 중 40건이 1.0 이라 우연 일치 확률이 이미 0.83 쯤이고, 분모(1 - Pe)가
    거의 0 이 된다. 일치율이 높아도 카파가 낮게 나오는 <카파 역설>이다.
    출력에서 이 값 옆에 반드시 그 주석을 함께 찍는다.
    """
    n = len(pairs)
    if n == 0:
        return 0.0
    idx = {v: i for i, v in enumerate(LABELS)}
    k = len(LABELS)

    def w(a: int, b: int) -> float:
        return 1.0 - abs(a - b) / (k - 1)

    obs = sum(w(idx[h], idx[j]) for h, j in pairs) / n
    hc = [sum(1 for h, _ in pairs if h == v) / n for v in LABELS]
    jc = [sum(1 for _, j in pairs if j == v) / n for v in LABELS]
    exp = sum(w(a, b) * hc[a] * jc[b] for a in range(k) for b in range(k))
    if abs(1.0 - exp) < 1e-12:
        return 0.0
    return (obs - exp) / (1.0 - exp)


def read_labels(path: str) -> dict[str, dict]:
    """이미 채워둔 라벨을 읽는다. 파일이 없으면 빈 dict."""
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return {c["case_id"]: c for c in data.get("cases", [])}


def build_payload(cases: list[Case], carried: dict[str, dict]) -> dict:
    """라벨 파일 내용을 만든다. 🔴 채점자 점수를 넣지 않는다.

    순서는 case_id(해시)로 정렬한다. 문항 번호나 run 순서가 단서로 남지 않게 하려는 것이다.
    """
    out = []
    for c in sorted(cases, key=lambda x: x.case_id):
        prev = carried.get(c.case_id, {})
        out.append({
            "case_id": c.case_id,
            "question_id": c.question_id,
            "question": c.question,
            "ground_truth": c.ground_truth,
            "generated_answer": c.generated_answer,
            "sources": [
                {"chunk_id": s.chunk_id, "filename": s.filename, "content": s.content}
                for s in c.sources
            ],
            "seen_in_runs": list(c.seen_in_runs),
            "label": prev.get("label"),
            "note": prev.get("note", ""),
        })
    return {"_readme": _README, "run_ids": list(DEFAULT_RUN_IDS), "cases": out}


def dump(run_ids: list[int], path: str) -> None:
    cases = load_cases(run_ids)
    carried = read_labels(path)
    payload = build_payload(cases, carried)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    done = sum(1 for c in payload["cases"] if c["label"] is not None)
    print(f"{path} 에 {len(payload['cases'])}건을 썼습니다. (이미 채운 라벨 {done}건을 이어받았습니다)")
    print("label 칸에 0 / 0.5 / 1 을 채운 뒤 `report` 를 돌리세요.")


class LabelFileProblem(RuntimeError):
    """라벨 파일이 없거나 덜 채워졌다. 부분 집계를 내지 않는다."""


def _load_pairs(path: str, cases: list[Case]) -> list[tuple[str, float, float]]:
    """(case_id, 사람 라벨, 채점자 점수) 목록. 하나라도 비면 실패한다.

    🔴 부분 집계를 내지 않는 이유: 한 번 찍힌 숫자는 결과로 인용된다.
       "44건 중 30건만 매긴 상태의 중간값" 이라는 꼬리표는 인용될 때 떨어져 나간다.
    """
    if not os.path.exists(path):
        raise LabelFileProblem(
            f"{path} 가 없습니다. 먼저 `python -m app.judge_agreement dump` 를 돌리고"
            " label 칸을 0 / 0.5 / 1 로 채우세요."
        )
    labels = read_labels(path)
    by_id = {c.case_id: c for c in cases}

    unknown = sorted(set(labels) - set(by_id))
    if unknown:
        raise LabelFileProblem(
            f"라벨 파일에 DB 에 없는 케이스 {len(unknown)}건이 있습니다: {unknown[:5]}"
            " ... 코퍼스나 평가셋이 바뀐 것입니다. `dump` 를 다시 돌리세요."
        )

    blank, bad, pairs = [], [], []
    for cid, c in by_id.items():
        rec = labels.get(cid)
        if rec is None or rec.get("label") is None:
            blank.append(cid)
            continue
        v = float(rec["label"])
        if v not in LABELS:
            bad.append((cid, rec["label"]))
            continue
        pairs.append((cid, v, c.judge_faithfulness))

    if bad:
        raise LabelFileProblem(
            f"라벨 값이 0 / 0.5 / 1 이 아닌 것이 {len(bad)}건 있습니다: {bad[:5]}"
        )
    if blank:
        raise LabelFileProblem(
            f"아직 매기지 않은 케이스가 {len(blank)}건 남았습니다"
            f" (전체 {len(by_id)}건). 남은 case_id 예: {blank[:5]}"
            " ... 전부 채운 뒤 다시 돌리세요. 부분 집계는 내지 않습니다."
        )
    return pairs


def _print_confusion(pairs: list[tuple[float, float]]) -> None:
    m = confusion(pairs)
    print("\n[1] 혼동행렬  (행 = 사람, 열 = 채점자)")
    print("            " + "".join(f"{j:>7.1f}" for j in LABELS))
    for h in LABELS:
        print(f"  사람 {h:>3.1f}   " + "".join(f"{m[(h, j)]:>7d}" for j in LABELS))


def _print_direction(pairs: list[tuple[float, float]]) -> None:
    generous, harsh, same = direction_counts(pairs)
    n = len(pairs)
    print(f"\n[2] 방향  (전체 {n}건)")
    print(f"  일치            {same:>3d}건  ({same / n:.1%})")
    print(f"  채점자가 후하다  {generous:>3d}건  → 전체충실성이 실제보다 <높게> 나온다")
    print(f"  채점자가 박하다  {harsh:>3d}건  → 전체충실성이 실제보다 <낮게> 나온다")
    kappa = linear_weighted_kappa(pairs)
    print(f"\n  선형가중 카파 {kappa:.3f}")
    print("  ⚠️ 이 값만 인용하지 말 것. 한쪽 값에 몰린 분포에서는 우연 일치 확률이")
    print("     높아 분모가 거의 0 이 되고, 일치율이 높아도 카파가 낮게 나온다(카파 역설).")


def _print_distortion(run_ids: list[int], label_of: dict[str, float]) -> None:
    """run 별로 <채점자 기준> 과 <사람 기준> 전체충실성을 나란히 놓는다."""
    from .eval_cases import case_key, chunk_ids_of

    print("\n[3] 전체충실성 왜곡량  (= avg × scored / total)")
    print("  run   문항  채점  채점자기준   사람기준      차이")
    with cursor() as cur:
        for rid in run_ids:
            cur.execute(
                """SELECT question_id, generated_answer, retrieved_chunks, faithfulness
                     FROM eval_results
                    WHERE run_id = %s AND generated_answer IS NOT NULL""",
                (rid,),
            )
            rows = cur.fetchall()
            total = len(rows)
            j_scores, h_scores = [], []
            for qid, answer, retrieved, faith in rows:
                if faith is None:
                    continue  # fallback. 양쪽 모두 분자에서 빠진다
                cid = case_key(int(qid), answer, chunk_ids_of(retrieved))
                j_scores.append(float(faith))
                h_scores.append(label_of[cid])
            j = overall_faithfulness(j_scores, total)
            h = overall_faithfulness(h_scores, total)
            print(f"  {rid:>3d}   {total:>4d}  {len(j_scores):>4d}"
                  f"    {j:>8.4f}   {h:>8.4f}   {h - j:>+8.4f}")
    print("\n  ⚠️ 실측 편차 폭은 0.032 다. 차이가 그보다 크면 이 저장소의 before/after")
    print("     비교표가 <채점자 오차 안에서> 움직였다는 뜻이 된다.")


def rescore_verdict(again: float | None, stored: float) -> str:
    """재호출 결과를 세 값 중 하나로 판정한다: `unmeasured` / `same` / `differs`.

    🔴 왜 함수로 뽑았나: 이 셋은 <원인이 다른 사실>이고 한 값으로 뭉개면 안 된다.
       못 불렀다(측정 실패) · 같은 점수를 줬다(결정성 확인) · 다른 점수를 줬다(발견).
       뭉개는 순간 "채점자가 흔들린다" 는 틀린 결론이 나온다.

    ⚠️ NaN 으로 표시하지 않는 이유가 여기 있다. `float("nan") != x` 는 언제나 참이라
       `!=` 분기를 그냥 지나가 <못 불렀다>가 <다르다>로 둔갑한다. 실제로 그렇게 짰다가
       2026-09-20 에 고쳤다. 이 저장소가 아홉 번 낸 뭉개기 부류의 열 번째가 될 뻔했다.
    """
    if again is None:
        return "unmeasured"
    return "same" if again == stored else "differs"


def fetch_reasons(cases: list[Case], mismatched_ids: list[str]) -> dict[str, tuple[float | None, str]]:
    """불일치 케이스만 채점자를 다시 불러 (점수, 사유)를 받는다.

    🔴 왜 다시 부르나: `eval_results` 에 reason 컬럼이 없다. judge.score 가 사유를
       파싱해 Scores 에 담는데 evalrun 의 INSERT 가 그것을 버린다. 사유가 없으면
       <틀린 것>과 <거짓 사유를 댄 것>을 가를 수 없다. q3 가 정확히 그 경우였다.

    🔴 덤으로 결정성 점검이 된다. 2026-09-18 에 확인한 것은 두 입력에서 15회씩
       안 흔들렸다는 것까지다. 재호출 점수가 DB 값과 다르면 <그 자체가 발견>이라
       조용히 넘기지 않고 찍는다.

    비용: 불일치분만이라 보통 수 건이고 회당 약 25 뉴런이다.
    """
    from .judge import score as judge_score

    by_id = {c.case_id: c for c in cases}
    unknown = [cid for cid in mismatched_ids if cid not in by_id]
    if unknown:
        raise KeyError(
            f"cases 에 없는 case_id {len(unknown)}건을 받았습니다: {unknown[:5]}"
            " ... 같은 run 목록으로 load_cases 한 결과를 넘기세요."
        )

    out: dict[str, tuple[float | None, str]] = {}
    for cid in mismatched_ids:
        c = by_id[cid]
        s = judge_score(
            question=c.question,
            ground_truth=c.ground_truth,
            sources=[src.to_source() for src in c.sources],
            answer=c.generated_answer,
        )
        if s is None:
            # 🔴 NaN 을 쓰지 않는다. NaN != x 가 언제나 참이라, 호출하는 쪽의
            #    "점수가 달라졌다" 분기를 그냥 지나가 <못 불렀다>가 <다른 점수를
            #    줬다>로 둔갑한다. 이 저장소가 아홉 번 낸 뭉개기 부류다.
            #    None 은 "재보지 못했다"이고 호출부가 반드시 따로 분기해야 한다.
            out[cid] = (None, "(채점 호출 실패)")
            continue
        out[cid] = (s.faithfulness, s.reason)
    return out


def report(run_ids: list[int], path: str, with_reasons: bool) -> int:
    cases = load_cases(run_ids)
    triples = _load_pairs(path, cases)
    pairs = [(h, j) for _, h, j in triples]
    label_of = {cid: h for cid, h, _ in triples}
    by_id = {c.case_id: c for c in cases}

    print(f"사람 라벨 {len(pairs)}건 · 채점자 {len(pairs)}건  (run {run_ids})")
    _print_confusion(pairs)
    _print_direction(pairs)
    _print_distortion(run_ids, label_of)

    mismatched = [(cid, h, j) for cid, h, j in triples if h != j]

    reasons: dict[str, tuple[float, str]] = {}
    if with_reasons and mismatched:
        print(f"\n  채점자를 {len(mismatched)}건 다시 부릅니다 (약 {len(mismatched) * 25} 뉴런)...")
        reasons = fetch_reasons(cases, [cid for cid, _, _ in mismatched])

    print(f"\n[4] 불일치 상세  {len(mismatched)}건")
    if not mismatched:
        print("  없음.")
    for cid, h, j in sorted(mismatched, key=lambda t: abs(t[2] - t[1]), reverse=True):
        c = by_id[cid]
        arrow = "후함" if j > h else "박함"
        print(f"\n  · {cid}  q{c.question_id}  사람 {h} / 채점자 {j}  ({arrow})")
        print(f"    질문: {c.question}")
        print(f"    기대: {c.ground_truth}")
        print(f"    답변: {c.generated_answer[:200]}")
        print(f"    근거: {[s.chunk_id for s in c.sources]}")
        if cid in reasons:
            again, why = reasons[cid]
            print(f"    사유: {why}")
            # 🔴 세 사실을 갈라 찍는다: 못 불렀다 / 같은 점수를 줬다 / 다른 점수를 줬다.
            #    NaN 으로 뭉개면 첫째가 셋째로 둔갑한다(2026-09-20 에 그 코드를 고쳤다).
            verdict = rescore_verdict(again, j)
            if verdict == "unmeasured":
                print("    ⚠️ 재호출이 실패해 <대조하지 못했습니다>. 다른 점수를 줬다는 뜻이 아닙니다.")
            elif verdict == "differs":
                print(f"    🔴 재호출 점수가 DB 값과 다릅니다: DB {j} vs 재호출 {again}")
                print("       채점자가 결정적이라는 전제가 이 입력에서는 성립하지 않습니다.")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="채점자를 사람 라벨과 대조한다")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dump", help="블라인드 라벨 파일을 내보낸다")
    d.add_argument("--path", default=DEFAULT_PATH)
    r = sub.add_parser("report", help="사람 라벨과 채점자를 대조한다")
    r.add_argument("--path", default=DEFAULT_PATH)
    r.add_argument("--reasons", action="store_true",
                   help="불일치 케이스만 채점자를 다시 불러 사유를 받는다 (외부 API 를 부른다)")
    args = p.parse_args(argv)
    if args.cmd == "dump":
        dump(DEFAULT_RUN_IDS, args.path)
    if args.cmd == "report":
        try:
            return report(DEFAULT_RUN_IDS, args.path, args.reasons)
        except LabelFileProblem as e:
            print(f"❌ {e}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    from .db import close_pool
    try:
        sys.exit(main())
    finally:
        close_pool()
