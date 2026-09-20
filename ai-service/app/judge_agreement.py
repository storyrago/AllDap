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


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="채점자를 사람 라벨과 대조한다")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dump", help="블라인드 라벨 파일을 내보낸다")
    d.add_argument("--path", default=DEFAULT_PATH)
    args = p.parse_args(argv)
    if args.cmd == "dump":
        dump(DEFAULT_RUN_IDS, args.path)
    return 0


if __name__ == "__main__":
    from .db import close_pool
    try:
        sys.exit(main())
    finally:
        close_pool()
