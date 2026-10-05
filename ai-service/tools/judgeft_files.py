"""채점 모델 파인튜닝 실험(2026-10-05)의 경로와 상수.

설계: docs/superpowers/specs/2026-10-05-judge-finetune-design.md (이하 스펙)

v2 실험(judge5v2_*)의 파일은 하나도 고치지 않는다. 이 실험의 도구는 v2 의 순수 함수만 가져다 쓰고,
경로와 분야와 할당량은 이 파일에 따로 둔다. v2 의 상수(DOMAINS, QUOTA)는 모듈 수준에 고정돼 있어서
인자로 바꿀 수 없고, 고치면 v2 의 보고서와 점검(judge5_check 44가지, judge5v2_check 66가지)이 흔들린다.
외부 API 도 DB 도 부르지 않는다.
"""
from __future__ import annotations

from pathlib import Path

# v2 의 읽고 쓰는 함수와 대응표를 그대로 쓴다. 다시 적으면 두 실험의 규칙이 어긋날 수 있다.
from .judge5v2_files import (  # noqa: F401 - 다른 judgeft 도구가 이 모듈에서 함께 가져간다
    TABLE_SCORE, TYPE_NAMES, append_jsonl, latest_by_qid, read_json, read_jsonl, value_in, write_json, write_jsonl,
)
from .judge5v2_files import ANSWER_KEY as V2_ANSWER_KEY  # noqa: F401
from .judge5v2_files import BOTS as V2_BOTS  # noqa: F401
from .judge5v2_files import CASES as V2_CASES  # noqa: F401
from .judge5v2_files import CORPUS_DIRS as V2_CORPUS_DIRS  # noqa: F401
from .judge5v2_files import QUESTIONS as V2_QUESTIONS  # noqa: F401
from .judge5v2_files import RESULTS_DIR as V2_RESULTS_DIR  # noqa: F401

# __file__ 은 ai-service/tools/judgeft_files.py 다. 두 번 올라가면 ai-service/ 다.
ROOT = Path(__file__).resolve().parent.parent
FT = ROOT / "testdata" / "judgeft"

FIELDS = FT / "fields.json"
BOTS = FT / "bots.json"
QUESTIONS = FT / "questions.jsonl"
RETRIEVED = FT / "retrieved.jsonl"
EXCLUDED = FT / "excluded.json"
ASSIGNMENT = FT / "assignment.json"
VARIANTS = FT / "variants.jsonl"
TEMPLATES = FT / "templates.json"
TRAIN = FT / "train.jsonl"
VAL = FT / "val.jsonl"
TRAIN_DROPPED = FT / "train_dropped.json"
TRAIN_SHA = FT / "train.sha256"
REVIEW = FT / "review.jsonl"
CASES = FT / "cases.jsonl"
CASES_SHA = FT / "cases.sha256"
ANSWER_KEY = FT / "answer_key.json"
MISMATCHES = FT / "mismatches.md"
GATE = FT / "gate.md"
GATE_A = FT / "gate_a.json"
GATE_B = FT / "gate_b.json"                 # 학습 노트북이 Drive 에 쓴 것을 옮긴다(계획 E14)
TRAINING_LOG = FT / "training_log.jsonl"    # 같다(E15). 세션마다 session_start 줄, 단계마다 step 줄
TRAIN_DONE = FT / "train_done.json"         # 같다(E15). 어댑터 해시
DETERMINISM = FT / "determinism.json"
RESULTS_DIR = FT / "results"
REPORT = FT / "report.md"
RUN_LOG = FT / "run_log.md"
CORPUS = FT / "corpus"

# 결과 폴더는 시험지마다 나눈다. new 는 새 시험지, frozen 은 동결 시험지(v2 의 cases.jsonl)다.
SHEETS: tuple[str, ...] = ("new", "frozen")
V2_ENV = V2_RESULTS_DIR / "env.json"
FROZEN_SHA256 = "bec2b58e943e3b2c296dec8b664dc78ed2548f1b6d6e67062e3a7684fd535fe2"

# 스펙 3-1절의 네 후보. 순서는 시드로 섞는다(스펙 3-2절).
FIELD_CANDIDATES: tuple[str, ...] = ("hospital", "school", "travel", "telecom")
# v2 의 시드(20261005)와 다른 값이다. 같은 값을 쓰면 v2 의 배정과 같은 난수열이 이 실험에 다시 쓰인다.
SEED = 20261006
# 데모 봇(1), 리랭커 실험 봇(7, 8). v2 의 봇 넷은 v2 의 bots.json 에서 읽어 함께 막는다(스펙 3-4절).
PROTECTED_BOTS: frozenset[int] = frozenset({1, 7, 8})

# 스펙 4-4절. 학습 데이터의 할당량(짝 문항 제외)과 짝 문항 수.
TRAIN_QUOTA: dict[int, int] = {1: 35, 2: 35, 3: 34, 4: 34, 5: 34, 6: 34, 7: 34, 8: 240}
PAIRS = 120
# 스펙 4-4절. 새 시험지의 할당량. ①, ② 중 CONTRAST_FIVE 만큼은 대상이 둘인 질문에서 먼저 뽑는다.
TEST_QUOTA: dict[int, int] = {1: 10, 2: 10, 3: 10, 4: 10, 5: 7, 6: 8, 7: 5, 8: 60}
CONTRAST_FIVE: dict[int, int] = {1: 6, 2: 6}
# 스펙 3-3절. ⑧ 자격 질문이 이보다 적으면 분야를 늘린다.
TEST_MIN_QUALIFIED = TEST_QUOTA[8] + sum(CONTRAST_FIVE.values())   # 72
TRAIN_MIN_QUALIFIED = TRAIN_QUOTA[8]                               # 240
MAX_TEST_FIELDS = 2
MAX_TRAIN_FIELDS = 3
# 스펙 6-3절. 검증 묶음은 질문 단위로 약 10%.
VAL_FRACTION = 0.1
# 스펙 4-4절. 검수 뒤 새 시험지의 세 조건.
MIN_EIGHTH_AFTER_REVIEW = 54
MIN_FIVE_AFTER_REVIEW = 15
MIN_CONTRAST_FIVE_AFTER_REVIEW = 10
# 스펙 7-1절. 관문 (a) 의 비율.
GATE_A_RATIO = 0.10

# 스펙 4-5절. 설계 문서의 모범 답안 예에만 쓰는 동결 시험지 문항의 값이다. 학습 데이터, 문장 틀, 노트북에 나오면
# 동결 시험지의 답이 학습에 샌 것이다. 점검이 글자로 찾는다.
FORBIDDEN_VALUES: tuple[str, ...] = ("OTP", "보안카드", "1일 5억 원", "1,000만 원")

# 스펙 6-1절, 6-2절. 바탕 모델과 학습 설정. 노트북 생성 도구가 이 값을 노트북에 그대로 넣는다.
M3_REPO = "Unbabel/M-Prometheus-14B"
M3_REVISION = "f790ee744ba08731697e9347c6ab709f9405a37e"   # v2 결과 1절의 리비전 f790ee74 의 전체 해시
LORA_R = 16
LORA_ALPHA = 32
LORA_DROPOUT = 0.05
LORA_TARGETS: tuple[str, ...] = ("q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj")
LEARNING_RATE = 2e-4
EPOCHS = 2
GRAD_ACCUM = 8
WARMUP_RATIO = 0.03
KEEP_CHECKPOINTS = 2
TRAIN_SEED = 20261006
# 스펙 6-2절의 라이브러리 판. torch 는 코랩에 깔린 것을 쓰고 판을 env.json 에 적는다(다시 깔면 약 2GB 를 받는다).
# transformers, bitsandbytes 는 v2 의 env.json 과 같은 판이다. peft, accelerate 는 그 transformers 판과 같은 시기의 판이다.
PINS: dict[str, str] = {"transformers": "4.57.6", "bitsandbytes": "0.50.2", "peft": "0.17.1", "accelerate": "1.10.1"}

# 결과 파일의 모델 이름. M3pre 는 학습 전 M3, M3ft 는 학습 후 M3 다(스펙 0절).
MODEL_KEYS: tuple[str, ...] = ("M1", "M3pre", "M3ft")


def result_path(sheet: str, model: str, run: int) -> Path:
    """결과 파일의 자리. results/<시험지>/<모델>_run<번호>.jsonl."""
    return RESULTS_DIR / sheet / f"{model}_run{run}.jsonl"


def fields_doc() -> dict:
    """fields.json 의 내용. 없으면 멈춘다(계획 E1 이 만든다)."""
    if not FIELDS.exists():
        raise SystemExit("testdata/judgeft/fields.json 이 없습니다. 계획 E1 의 `judgeft_fields order` 를 먼저 하세요.")
    return read_json(FIELDS)


def test_fields() -> list[str]:
    return list(fields_doc()["test"])


def train_fields() -> list[str]:
    return list(fields_doc()["train"])


def sheet_of(field: str) -> str:
    """분야가 시험용이면 "test", 학습용이면 "train". 둘 다 아니면(예비 분야) 멈춘다."""
    doc = fields_doc()
    if field in doc["test"]:
        return "test"
    if field in doc["train"]:
        return "train"
    raise SystemExit(f"분야 {field} 는 아직 열지 않았습니다(fields.json 의 test, train 어디에도 없다).")
