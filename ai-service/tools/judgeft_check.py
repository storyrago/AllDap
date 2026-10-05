"""파인튜닝 실험의 자체 점검 입구. DB 도 외부 API 도 모델도 쓰지 않는다. CI 에서 돈다.

실행:  cd ai-service && python -m tools.judgeft_check

도구마다 점검 파일이 따로 있다(v2 와 같은 이유: 도구를 서로 다른 세션이 만든다). 이 파일은 그것들을 모두 부르고,
도구 하나로는 볼 수 없는 것을 더 본다: 노트북이 생성 도구와 같은가, 노트북에 시험 문항이 없는가(스펙 5-3절 확인 4),
동결 시험지가 바뀌지 않았는가, 커밋된 배정이 시드로 재현되는가, 커밋된 시험지에 정답이 새지 않았는가,
커밋된 학습 데이터가 커밋된 입력에서 그대로 다시 만들어지는가.
커밋된 파일을 보는 점검은 파일이 아직 없으면(실행 태스크 전) 아무것도 보지 않고 통과한다.
"""
from __future__ import annotations

from . import (judgeft_assign_check, judgeft_cloudflare_check, judgeft_export_check, judgeft_fields_check,
               judgeft_gate_check, judgeft_labels_check, judgeft_rationale_check, judgeft_report_check,
               judgeft_search_check)
from .judge5 import sha256_file
from .judge5v2_export import CASE_KEYS
from .judgeft_assign import replay
from .judgeft_export import build_train, forbidden_problems, split_val
from .judgeft_files import (
    ASSIGNMENT, CASES, FROZEN_SHA256, QUESTIONS, RETRIEVED, TEMPLATES, TRAIN, TRAIN_SHA, V2_CASES, VAL, VARIANTS,
    read_json, read_jsonl,
)
from .judgeft_notebooks import expected
from .judgeft_rationale import load_templates


def check_frozen_sheet_is_unchanged() -> None:
    """동결 시험지(v2 의 cases.jsonl)가 v2 결과 1절의 해시 그대로다. 바뀌면 v2 의 결과와 비교할 수 없다."""
    assert sha256_file(V2_CASES) == FROZEN_SHA256


def check_notebooks_match_generator() -> None:
    """커밋된 노트북이 judgeft_notebooks 로 다시 만든 것과 바이트까지 같다. 손으로 고친 곳이 있으면 걸린다."""
    for path, text in expected().items():
        assert path.exists(), f"{path.name} 이 없다. `python -m tools.judgeft_notebooks` 로 만든다"
        assert path.read_text(encoding="utf-8") == text, f"{path.name} 이 생성 도구의 결과와 다르다"


def check_notebooks_have_no_test_questions() -> None:
    """스펙 5-3절 확인 4: 노트북에 동결 시험지와 새 시험지의 문항(질문 글)이 들어 있지 않다."""
    texts = "\n".join(expected().values())
    for path in (V2_CASES, CASES):
        for row in read_jsonl(path):
            user = row["messages"][1]["content"]
            question = user.split("<질문>\n", 1)[1].split("\n", 1)[0]
            assert question not in texts, f"노트북에 시험 문항의 질문이 있다: {question[:30]}"


def check_committed_cases_are_blind() -> None:
    """커밋된 새 시험지의 줄에는 v2 와 같은 네 키만 있다. 유형과 정답 점수가 새지 않는다."""
    for row in read_jsonl(CASES):
        assert set(row) == CASE_KEYS, set(row) ^ CASE_KEYS


def check_committed_assignment_replays() -> None:
    if not ASSIGNMENT.exists():
        return
    by = {q["qid"]: q for q in read_jsonl(QUESTIONS)}
    assert replay(read_json(ASSIGNMENT), by) == []


def check_committed_train_rebuilds() -> None:
    """커밋된 학습 데이터가 커밋된 입력(질문, 검색, 배정, 변형, 틀)에서 그대로 다시 만들어지고, 해시 기록과 같다."""
    if not TRAIN.exists():
        return
    items, _ = build_train(read_jsonl(QUESTIONS), read_jsonl(RETRIEVED), read_json(ASSIGNMENT), read_jsonl(VARIANTS),
                           load_templates())
    train, val = split_val(items)
    assert read_jsonl(TRAIN) == train and read_jsonl(VAL) == val, "학습 데이터가 입력에서 다시 만든 것과 다르다"
    recorded = dict(reversed(line.split()) for line in TRAIN_SHA.read_text(encoding="utf-8").splitlines())
    assert recorded["train.jsonl"] == sha256_file(TRAIN) and recorded["val.jsonl"] == sha256_file(VAL)


def check_forbidden_values_absent() -> None:
    """스펙 4-5절의 금지 값이 문장 틀, 두 노트북(시범 데이터 포함), 커밋된 학습 데이터에 없다."""
    texts = {"문장 틀": TEMPLATES.read_text(encoding="utf-8")}
    texts |= {path.name: text for path, text in expected().items()}
    for path in (TRAIN, VAL):
        if path.exists():
            texts[path.name] = path.read_text(encoding="utf-8")
    assert not (bad := forbidden_problems(texts)), bad


OWN = [check_frozen_sheet_is_unchanged, check_notebooks_match_generator, check_notebooks_have_no_test_questions,
       check_committed_cases_are_blind, check_committed_assignment_replays, check_committed_train_rebuilds,
       check_forbidden_values_absent]
CHECKS = (judgeft_fields_check.CHECKS + judgeft_search_check.CHECKS + judgeft_assign_check.CHECKS
          + judgeft_rationale_check.CHECKS + judgeft_export_check.CHECKS + judgeft_labels_check.CHECKS
          + judgeft_gate_check.CHECKS + judgeft_cloudflare_check.CHECKS + judgeft_report_check.CHECKS + OWN)


def main() -> None:
    for fn in CHECKS:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(CHECKS)}가지 전부 통과.")


if __name__ == "__main__":
    main()
