"""진짜 모델로 돌리는 종단 점검. <손으로> 돌린다.

    cd ai-service && .venv/bin/python -m app.local_reranker_e2e_check

CI 에 못 태우는 이유: 모델이 1.1GB 고 requirements-lab.txt 가 필요하다.
(app.fallback_e2e_check · app.upload_e2e_check 와 같은 이유로 손으로 돌리는 부류다.)

여기서 아는 것
─────────────────────────────────────────────────────────────────────────────
  ① 계약이 진짜로 지켜지는가 (모양 · 내림차순 · 인덱스 보전)
  ② fp32 와 INT8 이 <같은 순서를 내는가>. 다르면 그 자체가 결과다
  ③ 파일 크기 · 지연 · 최대 RSS. Task 8 의 표에 그대로 들어간다

⚠️ 여기서 재는 속도는 <이 기계의 속도>다. 개발 기계는 Apple M4 Pro(ARM)이고 EC2 는
   x86_64 다. INT8 가속은 아키텍처마다 다르므로, 표에 옮길 때 반드시 기계 이름을 붙일 것.
"""
from __future__ import annotations

from . import local_reranker
from .export_reranker import ONNX_FILENAME, artifact_status, variant_dir

# 실제 코퍼스와 같은 모양의 (질문, 후보) 다. 정답이 <두 번째> 라
# 순서가 제대로 뒤바뀌는지 눈으로 확인할 수 있다.
QUERY = "정규직의 업무용 컴퓨터 교체 주기는?"
TEXTS = [
    "제12조(복리후생) 회사는 임직원에게 식대와 교육비를 지원한다.",
    "제6조(비품) 노트북은 지급일로부터 3년마다 교체한다.",
    "인턴 운영지침 제3조 인턴에게는 노트북을 대여한다. 정규직에게는 적용하지 않는다.",
]


def main() -> None:
    missing = [v for v, ok in artifact_status().items() if not ok]
    if missing:
        raise SystemExit(
            f"산출물이 없습니다: {missing}. "
            "먼저 `.venv/bin/python -m app.export_reranker` 를 돌려주세요."
        )

    orders: dict[str, list[int]] = {}
    for variant in ("local", "local_int8"):
        # 첫 호출은 세션 로딩이 섞이므로 두 번 부르고 두 번째를 지연으로 본다.
        local_reranker.rerank(QUERY, TEXTS, variant=variant)
        result = local_reranker.rerank(QUERY, TEXTS, variant=variant)

        response = result["response"]
        assert set(result) == {"response"}, result
        assert sorted(item["id"] for item in response) == [0, 1, 2], response
        scores = [item["score"] for item in response]
        assert scores == sorted(scores, reverse=True), scores

        orders[variant] = [item["id"] for item in response]
        onnx = variant_dir(variant) / ONNX_FILENAME[variant]
        print(
            f"{variant}: 순서={orders[variant]} "
            f"크기={onnx.stat().st_size / 1024 / 1024:.1f}MB"
        )

    print("\n지연(ms):", local_reranker.latency_percentiles())
    print(f"최대 RSS: {local_reranker.max_rss_mb():.0f} MB")

    if orders["local"] != orders["local_int8"]:
        # 🔴 실패가 아니라 <결과>다. 양자화가 순서를 바꾼다는 사실 자체를 기록한다.
        print("\n⚠️ fp32 와 INT8 의 순서가 다르다. 이 사실을 표에 그대로 적을 것.")
    else:
        print("\n✅ fp32 와 INT8 이 같은 순서를 냈다(이 입력에서는).")


if __name__ == "__main__":
    main()
