# 리랭커 파인튜닝 전후 비교 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 리랭커(`bge-reranker-base`)를 학습용 문서로 파인튜닝하고, 학습에 쓰지 않은 시험용 문서에서 파인튜닝 전 모델(B)과 후 모델(D)의 상위 5개 진입률을 문제마다 짝지어 비교한다.

**Architecture:** 코퍼스 56개 문서를 문서 단위로 학습용 36개와 시험용 20개로 가르고(`split.json`), 로컬 Spring 으로 학습용 봇과 시험용 봇을 따로 만든다. 문제 파일은 기존 평가셋과 같은 형식이라 `app.eval_set` 으로 봇에 적재하고, `app.rank_trace` 의 새 비교 모드가 여러 로컬 리랭커로 순위를 재서 부호 검정까지 계산한다. 학습은 코랩 노트북이 하고, 결과 모델은 `app.export_reranker` 가 ONNX fp32 와 INT8 로 내보낸다. 파일 사이의 누출은 `app.finetune_split_check` 가 CI 에서 매번 확인한다.

**Tech Stack:** Python 3.13 표준 라이브러리(`json`, `hashlib`, `math`, `argparse`), 기존 `app.chunker`, `app.parsers`, `app.retriever`, `app.local_reranker`, `app.eval_set`, `app.rank_trace`, `app.export_reranker`. 학습은 코랩 T4 에서 `sentence-transformers==3.4.1` 의 `CrossEncoder`. 내보내기는 `requirements-lab.txt` 의 `optimum-onnx`, `onnxruntime`.

## Global Constraints

- 설계 원본: `docs/superpowers/specs/2026-10-01-reranker-finetune-design.md`. 이 계획과 스펙이 다르면 스펙을 따르고, 다른 점을 계획에 적어 고친다.
- 분할: 시험용 20개, 학습용 36개, 합 56개. 목록은 스펙 §2-5, §2-6 그대로다. **분할을 바꾸지 않는다.** 규칙을 어기는 문제를 발견하면 분할이 아니라 그 문제를 버린다(핸드오프 §7).
- 봇 1번과 `testdata/eval_questions.json` 은 건드리지 않는다. `eval_set load --replace` 를 봇 1번에 쓰지 않는다.
- 비교 기준은 로컬 fp32 원본(B, `local`)이다. Cloudflare 리랭커와 비교하지 않는다.
- 판정: 좋아진 문제 수와 나빠진 문제 수의 양측 부호 검정, p < 0.05 이고 좋아짐이 더 많으면 효과 있음. 결과를 보기 전에 정한 규칙이다(스펙 §5-3). 나빠진 문제의 목록은 판정과 관계없이 기록한다.
- 관문: 시험 문제 전체 중 "고칠 수 있는데 B 에서 5위 밖" 인 문제가 4분의 1 이상이어야 학습을 시작한다(스펙 §5-2).
- 문제는 전부 Claude 가 쓴다. Gemini 질문 생성기를 쓰지 않는다(스펙 §4-1).
- 말투 표시 키는 `style`, 값은 `polite`(정중한 문장), `casual`(짧은 구어체), `keyword`(키워드만), `situation`(상황 설명형), `typo`(오타와 띄어쓰기 오류) 다섯 가지다(스펙 §4-2).
- 청킹 설정은 `chunk_size=500`, `chunk_overlap=50`, `chunk_split_headings=true` 로 고정한다(현재 `app/config.py` 기본값).
- 에폭 선택은 연습 문제 20% 검증용의 정답 청크 평균 순위로 한다. **시험 문제 성적으로 학습 설정을 고르지 않는다**(스펙 §6-2).
- `reranker_provider` 기본값은 `cloudflare` 그대로 둔다. 운영 배포는 하지 않는다(스펙 §10).
- **AGENTS.md 에 실측 결과를 적지 않는다.** 결과는 results 문서, `docs/decisions.md`, `docs/BACKLOG.md` 에 적는다.
- 새 의존성을 `requirements.txt` 에 더하지 않는다. CI 에서 도는 점검은 표준 라이브러리와 기존 `app` 모듈만 쓴다.
- 테스트는 이 저장소 관례대로 `python -m app.<이름>_check` 다(pytest 아님). 모든 명령은 `ai-service/` 에서 `.venv/bin/python` 으로 돌린다.
- 주석, 출력, 오류 메시지는 한국어. 사용자에게 보이는 오류는 무엇을 어떻게 하면 되는지까지 적는다. **em dash 문자를 쓰지 않는다**(쉼표, 콜론, 괄호로 대신한다).
- Python 코드에는 왜 그렇게 쓰는지(문법, 관용구 포함) 짧은 주석을 붙인다(AGENTS.md: 개발자가 Python 에 약하다).
- 구현은 워크트리에서 한다. 메인 폴더에서 브랜치를 바꾸지 않는다(여러 세션이 같은 폴더를 쓴다).

---

## 파일 구조

| 파일 | 새로/고침 | 책임 | 태스크 |
|---|---|---|---|
| `ai-service/testdata/finetune/split.json` | 새로 | 문서 56개의 쪽(train, test)과 이유 | 1 |
| `ai-service/testdata/finetune/twins.json` | 새로 | 쌍둥이 청크 27쌍(문서, 청크 번호, 본문 전문) | 1 |
| `ai-service/app/finetune_split_check.py` | 새로 | 스펙 §8 누출 검사 7가지 + 규칙 함수 자기 점검 + 문제 작성용 청크 출력 | 1 |
| `ai-service/app/eval_set.py` | 고침 | `load`, `dump` 에 `--file`. `dump` 가 `style` 키를 보존 | 2 |
| `ai-service/app/eval_set_io_check.py` | 새로 | 위 고침의 점검(DB 없음) | 2 |
| `ai-service/app/rank_trace.py` | 고침 | `--compare` 비교 모드: 여러 로컬 모델 순위, 지표, 좋아짐과 나빠짐, 부호 검정, 관문 | 3 |
| `ai-service/app/rank_trace_check.py` | 새로 | 비교 모드의 순수 함수 점검 | 3 |
| `ai-service/testdata/finetune/holdout_questions.json` | 새로 | 예비 시험 문제 약 30개 | 5 |
| `ai-service/testdata/finetune/test_questions.json` | 새로 | 시험 문제 60개 이상 | 6 |
| `ai-service/testdata/finetune/gate_B.json` | 새로 | 관문 측정 결과 | 7 |
| `ai-service/app/finetune_data.py` | 새로 | 연습 문제 → `train_pairs.jsonl` (스펙 §5-1) | 8 |
| `ai-service/app/finetune_data_check.py` | 새로 | 위의 순수 함수 점검 | 8 |
| `ai-service/testdata/finetune/train_questions.json` | 새로 | 연습 문제 300~400개 | 9 |
| `ai-service/testdata/finetune/train_pairs.jsonl` | 새로 | 학습 데이터, 노트북의 유일한 입력 | 9 |
| `ai-service/notebooks/train_reranker.ipynb` | 새로 | 코랩 학습 노트북 (스펙 §6-2) | 10 |
| `ai-service/app/export_reranker.py` | 고침 | `local_ft`, `local_ft_int8` 등록 + 스펙 §6-4 의 네 자리 | 12 |
| `ai-service/app/export_reranker_check.py` | 고침 | 양자화 변형의 입력이 대응 fp32 변형인지 검사 | 12 |
| `ai-service/app/config.py` | 주석만 | `reranker_provider` 가능한 값에 두 변형 추가 | 12 |
| `ai-service/testdata/finetune/compare_test.json` | 새로 | 시험용 봇의 B, C, D, E 비교 결과 | 13 |
| `ai-service/testdata/finetune/compare_holdout.json` | 조건부 | 예비 시험 문제 비교 결과(효과 있음이 아닐 때만) | 14 |
| `docs/superpowers/plans/2026-10-01-reranker-finetune-results.md` | 새로 | 결과 기록 | 16 |
| `.github/workflows/ci.yml` | 고침 | 새 점검 4개 등록 | 1, 2, 3, 8 |

**스펙 §7 표에 없는 파일이 셋 있다.** `eval_set_io_check.py`, `rank_trace_check.py`, `finetune_data_check.py` 는 고치거나 새로 만드는 코드의 점검 파일이다. 스펙은 결과물 파일만 적었고, 이 저장소는 고친 코드마다 `_check` 를 둔다(`inject_probe_check.py` 가 예).

## 작업 단위와 PR

- **PR 1 (`feat/reranker-finetune-tools`)**: 태스크 1~3. 데이터 없이 돌아가는 도구와 검사다. 리뷰할 수 있는 크기로 먼저 머지한다.
- **PR 2 (`feat/reranker-finetune`)**: 태스크 4~16. **PR 1 이 머지된 뒤에** `main` 에서 새로 딴다. 스택 브랜치를 만들지 않는다(AGENTS.md 브랜치 절).
- 사람이 해야 하는 태스크가 셋 있다: 태스크 6 의 시험 문제 검토, 태스크 11 의 코랩 실행, 태스크 7 과 13 의 판정 확인. 그 자리에서 멈추고 사용자에게 넘긴다.

## 권장 모델 (AGENTS.md "모델 선택")

| 태스크 | 모델 | 이유 |
|---|---|---|
| 1 (누출 검사), 3 (판정 통계), 5, 6, 9 (문제 작성), 13, 14 (판정) | 상속(Opus) | 검증 로직, 판정, 출제 품질이 실험의 신뢰를 좌우한다 |
| 2, 8, 10, 12 | Sonnet 가능 | 이 계획에 코드가 확정돼 있다 |
| 4, 7, 15 | 상속 | 실행 결과를 읽고 다음 단계를 정한다 |

---

### Task 0: 워크트리 준비

**Files:** 없음

- [ ] **Step 1: PR 1 워크트리를 만든다**

```bash
cd /Users/cheonjamin/projects/AllDap
git fetch origin
git worktree add ../AllDap-ft-tools -b feat/reranker-finetune-tools origin/main
cd ../AllDap-ft-tools/ai-service
ln -s ../../AllDap/ai-service/.venv .venv   # 가상환경은 새로 만들지 않고 메인 폴더 것을 쓴다
ln -s ../../AllDap/ai-service/models models # 모델 산출물(git 제외, 수 GB)도 같은 이유로 공유한다
# .gitignore 의 `.venv/`, `ai-service/models/` 는 끝에 / 가 있어 디렉터리만 걸린다. 심볼릭 링크는
# 파일이라 걸리지 않으므로 저장소 공통 exclude 에 더한다(모든 워크트리가 같은 파일을 쓴다).
printf 'ai-service/.venv\nai-service/models\n' >> "$(git rev-parse --git-common-dir)/info/exclude"
git status --short   # 아무것도 안 나와야 한다
.venv/bin/python -m app.eval_set_check
```

Expected: 마지막 줄 `전부 통과.`

- [ ] **Step 2: 기존 점검이 깨끗한지 본다**

```bash
.venv/bin/python -m app.export_reranker_check && .venv/bin/python -m app.local_reranker_check
```

Expected: 두 점검 모두 `전부 통과` 류의 마지막 줄. 실패하면 이 계획을 시작하기 전에 원인을 먼저 보고한다.

---

### Task 1: 분할 파일, 쌍둥이 청크 파일, 누출 검사

**Files:**
- Create: `ai-service/testdata/finetune/split.json`
- Create: `ai-service/testdata/finetune/twins.json`
- Create: `ai-service/app/finetune_split_check.py`
- Modify: `.github/workflows/ci.yml` (자체 점검 목록, 현재 252~268행)

**Interfaces:**
- Consumes: `app.chunker.chunk_text(text, size, overlap, split_headings) -> list[Chunk]` (`Chunk.index`, `Chunk.content`), `app.parsers.extract_text(filename, data) -> tuple[str, str]`
- Produces (태스크 8 이 import 한다):
  - `CHUNKING: dict` (`{"chunk_size": 500, "chunk_overlap": 50, "chunk_split_headings": True}`)
  - `STYLES: tuple[str, ...]`
  - `chunks_of(name: str) -> list[str] | None` (코퍼스 문서를 업로드 경로와 같게 잘라 본문 목록. 없으면 None)
  - `twin_texts(text: str, twins: dict) -> set[str]` (그 본문의 쌍둥이 청크 본문들)
  - `protected_texts(payloads: dict[str, dict], twins: dict) -> set[str]` (시험 문제와 예비 시험 문제의 정답 본문 + 그 쌍둥이 청크 본문)
  - 파일 형식:
    - `split.json`: `{"corpus": "testdata/corpus", "documents": [{"file": str, "side": "train"|"test", "reason": str}, ...]}`
    - `twins.json`: `{"source": str, "chunking": {...}, "pairs": [{"id": int, "a": {"doc": str, "index": int, "text": str}, "b": {...}}, ...]}`
    - 문제 파일(`train_questions.json`, `test_questions.json`, `holdout_questions.json`): 기존 `eval_questions.json` 과 같은 최상위(`corpus`, `chunking`, `questions`)이고 문항마다 `id`, `question`, `ground_truth`, `source_doc`, `source_text`, `active`, `style`

- [ ] **Step 1: 누출 검사를 자기 점검부터 쓴다 (규칙 함수 + 틀린 입력으로 잡는지 확인)**

`ai-service/app/finetune_split_check.py`:

```python
"""리랭커 파인튜닝 실험의 누출 검사. CI 에서 돈다.

실행:
    cd ai-service && .venv/bin/python -m app.finetune_split_check
    cd ai-service && .venv/bin/python -m app.finetune_split_check --show-chunks 50_부설연구소_별도규정.md

설계: docs/superpowers/specs/2026-10-01-reranker-finetune-design.md §8

무엇을 막는가
─────────────────────────────────────────────────────────────────────────────
파인튜닝 전후 비교가 뜻을 가지려면 시험 문제의 답을 학습 때 보지 않았어야 한다.
이 검사는 파일끼리의 관계(어느 문서가 어느 쪽인가, 어느 청크가 학습 데이터에 나오는가)만
본다. DB 와 외부 API 를 쓰지 않으므로 CI 에서 돈다. 이 검사가 있어야 "학습 때 시험 문제를
본 것 아닌가" 라는 질문에 "CI 가 매번 확인한다" 고 답할 수 있다.

번호는 스펙 §8 의 번호다.
  1. 시험용 문서와 학습용 문서가 겹치지 않는다
  2. 시험, 예비 시험 문제의 정답 청크(와 쌍둥이 청크)가 학습 데이터에 나오지 않는다
  3. 쌍둥이 청크의 두 문서가 다른 쪽으로 갈리지 않았다
  4. 취업규칙, 휴가규정을 정답 문서로 쓰지 않았다
  5. 문제의 정답 문서가 그 문제 종류의 쪽에 있다
  6. train_pairs.jsonl 의 해시가 노트북에 적힌 값과 같다
  7. 연습, 예비 시험 문제의 질문에 시험용 대상 낱말이 없다

파일이 아직 없으면 그 항목은 건너뛰고 건너뛰었다고 출력한다. 단 split.json 과
twins.json 은 검사의 기준이라 없으면 실패한다(스펙 §8 마지막 문단).

먼저 자기 점검을 돈다
─────────────────────────────────────────────────────────────────────────────
규칙 함수마다 일부러 틀린 작은 입력을 넣어 위반을 잡는지 확인한 뒤에 실제 파일을 본다.
실제 파일이 깨끗하면 규칙이 아무것도 못 잡는 상태여도 초록불이 나기 때문이다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Callable
from functools import cache
from pathlib import Path

from .chunker import chunk_text
from .parsers import extract_text

# __file__ 은 app/finetune_split_check.py 이므로 두 번 올라가면 ai-service/ 다.
# 실행 위치(cwd)와 무관하게 같은 파일을 가리키려고 __file__ 기준으로 잡는다.
ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = ROOT / "testdata" / "corpus"
FT_DIR = ROOT / "testdata" / "finetune"
SPLIT_FILE = FT_DIR / "split.json"
TWINS_FILE = FT_DIR / "twins.json"
PAIRS_FILE = FT_DIR / "train_pairs.jsonl"
NOTEBOOK_FILE = ROOT / "notebooks" / "train_reranker.ipynb"
QUESTION_FILES = {
    "train": FT_DIR / "train_questions.json",
    "test": FT_DIR / "test_questions.json",
    "holdout": FT_DIR / "holdout_questions.json",
}

# 업로드할 때와 같은 청킹 설정. 문제 파일과 twins.json 도 이 값이어야 한다.
CHUNKING = {"chunk_size": 500, "chunk_overlap": 50, "chunk_split_headings": True}
EXPECTED_SIDE_COUNTS = {"train": 36, "test": 20}
EXPECTED_TWIN_PAIRS = 27
# 문제 종류 → 정답 문서가 있어야 하는 쪽. 예비 시험 문제는 학습용 문서에서 뽑는다(스펙 §0).
QUESTION_SIDE = {"train": "train", "holdout": "train", "test": "test"}
FORBIDDEN_GOLD_DOCS = ("취업규칙.md", "휴가규정.md")
# (문서, 청크 번호, 이 청크를 정답으로 쓰면 안 되는 문제 종류). 스펙 §4-4 규칙 10.
# 08 의 4번 청크는 "직장 내 괴롭힘", 34 의 5번 청크는 "불이익 금지" 다(2026-10-01 확인).
FORBIDDEN_GOLD_CHUNKS = (
    ("08_징계_및_고충처리.md", 4, ("train", "holdout")),
    ("34_직장내괴롭힘_예방.md", 5, ("test",)),
)
# 스펙 §8 7번의 낱말 그대로다. "지사" 는 "공지사항" 에도 걸린다. 걸리면 질문을 다르게 쓴다
# (낱말을 목록에서 빼지 않는다. 빼면 "지사 직원" 같은 질문이 통과한다).
TEST_TARGET_WORDS = (
    "파견", "연구직", "연구소", "해외지사", "지사", "자회사",
    "시간제", "재택근무 전담", "촉탁", "현장실습", "주재원",
)
STYLES = ("polite", "casual", "keyword", "situation", "typo")
REQUIRED_QUESTION_FIELDS = ("id", "question", "ground_truth", "source_doc", "source_text", "style")
# 노트북 코드 칸에서 해시를 찾는 정규식. ([0-9a-f]{64}) 는 SHA-256 16진수 64자리를 꺼낸다.
_SHA_RE = re.compile(r'EXPECTED_SHA256\s*=\s*"([0-9a-f]{64})"')

# 타입 별칭. "문서 이름을 받아 청크 본문 목록(없으면 None)을 돌려주는 함수" 라는 뜻이다.
# 규칙 함수가 코퍼스를 직접 읽지 않고 이 함수를 받게 하면, 자기 점검에서 가짜 코퍼스를 넣을 수 있다.
ChunksOf = Callable[[str], "list[str] | None"]


@cache  # 같은 문서를 여러 문항이 가리키므로 한 번만 자른다. functools.cache 는 인자별로 결과를 기억한다.
def _corpus_chunks(name: str) -> tuple[str, ...] | None:
    path = CORPUS_DIR / name
    if not path.is_file():
        return None
    # 업로드 경로(app/main.py)와 같게 extract_text → chunk_text 순서로 자른다.
    # Path.read_text 로 바로 읽으면 정규화 한 겹이 빠져 실제 청크와 갈린다(eval_set_check 와 같은 이유).
    _, text = extract_text(name, path.read_bytes())
    chunks = chunk_text(
        text,
        size=CHUNKING["chunk_size"],
        overlap=CHUNKING["chunk_overlap"],
        split_headings=CHUNKING["chunk_split_headings"],
    )
    return tuple(c.content for c in chunks)  # tuple 은 바꿀 수 없어 캐시된 값을 누가 고칠 수 없다


def chunks_of(name: str) -> list[str] | None:
    got = _corpus_chunks(name)
    return list(got) if got is not None else None


# ─────────────────────────────────────────────────────────────────────────────
# 규칙 함수. 전부 위반 메시지 목록을 돌려준다(빈 목록 = 통과).
# ─────────────────────────────────────────────────────────────────────────────

def side_of(split: dict) -> dict[str, str]:
    """split.json → {문서: 쪽}. 같은 문서가 두 번 있으면 처음 것을 쓴다(중복은 check_split 이 잡는다)."""
    out: dict[str, str] = {}
    for d in split.get("documents") or []:
        out.setdefault(d.get("file"), d.get("side"))
    return out


def check_split(split: dict, corpus_files: set[str]) -> list[str]:
    """스펙 §8 1번 + 코퍼스 전체가 정확히 한 번씩 나오는가."""
    docs = split.get("documents")
    if not isinstance(docs, list):
        return ["split.json 에 documents 배열이 없습니다."]
    errors: list[str] = []
    seen: dict[str, str] = {}
    for d in docs:
        f, side, reason = d.get("file"), d.get("side"), d.get("reason")
        if side not in ("train", "test"):
            errors.append(f"{f}: side 는 train 또는 test 여야 합니다 (지금: {side!r}).")
        if not isinstance(reason, str) or not reason.strip():
            errors.append(f"{f}: reason 이 비어 있습니다. 왜 그쪽인지 적어주세요.")
        if f in seen:
            errors.append(f"{f}: 두 번 나옵니다 ({seen[f]}, {side}). 한 문서는 한쪽에만 있어야 합니다.")
        seen.setdefault(f, side)
    for f in sorted(corpus_files - set(seen)):
        errors.append(f"{f}: 코퍼스에 있는데 split.json 에 없습니다.")
    for f in sorted(set(seen) - corpus_files):
        errors.append(f"{f}: split.json 에 있는데 코퍼스에 없습니다.")
    counts = {s: sum(1 for v in seen.values() if v == s) for s in EXPECTED_SIDE_COUNTS}
    if counts != EXPECTED_SIDE_COUNTS:
        errors.append(f"쪽별 문서 수가 {counts} 입니다. 스펙 §2-6 의 {EXPECTED_SIDE_COUNTS} 와 다릅니다.")
    return errors


def check_twins(twins: dict, chunks: ChunksOf, sides: dict[str, str]) -> list[str]:
    """twins.json 의 본문이 실제 청크인가 + 스펙 §8 3번(쌍둥이 청크가 경계를 넘지 않는다)."""
    pairs = twins.get("pairs") or []
    errors: list[str] = []
    if len(pairs) != EXPECTED_TWIN_PAIRS:
        errors.append(f"쌍둥이 청크가 {len(pairs)}쌍입니다. 감사 문서의 {EXPECTED_TWIN_PAIRS}쌍이어야 합니다.")
    for p in pairs:
        pid = p.get("id")
        for key in ("a", "b"):
            c = p.get(key) or {}
            doc, idx, text = c.get("doc"), c.get("index"), c.get("text")
            got = chunks(doc) if isinstance(doc, str) else None
            if got is None:
                errors.append(f"쌍 {pid}{key}: 문서 {doc} 가 코퍼스에 없습니다.")
            elif not isinstance(idx, int) or not 0 <= idx < len(got) or got[idx] != text:
                errors.append(f"쌍 {pid}{key}: {doc} 의 {idx}번 청크 본문과 다릅니다. "
                              "코퍼스나 청킹 설정이 바뀌었는지 확인해주세요.")
        da = (p.get("a") or {}).get("doc")
        db = (p.get("b") or {}).get("doc")
        if da in sides and db in sides and sides[da] != sides[db]:
            errors.append(f"쌍 {pid}: {da}({sides[da]}) 와 {db}({sides[db]}) 가 다른 쪽입니다. "
                          "쌍둥이 청크가 경계를 넘으면 시험 답을 학습에서 본 것과 같습니다.")
    return errors


def twin_texts(text: str, twins: dict) -> set[str]:
    """그 본문과 쌍을 이루는 청크 본문들. 직접 연결된 쌍만 본다.

    한 다리 건너(A~B, B~C 이면 A~C)까지 따라가지 않는 이유: 쌍둥이 청크는 같은 규정을
    거의 같은 문장으로 적은 쌍이라, A 와 C 가 직접 쌍이 아니면 감사에서 같은 규정으로
    판정되지 않은 것이다.
    """
    out: set[str] = set()
    for p in twins.get("pairs") or []:
        a, b = p["a"]["text"], p["b"]["text"]
        if text == a:
            out.add(b)
        if text == b:
            out.add(a)
    return out


def check_questions(kind: str, payload: dict, chunks: ChunksOf,
                    sides: dict[str, str], twins: dict) -> list[str]:
    """문제 파일 하나. 스펙 §8 4번, 5번, 7번 + §4-4 규칙 5, 8, 10."""
    errors: list[str] = []
    if payload.get("chunking") != CHUNKING:
        errors.append(f"{kind}: chunking 이 {CHUNKING} 이 아닙니다.")
    questions = payload.get("questions")
    if not isinstance(questions, list) or not questions:
        return errors + [f"{kind}: questions 가 비어 있습니다."]
    want = QUESTION_SIDE[kind]
    # 집합 내포(set comprehension). 이 문제 종류에 해당하는 (문서, 청크 번호)만 모은다.
    forbidden = {(doc, idx) for doc, idx, kinds in FORBIDDEN_GOLD_CHUNKS if kind in kinds}
    ids: set[str] = set()
    for q in questions:
        qid = q.get("id", "(id 없음)")
        blanks = [f for f in REQUIRED_QUESTION_FIELDS
                  if not isinstance(q.get(f), str) or not q[f].strip()]
        if blanks:
            errors.append(f"{kind} [{qid}]: 비어 있거나 문자열이 아닌 칸: {', '.join(blanks)}")
            continue
        if qid in ids:
            errors.append(f"{kind} [{qid}]: id 가 중복입니다.")
        ids.add(qid)
        if q["style"] not in STYLES:
            errors.append(f"{kind} [{qid}]: style {q['style']!r} 은 {STYLES} 중 하나여야 합니다.")
        doc = q["source_doc"]
        if doc in FORBIDDEN_GOLD_DOCS:
            errors.append(f"{kind} [{qid}]: {doc} 는 정답 문서로 쓰지 않습니다(스펙 §4-4 규칙 4).")
        if sides.get(doc) != want:
            errors.append(f"{kind} [{qid}]: 정답 문서 {doc} 가 {sides.get(doc)} 쪽입니다. "
                          f"{want} 쪽 문서여야 합니다(스펙 §8 5번).")
        got = chunks(doc)
        if got is None or q["source_text"] not in got:
            errors.append(f"{kind} [{qid}]: source_text 가 {doc} 의 실제 청크와 글자까지 같지 않습니다. "
                          f"`python -m app.finetune_split_check --show-chunks {doc}` 로 본문을 복사해주세요.")
            continue
        if (doc, got.index(q["source_text"])) in forbidden:
            errors.append(f"{kind} [{qid}]: 이 청크는 {kind} 문제의 정답으로 쓰지 않습니다"
                          "(08 과 34 의 경계를 넘는 모순 짝, 스펙 §4-4 규칙 10).")
        if kind != "test":
            hits = [w for w in TEST_TARGET_WORDS if w in q["question"]]
            if hits:
                errors.append(f"{kind} [{qid}]: 질문에 시험용 대상 낱말 {hits} 가 있습니다"
                              "(스펙 §4-4 규칙 7). 질문을 다르게 써주세요.")
        if kind == "holdout" and twin_texts(q["source_text"], twins):
            errors.append(f"holdout [{qid}]: 정답 청크에 쌍둥이 청크가 있습니다(스펙 §4-4 규칙 8).")
    return errors


def protected_texts(payloads: dict[str, dict], twins: dict) -> set[str]:
    """학습 데이터에 나오면 안 되는 본문: 시험, 예비 시험 문제의 정답 청크와 그 쌍둥이 청크."""
    out: set[str] = set()
    for kind in ("test", "holdout"):
        for q in (payloads.get(kind) or {}).get("questions") or []:
            text = q.get("source_text")
            if text:
                out.add(text)
                out |= twin_texts(text, twins)  # |= 는 집합에 다른 집합을 합쳐 넣는다
    return out


def check_pairs(pairs: list[dict], protected: set[str]) -> list[str]:
    """스펙 §8 2번. 정답으로도 오답 예시로도 나오면 안 된다."""
    errors: list[str] = []
    for p in pairs:
        if p.get("positive") in protected:
            errors.append(f"train_pairs [{p.get('id')}]: 정답 청크가 시험 또는 예비 시험 문제의 "
                          "정답(또는 그 쌍둥이 청크)입니다.")
        leaked = [n for n in p.get("negatives") or [] if n in protected]
        if leaked:
            errors.append(f"train_pairs [{p.get('id')}]: 오답 예시 {len(leaked)}개가 시험 또는 "
                          "예비 시험 문제의 정답(또는 그 쌍둥이 청크)입니다.")
    return errors


def _code_of(notebook: dict) -> str:
    """노트북의 코드 칸을 이어 붙인다. ipynb 의 source 는 문자열일 수도, 줄 목록일 수도 있다."""
    parts = []
    for cell in notebook.get("cells") or []:
        if cell.get("cell_type") != "code":
            continue
        src = cell.get("source") or ""
        parts.append("".join(src) if isinstance(src, list) else src)
    return "\n".join(parts)


def check_notebook_hash(pairs_bytes: bytes, notebook: dict) -> list[str]:
    """스펙 §8 6번."""
    m = _SHA_RE.search(_code_of(notebook))
    if not m:
        return ['노트북 코드에 EXPECTED_SHA256 = "<64자리>" 줄이 없습니다.']
    actual = hashlib.sha256(pairs_bytes).hexdigest()
    if m.group(1) != actual:
        return [f"노트북의 해시({m.group(1)[:12]}...)와 train_pairs.jsonl 의 해시({actual[:12]}...)가 "
                "다릅니다. 학습 데이터를 다시 만들었다면 노트북의 EXPECTED_SHA256 도 고쳐주세요."]
    return []


# ─────────────────────────────────────────────────────────────────────────────
# 자기 점검: 규칙마다 틀린 입력을 넣어 잡는지 본다.
# ─────────────────────────────────────────────────────────────────────────────

def _self_test() -> list[str]:
    """잡아야 할 것을 못 잡은 규칙의 설명 목록(빈 목록 = 전부 잡았다)."""
    fake = {
        "a.md": ["# A", "## 재택\n주 2회"],
        "b.md": ["# B", "## 재택\n주 2회 같음"],
        "t.md": ["# T", "## 재택\n주 5회"],
        "취업규칙.md": ["# 취업규칙", "## 제1조"],
        "08_징계_및_고충처리.md": ["0", "1", "2", "3", "## 직장 내 괴롭힘\n신고"],
    }
    chunks = fake.get  # dict.get 은 없는 키에 None 을 돌려주므로 ChunksOf 모양과 같다
    sides = {"a.md": "train", "b.md": "train", "t.md": "test",
             "취업규칙.md": "train", "08_징계_및_고충처리.md": "train"}
    twins = {"pairs": [{"id": 1, "a": {"doc": "a.md", "index": 1, "text": fake["a.md"][1]},
                        "b": {"doc": "b.md", "index": 1, "text": fake["b.md"][1]}}]}

    def q(**over) -> dict:
        base = {"id": "x1", "question": "재택 몇 번", "ground_truth": "주 2회",
                "source_doc": "a.md", "source_text": fake["a.md"][1], "style": "keyword"}
        return base | over  # 딕셔너리 합치기(3.9+). 오른쪽 값이 이긴다

    def payload(*qs: dict) -> dict:
        return {"chunking": CHUNKING, "questions": list(qs)}

    def caught(errors: list[str], word: str) -> bool:
        return any(word in e for e in errors)

    misses: list[str] = []
    dup_split = {"documents": [{"file": "a.md", "side": "train", "reason": "r"},
                               {"file": "a.md", "side": "test", "reason": "r"}]}
    if not caught(check_split(dup_split, {"a.md"}), "두 번"):
        misses.append("check_split 이 한 문서가 양쪽에 있는 것을 못 잡았다")
    cross = {"pairs": [{"id": 9, "a": {"doc": "a.md", "index": 1, "text": fake["a.md"][1]},
                        "b": {"doc": "t.md", "index": 1, "text": fake["t.md"][1]}}]}
    if not caught(check_twins(cross, chunks, sides), "다른 쪽"):
        misses.append("check_twins 가 경계를 넘는 쌍둥이 청크를 못 잡았다")
    wrong = {"pairs": [{"id": 9, "a": {"doc": "a.md", "index": 1, "text": "다른 본문"},
                        "b": {"doc": "b.md", "index": 1, "text": fake["b.md"][1]}}]}
    if not caught(check_twins(wrong, chunks, sides), "본문과 다릅니다"):
        misses.append("check_twins 가 실제 청크가 아닌 본문을 못 잡았다")
    if check_questions("train", payload(q()), chunks, sides, twins):
        misses.append("check_questions 가 깨끗한 연습 문제를 위반으로 봤다")
    if not caught(check_questions("train", payload(q(source_doc="t.md", source_text=fake["t.md"][1])),
                                  chunks, sides, twins), "쪽 문서여야"):
        misses.append("check_questions 가 시험용 문서를 정답으로 쓴 연습 문제를 못 잡았다")
    if not caught(check_questions("train", payload(q(question="자회사 재택")), chunks, sides, twins),
                  "시험용 대상 낱말"):
        misses.append("check_questions 가 연습 문제의 시험용 대상 낱말을 못 잡았다")
    if not caught(check_questions("holdout", payload(q()), chunks, sides, twins), "쌍둥이"):
        misses.append("check_questions 가 쌍둥이 청크가 있는 예비 시험 정답을 못 잡았다")
    if not caught(check_questions("train", payload(q(source_doc="취업규칙.md",
                                                     source_text=fake["취업규칙.md"][1])),
                                  chunks, sides, twins), "정답 문서로 쓰지 않습니다"):
        misses.append("check_questions 가 취업규칙을 정답 문서로 쓴 것을 못 잡았다")
    if not caught(check_questions("holdout", payload(q(source_doc="08_징계_및_고충처리.md",
                                                       source_text=fake["08_징계_및_고충처리.md"][4])),
                                  chunks, sides, twins), "규칙 10"):
        misses.append("check_questions 가 08 의 괴롭힘 청크를 정답으로 쓴 것을 못 잡았다")
    if not caught(check_questions("train", payload(q(style="formal")), chunks, sides, twins), "style"):
        misses.append("check_questions 가 모르는 말투를 못 잡았다")
    if not caught(check_questions("train", payload(q(source_text="없는 본문")), chunks, sides, twins),
                  "글자까지"):
        misses.append("check_questions 가 실제 청크가 아닌 정답 본문을 못 잡았다")
    protected = protected_texts({"test": payload(q(source_doc="t.md", source_text=fake["t.md"][1]))}, twins)
    leak = [{"id": "p1", "positive": fake["a.md"][1], "negatives": [fake["t.md"][1]]}]
    if not caught(check_pairs(leak, protected), "오답 예시"):
        misses.append("check_pairs 가 오답 예시로 새어 들어간 시험 정답을 못 잡았다")
    if protected_texts({"holdout": payload(q())}, twins) != {fake["a.md"][1], fake["b.md"][1]}:
        misses.append("protected_texts 가 예비 시험 정답의 쌍둥이 청크를 넣지 않았다")
    nb = {"cells": [{"cell_type": "code", "source": ['EXPECTED_SHA256 = "' + "0" * 64 + '"\n']}]}
    if not check_notebook_hash(b"data", nb):
        misses.append("check_notebook_hash 가 다른 해시를 못 잡았다")
    good = {"cells": [{"cell_type": "code",
                       "source": f'EXPECTED_SHA256 = "{hashlib.sha256(b"data").hexdigest()}"'}]}
    if check_notebook_hash(b"data", good):
        misses.append("check_notebook_hash 가 같은 해시를 위반으로 봤다")
    return misses


# ─────────────────────────────────────────────────────────────────────────────
# 실행
# ─────────────────────────────────────────────────────────────────────────────

def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"❌ JSON 을 읽지 못했습니다 ({path.name}): {e.lineno}번째 줄, {e.msg}")
        return None


def _show_chunks(name: str) -> int:
    """문제 작성용. 청크 번호와 JSON 문자열로 쓴 본문을 찍는다(그대로 붙여 넣으면 된다)."""
    got = chunks_of(name)
    if got is None:
        print(f"코퍼스에 {name} 가 없습니다. 파일 이름을 testdata/corpus/ 에서 확인해주세요.")
        return 1
    for i, text in enumerate(got):
        print(f"[{i}] {json.dumps(text, ensure_ascii=False)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="리랭커 파인튜닝 실험의 누출 검사")
    parser.add_argument("--show-chunks", metavar="DOC", default=None,
                        help="코퍼스 문서 하나의 청크를 번호와 함께 찍는다(문제 작성용)")
    args = parser.parse_args()
    if args.show_chunks:
        return _show_chunks(args.show_chunks)

    misses = _self_test()
    if misses:
        for m in misses:
            print(f"❌ 자기 점검: {m}")
        return 1
    print("✅ 자기 점검: 규칙 함수마다 틀린 입력을 잡았습니다")

    failures = 0

    def report(name: str, errors: list[str]) -> None:
        # nonlocal: 바깥 함수(main)의 변수 failures 를 이 안쪽 함수에서 고치겠다는 선언이다.
        nonlocal failures
        if errors:
            failures += len(errors)
            for e in errors:
                print(f"❌ [{name}] {e}")
        else:
            print(f"✅ {name}")

    def skip(message: str) -> None:
        print(f"⏭  {message}")

    for base in (SPLIT_FILE, TWINS_FILE):
        if not base.exists():
            print(f"❌ 기준 파일이 없습니다: {base}. 이 파일은 건너뛰지 않습니다(스펙 §8).")
            return 1
    split, twins = _read_json(SPLIT_FILE), _read_json(TWINS_FILE)
    if split is None or twins is None:
        return 1

    corpus_files = {p.name for p in CORPUS_DIR.glob("*.md")}
    report("1. 학습용과 시험용 문서가 겹치지 않는다", check_split(split, corpus_files))
    sides = side_of(split)
    report("3. 쌍둥이 청크가 실제 청크이고 경계를 넘지 않는다", check_twins(twins, chunks_of, sides))
    if twins.get("chunking") != CHUNKING:
        report("3. twins.json 청킹 설정", [f"twins.json 의 chunking 이 {CHUNKING} 이 아닙니다."])

    payloads: dict[str, dict] = {}
    for kind, path in QUESTION_FILES.items():
        if not path.exists():
            skip(f"{path.name} 이 아직 없어 이 파일의 4, 5, 7번 검사를 건너뜁니다")
            continue
        loaded = _read_json(path)
        if loaded is None:
            failures += 1
            continue
        payloads[kind] = loaded
        report(f"4, 5, 7. {path.name}", check_questions(kind, loaded, chunks_of, sides, twins))

    if not PAIRS_FILE.exists():
        skip("train_pairs.jsonl 이 아직 없어 2번, 6번 검사를 건너뜁니다")
    else:
        lines = PAIRS_FILE.read_text(encoding="utf-8").splitlines()
        pairs = [json.loads(line) for line in lines if line.strip()]
        report("2. 시험, 예비 시험 정답이 학습 데이터에 없다",
               check_pairs(pairs, protected_texts(payloads, twins)))
        if not NOTEBOOK_FILE.exists():
            skip("노트북이 아직 없어 6번 검사를 건너뜁니다")
        else:
            notebook = _read_json(NOTEBOOK_FILE)
            if notebook is None:
                failures += 1
            else:
                report("6. 노트북의 해시가 학습 데이터와 같다",
                       check_notebook_hash(PAIRS_FILE.read_bytes(), notebook))

    print(f"\n❌ {failures}건 실패." if failures else "\n전부 통과.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: 기준 파일 없이 돌려 실패하는지 본다**

Run: `cd ai-service && .venv/bin/python -m app.finetune_split_check`
Expected: `✅ 자기 점검: ...` 다음에 `❌ 기준 파일이 없습니다: .../split.json. 이 파일은 건너뛰지 않습니다(스펙 §8).`, 종료코드 1 (`echo $?` 가 `1`).

- [ ] **Step 3: `split.json` 을 쓴다**

`ai-service/testdata/finetune/split.json` (스펙 §2-5, §2-6 그대로. 학습용 36개, 시험용 20개):

```json
{
  "corpus": "testdata/corpus",
  "spec": "docs/superpowers/specs/2026-10-01-reranker-finetune-design.md §2",
  "documents": [
    {"file": "01_정규직_인사규정.md", "side": "train", "reason": "본사 덩어리: 쌍둥이 청크로 이어진 본사 문서 11개를 한쪽에 둔다(스펙 §2-4)"},
    {"file": "05_복리후생_지원제도.md", "side": "train", "reason": "본사 덩어리(스펙 §2-4). 21, 24, 27 과 모순 짝이다(스펙 §2-6)"},
    {"file": "06_건강검진_안내.md", "side": "train", "reason": "본사 덩어리(스펙 §2-4)"},
    {"file": "07_경조사_지원규정.md", "side": "train", "reason": "본사 덩어리(스펙 §2-4)"},
    {"file": "08_징계_및_고충처리.md", "side": "train", "reason": "본사 덩어리(스펙 §2-4). 예외: 34_직장내괴롭힘_예방(시험용)과 경계를 넘는 모순 짝이다(괴롭힘 신고 창구와 조사 중 조치). 분할은 바꾸지 않고 출제 규칙으로 막는다(스펙 §2-6, §4-4 규칙 10)"},
    {"file": "09_출장_및_경비.md", "side": "train", "reason": "본사 덩어리(스펙 §2-4)"},
    {"file": "12_자주_묻는_질문.md", "side": "train", "reason": "본사 덩어리(스펙 §2-4)"},
    {"file": "31_퇴직_및_퇴직금.md", "side": "train", "reason": "본사 덩어리(스펙 §2-4)"},
    {"file": "32_노사협의회_운영.md", "side": "train", "reason": "본사 덩어리(스펙 §2-4)"},
    {"file": "취업규칙.md", "side": "train", "reason": "본사 덩어리(스펙 §2-4). 정답 문서로 쓰지 않는다(스펙 §4-4 규칙 4)"},
    {"file": "휴가규정.md", "side": "train", "reason": "본사 덩어리(스펙 §2-4). 정답 문서로 쓰지 않는다(스펙 §4-4 규칙 4)"},
    {"file": "02_계약직_인사규정.md", "side": "train", "reason": "01_정규직을 네 번 참조한다. 시험용에 두면 그 참조를 따라가는 문제는 시험용 봇 안에 답이 없다(스펙 §2-5)"},
    {"file": "03_인턴_운영지침.md", "side": "train", "reason": "식대 문장 하나로 본사 덩어리와 쌍둥이 청크가 있다(스펙 §2-4)"},
    {"file": "10_보안_및_정보관리.md", "side": "train", "reason": "학습용 고정(사용자 결정, 2026-10-01). 48_모바일과 쌍둥이 청크, 23_문서관리와 모순 짝이고 04_파견의 보안 규정이 이 문서에 기댄다(스펙 §2-5)"},
    {"file": "11_채용_절차.md", "side": "train", "reason": "학습용 고정(사용자 결정, 2026-10-01). 본사 신규 입사자의 수습 기간과 추천 포상금을 적는 본사 채용 규정이다(스펙 §2-5)"},
    {"file": "51_생산공장_근무규정.md", "side": "train", "reason": "헷갈림 묶음의 학습용 대상(생산직)(스펙 §2-5)"},
    {"file": "54_협력사_상주인력_지침.md", "side": "train", "reason": "헷갈림 묶음의 학습용 대상(협력사 상주인력)(스펙 §2-5)"},
    {"file": "55_임원_처우규정.md", "side": "train", "reason": "헷갈림 묶음의 학습용 대상(임원)(스펙 §2-5)"},
    {"file": "59_프로젝트계약직_지침.md", "side": "train", "reason": "헷갈림 묶음의 학습용 대상(프로젝트계약직)(스펙 §2-5)"},
    {"file": "61_비상근자문역_처우지침.md", "side": "train", "reason": "헷갈림 묶음의 학습용 대상(비상근 자문역)(스펙 §2-5)"},
    {"file": "21_사무용품_및_비품.md", "side": "train", "reason": "05_복리후생과 모순 짝(키보드와 마우스 한도)이라 학습용에 고정(스펙 §2-6)"},
    {"file": "23_문서관리_및_보존.md", "side": "train", "reason": "10_보안과 모순 짝(문서 등급 이름)이라 학습용에 고정(스펙 §2-6)"},
    {"file": "24_사내동호회_운영.md", "side": "train", "reason": "05_복리후생과 모순 짝(동호회 지원 조건)이라 학습용에 고정(스펙 §2-6)"},
    {"file": "27_자격증_취득지원.md", "side": "train", "reason": "05_복리후생과 모순 짝(자격증 지원 조건)이라 학습용에 고정(스펙 §2-6)"},
    {"file": "48_모바일기기_및_계정관리.md", "side": "train", "reason": "10_보안과 모순 짝(비밀번호 재사용 제한)이자 쌍둥이 청크(90일마다 변경)라 학습용에 고정(스펙 §2-6)"},
    {"file": "22_차량등록_및_주차.md", "side": "train", "reason": "일반 문서. 번호 순서로 시험용부터 번갈아 배정한 결과 학습용(스펙 §2-6)"},
    {"file": "26_신입사원_온보딩.md", "side": "train", "reason": "일반 문서. 번갈아 배정 결과 학습용(스펙 §2-6)"},
    {"file": "29_승진_및_직급체계.md", "side": "train", "reason": "일반 문서. 번갈아 배정 결과 학습용(스펙 §2-6)"},
    {"file": "33_산업안전보건.md", "side": "train", "reason": "일반 문서. 번갈아 배정 결과 학습용(스펙 §2-6)"},
    {"file": "35_개인정보_처리.md", "side": "train", "reason": "일반 문서. 번갈아 배정 결과 학습용(스펙 §2-6)"},
    {"file": "37_사내식당_운영.md", "side": "train", "reason": "일반 문서. 번갈아 배정 결과 학습용(스펙 §2-6)"},
    {"file": "39_기숙사_및_사택.md", "side": "train", "reason": "일반 문서. 번갈아 배정 결과 학습용(스펙 §2-6)"},
    {"file": "41_장기근속_포상.md", "side": "train", "reason": "일반 문서. 번갈아 배정 결과 학습용(스펙 §2-6)"},
    {"file": "44_지식재산_보상.md", "side": "train", "reason": "일반 문서. 번갈아 배정 결과 학습용(스펙 §2-6)"},
    {"file": "46_협력사_관리.md", "side": "train", "reason": "일반 문서. 번갈아 배정 결과 학습용(스펙 §2-6)"},
    {"file": "49_증명서_및_민원.md", "side": "train", "reason": "일반 문서. 번갈아 배정 결과 학습용(스펙 §2-6)"},
    {"file": "04_파견인력_관리지침.md", "side": "test", "reason": "헷갈림 묶음의 시험용 대상(파견인력). SEC-002 규정은 10_보안(학습용)에 기대므로 그 규정을 묻는 시험 문제는 쓰지 않는다(스펙 §4-4 규칙 3)"},
    {"file": "50_부설연구소_별도규정.md", "side": "test", "reason": "헷갈림 묶음의 시험용 대상(연구직). 본문에 없는 주제는 취업규칙(학습용)이 적용되므로 본문에 적힌 주제만 묻는다(스펙 §4-4 규칙 3)"},
    {"file": "52_해외지사_인사규정.md", "side": "test", "reason": "헷갈림 묶음의 시험용 대상(해외지사 현지 채용 인력과 주재원)(스펙 §2-5)"},
    {"file": "53_자회사_올댑랩스_인사규정.md", "side": "test", "reason": "헷갈림 묶음의 시험용 대상(자회사)(스펙 §2-5)"},
    {"file": "56_시간제근로자_운영지침.md", "side": "test", "reason": "헷갈림 묶음의 시험용 대상(시간제)(스펙 §2-5)"},
    {"file": "57_재택근무전담자_지침.md", "side": "test", "reason": "헷갈림 묶음의 시험용 대상(재택근무 전담자)(스펙 §2-5)"},
    {"file": "58_촉탁직_재고용규정.md", "side": "test", "reason": "헷갈림 묶음의 시험용 대상(촉탁직)(스펙 §2-5)"},
    {"file": "60_현장실습생_운영지침.md", "side": "test", "reason": "헷갈림 묶음의 시험용 대상(현장실습생)(스펙 §2-5)"},
    {"file": "42_해외주재원_운영.md", "side": "test", "reason": "52_해외지사가 주재원에게도 적용한다고 적어 대상이 같으므로 52 와 같은 쪽(스펙 §2-5)"},
    {"file": "20_회의실_및_공용공간.md", "side": "test", "reason": "일반 문서. 번호 순서로 시험용부터 번갈아 배정한 결과 시험용(스펙 §2-6)"},
    {"file": "25_사원증_및_출입관리.md", "side": "test", "reason": "일반 문서. 번갈아 배정 결과 시험용(스펙 §2-6)"},
    {"file": "28_성과평가_제도.md", "side": "test", "reason": "일반 문서. 번갈아 배정 결과 시험용(스펙 §2-6)"},
    {"file": "30_임금_및_상여지급.md", "side": "test", "reason": "일반 문서. 번갈아 배정 결과 시험용(스펙 §2-6). 식대 금액은 적혀 있지 않다(스펙 §4-4 규칙 3)"},
    {"file": "34_직장내괴롭힘_예방.md", "side": "test", "reason": "일반 문서. 번갈아 배정 결과 시험용(스펙 §2-6). 예외: 08_징계(학습용)와 경계를 넘는 모순 짝이다. 분할은 바꾸지 않고 불이익 금지 조항을 시험 문제로 묻지 않는다(스펙 §4-4 규칙 10)"},
    {"file": "36_비상대응_및_재해.md", "side": "test", "reason": "일반 문서. 번갈아 배정 결과 시험용(스펙 §2-6)"},
    {"file": "38_통근버스_운영.md", "side": "test", "reason": "일반 문서. 번갈아 배정 결과 시험용(스펙 §2-6)"},
    {"file": "40_육아휴직_및_돌봄.md", "side": "test", "reason": "일반 문서. 번갈아 배정 결과 시험용(스펙 §2-6)"},
    {"file": "43_외부강연_및_겸직.md", "side": "test", "reason": "일반 문서. 번갈아 배정 결과 시험용(스펙 §2-6)"},
    {"file": "45_아이디어_제안제도.md", "side": "test", "reason": "일반 문서. 번갈아 배정 결과 시험용(스펙 §2-6)"},
    {"file": "47_사내공지_및_커뮤니케이션.md", "side": "test", "reason": "일반 문서. 번갈아 배정 결과 시험용(스펙 §2-6)"}
  ]
}
```

- [ ] **Step 4: `twins.json` 을 만든다 (한 번만 돌리는 스크립트, 저장소에 넣지 않는다)**

감사 문서 `docs/코퍼스-중복-감사-2026-09-18.md` §3-A(20쌍)와 §3-B(7쌍)의 `문서#번호` 는 청커의 `Chunk.index`(0번이 제목) 그대로다. 2026-10-01 에 27쌍 전부 청크 제목이 감사 표와 맞는 것을 확인했다. 아래를 스크래치 디렉터리에 `build_twins.py` 로 저장하고 `ai-service/` 에서 돌린다.

```python
"""twins.json 을 만든다. 저장소에 넣지 않는다(결과 파일만 커밋한다)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))  # ai-service 에서 실행한다
from app.finetune_split_check import CHUNKING, chunks_of

# (감사 번호, 문서 A, 청크 번호 A, 제목에 있어야 할 말 A, 문서 B, 청크 번호 B, 제목에 있어야 할 말 B)
PAIRS = [
    (1, "05_복리후생_지원제도.md", 5, "장비 지원", "취업규칙.md", 6, "제6조"),
    (2, "01_정규직_인사규정.md", 3, "근무", "취업규칙.md", 2, "제2조"),
    (3, "01_정규직_인사규정.md", 4, "재택", "취업규칙.md", 3, "제3조"),
    (4, "01_정규직_인사규정.md", 5, "퇴직금", "취업규칙.md", 9, "제9조"),
    (5, "08_징계_및_고충처리.md", 1, "징계", "취업규칙.md", 10, "제10조"),
    (6, "01_정규직_인사규정.md", 1, "연차", "휴가규정.md", 1, "연차"),
    (7, "01_정규직_인사규정.md", 2, "반차", "휴가규정.md", 2, "반차"),
    (8, "05_복리후생_지원제도.md", 1, "교육비", "취업규칙.md", 5, "제5조"),
    (9, "06_건강검진_안내.md", 1, "대상", "취업규칙.md", 7, "제7조"),
    (10, "07_경조사_지원규정.md", 1, "결혼", "취업규칙.md", 8, "제8조"),
    (11, "09_출장_및_경비.md", 3, "식대", "취업규칙.md", 4, "제4조"),
    (12, "06_건강검진_안내.md", 4, "휴가", "취업규칙.md", 7, "제7조"),
    (13, "08_징계_및_고충처리.md", 2, "절차", "취업규칙.md", 10, "제10조"),
    (14, "08_징계_및_고충처리.md", 3, "고충", "32_노사협의회_운영.md", 4, "고충"),
    (15, "07_경조사_지원규정.md", 3, "사망", "취업규칙.md", 8, "제8조"),
    (16, "10_보안_및_정보관리.md", 1, "계정", "48_모바일기기_및_계정관리.md", 3, "계정"),
    (17, "09_출장_및_경비.md", 1, "국내", "취업규칙.md", 4, "제4조"),
    (18, "01_정규직_인사규정.md", 5, "퇴직금", "31_퇴직_및_퇴직금.md", 2, "퇴직금"),
    (19, "12_자주_묻는_질문.md", 1, "휴가", "01_정규직_인사규정.md", 2, "반차"),
    (20, "05_복리후생_지원제도.md", 4, "어학", "취업규칙.md", 5, "제5조"),
    (21, "31_퇴직_및_퇴직금.md", 2, "퇴직금", "취업규칙.md", 9, "제9조"),
    (22, "07_경조사_지원규정.md", 2, "출산", "취업규칙.md", 8, "제8조"),
    (23, "휴가규정.md", 3, "경조사", "취업규칙.md", 8, "제8조"),
    (24, "휴가규정.md", 3, "경조사", "07_경조사_지원규정.md", 1, "결혼"),
    (25, "휴가규정.md", 4, "신청", "01_정규직_인사규정.md", 1, "연차"),
    (26, "03_인턴_운영지침.md", 4, "복리후생", "09_출장_및_경비.md", 3, "식대"),
    (27, "03_인턴_운영지침.md", 4, "복리후생", "취업규칙.md", 4, "제4조"),
]


def side(doc: str, idx: int, must: str) -> dict:
    text = chunks_of(doc)[idx]
    title = text.split("\n")[0]
    # 번호가 밀렸으면 여기서 멈춘다. 조용히 다른 청크를 적는 것이 가장 나쁜 실패다.
    assert must in title, f"{doc} {idx}번 청크 제목이 {title!r} 이다. '{must}' 가 있어야 한다."
    return {"doc": doc, "index": idx, "text": text}


out = {
    "source": "docs/코퍼스-중복-감사-2026-09-18.md §3-A, §3-B (부류 1 중복 27쌍)",
    "chunking": CHUNKING,
    "pairs": [{"id": n, "a": side(da, ia, ma), "b": side(db, ib, mb)}
              for n, da, ia, ma, db, ib, mb in PAIRS],
}
Path("testdata/finetune/twins.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"{len(out['pairs'])}쌍을 썼다")
```

Run: `cd ai-service && .venv/bin/python <스크래치>/build_twins.py`
Expected: `27쌍을 썼다`

- [ ] **Step 5: 검사를 돌려 통과하는지 본다**

Run: `cd ai-service && .venv/bin/python -m app.finetune_split_check`
Expected:
```
✅ 자기 점검: 규칙 함수마다 틀린 입력을 잡았습니다
✅ 1. 학습용과 시험용 문서가 겹치지 않는다
✅ 3. 쌍둥이 청크가 실제 청크이고 경계를 넘지 않는다
⏭  train_questions.json 이 아직 없어 이 파일의 4, 5, 7번 검사를 건너뜁니다
⏭  test_questions.json 이 아직 없어 ...
⏭  holdout_questions.json 이 아직 없어 ...
⏭  train_pairs.jsonl 이 아직 없어 2번, 6번 검사를 건너뜁니다

전부 통과.
```

- [ ] **Step 6: 변이 시험으로 검사가 실제로 잡는지 본다**

`split.json` 에서 `42_해외주재원_운영.md` 의 `side` 를 잠시 `train` 으로 바꿔 돌린다.
Expected: `❌ [1. ...] 쪽별 문서 수가 {'train': 37, 'test': 19} 입니다...` 로 실패. 확인 뒤 `git checkout -- testdata/finetune/split.json` 이 아니라(아직 커밋 전) 편집기로 `test` 로 되돌리고 Step 5 를 다시 돌려 통과를 확인한다.

이어서 `split.json` 에서 `48_모바일기기_및_계정관리.md` 를 `test` 로, `20_회의실_및_공용공간.md` 를 `train` 으로 바꿔(문서 수는 그대로) 돌린다.
Expected: `❌ [3. ...] 쌍 16: 10_보안_및_정보관리.md(train) 와 48_모바일기기_및_계정관리.md(test) 가 다른 쪽입니다...`. 확인 뒤 두 줄을 되돌리고 다시 통과를 확인한다.

- [ ] **Step 7: CI 에 등록한다**

`.github/workflows/ci.yml` 의 자체 점검 목록에서 `python -m app.eval_set_check` 줄 바로 아래에 한 줄을 더한다:

```yaml
          python -m app.finetune_split_check
```

그리고 같은 파일의 설명 주석(현재 241행 근처, `✅ app.eval_set_check 는 ...` 문단) 아래에 두 줄을 더한다:

```yaml
      #    ✅ app.finetune_split_check 는 리랭커 파인튜닝의 분할, 문제, 학습 데이터 파일이
      #       서로 새지 않는지 파일만 읽고 본다(스펙 2026-10-01 §8).
```

- [ ] **Step 8: 커밋한다**

```bash
git add ai-service/app/finetune_split_check.py ai-service/testdata/finetune/split.json \
        ai-service/testdata/finetune/twins.json .github/workflows/ci.yml
git commit -m "feat: 리랭커 파인튜닝의 분할 파일과 누출 검사를 더한다"
```

---

### Task 2: `eval_set` 에 `--file` 을 더하고 `style` 을 보존한다

**Files:**
- Modify: `ai-service/app/eval_set.py`
- Create: `ai-service/app/eval_set_io_check.py`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `resolve_file(arg: str | None) -> Path` (None 이면 `EVAL_SET_PATH`, 상대 경로는 `ai-service/` 기준)
  - `previous_annotations(path: Path = EVAL_SET_PATH) -> dict[str, dict]`
  - `read_payload(path: Path = EVAL_SET_PATH) -> dict`
  - `dump(bot_id: Id, path: Path = EVAL_SET_PATH) -> int`
  - `load(bot_id: Id, replace: bool, path: Path = EVAL_SET_PATH) -> int`
  - `resolve_chunk(bot_id, source_text) -> list[Id]` (그대로, 태스크 8 이 쓴다)
  - CLI: `python -m app.eval_set load --bot-id N --file testdata/finetune/test_questions.json`

**왜 고치는가:** 지금 `load` 와 `dump` 는 봇 1번 평가셋 파일만 쓴다. 고치지 않고 시험용 봇을 `dump` 하면 봇 1번 평가셋 파일을 덮어쓴다(스펙 §7). 그리고 `dump` 는 기존 파일에서 `review`, `difficulty` 만 이어받아 새 키 `style` 을 잃는다.

- [ ] **Step 1: 실패하는 점검을 쓴다**

`ai-service/app/eval_set_io_check.py`:

```python
"""eval_set 의 파일 입출력 점검. DB 를 쓰지 않는다. CI 에서 돈다.

실행:  cd ai-service && .venv/bin/python -m app.eval_set_io_check

보는 것 (2026-10-01, 리랭커 파인튜닝 실험이 계기)
  ① --file 이 없으면 봇 1번 평가셋 파일을 가리킨다(기존 동작 유지)
  ② 상대 경로는 ai-service/ 기준이다(실행 위치에 따라 다른 파일을 쓰지 않는다)
  ③ dump 가 기존 파일의 style 을 이어받는다(안 하면 dump 한 번에 말투 표시가 지워진다)
  ④ style 이 없던 문항에는 style 칸을 만들지 않는다(봇 1번 파일에 빈 칸이 생기지 않는다)
"""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from . import eval_set


def _row(question: str) -> tuple:
    # fetch_questions 가 돌려주는 행 모양: (db id, 질문, 정답, 활성, 파일명, 청크 본문)
    return (1, question, "답", True, "a.md", "본문")


def check_default_file_is_bot1_file() -> None:
    assert eval_set.resolve_file(None) == eval_set.EVAL_SET_PATH


def check_relative_file_is_under_ai_service() -> None:
    got = eval_set.resolve_file("testdata/finetune/test_questions.json")
    assert got == eval_set._AI_SERVICE_DIR / "testdata" / "finetune" / "test_questions.json", got


def check_previous_annotations_reads_given_file_and_style() -> None:
    with TemporaryDirectory() as tmp:
        f = Path(tmp) / "x.json"
        f.write_text(json.dumps({"questions": [{"question": "질문1", "style": "typo"}]},
                                ensure_ascii=False), encoding="utf-8")
        ann = eval_set.previous_annotations(f)
    assert ann["질문1"]["style"] == "typo", ann
    assert ann["질문1"]["review"] == {"verdict": "", "note": ""}, ann


def check_missing_file_gives_empty_annotations() -> None:
    assert eval_set.previous_annotations(Path("/없는/경로/x.json")) == {}


def check_build_payload_keeps_style_only_when_present() -> None:
    payload = eval_set.build_payload([_row("질문1"), _row("질문2")], {"질문1": {"style": "casual"}})
    q1, q2 = payload["questions"]
    assert q1["style"] == "casual", q1
    assert "style" not in q2, q2


def main() -> None:
    checks = [
        check_default_file_is_bot1_file,
        check_relative_file_is_under_ai_service,
        check_previous_annotations_reads_given_file_and_style,
        check_missing_file_gives_empty_annotations,
        check_build_payload_keeps_style_only_when_present,
    ]
    for fn in checks:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(checks)}가지 전부 통과.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 실패하는지 본다**

Run: `cd ai-service && .venv/bin/python -m app.eval_set_io_check`
Expected: `AttributeError: module 'app.eval_set' has no attribute 'resolve_file'`

- [ ] **Step 3: `eval_set.py` 를 고친다**

(1) 모듈 설명의 `실행:` 아래에 두 줄을 더한다:

```python
    cd ai-service && .venv/bin/python -m app.eval_set load --bot-id 3 --file testdata/finetune/test_questions.json
    cd ai-service && .venv/bin/python -m app.eval_set dump --bot-id 3 --file testdata/finetune/test_questions.json
```

(2) `_FILE_ONLY_KEYS = ...` 줄 바로 아래에 더한다:

```python
# 있을 때만 이어받는 칸. 빈 칸을 미리 만들지 않는다.
# style(말투 표시)은 리랭커 파인튜닝 문제 파일에만 있다(2026-10-01). 봇 1번 평가셋에는 없으므로
# 빈 칸을 만들면 dump 한 번에 봇 1번 파일 전체에 쓸모없는 칸이 생긴다.
_OPTIONAL_FILE_KEYS = ("style",)
```

(3) `previous_annotations` 를 경로를 받게 바꾼다. 시그니처와 앞부분, 그리고 `ann = ...` 줄:

```python
def previous_annotations(path: Path = EVAL_SET_PATH) -> dict[str, dict]:
```

함수 본문의 `EVAL_SET_PATH` 두 곳(`if not EVAL_SET_PATH.exists():`, `EVAL_SET_PATH.read_text(...)`)을 `path` 로 바꾼다. 그리고 `ann = {key: ...}` 줄 바로 아래에 더한다:

```python
        # 있는 것만 담는다. `if q.get(key)` 는 키가 없거나 빈 문자열이면 거짓이다.
        ann.update({key: q[key] for key in _OPTIONAL_FILE_KEYS if q.get(key)})
```

(4) `build_payload` 의 `questions.append({...})` 를 아래로 바꾼다:

```python
        item = {
            "id": f"q{n}",
            "question": question,
            "ground_truth": ground_truth,
            # 정답 청크가 끊긴 질문은 None 으로 남긴다. 빈 문자열로 적으면
            # "본문이 빈 청크"와 "가리키는 청크가 없음"이 같은 값이 된다.
            "source_doc": filename,
            "source_text": content,
            # DB 의 is_active 를 그대로 쓴다(파일에서 이어받지 않는다). 근거는
            # previous_annotations 의 주석 마지막 문단에 있다.
            "active": bool(is_active),
            # 검수와 난이도는 사람이 적는다. 빈 칸을 미리 만들어 두는 이유는,
            # 칸이 아예 없으면 적는 사람이 무엇을 적어야 하는지 모르기 때문이다.
            "review": ann.get("review") or _empty_review(),
            "difficulty": ann.get("difficulty") or _empty_difficulty(),
        }
        for key in _OPTIONAL_FILE_KEYS:
            if ann.get(key):
                item[key] = ann[key]
        questions.append(item)
```

(5) `dump` 를 경로를 받게 바꾼다:

```python
def dump(bot_id: Id, path: Path = EVAL_SET_PATH) -> int:
```

본문에서 `previous_annotations()` 를 `previous_annotations(path)` 로, `EVAL_SET_PATH` 다섯 곳(`elif EVAL_SET_PATH.exists()`, `EVAL_SET_PATH.parent.mkdir`, `EVAL_SET_PATH.write_text`, 마지막 `print(f"{EVAL_SET_PATH} 에 ...")`)을 `path` 로 바꾼다.

(6) `read_payload` 와 `load` 를 경로를 받게 바꾼다:

```python
def read_payload(path: Path = EVAL_SET_PATH) -> dict:
```

본문의 `EVAL_SET_PATH` 세 곳을 `path` 로 바꾼다.

```python
def load(bot_id: Id, replace: bool, path: Path = EVAL_SET_PATH) -> int:
    """파일의 질문을 DB 에 넣는다. 성공하면 0, 실패하면 1."""
    payload = read_payload(path)
    questions = payload.get("questions") or []
    if not questions:
        print(f"{path} 에 questions 가 비어 있습니다.")
        return 1
```

(나머지 본문은 그대로 둔다.)

(7) `# 3. CLI` 구분선 바로 위에 더한다:

```python
def resolve_file(arg: str | None) -> Path:
    """--file 값 → 실제 경로. 없으면 봇 1번 평가셋 파일이다.

    상대 경로를 ai-service/ 기준으로 붙이는 이유: 현재 디렉터리 기준으로 두면 어디서
    실행했는가에 따라 다른 파일을 쓰게 된다(EVAL_SET_PATH 를 __file__ 기준으로 잡은 것과 같은 이유).
    """
    if arg is None:
        return EVAL_SET_PATH
    p = Path(arg)
    return p if p.is_absolute() else _AI_SERVICE_DIR / p
```

(8) `main()` 에서 두 하위 명령에 `--file` 을 더하고 넘긴다:

```python
    _file_help = ("문제 파일 경로(ai-service/ 기준). 없으면 봇 1번 평가셋 "
                  "testdata/eval_questions.json 이다. 다른 봇에는 반드시 지정할 것")
    p_dump = sub.add_parser("dump", help="DB 의 질문을 파일로 쓴다")
    p_dump.add_argument("--bot-id", type=int, required=True)
    p_dump.add_argument("--file", default=None, help=_file_help)

    p_load = sub.add_parser("load", help="파일의 질문을 DB 에 넣는다")
    p_load.add_argument("--bot-id", type=int, required=True)
    p_load.add_argument("--file", default=None, help=_file_help)
    p_load.add_argument(
        "--replace", action="store_true",
        help="기존 질문을 지우고 넣는다 (평가 결과도 CASCADE 로 함께 지워진다)")

    args = parser.parse_args()
    path = resolve_file(args.file)
    if args.command == "dump":
        return dump(args.bot_id, path)
    return load(args.bot_id, args.replace, path)
```

- [ ] **Step 4: 점검이 통과하는지 본다**

Run: `cd ai-service && .venv/bin/python -m app.eval_set_io_check && .venv/bin/python -m app.eval_set_check`
Expected: `5가지 전부 통과.` 그리고 `전부 통과.` (봇 1번 평가셋 파일은 바뀌지 않았다: `git status ai-service/testdata/eval_questions.json` 에 변경 없음)

- [ ] **Step 5: CI 에 등록하고 커밋한다**

`.github/workflows/ci.yml` 의 `python -m app.finetune_split_check` 줄 아래에:

```yaml
          python -m app.eval_set_io_check
```

```bash
git add ai-service/app/eval_set.py ai-service/app/eval_set_io_check.py .github/workflows/ci.yml
git commit -m "feat: eval_set 의 load, dump 에 --file 을 더하고 말투 표시를 보존한다"
```

---

### Task 3: `rank_trace` 비교 모드

**Files:**
- Modify: `ai-service/app/rank_trace.py`
- Create: `ai-service/app/rank_trace_check.py`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `rank_trace._questions`, `_all_distances`, `_candidates`, `_cut` (기존), `retriever.embed_one`, `retriever.fetch_contents`, `retriever._apply_order`, `local_reranker.rerank(query, texts, *, variant) -> {"response": [{"id", "score"}]}`
- Produces:
  - 결과 한 건의 모양: `{"qid": int, "question": str, "status": "fixable"|"gate"|"cut"|"outside", "ranks": {variant: int}}` (`ranks` 는 `fixable` 일 때만 채운다)
  - `sign_test_p(improved: int, worsened: int) -> float`
  - `judge(improved: int, worsened: int) -> str` (`"효과 있음"`, `"악화"`, `"구별되지 않음"`)
  - `summarize(results: list[dict], variant: str, top_k: int) -> dict`
  - `paired(results: list[dict], base: str, target: str, top_k: int) -> tuple[list[dict], list[dict]]` (좋아진 문제, 나빠진 문제)
  - `gate_count(results: list[dict], variant: str, top_k: int) -> tuple[int, int]` (고칠 수 있는데 5위 밖, 전체)
  - `measure_variants(bot_id: Id, variants: list[str]) -> list[dict]` (DB, 임베딩)
  - CLI: `--compare V1,V2 [--pair BASE:TARGET ...] [--gate VARIANT] [--out PATH]`

- [ ] **Step 1: 실패하는 점검을 쓴다**

`ai-service/app/rank_trace_check.py`:

```python
"""rank_trace 비교 모드의 순수 함수 점검. DB 도 모델도 쓰지 않는다. CI 에서 돈다.

실행:  cd ai-service && .venv/bin/python -m app.rank_trace_check

판정 규칙의 숫자는 스펙(2026-10-01-reranker-finetune-design.md §5-3)에 적힌 예와 같아야 한다.
  좋아짐 12, 나빠짐 2 → p 약 0.013 → 효과 있음
  좋아짐 6, 나빠짐 4 → p 약 0.75 → 구별되지 않음
  6:0 → 약 0.031, 5:0 → 0.0625 (갈린 문제가 5개 이하면 결과와 관계없이 구별되지 않음)
"""
from __future__ import annotations

from .rank_trace import gate_count, judge, paired, sign_test_p, summarize


def _r(qid: int, status: str, **ranks: int) -> dict:
    # **ranks 는 키워드 인자를 딕셔너리로 모은다. _r(1, "fixable", local=3) → ranks={"local": 3}
    return {"qid": qid, "question": f"질문{qid}", "status": status, "ranks": dict(ranks)}


def check_sign_test_matches_spec_examples() -> None:
    assert abs(sign_test_p(12, 2) - 0.01294) < 1e-4, sign_test_p(12, 2)
    assert abs(sign_test_p(6, 4) - 0.75391) < 1e-4, sign_test_p(6, 4)
    assert abs(sign_test_p(6, 0) - 0.03125) < 1e-9
    assert abs(sign_test_p(5, 0) - 0.0625) < 1e-9
    assert sign_test_p(2, 12) == sign_test_p(12, 2), "양측 검정은 방향에 대칭이다"
    assert sign_test_p(0, 0) == 1.0
    assert sign_test_p(6, 6) == 1.0, "1 을 넘으면 1 로 자른다"


def check_judge() -> None:
    assert judge(12, 2) == "효과 있음"
    assert judge(2, 12) == "악화"
    assert judge(6, 4) == "구별되지 않음"
    assert judge(5, 0) == "구별되지 않음"
    assert judge(6, 0) == "효과 있음"


def check_summarize_counts_unfixable_in_denominator() -> None:
    results = [
        _r(1, "fixable", local=1),
        _r(2, "fixable", local=7),
        _r(3, "gate"),
        _r(4, "outside"),
    ]
    s = summarize(results, "local", top_k=5)
    assert s["n"] == 4 and s["fixable"] == 2 and s["hit"] == 1, s
    assert s["top_rate"] == 0.25, "분모는 시험 문제 전체다(스펙 §5-3)"
    assert s["fixable_rate"] == 0.5
    assert s["mean_rank"] == 4.0
    assert s["status_counts"] == {"fixable": 2, "gate": 1, "cut": 0, "outside": 1}, s


def check_paired_ignores_ties_and_unfixable() -> None:
    results = [
        _r(1, "fixable", local=7, local_ft=2),   # 좋아짐
        _r(2, "fixable", local=3, local_ft=9),   # 나빠짐
        _r(3, "fixable", local=2, local_ft=4),   # 둘 다 5위 안: 동점
        _r(4, "fixable", local=8, local_ft=6),   # 둘 다 5위 밖: 동점
        _r(5, "cut"),
    ]
    up, down = paired(results, "local", "local_ft", top_k=5)
    assert [r["qid"] for r in up] == [1], up
    assert [r["qid"] for r in down] == [2], down


def check_gate_count_uses_all_questions() -> None:
    results = [_r(1, "fixable", local=6), _r(2, "fixable", local=1), _r(3, "gate"), _r(4, "outside")]
    assert gate_count(results, "local", top_k=5) == (1, 4)


def main() -> None:
    checks = [
        check_sign_test_matches_spec_examples,
        check_judge,
        check_summarize_counts_unfixable_in_denominator,
        check_paired_ignores_ties_and_unfixable,
        check_gate_count_uses_all_questions,
    ]
    for fn in checks:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(checks)}가지 전부 통과.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 실패하는지 본다**

Run: `cd ai-service && .venv/bin/python -m app.rank_trace_check`
Expected: `ImportError: cannot import name 'gate_count' from 'app.rank_trace'`

- [ ] **Step 3: 순수 함수와 측정 함수를 더한다**

`rank_trace.py` 의 import 블록을 아래로 바꾼다:

```python
from __future__ import annotations

import argparse
import json
import math
from datetime import date
from pathlib import Path

from .config import get_settings
from .db import close_pool, cursor
from .schemas import Id, Source
```

`def main() -> None:` 바로 위에 아래 절을 통째로 더한다:

```python
# ─────────────────────────────────────────────────────────────────────────────
# 여러 모델 비교 (2026-10-01, 리랭커 파인튜닝 실험)
# 설계: docs/superpowers/specs/2026-10-01-reranker-finetune-design.md §5
# ─────────────────────────────────────────────────────────────────────────────
#
# 무엇이 위의 trace() 와 다른가
#   trace() 는 설정의 reranker_provider 하나로 잰다. 비교 모드는 같은 리랭커 후보에
#   로컬 변형 여러 개를 차례로 넣는다. 후보를 한 번만 만들기 때문에, 변형끼리의 차이는
#   리랭커 하나에서만 생긴다.
#
# 문제마다 상태가 넷 중 하나다(스펙 §0 "고칠 수 있는 문제", §5-4).
#   fixable  거리 게이트를 통과했고 정답 청크가 거리 컷을 통과해 리랭커 후보 안에 있다
#   gate     거리 게이트에 걸려 근거가 모두 버려진다(리랭커가 불리지 않는다)
#   cut      정답 청크가 거리 컷(max_distance)에 잘린다
#   outside  정답 청크가 리랭커 후보 밖이다
# gate, cut, outside 는 리랭커가 바꿀 수 없으므로 모든 변형에서 결과가 같다.

STATUSES = ("fixable", "gate", "cut", "outside")
_STATUS_LABELS = {
    "fixable": "고칠 수 있는 문제",
    "gate": "거리 게이트에 걸림",
    "cut": "정답 청크가 거리 컷에 잘림",
    "outside": "정답 청크가 리랭커 후보 밖",
}
ALPHA = 0.05            # 판정 유의수준. 결과를 보기 전에 정했다(스펙 §5-3).
GATE_MIN_RATIO = 0.25   # 관문: 고칠 수 있는데 5위 밖인 문제가 시험 문제 전체의 4분의 1 이상(스펙 §5-2).


def sign_test_p(improved: int, worsened: int) -> float:
    """양측 부호 검정의 p 값.

    갈린 문제 n 개가 동전 던지기처럼 반반으로 갈린다고 가정할 때, 지금보다 한쪽으로 더
    치우친 결과가 나올 확률이다. 작은 쪽 개수를 k 라 하면
        p = 2 × (C(n,0) + C(n,1) + ... + C(n,k)) / 2^n
    math.comb(n, i) 가 C(n, i)(n 개 중 i 개를 고르는 경우의 수)다. scipy 를 쓰지 않는 이유는
    CI 가 requirements.txt 만 설치하고, 식이 이 한 줄이라 의존성을 늘릴 값어치가 없어서다.
    """
    n = improved + worsened
    if n == 0:
        return 1.0
    k = min(improved, worsened)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * tail)  # 양쪽이 같으면 2 × tail 이 1 을 넘으므로 자른다


def judge(improved: int, worsened: int) -> str:
    """스펙 §5-3 의 판정 규칙."""
    p = sign_test_p(improved, worsened)
    if p < ALPHA and improved > worsened:
        return "효과 있음"
    if p < ALPHA and worsened > improved:
        return "악화"
    return "구별되지 않음"


def _in_top(r: dict, variant: str, top_k: int) -> bool:
    return r["status"] == "fixable" and r["ranks"][variant] <= top_k


def summarize(results: list[dict], variant: str, top_k: int) -> dict:
    """한 변형의 지표. 대표 지표의 분모는 시험 문제 전체다(고칠 수 없는 문제 포함)."""
    fixable = [r for r in results if r["status"] == "fixable"]
    hit = sum(1 for r in fixable if r["ranks"][variant] <= top_k)
    n = len(results)
    return {
        "variant": variant,
        "n": n,
        "fixable": len(fixable),
        "hit": hit,
        "top_rate": hit / n if n else 0.0,
        "fixable_rate": hit / len(fixable) if fixable else 0.0,
        # 평균 순위는 고칠 수 있는 문제만으로 낸다. 다른 문제에는 리랭커 순위가 없다.
        "mean_rank": (sum(r["ranks"][variant] for r in fixable) / len(fixable)) if fixable else None,
        "status_counts": {s: sum(1 for r in results if r["status"] == s) for s in STATUSES},
    }


def paired(results: list[dict], base: str, target: str, top_k: int) -> tuple[list[dict], list[dict]]:
    """(좋아진 문제, 나빠진 문제). 둘 다 5위 안이거나 둘 다 5위 밖인 동점은 뺀다."""
    up = [r for r in results if not _in_top(r, base, top_k) and _in_top(r, target, top_k)]
    down = [r for r in results if _in_top(r, base, top_k) and not _in_top(r, target, top_k)]
    return up, down


def gate_count(results: list[dict], variant: str, top_k: int) -> tuple[int, int]:
    """(고칠 수 있는데 5위 밖인 문제 수, 시험 문제 전체 수). 분모를 전체로 잡는 이유는 스펙 §5-2."""
    room = sum(1 for r in results if r["status"] == "fixable" and r["ranks"][variant] > top_k)
    return room, len(results)


def measure_variants(bot_id: Id, variants: list[str]) -> list[dict]:
    """봇의 활성 평가 질문마다 리랭커 후보를 한 번 만들고, 변형마다 정답 청크의 순위를 잰다."""
    from . import local_reranker, retriever  # 늦은 import: 이 모듈을 열기만 해서 모델이 뜨면 안 된다

    s = get_settings()
    if s.rerank_fusion:
        # 이 모드는 리랭커 순서를 그대로 최종 순서로 본다. 융합이 켜져 있으면 실제 검색과 달라진다.
        raise SystemExit("rerank_fusion 이 켜져 있습니다. 비교 모드는 기본값(꺼짐)에서만 돌립니다. "
                         "RERANK_FUSION=false 로 다시 실행해주세요.")
    if not s.reranker_enabled:
        raise SystemExit("reranker_enabled 가 꺼져 있습니다. RERANKER_ENABLED=true 로 다시 실행해주세요.")

    rows = _questions(bot_id, None)
    no_gold = [qid for qid, _, gold, _ in rows if gold is None]
    if no_gold:
        raise SystemExit(f"정답 청크가 끊긴 문항이 있습니다: {no_gold}. "
                         "`python -m app.eval_set load --file ...` 로 다시 적재해주세요.")
    if not rows:
        raise SystemExit(f"봇 {bot_id} 에 활성 평가 질문이 없습니다. 먼저 문제 파일을 적재해주세요.")

    out: list[dict] = []
    for i, (qid, question, gold, _active) in enumerate(rows, 1):
        r: dict = {"qid": qid, "question": question, "ranks": {}}
        qvec = retriever.embed_one(question)
        allrows = _all_distances(bot_id, qvec)
        dist = {cid: float(d) for cid, d in allrows}
        d1 = float(allrows[0][1])
        if s.answerable_max_distance is not None and d1 > s.answerable_max_distance:
            r["status"] = "gate"
        elif gold not in dist or dist[gold] > s.max_distance:
            r["status"] = "cut"
        else:
            cand, _, _ = _candidates(bot_id, question, qvec)
            sources = _cut(cand)
            ids = [x.chunk_id for x in sources]
            if gold not in ids:
                r["status"] = "outside"
            else:
                r["status"] = "fixable"
                contents = retriever.fetch_contents(ids)
                texts = [contents.get(x.chunk_id, x.preview) for x in sources]
                for variant in variants:
                    ranked = sources
                    if len(sources) > 1:  # 후보가 하나면 리랭커를 부르지 않는다(search() 와 같다)
                        resp = local_reranker.rerank(question, texts, variant=variant)
                        ranked = retriever._apply_order(sources, [it["id"] for it in resp["response"]])
                    r["ranks"][variant] = [x.chunk_id for x in ranked].index(gold) + 1
        out.append(r)
        print(f"  {i}/{len(rows)} 질문 {qid}: {r['status']} {r['ranks'] or ''}", flush=True)
    return out


def _print_compare(results: list[dict], variants: list[str], pairs: list[tuple[str, str]],
                   gate: str | None, top_k: int) -> None:
    print(f"\n시험 문제 {len(results)}개, top_k={top_k}")
    print(f"{'변형':<15} {'상위 5개 진입률':>14} {'고칠 수 있는 문제 기준':>20} {'정답 평균 순위':>14}")
    for v in variants:
        m = summarize(results, v, top_k)
        mean = f"{m['mean_rank']:.2f}" if m["mean_rank"] is not None else "-"
        print(f"{v:<15} {m['hit']:>3}/{m['n']:<3} {m['top_rate']:>6.3f}   "
              f"{m['hit']:>3}/{m['fixable']:<3} {m['fixable_rate']:>6.3f}       {mean:>8}")
    counts = summarize(results, variants[0], top_k)["status_counts"]
    print("\n따로 세는 문제(모든 변형에서 결과가 같다, 스펙 §5-4):")
    for status in STATUSES[1:]:
        print(f"  {counts[status]:>3}  {_STATUS_LABELS[status]}")

    for base, target in pairs:
        up, down = paired(results, base, target, top_k)
        p = sign_test_p(len(up), len(down))
        print(f"\n비교 {base} → {target}: 좋아짐 {len(up)}, 나빠짐 {len(down)}, "
              f"부호 검정 p={p:.4f} → {judge(len(up), len(down))}")
        # 나빠진 문제는 판정과 관계없이 전부 찍는다(스펙 §5-3 마지막 줄).
        for r in down:
            print(f"    나빠짐 [{r['qid']}] {r['ranks'][base]}위 → {r['ranks'][target]}위  {r['question']}")
        for r in up:
            print(f"    좋아짐 [{r['qid']}] {r['ranks'][base]}위 → {r['ranks'][target]}위  {r['question']}")

    if gate:
        room, n = gate_count(results, gate, top_k)
        ratio = room / n if n else 0.0
        verdict = "통과" if ratio >= GATE_MIN_RATIO else "통과하지 못함"
        print(f"\n관문({gate}): 고칠 수 있는데 5위 밖 {room}/{n} = {ratio:.3f} "
              f"(기준 {GATE_MIN_RATIO} 이상) → {verdict}")


def _write_compare(path: Path, bot_id: Id, variants: list[str], results: list[dict]) -> None:
    s = get_settings()
    payload = {
        "bot_id": bot_id,
        "measured_on": date.today().isoformat(),
        # 설정을 함께 적는다. 다른 설정으로 잰 결과와 이어 붙이지 않기 위해서다.
        "settings": {
            "answerable_max_distance": s.answerable_max_distance,
            "max_distance": s.max_distance,
            "top_k": s.top_k,
            "rerank_candidates": s.rerank_candidates,
            "hybrid_enabled": s.hybrid_enabled,
            "rerank_fusion": s.rerank_fusion,
        },
        "variants": variants,
        "results": results,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n{path} 에 썼습니다.")
```

- [ ] **Step 4: CLI 를 더한다**

`main()` 의 `parser.add_argument("--variants", ...)` 다음 줄에 더한다:

```python
    parser.add_argument("--compare", default=None, metavar="V1,V2",
                        help="활성 문항 전부를 이 로컬 변형들로 잰다(쉼표 구분). 예: local,local_ft")
    parser.add_argument("--pair", action="append", default=[], metavar="BASE:TARGET",
                        help="--compare 와 함께. 좋아짐, 나빠짐, 부호 검정을 낼 짝. 여러 번 줄 수 있다")
    parser.add_argument("--gate", default=None, metavar="VARIANT",
                        help="--compare 와 함께. 이 변형으로 학습 전 관문(4분의 1)을 판정한다")
    parser.add_argument("--out", default=None, metavar="PATH",
                        help="--compare 결과를 JSON 으로 쓴다(ai-service/ 기준 상대 경로)")
```

`args = parser.parse_args()` 바로 다음, `if args.scores is not None:` 앞에 더한다:

```python
    if args.compare:
        variants = [v.strip() for v in args.compare.split(",") if v.strip()]
        # "a:b" 를 (a, b) 로. split(":", 1) 은 처음 콜론에서 한 번만 자른다.
        pairs = [tuple(p.split(":", 1)) for p in args.pair]
        for pair in pairs:
            if len(pair) != 2 or pair[0] not in variants or pair[1] not in variants:
                raise SystemExit(f"--pair {':'.join(pair)} 의 두 변형이 --compare 목록에 있어야 합니다.")
        if args.gate and args.gate not in variants:
            raise SystemExit(f"--gate {args.gate} 가 --compare 목록에 없습니다.")
        results = measure_variants(args.bot_id, variants)
        _print_compare(results, variants, pairs, args.gate, get_settings().top_k)
        if args.out:
            out = Path(args.out)
            if not out.is_absolute():
                out = Path(__file__).resolve().parent.parent / out
            _write_compare(out, args.bot_id, variants, results)
        return
```

그리고 모듈 설명의 `실행:` 아래에 더한다:

```python
    cd ai-service && .venv/bin/python -m app.rank_trace --bot-id 3 --compare local --gate local
    cd ai-service && .venv/bin/python -m app.rank_trace --bot-id 3 \
        --compare local,local_int8,local_ft,local_ft_int8 \
        --pair local:local_ft --pair local_ft:local_ft_int8 --out testdata/finetune/compare_test.json
```

- [ ] **Step 5: 점검이 통과하는지 본다**

Run: `cd ai-service && .venv/bin/python -m app.rank_trace_check`
Expected: `5가지 전부 통과.`

- [ ] **Step 6: 봇 1번으로 비교 모드가 실제로 도는지 본다 (읽기만 한다)**

DB 와 로컬 모델 `local`, `local_int8` 이 있어야 한다(`docker compose up -d`).

Run: `cd ai-service && .venv/bin/python -m app.rank_trace --bot-id 1 --compare local,local_int8 --pair local:local_int8 --gate local`
Expected: 26문항 진행 줄, 변형별 표, 따로 세는 문제, `비교 local → local_int8: ...`, `관문(local): 고칠 수 있는데 5위 밖 1/26 = 0.038 ... → 통과하지 못함`. 스펙 §1-2 가 적은 "고칠 수 있으면서 5위 밖이 1개" 와 같으면 재현된 것이다. 다르면 멈추고 보고한다(설정이나 코퍼스가 그때와 다르다는 뜻이다).

- [ ] **Step 7: CI 등록, 커밋, PR 1**

`.github/workflows/ci.yml` 의 `python -m app.eval_set_io_check` 줄 아래에:

```yaml
          python -m app.rank_trace_check
```

```bash
git add ai-service/app/rank_trace.py ai-service/app/rank_trace_check.py .github/workflows/ci.yml
git commit -m "feat: rank_trace 에 여러 로컬 리랭커를 나란히 재는 비교 모드를 더한다"
cd ai-service && .venv/bin/python -m app.finetune_split_check && .venv/bin/python -m app.eval_set_io_check \
  && .venv/bin/python -m app.rank_trace_check && .venv/bin/python -m app.eval_set_check
git push -u origin feat/reranker-finetune-tools
gh pr create --title "feat: 리랭커 파인튜닝 실험의 도구 (분할 검사, eval_set --file, rank_trace 비교 모드)" \
  --body-file <스크래치>/pr1.md
```

PR 본문은 `.github/PULL_REQUEST_TEMPLATE.md` 를 채운다. "어떻게 해결했나요" 에 Step 5, Step 6 의 실제 출력을 붙인다. "한계 & 트레이드오프" 에 적을 것: 부호 검정은 동점을 버리므로 갈린 문제가 5개 이하면 결과와 관계없이 구별되지 않음이 나온다 / `twin_texts` 는 직접 연결된 쌍만 본다 / 낱말 검사는 다른 말로 부른 대상을 못 잡는다(스펙 §8 7번). CI 는 기다리지 않는다(사용자 규칙). **PR 1 이 머지될 때까지 태스크 4 를 시작하지 않는다.**

---

### Task 4: 봇 두 개를 만들고 문서를 올린다

**Files:** 없음(로컬 DB 만 바뀐다)

**Interfaces:**
- Produces: `TRAIN_BOT`(학습용 봇 번호), `TEST_BOT`(시험용 봇 번호). 이 뒤의 모든 태스크가 쓴다. 결과 문서와 PR 2 본문에 적는다.

- [ ] **Step 1: PR 2 워크트리를 만든다 (PR 1 머지 뒤)**

```bash
cd /Users/cheonjamin/projects/AllDap
git fetch origin
git worktree add ../AllDap-ft -b feat/reranker-finetune origin/main
cd ../AllDap-ft/ai-service
ln -s ../../AllDap/ai-service/.venv .venv
ln -s ../../AllDap/ai-service/models models
ls app/finetune_split_check.py   # PR 1 이 들어왔는지 확인
```

- [ ] **Step 2: 서비스 셋을 순서대로 띄운다**

```bash
cd ../AllDap-ft
docker compose up -d
(cd api && ./gradlew bootRun)                                    # 별도 터미널(또는 백그라운드)
(cd ai-service && .venv/bin/uvicorn app.main:app --port 8001)    # 별도 터미널(또는 백그라운드)
curl -s localhost:8080/actuator/health
```

Expected: `{"status":"UP"...}`. Spring 이 먼저 떠야 스키마가 있다(AGENTS.md Flyway 규칙 2).

- [ ] **Step 3: 계정과 봇 둘을 만든다**

```bash
TOKEN=$(curl -s -X POST localhost:8080/api/auth/signup -H 'Content-Type: application/json' \
  -d '{"email":"finetune@local.test","password":"finetune-local-1","name":"파인튜닝 실험"}' | jq -r .token)
# 이미 가입돼 있으면 signup 이 실패한다. 그때는 login 으로 받는다:
[ "$TOKEN" = "null" ] && TOKEN=$(curl -s -X POST localhost:8080/api/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"finetune@local.test","password":"finetune-local-1"}' | jq -r .token)
TRAIN_BOT=$(curl -s -X POST localhost:8080/api/bots -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"name":"파인튜닝 학습용"}' | jq -r .id)
TEST_BOT=$(curl -s -X POST localhost:8080/api/bots -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"name":"파인튜닝 시험용"}' | jq -r .id)
echo "TRAIN_BOT=$TRAIN_BOT TEST_BOT=$TEST_BOT"
```

Expected: 두 번호가 숫자로 나온다(아마 2, 3). `null` 이면 응답 본문을 `jq .` 로 찍어 오류 안내를 읽는다.

- [ ] **Step 4: 분할대로 문서를 올린다**

```bash
upload() {  # $1 = 봇 번호, $2 = train 또는 test
  for f in $(jq -r --arg s "$2" '.documents[] | select(.side==$s) | .file' ai-service/testdata/finetune/split.json); do
    curl -s -o /dev/null -w "%{http_code} $f\n" -X POST "localhost:8080/api/bots/$1/documents" \
      -H "Authorization: Bearer $TOKEN" -F "file=@ai-service/testdata/corpus/$f"
  done
}
upload "$TRAIN_BOT" train
upload "$TEST_BOT" test
```

Expected: 학습용 36줄, 시험용 20줄, 전부 `202`.

- [ ] **Step 5: 처리가 끝났고 청크 수가 맞는지 본다**

```bash
docker exec -i alldap-db psql -U alldap alldap -c \
  "SELECT bot_id, status, count(*) FROM documents WHERE bot_id IN ($TRAIN_BOT,$TEST_BOT) GROUP BY 1,2 ORDER BY 1,2;"
```

Expected: 두 봇 모두 `ready` 만 있고 36, 20. `pending` 이 있으면 몇십 초 뒤 다시 본다. `failed` 가 있으면 멈추고 보고한다.

```bash
cd ai-service && .venv/bin/python -c "
import json
from app.finetune_split_check import SPLIT_FILE, chunks_of
split = json.loads(SPLIT_FILE.read_text())
for side in ('train', 'test'):
    print(side, sum(len(chunks_of(d['file'])) for d in split['documents'] if d['side'] == side))
"
docker exec -i alldap-db psql -U alldap alldap -c \
  "SELECT bot_id, count(*) FROM chunks WHERE bot_id IN ($TRAIN_BOT,$TEST_BOT) GROUP BY 1 ORDER BY 1;"
```

Expected: 두 출력의 청크 수가 쪽마다 같다. 다르면 업로드 경로와 다시 자른 결과가 갈린 것이므로 멈추고 보고한다(문제 파일의 정답 본문 대조가 전부 틀어진다).

- [ ] **Step 6: 봇 번호를 기록한다**

`docs/superpowers/plans/2026-10-01-reranker-finetune.md`(이 문서) 맨 아래 "실행 기록" 절에 `학습용 봇 = N, 시험용 봇 = M, 청크 수 학습용 X, 시험용 Y (2026-..-..)` 한 줄을 적고 커밋한다.

```bash
git add docs/superpowers/plans/2026-10-01-reranker-finetune.md
git commit -m "docs: 파인튜닝 실험의 봇 번호와 청크 수를 기록한다"
```

---

### Task 5: 예비 시험 문제 약 30개를 쓰고 학습용 봇에 적재한다

**Files:**
- Create: `ai-service/testdata/finetune/holdout_questions.json`

**왜 학습 데이터보다 먼저인가:** 파인튜닝이 효과 없을 때 "학습 실패" 와 "일반화 실패" 를 가르려면, 예비 시험 문제의 정답 청크가 학습에 한 번도 쓰이지 않았어야 한다(스펙 §5-5). 나중에 쓰면 이미 학습에 쓰인 청크를 고를 수 있다.

- [ ] **Step 1: 출제 규칙을 확인한다**

예비 시험 문제는 아래를 전부 지킨다.
- 정답 문서는 학습용 문서다(`split.json` 의 `train`). `취업규칙.md`, `휴가규정.md` 는 정답 문서로 쓰지 않는다.
- 정답 청크에 쌍둥이 청크가 없다(`twins.json` 에 없는 청크). 감사 문서 §5 의 "쓸 수 있는 자리" 표가 출발점이다.
- `08_징계_및_고충처리.md` 의 4번 청크(직장 내 괴롭힘)를 정답으로 쓰지 않는다.
- 질문에 시험용 대상 낱말(파견, 연구직, 연구소, 해외지사, 지사, 자회사, 시간제, 재택근무 전담, 촉탁, 현장실습, 주재원)이 없다. "공지사항" 처럼 낱말 안에 "지사" 가 들어가는 말도 피한다.
- 대부분은 헷갈림 묶음을 겨냥한다: 질문에 학습용 대상(정규직, 계약직, 인턴, 생산직, 협력사 상주인력, 임원, 프로젝트계약직, 비상근 자문역 등)을 넣고, 같은 봇에 같은 주제를 다른 대상에 대해 규정한 문서가 있어야 한다.
- 질문이 묻는 대상은 정답 청크의 대상과 같다(인턴 규정을 수습 직원으로 묻지 않는다).
- 다섯 말투를 고르게 섞는다(각 6개 안팎).

- [ ] **Step 2: 정답 청크 본문을 뽑아 쓴다**

```bash
cd ai-service && .venv/bin/python -m app.finetune_split_check --show-chunks 51_생산공장_근무규정.md
```

출력의 `[번호] "..."` 에서 따옴표를 포함한 JSON 문자열을 그대로 `source_text` 에 붙인다. 파일 모양:

```json
{
  "corpus": "testdata/corpus",
  "chunking": {"chunk_size": 500, "chunk_overlap": 50, "chunk_split_headings": true},
  "questions": [
    {
      "id": "h1",
      "question": "생산직 수습 기간은 몇 개월인가요?",
      "ground_truth": "2개월입니다.",
      "source_doc": "51_생산공장_근무규정.md",
      "source_text": "<--show-chunks 출력의 JSON 문자열 그대로>",
      "active": true,
      "style": "polite"
    }
  ]
}
```

(위 질문은 모양을 보이는 예다. 실제로 쓸 때 `51` 의 그 청크가 쌍둥이 청크가 아닌지, 다른 학습용 문서가 다른 대상의 수습 기간을 적는지 확인한다.)

- [ ] **Step 3: 검사가 통과하는지 본다**

Run: `cd ai-service && .venv/bin/python -m app.finetune_split_check`
Expected: `✅ 4, 5, 7. holdout_questions.json` 그리고 `전부 통과.` 위반이 나오면 그 문제를 고치거나 버린다(분할은 고치지 않는다).

- [ ] **Step 4: 학습용 봇에 적재한다**

Run: `cd ai-service && .venv/bin/python -m app.eval_set load --bot-id $TRAIN_BOT --file testdata/finetune/holdout_questions.json`
Expected: `봇 N 에 30문항을 넣었습니다 (활성 30문항).` (`--replace` 를 쓰지 않는다. 새 봇이라 비어 있다)

- [ ] **Step 5: 커밋한다**

```bash
git add ai-service/testdata/finetune/holdout_questions.json
git commit -m "feat: 리랭커 파인튜닝의 예비 시험 문제를 더한다"
```

---

### Task 6: 시험 문제 60개 이상을 쓰고, 사용자 검토 뒤 시험용 봇에 적재한다

**Files:**
- Create: `ai-service/testdata/finetune/test_questions.json`

- [ ] **Step 1: 출제 규칙을 확인한다 (스펙 §4-4)**

- 정답 문서는 시험용 문서다. id 는 `t1`, `t2`, ... 로 매긴다.
- 대부분(3분의 2 이상)은 헷갈림 묶음을 겨냥한다: 질문에 시험용 대상(파견, 연구직, 해외지사, 자회사, 시간제, 재택근무 전담, 촉탁, 현장실습, 주재원)이 들어가고, 시험용 봇 안에 같은 주제를 다른 대상에 대해 규정한 문서가 있다.
- 시험용 봇 안의 문서만으로 답할 수 있다. `04_파견` 의 `SEC-002` 규정은 묻지 않는다. `50_부설연구소` 는 본문에 실제로 적힌 주제만 묻는다. 본사 직원 식대처럼 답이 학습용 문서에만 있는 것은 묻지 않는다(시험용 봇 안의 식대 값은 `56` 월 5만원, `57` 미지급, `04` 본인 부담뿐이다).
- 주재원의 재택, 노트북, 결혼휴가 질문은 정답이 `42_해외주재원` 이 아니라 `52_해외지사` 다.
- `34_직장내괴롭힘_예방.md` 의 5번 청크(불이익 금지)를 정답으로 쓰지 않는다.
- 질문이 묻는 대상은 정답 청크의 대상과 같다.
- 다섯 말투를 고르게 섞는다(각 12개 안팎). 형식은 태스크 5 Step 2 와 같다.

- [ ] **Step 2: 검사가 통과하는지 본다**

Run: `cd ai-service && .venv/bin/python -m app.finetune_split_check`
Expected: `✅ 4, 5, 7. test_questions.json` 그리고 `전부 통과.`

- [ ] **Step 3: 사용자 검토용 목록을 만든다**

```bash
cd ai-service && .venv/bin/python -c "
import json
qs = json.load(open('testdata/finetune/test_questions.json'))['questions']
print('| id | 말투 | 정답 문서 | 질문 | 정답 |'); print('|---|---|---|---|---|')
for q in qs:
    print(f\"| {q['id']} | {q['style']} | {q['source_doc'][:12]} | {q['question']} | {q['ground_truth']} |\")
"
```

이 표를 사용자에게 보이고 **멈춘다.** 사용자가 고치라고 한 문제는 고치거나 버리고 Step 2 를 다시 돈다. 사용자가 확정하면 다음으로 간다(스펙 §4-4 규칙 6).

- [ ] **Step 4: 시험용 봇에 적재하고 커밋한다**

Run: `cd ai-service && .venv/bin/python -m app.eval_set load --bot-id $TEST_BOT --file testdata/finetune/test_questions.json`
Expected: `봇 M 에 N문항을 넣었습니다 (활성 N문항).` (N ≥ 60)

```bash
git add ai-service/testdata/finetune/test_questions.json
git commit -m "feat: 리랭커 파인튜닝의 시험 문제를 더한다 (사용자 검토 완료)"
```

---

### Task 7: 학습 전 관문을 잰다

**Files:**
- Create: `ai-service/testdata/finetune/gate_B.json`

- [ ] **Step 1: B 로 시험 문제를 잰다**

Run:
```bash
cd ai-service && .venv/bin/python -m app.rank_trace --bot-id $TEST_BOT --compare local --gate local \
  --out testdata/finetune/gate_B.json
```

Expected: 마지막 줄 `관문(local): 고칠 수 있는데 5위 밖 k/N = r (기준 0.25 이상) → 통과` 또는 `→ 통과하지 못함`.

- [ ] **Step 2: 판정에 따라 갈린다**

- **통과**: 커밋하고 태스크 8 로 간다.
- **통과하지 못함**: 학습하지 않는다. 결과(따로 세는 문제의 개수, 5위 안인 문제 수)를 사용자에게 보고하고 **멈춘다.** 사용자와 정한 뒤 태스크 6 으로 돌아가 시험 문제를 다시 쓴다(스펙 §3-1 4단계). 이미 시험용 봇에 적재한 문제를 바꾸려면 `eval_set load --bot-id $TEST_BOT --replace --file ...` 를 쓴다(이 봇에는 평가 결과가 없으므로 CASCADE 로 지워지는 것이 없다. 실행 전에 `count_existing` 출력으로 확인한다).

```bash
git add ai-service/testdata/finetune/gate_B.json
git commit -m "feat: 리랭커 파인튜닝의 학습 전 관문을 잰 결과를 남긴다"
```

---

### Task 8: 학습 데이터 생성 도구 `finetune_data.py`

**Files:**
- Create: `ai-service/app/finetune_data.py`
- Create: `ai-service/app/finetune_data_check.py`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `finetune_split_check.twin_texts`, `protected_texts`, `STYLES` (태스크 1), `eval_set.resolve_chunk` (태스크 2), `rank_trace._all_distances`, `_candidates`, `_cut`, `retriever.embed_one`, `retriever.fetch_contents`
- Produces:
  - `select_negatives(cut_texts: list[str], gold: str, excluded: set[str], k: int = 7) -> list[str]`
  - `drop_reason(gate_pass: bool, gold_cut_pass: bool, gold_in_cut: bool, n_negatives: int) -> str | None`
  - `train_pairs.jsonl` 한 줄 모양: `{"id": str, "query": str, "positive": str, "negatives": [str, ...], "style": str, "source_doc": str}` (태스크 10 노트북이 읽는다)

- [ ] **Step 1: 실패하는 점검을 쓴다**

`ai-service/app/finetune_data_check.py`:

```python
"""finetune_data 의 순수 함수 점검. DB 도 외부 API 도 쓰지 않는다. CI 에서 돈다.

실행:  cd ai-service && .venv/bin/python -m app.finetune_data_check
"""
from __future__ import annotations

from .finetune_data import drop_reason, select_negatives


def check_negatives_skip_gold_excluded_and_duplicates() -> None:
    cut = ["정답", "오답1", "쌍둥이", "오답1", "시험정답", "오답2"]
    got = select_negatives(cut, gold="정답", excluded={"쌍둥이", "시험정답"})
    assert got == ["오답1", "오답2"], got


def check_negatives_keep_retrieval_order_and_limit() -> None:
    cut = [f"오답{i}" for i in range(10)]
    assert select_negatives(cut, gold="정답", excluded=set()) == cut[:7]
    assert select_negatives(cut, gold="정답", excluded=set(), k=3) == cut[:3]


def check_drop_reason_follows_rank_trace_order() -> None:
    # 거리 게이트 → 거리 컷 → 후보 밖 → 오답 0개 순서로 본다(rank_trace.trace 의 판정 순서와 같다).
    assert drop_reason(False, False, False, 0) == "gate"
    assert drop_reason(True, False, False, 0) == "cut"
    assert drop_reason(True, True, False, 3) == "outside"
    assert drop_reason(True, True, True, 0) == "no_negatives"
    assert drop_reason(True, True, True, 1) is None


def main() -> None:
    checks = [
        check_negatives_skip_gold_excluded_and_duplicates,
        check_negatives_keep_retrieval_order_and_limit,
        check_drop_reason_follows_rank_trace_order,
    ]
    for fn in checks:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(checks)}가지 전부 통과.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 실패하는지 본다**

Run: `cd ai-service && .venv/bin/python -m app.finetune_data_check`
Expected: `ModuleNotFoundError: No module named 'app.finetune_data'`

- [ ] **Step 3: `finetune_data.py` 를 쓴다**

```python
"""연습 문제로 리랭커 학습 데이터(train_pairs.jsonl)를 만든다.

실행:
    cd ai-service && .venv/bin/python -m app.finetune_data --bot-id <학습용 봇 번호>

설계: docs/superpowers/specs/2026-10-01-reranker-finetune-design.md §5-1

하는 일
─────────────────────────────────────────────────────────────────────────────
연습 문제마다 학습용 봇에서 실제 검색 경로(벡터 검색, 하이브리드, 거리 게이트, 거리 컷)를
태워 리랭커 후보를 얻는다. 그중 정답 청크를 뺀 상위 청크(리랭커에 들어가기 직전 순서)
최대 7개를 오답 예시로 쓴다.

오답 예시를 검색 결과에서 뽑는 이유: 리랭커가 실제로 틀리는 경우는 검색이 가져온 비슷한
청크를 정답보다 위에 둘 때다. 무작위 청크를 오답으로 주면 구분이 너무 쉬워 배울 것이 없다.

오답 예시에서 빼는 것
  - 정답 청크의 쌍둥이 청크: 같은 내용을 오답으로 가르치면 모순된 신호가 된다
  - 시험, 예비 시험 문제의 정답 청크와 그 쌍둥이 청크: 학습에 나오면 비교가 무의미해진다

버리는 연습 문제 (실제 검색에서 리랭커가 그 정답을 볼 일이 없거나, 배울 재료가 없다)
  gate          거리 게이트에 걸린다
  cut           정답 청크가 거리 컷에 잘린다
  outside       정답 청크가 리랭커 후보 밖이다
  no_negatives  오답 예시가 0개다

학습 입력은 추론 때와 같은 모양이다: 청크 본문 전체만 쓰고 파일명이나 제목을 덧붙이지 않는다.
길이 제한(512 토큰)은 노트북이 local_reranker.MAX_LENGTH 와 같은 값으로 건다.

CI 에서 돌지 않는다(진짜 DB 와 임베딩이 필요하다). 순수 함수는 finetune_data_check 가 본다.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from .db import close_pool
from .schemas import Id

ROOT = Path(__file__).resolve().parent.parent
FT_DIR = ROOT / "testdata" / "finetune"
TRAIN_FILE = FT_DIR / "train_questions.json"
TEST_FILE = FT_DIR / "test_questions.json"
HOLDOUT_FILE = FT_DIR / "holdout_questions.json"
TWINS_FILE = FT_DIR / "twins.json"
OUT_FILE = FT_DIR / "train_pairs.jsonl"

MAX_NEGATIVES = 7  # 스펙 §5-1, §6-2 "질문당 오답 예시 최대 7개"
_REASON_LABELS = {
    "gate": "거리 게이트에 걸림",
    "cut": "정답 청크가 거리 컷에 잘림",
    "outside": "정답 청크가 리랭커 후보 밖",
    "no_negatives": "오답 예시 0개",
}


def select_negatives(cut_texts: list[str], gold: str, excluded: set[str],
                     k: int = MAX_NEGATIVES) -> list[str]:
    """리랭커 후보 순서대로 오답 예시를 고른다. 정답, 제외 목록, 이미 고른 본문은 건너뛴다.

    같은 본문을 두 번 넣지 않는 이유: 같은 문장을 가진 청크가 두 문서에 있으면 후보에
    두 번 나온다. 그대로 두면 한 오답에 두 배 무게가 실린다.
    """
    out: list[str] = []
    for text in cut_texts:
        if text == gold or text in excluded or text in out:
            continue
        out.append(text)
        if len(out) == k:
            break
    return out


def drop_reason(gate_pass: bool, gold_cut_pass: bool, gold_in_cut: bool,
                n_negatives: int) -> str | None:
    """버릴 이유. 버리지 않으면 None. 판정 순서는 rank_trace.trace 와 같다."""
    if not gate_pass:
        return "gate"
    if not gold_cut_pass:
        return "cut"
    if not gold_in_cut:
        return "outside"
    if n_negatives == 0:
        return "no_negatives"
    return None


def _read(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"{path} 이 없습니다. 계획의 순서대로 먼저 만들어주세요.")
    return json.loads(path.read_text(encoding="utf-8"))


def build(bot_id: Id) -> int:
    from . import retriever  # 늦은 import: 이 모듈을 열기만 해도 임베딩 클라이언트가 뜨면 안 된다
    from .config import get_settings
    from .eval_set import resolve_chunk
    from .finetune_split_check import protected_texts, twin_texts
    from .rank_trace import _all_distances, _candidates, _cut

    s = get_settings()
    train = _read(TRAIN_FILE)["questions"]
    twins = _read(TWINS_FILE)
    # 예비 시험 문제가 먼저 있어야 한다(스펙 §5-5). 없이 만들면 그 정답 청크가 오답 예시로 섞일 수 있다.
    payloads = {"holdout": _read(HOLDOUT_FILE)}
    if TEST_FILE.exists():
        payloads["test"] = _read(TEST_FILE)
    protected = protected_texts(payloads, twins)

    # 1. 정답 청크를 전부 먼저 확정한다. 하나라도 못 찾으면 아무것도 쓰지 않는다
    #    (절반만 만든 학습 데이터로 학습하면 무엇을 학습했는지 알 수 없다).
    gold_ids: dict[str, Id] = {}
    errors: list[str] = []
    for q in train:
        ids = resolve_chunk(bot_id, q["source_text"])
        if len(ids) == 1:
            gold_ids[q["id"]] = ids[0]
        else:
            errors.append(f"[{q['id']}] 본문이 같은 청크가 봇 {bot_id} 에 {len(ids)}개입니다 "
                          f"({q['source_doc']}). 학습용 봇이 맞는지, 문서를 두 번 올리지 않았는지 확인해주세요.")
    if errors:
        print(f"정답 청크를 확정하지 못한 연습 문제가 {len(errors)}개라 아무것도 쓰지 않았습니다.")
        for e in errors:
            print(f"  {e}")
        return 1

    # 2. 문제마다 검색 경로를 태운다.
    lines: list[dict] = []
    drops: Counter[str] = Counter()  # Counter 는 없는 키를 0 으로 세는 딕셔너리다
    few = 0
    for i, q in enumerate(train, 1):
        gold = gold_ids[q["id"]]
        qvec = retriever.embed_one(q["question"])
        allrows = _all_distances(bot_id, qvec)
        dist = {cid: float(d) for cid, d in allrows}
        gate_pass = (s.answerable_max_distance is None
                     or float(allrows[0][1]) <= s.answerable_max_distance)
        gold_cut_pass = gold in dist and dist[gold] <= s.max_distance
        sources = []
        if gate_pass:
            cand, _, _ = _candidates(bot_id, q["question"], qvec)
            sources = _cut(cand)  # 리랭커에 들어가기 직전 순서(벡터 또는 하이브리드 RRF)
        ids = [x.chunk_id for x in sources]
        contents = retriever.fetch_contents(ids) if ids else {}
        texts = [contents[cid] for cid in ids]  # preview(앞 200자)가 아니라 본문 전체
        excluded = protected | twin_texts(q["source_text"], twins)
        negatives = select_negatives(texts, q["source_text"], excluded)

        reason = drop_reason(gate_pass, gold_cut_pass, gold in ids, len(negatives))
        if reason:
            drops[reason] += 1
            print(f"  {i}/{len(train)} [{q['id']}] 버림: {_REASON_LABELS[reason]}", flush=True)
            continue
        if len(negatives) <= 4:
            few += 1
        lines.append({
            "id": q["id"],
            "query": q["question"],
            "positive": q["source_text"],
            "negatives": negatives,
            "style": q["style"],
            "source_doc": q["source_doc"],
        })
        print(f"  {i}/{len(train)} [{q['id']}] 오답 예시 {len(negatives)}개", flush=True)

    # 3. 쓴다. 한 줄에 문제 하나(JSON Lines). 줄 순서는 연습 문제 파일 순서 그대로라
    #    같은 입력이면 같은 파일(같은 해시)이 나온다.
    OUT_FILE.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines),
                        encoding="utf-8")
    print(f"\n{OUT_FILE} 에 {len(lines)}문제를 썼습니다 (연습 문제 {len(train)}개 중).")
    print(f"버린 문제 {sum(drops.values())}개:")
    for key, label in _REASON_LABELS.items():
        print(f"  {drops[key]:>3}  {label}")
    # 오답이 4개 이하면 정답이 꼴찌여도 5위 안이다. 검증 성적의 상위 5개 진입률이 그만큼 무뎌진다(스펙 §5-1).
    print(f"오답 예시가 1~4개인 문제: {few}개")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="연습 문제로 리랭커 학습 데이터를 만든다")
    parser.add_argument("--bot-id", type=int, required=True, help="학습용 봇 번호")
    args = parser.parse_args()
    return build(args.bot_id)


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        close_pool()
```

- [ ] **Step 4: 점검이 통과하는지 본다**

Run: `cd ai-service && .venv/bin/python -m app.finetune_data_check`
Expected: `3가지 전부 통과.`

- [ ] **Step 5: CI 등록과 커밋**

`.github/workflows/ci.yml` 의 `python -m app.rank_trace_check` 줄 아래에:

```yaml
          python -m app.finetune_data_check
```

```bash
git add ai-service/app/finetune_data.py ai-service/app/finetune_data_check.py .github/workflows/ci.yml
git commit -m "feat: 연습 문제로 리랭커 학습 데이터를 만드는 도구를 더한다"
```

---

### Task 9: 연습 문제 300~400개를 쓰고 학습 데이터를 만든다

**Files:**
- Create: `ai-service/testdata/finetune/train_questions.json`
- Create: `ai-service/testdata/finetune/train_pairs.jsonl`

- [ ] **Step 1: 출제 규칙을 확인한다**

예비 시험 문제(태스크 5 Step 1)의 규칙과 같고, 아래만 다르다.
- 쌍둥이 청크가 있는 청크도 정답으로 쓸 수 있다(예비 시험 문제만 금지). 단 예비 시험 문제의 정답 청크와 같은 청크는 쓰지 않는다(`check_pairs` 가 잡는다).
- id 는 `p1`, `p2`, ... 로 매긴다.
- 학습용 문서 36개(정답 문서 금지 2개를 빼면 34개)에 고르게 나눈다. 문서마다 정답이 될 수 있는 청크 수에 비례해 문서당 6~15문제.
- 3분의 2 이상은 헷갈림 묶음을 겨냥한다(대상을 질문에 넣는다). 나머지는 일반 문서의 주제 질문이다.
- 다섯 말투를 고르게 섞는다.

작업이 크므로 문서 묶음별로 나눠 쓰고 한 파일로 합친다(예: 본사 덩어리, 대상 문서 9개, 일반 문서 16개). 합칠 때 id 를 `p1` 부터 다시 매긴다.

- [ ] **Step 2: 검사가 통과하는지 본다**

Run: `cd ai-service && .venv/bin/python -m app.finetune_split_check`
Expected: `✅ 4, 5, 7. train_questions.json` 그리고 `전부 통과.`

- [ ] **Step 3: 학습 데이터를 만든다**

Run: `cd ai-service && .venv/bin/python -m app.finetune_data --bot-id $TRAIN_BOT`
Expected: 문제마다 한 줄, 마지막에 `... 에 K문제를 썼습니다 (연습 문제 N개 중).`, 버린 이유별 개수, `오답 예시가 1~4개인 문제: m개`. 이 출력 전체를 결과 문서에 옮길 수 있게 스크래치에 저장한다(`| tee <스크래치>/finetune_data.log`).

K 가 250 보다 적으면 멈추고 보고한다(버린 이유를 보고 연습 문제를 더 쓸지 정한다).

- [ ] **Step 4: 누출 검사를 다시 돈다**

Run: `cd ai-service && .venv/bin/python -m app.finetune_split_check`
Expected: `✅ 2. 시험, 예비 시험 정답이 학습 데이터에 없다`, `⏭  노트북이 아직 없어 6번 검사를 건너뜁니다`, `전부 통과.`

- [ ] **Step 5: 커밋한다**

```bash
git add ai-service/testdata/finetune/train_questions.json ai-service/testdata/finetune/train_pairs.jsonl
git commit -m "feat: 리랭커 파인튜닝의 연습 문제와 학습 데이터를 더한다"
```

---

### Task 10: 코랩 학습 노트북

**Files:**
- Create: `ai-service/notebooks/train_reranker.ipynb`

**Interfaces:**
- Consumes: `train_pairs.jsonl` (태스크 9)
- Produces: zip `bge-reranker-base-ft.zip`. 풀면 `bge-reranker-base-ft/` 디렉터리 하나가 나오고, 그 안에 Hugging Face `save_pretrained` 형식(`config.json`, 가중치, 토크나이저 파일)과 `training_log.json` 이 있다. 태스크 12 의 내보내기가 `ai-service/models/bge-reranker-base-ft/` 를 원본 경로로 읽는다.

- [ ] **Step 1: 노트북을 만드는 스크립트를 쓴다 (스크래치, 저장소에 넣지 않는다)**

`<스크래치>/build_notebook.py`. 해시는 실행 때 `train_pairs.jsonl` 에서 계산해 넣는다:

```python
"""train_reranker.ipynb 를 만든다. ai-service/ 에서 실행한다."""
import hashlib
import json
from pathlib import Path

SHA = hashlib.sha256(Path("testdata/finetune/train_pairs.jsonl").read_bytes()).hexdigest()

MD, CODE = "markdown", "code"
cells = [
(MD, """# 리랭커 파인튜닝 (bge-reranker-base)

설계: `docs/superpowers/specs/2026-10-01-reranker-finetune-design.md` §6

**사용자가 할 일**
1. 런타임 → 런타임 유형 변경 → **T4 GPU**
2. 런타임 → **모두 실행**
3. 셋째 칸이 띄우는 파일 선택 창에서 `ai-service/testdata/finetune/train_pairs.jsonl` 을 고른다
4. 마지막 칸이 내려주는 `bge-reranker-base-ft.zip` 을 저장하고 위치를 알려준다

세션이 끊기면 모두 실행을 다시 하면 된다."""),
(MD, """## 1. 라이브러리 설치

버전을 고정한다. 코랩의 torch 는 기본 이미지의 GPU 빌드를 그대로 쓴다.
transformers 는 우리 내보내기 환경(`requirements-lab.txt`)과 같은 버전이다."""),
(CODE, """!pip install -q sentence-transformers==3.4.1 transformers==4.57.6"""),
(MD, """## 2. 설정

결과를 보기 전에 정한 값이다. 에폭은 1, 2, 3 중 **검증용 문제의 정답 청크 평균 순위가 가장 낮은 것**을 고른다.
시험 문제는 이 노트북에 없다. 시험 문제 성적으로 설정을 고르지 않기 위해서다(스펙 §6-2)."""),
(CODE, f'''EXPECTED_SHA256 = "{SHA}"
BASE_MODEL = "BAAI/bge-reranker-base"
BASE_REVISION = "2cfc18c9415c912f9d8155881c133215df768a70"  # app/export_reranker.py 의 REVISION 과 같다
SEED = 42
LR = 2e-5
BATCH = 16
MAX_EPOCHS = 3
VAL_RATIO = 0.2
MAX_LENGTH = 512   # app/local_reranker.py 의 MAX_LENGTH 와 같다. 학습과 추론의 입력 모양을 맞춘다
SMOKE = False      # 로컬 연기 시험에서만 True 로 바꾼다(문제 몇 개로 끝까지 도는지만 본다)'''),
(MD, """## 3. 학습 데이터 올리기와 해시 확인

다른 파일로 학습하는 실수를 막으려고, 파일의 SHA-256 이 위의 값과 다르면 학습 전에 멈춘다."""),
(CODE, '''import hashlib, json, os, sys

IN_COLAB = "google.colab" in sys.modules
if IN_COLAB:
    from google.colab import files
    uploaded = files.upload()
    # 코랩은 같은 이름이 있으면 "train_pairs (1).jsonl" 처럼 이름을 바꾼다. 파일 하나만 받는다.
    assert len(uploaded) == 1, f"파일을 하나만 올려주세요. 지금 {list(uploaded)}"
    raw = next(iter(uploaded.values()))
else:
    raw = open(os.environ.get("TRAIN_PAIRS", "../testdata/finetune/train_pairs.jsonl"), "rb").read()

digest = hashlib.sha256(raw).hexdigest()
if digest != EXPECTED_SHA256 and not SMOKE:
    raise SystemExit(f"train_pairs.jsonl 의 해시가 다릅니다({digest[:12]}...). 저장소의 그 파일을 올렸는지 확인해주세요.")
rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
print(f"문제 {len(rows)}개, 해시 {digest[:12]}...")'''),
(MD, """## 4. 학습용과 검증용 나누기 (문제 단위 80:20, 씨앗 고정)"""),
(CODE, '''import random

order = list(range(len(rows)))
random.Random(SEED).shuffle(order)
n_val = round(len(rows) * VAL_RATIO)
val = [rows[i] for i in sorted(order[:n_val])]
train = [rows[i] for i in sorted(order[n_val:])]
if SMOKE:
    train, val = train[:8], val[:4]
print(f"학습용 {len(train)}문제, 검증용 {len(val)}문제")'''),
(MD, """## 5. 원본 모델 불러오기

GPU 연산은 같은 씨앗에서도 결과가 조금 다를 수 있다. 그래서 씨앗을 고정해도 완전히 재현된다고 말하지 않는다."""),
(CODE, '''import numpy as np
import torch
from sentence_transformers import CrossEncoder, InputExample
from torch.utils.data import DataLoader

random.seed(SEED); np.random.seed(SEED); torch.manual_seed(SEED); torch.cuda.manual_seed_all(SEED)
# num_labels=1 이면 출력이 점수 하나이고, 기본 손실이 이진 교차 엔트로피(BCE)다(정답 1, 오답 0).
model = CrossEncoder(BASE_MODEL, num_labels=1, max_length=MAX_LENGTH, revision=BASE_REVISION)'''),
(MD, """## 6. 학습 예시 만들기

문제마다 (질문, 정답 청크) 를 1 로, (질문, 오답 예시) 를 0 으로 둔다. 청크 본문만 쓴다(파일명, 제목을 덧붙이지 않는다)."""),
(CODE, '''examples = [InputExample(texts=[r["query"], r["positive"]], label=1.0) for r in train]
examples += [InputExample(texts=[r["query"], neg], label=0.0) for r in train for neg in r["negatives"]]
loader = DataLoader(examples, shuffle=True, batch_size=BATCH,
                    generator=torch.Generator().manual_seed(SEED))
print(f"학습 예시 {len(examples)}쌍")'''),
(MD, """## 7. 검증 성적

검증용 문제마다 정답 청크와 오답 예시를 모델로 줄 세워 정답 청크의 순위를 낸다. 동점이면 정답을 위로 친다.
상위 5개 진입률은 참고로만 적는다. 오답이 4개 이하인 문제는 정답이 꼴찌여도 5위 안이라 차이를 잘 드러내지 못한다."""),
(CODE, '''def val_scores(model, rows):
    ranks = []
    for r in rows:
        cands = [r["positive"], *r["negatives"]]
        scores = model.predict([[r["query"], c] for c in cands], batch_size=32, show_progress_bar=False)
        ranks.append(1 + sum(1 for s in scores[1:] if s > scores[0]))
    return {"mean_rank": sum(ranks) / len(ranks), "top5": sum(1 for x in ranks if x <= 5) / len(ranks)}

log = {"epoch0": val_scores(model, val), "epochs": []}
print("학습 전", log["epoch0"])'''),
(MD, """## 8. 학습 (에폭마다 저장하고 검증)

`fit` 을 에폭 하나씩 세 번 부른다. 학습률 스케줄은 고정(constantlr)이라 부를 때마다 처음으로 돌아가는 일이 없다."""),
(CODE, '''import time

started = time.time()
for epoch in range(1, MAX_EPOCHS + 1):
    model.fit(train_dataloader=loader, epochs=1, warmup_steps=0, scheduler="constantlr",
              optimizer_params={"lr": LR}, show_progress_bar=True)
    m = val_scores(model, val) | {"epoch": epoch}
    log["epochs"].append(m)
    model.save(f"ckpt/epoch{epoch}")
    print(m)
log["seconds"] = round(time.time() - started)
# 평균 순위가 가장 낮은 에폭. 같으면 이른 에폭(덜 학습한 쪽)을 고른다.
best = min(log["epochs"], key=lambda m: (m["mean_rank"], m["epoch"]))
print("고른 에폭:", best)'''),
(MD, """## 9. 결과 묶기와 내려받기"""),
(CODE, '''import platform, shutil
import sentence_transformers, transformers

out = "bge-reranker-base-ft"
shutil.rmtree(out, ignore_errors=True)
shutil.copytree(f"ckpt/epoch{best['epoch']}", out)
log.update({
    "best_epoch": best["epoch"], "selection": "검증용 문제의 정답 청크 평균 순위 최소",
    "base_model": BASE_MODEL, "base_revision": BASE_REVISION, "seed": SEED, "lr": LR, "batch": BATCH,
    "max_length": MAX_LENGTH, "val_ratio": VAL_RATIO, "n_train": len(train), "n_val": len(val),
    "train_pairs_sha256": digest, "smoke": SMOKE,
    "versions": {"python": platform.python_version(), "torch": torch.__version__,
                 "transformers": transformers.__version__,
                 "sentence_transformers": sentence_transformers.__version__},
    "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu",
    "note": "GPU 연산은 같은 입력과 씨앗에서도 결과가 조금 다를 수 있다",
})
with open(f"{out}/training_log.json", "w", encoding="utf-8") as f:
    json.dump(log, f, ensure_ascii=False, indent=2)
shutil.make_archive(out, "zip", ".", out)  # zip 을 풀면 bge-reranker-base-ft/ 디렉터리 하나가 나온다
print(json.dumps(log, ensure_ascii=False, indent=2))
if IN_COLAB:
    files.download(f"{out}.zip")'''),
]


def cell(kind: str, text: str) -> dict:
    src = text.splitlines(keepends=True)
    if kind == MD:
        return {"cell_type": "markdown", "metadata": {}, "source": src}
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": src}


nb = {
    "nbformat": 4, "nbformat_minor": 5,
    "metadata": {"accelerator": "GPU", "colab": {"provenance": []},
                 "kernelspec": {"name": "python3", "display_name": "Python 3"},
                 "language_info": {"name": "python"}},
    "cells": [cell(k, t) for k, t in cells],
}
Path("notebooks").mkdir(exist_ok=True)
Path("notebooks/train_reranker.ipynb").write_text(
    json.dumps(nb, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print("notebooks/train_reranker.ipynb 를 썼다. 해시", SHA[:12])
```

Run: `cd ai-service && .venv/bin/python <스크래치>/build_notebook.py`
Expected: `notebooks/train_reranker.ipynb 를 썼다. 해시 ...`

- [ ] **Step 2: 해시 검사가 통과하는지 본다**

Run: `cd ai-service && .venv/bin/python -m app.finetune_split_check`
Expected: `✅ 6. 노트북의 해시가 학습 데이터와 같다` 그리고 `전부 통과.`

- [ ] **Step 3: 로컬에서 연기 시험을 한다 (문제 몇 개로 끝까지 도는지만)**

코랩에서 처음 실패하면 사용자가 다시 올려야 한다. 그래서 같은 코드를 로컬에서 먼저 돌린다. `sentence-transformers` 는 이 확인에만 쓰고 `requirements` 파일에 넣지 않는다.

`.venv` 는 메인 폴더와 공유하는 실험 환경이다. `sentence-transformers` 를 깔면 `scikit-learn` 같은 의존성이 함께 들어온다. `transformers` 는 3.4.1 의 요구 범위(5 미만) 안이라 4.57.6 그대로 남는다. 설치 뒤 `.venv/bin/pip show transformers` 로 확인한다.

```bash
cd ai-service
.venv/bin/pip install -q sentence-transformers==3.4.1
.venv/bin/pip show transformers | grep Version     # 4.57.6 이어야 한다
SMOKE_DIR=$(mktemp -d)                             # 산출물(ckpt, zip)이 저장소 밖에 떨어지게 한다
TRAIN_PAIRS="$PWD/testdata/finetune/train_pairs.jsonl" SMOKE_DIR="$SMOKE_DIR" .venv/bin/python - <<'EOF'
import json, os, re
from pathlib import Path

nb = json.loads(Path("notebooks/train_reranker.ipynb").read_text(encoding="utf-8"))
code = "\n".join("".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code")
code = "\n".join(l for l in code.splitlines() if not l.startswith("!"))  # pip 줄은 뺀다
code = re.sub(r"^SMOKE = False", "SMOKE = True", code, flags=re.M)
code = re.sub(r"^MAX_EPOCHS = 3", "MAX_EPOCHS = 1", code, flags=re.M)
os.chdir(os.environ["SMOKE_DIR"])
# 노트북의 셋째 코드 칸은 코랩이 아니면 환경변수 TRAIN_PAIRS 의 파일을 읽는다.
exec(compile(code, "train_reranker", "exec"), {"__name__": "__main__"})
EOF
ls "$SMOKE_DIR/bge-reranker-base-ft"
```

Expected: 학습 전과 에폭 1 의 검증 성적이 찍히고, 마지막 `ls` 에 `config.json`, `model.safetensors`, `tokenizer.json`, `tokenizer_config.json`, `training_log.json` 이 있다. 실패하면 노트북 코드를 고치고 Step 1 부터 다시 한다(라이브러리 API 가 이 계획과 다르면 실제로 깔린 버전의 API 에 맞추고, 무엇을 바꿨는지 결과 문서에 적는다). 확인 뒤 `rm -rf "$SMOKE_DIR"` 로 지운다.

- [ ] **Step 4: 커밋한다**

```bash
git add ai-service/notebooks/train_reranker.ipynb
git commit -m "feat: 리랭커 파인튜닝 코랩 노트북을 더한다"
```

---

### Task 11: 사용자가 코랩에서 학습한다

**Files:** 없음

- [ ] **Step 1: 사용자에게 넘기고 멈춘다**

사용자에게 아래를 그대로 전한다.

1. 코랩에서 파일 → 노트북 업로드 → `ai-service/notebooks/train_reranker.ipynb`
2. 런타임 → 런타임 유형 변경 → T4 GPU
3. 런타임 → 모두 실행
4. 셋째 코드 칸의 파일 선택 창에서 `ai-service/testdata/finetune/train_pairs.jsonl` 을 고른다
5. 마지막 칸이 내려주는 `bge-reranker-base-ft.zip` 을 저장하고 위치를 알려준다

- [ ] **Step 2: zip 을 풀고 학습 기록을 확인한다**

```bash
cd ai-service && unzip -o <사용자가 알려준 경로>/bge-reranker-base-ft.zip -d models/
cat models/bge-reranker-base-ft/training_log.json
```

Expected: `smoke: false`, `train_pairs_sha256` 이 저장소 파일의 해시와 같다(`shasum -a 256 testdata/finetune/train_pairs.jsonl`), `best_epoch` 가 1~3, `epochs` 에 세 에폭의 검증 성적. 학습 기록 전체를 결과 문서에 옮긴다(태스크 16). `models/` 는 git 에 올라가지 않는다.

---

### Task 12: `export_reranker` 가 파인튜닝 모델을 받게 고친다

**Files:**
- Modify: `ai-service/app/export_reranker.py`
- Modify: `ai-service/app/export_reranker_check.py`
- Modify: `ai-service/app/config.py` (주석만)

**Interfaces:**
- Produces:
  - 변형 `local_ft`(디렉터리 `bge-reranker-base-ft-onnx`, 파일 `model.onnx`), `local_ft_int8`(디렉터리 `bge-reranker-base-ft-onnx-int8`, 파일 `model_quantized.onnx`, per_channel=False)
  - `FINETUNED_SOURCE_NAME = "bge-reranker-base-ft"` (zip 을 푼 디렉터리 이름)
  - `FP32_PARENT: dict[str, str]` (양자화 변형 → 입력 fp32 변형)
  - `fp32_parent(variant: str) -> str` (fp32 변형이면 자기 자신)
  - `model_source(fp32_variant: str, models_dir: Path | None = None) -> tuple[str, str | None]` ((저장소 이름 또는 경로, 리비전 또는 None))

**왜 고치는가:** 지금 도구는 원본 모델 하나만 가정한다. 고정된 자리가 넷이다(스펙 §6-4): 원본이 `REPO_ID@REVISION` 으로 고정, 양자화 입력이 `variant_dir("local")` 로 고정, 등가 검증 기준선이 Hugging Face 원본, 허용 오차 강제가 `variant == "local"` 에만. 변형 이름만 더하면 원본 모델을 양자화한 결과가 E 라는 이름으로 저장되고, 검증도 원본과 비교하므로 통과한다. 결과 파일만 보고는 이 실수를 알 수 없다.

- [ ] **Step 1: 실패하는 점검을 쓴다**

`export_reranker_check.py` 의 import 를 바꾼다:

```python
from .export_reranker import (
    FINETUNED_SOURCE_NAME,
    FP32_PARENT,
    MODELS_DIR,
    ONNX_FILENAME,
    QUANT_PER_CHANNEL,
    REPO_ID,
    REVISION,
    VARIANT_DIRS,
    artifact_status,
    fp32_parent,
    missing_message,
    model_source,
)
```

`check_every_variant_is_fully_registered` 의 마지막 두 줄(per_channel 값이 서로 달라야 한다는 assert)을 아래로 바꾼다:

```python
    # 🔴 같은 fp32 원본에서 나온 양자화 변형끼리는 per_channel 값이 달라야 비교가 성립한다.
    #    원본이 다른 변형(local_int8 과 local_ft_int8)은 같은 값이어야 오히려 맞다
    #    (파인튜닝 전후를 같은 양자화 설정으로 비교한다). 그래서 원본별로 묶어서 본다.
    by_parent: dict[str, list[bool]] = {}
    for variant, per_channel in QUANT_PER_CHANNEL.items():
        by_parent.setdefault(FP32_PARENT[variant], []).append(per_channel)
    for parent, values in by_parent.items():
        assert len(set(values)) == len(values), f"{parent} 의 양자화 변형끼리 per_channel 이 겹친다: {values}"
```

파일에 두 점검을 더한다(`check_missing_message_tells_what_to_do` 위):

```python
def check_quant_input_is_matching_fp32() -> None:
    """🔴 양자화 변형의 입력이 대응 fp32 변형인가(스펙 2026-10-01 §6-4 4번).

    이 실수(local_ft_int8 을 local 에서 양자화)는 산출물만 보고는 알 수 없다. 이름이 맞고,
    등가 검증도 원본끼리 비교하므로 통과한다. 그래서 표 수준에서 막는다.
    규칙: 입력 fp32 변형은 이름이 그 변형의 앞부분과 겹치는 fp32 변형 중 가장 긴 것이다
    (local_ft_int8 → local 이 아니라 local_ft).
    """
    fp32 = [v for v in VARIANT_DIRS if v not in QUANT_PER_CHANNEL]
    assert set(FP32_PARENT) == set(QUANT_PER_CHANNEL), (
        f"FP32_PARENT 와 QUANT_PER_CHANNEL 의 변형 목록이 다르다: {sorted(FP32_PARENT)} != {sorted(QUANT_PER_CHANNEL)}")
    for variant, parent in FP32_PARENT.items():
        assert parent in fp32, f"{variant} 의 입력 {parent} 가 fp32 변형이 아니다"
        expected = max((f for f in fp32 if variant.startswith(f + "_")), key=len)
        assert parent == expected, f"{variant} 의 입력이 {parent} 다. {expected} 여야 한다"
        assert fp32_parent(variant) == parent
    for f in fp32:
        assert fp32_parent(f) == f


def check_model_source_per_fp32_variant() -> None:
    """fp32 변형마다 PyTorch 원본이 정해져 있다. 원본 모델은 리비전을 못박고, 파인튜닝 모델은 로컬 디렉터리다."""
    assert model_source("local") == (REPO_ID, REVISION)
    path, rev = model_source("local_ft")
    assert rev is None and Path(path) == MODELS_DIR / FINETUNED_SOURCE_NAME, (path, rev)
    for f in (v for v in VARIANT_DIRS if v not in QUANT_PER_CHANNEL):
        model_source(f)  # 원본이 정해지지 않은 fp32 변형이면 ValueError
```

`main()` 의 `checks` 목록에 두 함수를 더한다(`check_every_variant_is_fully_registered` 다음).

- [ ] **Step 2: 실패하는지 본다**

Run: `cd ai-service && .venv/bin/python -m app.export_reranker_check`
Expected: `ImportError: cannot import name 'FINETUNED_SOURCE_NAME' from 'app.export_reranker'`

- [ ] **Step 3: 등록 표와 원본 함수를 고친다**

`export_reranker.py` 모듈 설명의 "만들 수 있는 변형 3가지" 표를 바꾼다:

```python
만들 수 있는 변형 5가지
─────────────────────────────────────────────────────────────────────────────
  local          ONNX fp32 원본
  local_int8     동적 INT8 (per_channel=False) - 텐서 하나에 스케일 하나
  local_int8_pc  동적 INT8 (per_channel=True)  - 출력 채널마다 스케일을 따로
  local_ft       파인튜닝 모델의 ONNX fp32 (2026-10-01). 원본은 코랩 zip 을 푼
                 models/bge-reranker-base-ft/ 다
  local_ft_int8  local_ft 를 local_int8 과 같은 설정으로 양자화한 것
자세한 근거는 아래 QUANT_PER_CHANNEL, FP32_PARENT 주석에 있다.

    cd ai-service && .venv/bin/python -m app.export_reranker --variants local_ft,local_ft_int8
```

`MODELS_DIR = ...` 아래의 세 표와 그 사이를 아래로 바꾼다(기존 주석은 그대로 두고 항목만 더한다):

```python
VARIANT_DIRS = {
    "local": "bge-reranker-base-onnx",
    "local_int8": "bge-reranker-base-onnx-int8",
    "local_int8_pc": "bge-reranker-base-onnx-int8-pc",
    "local_ft": "bge-reranker-base-ft-onnx",
    "local_ft_int8": "bge-reranker-base-ft-onnx-int8",
}
ONNX_FILENAME = {
    "local": "model.onnx",
    "local_int8": "model_quantized.onnx",
    # ORTQuantizer 는 저장 디렉터리와 무관하게 이 이름으로 떨군다. 변형마다 디렉터리를
    # 나누는 이유가 이것이다 - 같은 디렉터리에 두면 뒤에 돌린 것이 앞의 것을 덮는다.
    "local_int8_pc": "model_quantized.onnx",
    "local_ft": "model.onnx",
    "local_ft_int8": "model_quantized.onnx",
}
```

`QUANT_PER_CHANNEL` 표에 한 줄을 더하고, 그 아래에 새 표와 함수를 둔다:

```python
QUANT_PER_CHANNEL = {
    "local_int8": False,
    "local_int8_pc": True,
    # 파인튜닝 전후를 같은 양자화 설정으로 비교한다(C 와 E 의 차이가 파인튜닝 하나로만 생기게).
    "local_ft_int8": False,
}

# 양자화 변형 → 입력으로 쓰는 fp32 변형 (2026-10-01).
#
# 🔴 이 표가 생기기 전에는 양자화 입력이 variant_dir("local") 로 고정돼 있었다. 그 상태로
#    local_ft_int8 을 더하면 원본 모델을 양자화한 것이 E 라는 이름으로 저장되고, 등가 검증도
#    원본끼리 비교하므로 통과한다. 결과 파일만 보고는 알 수 없는 실수라 표로 못박고
#    export_reranker_check 가 이름 규칙으로 검사한다.
FP32_PARENT = {
    "local_int8": "local",
    "local_int8_pc": "local",
    "local_ft_int8": "local_ft",
}
# 코랩 노트북이 내려주는 zip 을 models/ 아래에 풀면 생기는 디렉터리 이름.
FINETUNED_SOURCE_NAME = "bge-reranker-base-ft"


def fp32_parent(variant: str) -> str:
    """양자화 변형이면 입력 fp32 변형, fp32 변형이면 자기 자신."""
    return FP32_PARENT.get(variant, variant)


def model_source(fp32_variant: str, models_dir: Path | None = None) -> tuple[str, str | None]:
    """fp32 변형의 PyTorch 원본: (Hugging Face 저장소 이름 또는 로컬 경로, 리비전 또는 None).

    원본 모델은 리비전을 못박아 받는다(모듈 설명의 "리비전을 못박는 이유").
    파인튜닝 모델은 로컬 디렉터리라 리비전이 없다. 대신 학습 기록(training_log.json)에
    학습 데이터 해시와 원본 리비전이 적혀 있다.
    """
    if fp32_variant == "local":
        return REPO_ID, REVISION
    if fp32_variant == "local_ft":
        return str((models_dir or MODELS_DIR) / FINETUNED_SOURCE_NAME), None
    raise ValueError(f"PyTorch 원본이 정해지지 않은 fp32 변형입니다: {fp32_variant}")


def _from_pretrained_kwargs(revision: str | None) -> dict:
    """리비전이 있을 때만 넘긴다. 로컬 디렉터리에 revision 을 넘기면 의미가 없고 헷갈린다."""
    return {"revision": revision} if revision else {}
```

- [ ] **Step 4: 기준선, 등가 검증, 내보내기를 변형별로 고친다**

`_torch_logits` 를 바꾼다:

```python
def _torch_logits(tokenizer_dir: Path, source: str, revision: str | None) -> "list[float]":
    """그 변형의 PyTorch 원본으로 같은 입력의 로짓을 뽑는다. 이것이 비교의 기준선이다.

    🔴 기준선이 변형마다 다르다(2026-10-01). local 계열은 Hugging Face 원본, local_ft 계열은
       코랩 zip 의 모델이다. 예전처럼 늘 원본과 비교하면 local_ft 의 변환이 틀어져도
       "원본과 다르다" 로만 보여 원인을 가를 수 없다.
    """
    import torch  # noqa: PLC0415
    from transformers import AutoModelForSequenceClassification, AutoTokenizer  # noqa: PLC0415

    tok = AutoTokenizer.from_pretrained(tokenizer_dir)
    model = AutoModelForSequenceClassification.from_pretrained(source, **_from_pretrained_kwargs(revision))
    model.eval()
    enc = tok(
        [q for q, _ in _VERIFY_PAIRS],
        [p for _, p in _VERIFY_PAIRS],
        padding=True,
        truncation=True,
        max_length=512,
        return_tensors="pt",
    )
    with torch.no_grad():
        logits = model(**enc).logits
    return [float(x) for x in logits.reshape(-1)]
```

`_verify_equivalence` 를 바꾼다(설명 주석의 첫 두 문단은 그대로 두고 본문을 아래로):

```python
def _verify_equivalence(variants: list[str]) -> None:
    """내보낸 ONNX 가 PyTorch 원본과 같은 출력을 내는지 확인한다.

    fp32 는 같아야 한다(허용오차 VERIFY_ATOL). 어긋나면 변환이 틀어진 것이므로 여기서 멈춘다.
    INT8 계열은 달라지는 것이 정상이라 기준선을 걸지 않고 차이값만 찍는다.

    🔴 fp32 원본별로 묶어서 본다(2026-10-01). 같은 원본에서 나온 변형만 한 기준선과 비교한다.
       fp32 변형은 local 이든 local_ft 든 전부 1e-4 를 강제한다.
    """
    import numpy as np  # noqa: PLC0415

    groups: dict[str, list[str]] = {}
    for variant in variants:
        groups.setdefault(fp32_parent(variant), []).append(variant)

    failed: list[str] = []
    for parent, members in groups.items():
        source, revision = model_source(parent)
        if revision is None and not (Path(source) / "config.json").is_file():
            print(f"   ⏭  {parent} 계열: PyTorch 원본({source})이 없어 등가 검증을 건너뛴다")
            continue
        ref = np.asarray(_torch_logits(variant_dir(parent), source, revision))
        print(f"   [{parent} 계열] PyTorch 로짓: {np.round(ref, 4).tolist()}")
        for variant in members:
            d = variant_dir(variant)
            got = np.asarray(_onnx_logits(d / ONNX_FILENAME[variant], d))
            diff = float(np.max(np.abs(got - ref)))
            same_order = np.argsort(-got).tolist() == np.argsort(-ref).tolist()
            print(
                f"   {variant:<13} : {np.round(got, 4).tolist()}  "
                f"(최대 오차 {diff:.3e} · 순위 일치 {same_order})"
            )
            if variant == parent and diff > VERIFY_ATOL:
                failed.append(f"{variant}({diff:.3e})")

    if failed:
        raise SystemExit(
            f"내보낸 fp32 ONNX 가 PyTorch 원본과 다릅니다: {', '.join(failed)} > {VERIFY_ATOL:.0e}. "
            f"변환이 틀어진 것이므로 이 산출물로 측정하면 안 됩니다. 그 변형의 디렉터리를 "
            f"ai-service/models/ 에서 지우고 `.venv/bin/python -m app.export_reranker --variants <변형>` 를 "
            f"다시 돌려주세요. 그래도 같으면 requirements-lab.txt 의 버전 조합을 의심할 것."
        )
```

`export()` 에서 `fp32_dir = variant_dir("local")` 줄부터 함수 끝(`_verify_equivalence(...)` 호출 포함)까지를 아래로 바꾼다:

```python
    fp32_todo = [v for v in todo if v not in QUANT_PER_CHANNEL]
    quant_todo = [v for v in todo if v in QUANT_PER_CHANNEL]

    for variant in fp32_todo:
        source, revision = model_source(variant)
        if revision is None and not (Path(source) / "config.json").is_file():
            raise SystemExit(
                f"{variant} 의 원본 모델 디렉터리가 없습니다: {source}\n"
                f"코랩 노트북이 내려준 {FINETUNED_SOURCE_NAME}.zip 을 ai-service/models/ 에 풀어주세요 "
                f"(`unzip <zip> -d ai-service/models/`)."
            )
        label = f"{source}@{revision[:8]}" if revision else source
        print(f"① ONNX 변환: {variant} ← {label}")
        out_dir = variant_dir(variant)
        out_dir.mkdir(parents=True, exist_ok=True)
        model = ORTModelForSequenceClassification.from_pretrained(
            source, export=True, **_from_pretrained_kwargs(revision)
        )
        model.save_pretrained(out_dir)
        AutoTokenizer.from_pretrained(source, **_from_pretrained_kwargs(revision)).save_pretrained(out_dir)

    # 양자화는 입력 fp32 변형별로 묶는다. 전처리는 묶음마다 한 번만 하고 그 결과를 변형들이 공유한다
    # (변형마다 전처리하면 per_channel 말고 전처리 결과도 달라질 수 있어 원인이 둘로 는다).
    present = artifact_status()
    for parent in sorted({FP32_PARENT[v] for v in quant_todo}):
        group = [v for v in quant_todo if FP32_PARENT[v] == parent]
        if not present.get(parent, False):
            # 양자화는 fp32 산출물에서 출발한다. 없는데 시작하면 중간에서 죽는다.
            raise SystemExit(
                f"양자화({', '.join(group)})의 출발점인 fp32 산출물 {parent} 가 없습니다. "
                f"`.venv/bin/python -m app.export_reranker --variants {parent}` 를 먼저 돌려주세요."
            )
        parent_dir = variant_dir(parent)
        print(f"② 동적 INT8 양자화: {', '.join(group)} ← {parent}")
        # 🔴 quantize 앞에 quant_pre_process 를 둔다(ONNX Runtime 공식 권장 경로). 이유는 _pre_process 주석.
        # ⚠️ 전처리 결과를 parent_dir 에 덮어쓰지 않고 임시 디렉터리에 만든다. parent_dir 은
        #    fp32 설정(B 또는 D)이 그대로 쓰는 산출물이라, 최적화된 그래프로 바꾸면 원본이 아니게 된다.
        with TemporaryDirectory() as tmp:
            prep_dir = Path(tmp) / "prep"
            shutil.copytree(parent_dir, prep_dir)
            _pre_process(parent_dir / ONNX_FILENAME[parent], prep_dir / ONNX_FILENAME[parent])
            quantizer = ORTQuantizer.from_pretrained(prep_dir)
            for variant in group:
                out_dir = variant_dir(variant)
                out_dir.mkdir(parents=True, exist_ok=True)
                # avx512_vnni 는 x86 가속 힌트일 뿐이고, 양자화된 가중치 자체는 어느 CPU 에서도 돈다.
                # ⚠️ 그래서 속도는 아키텍처마다 다르다. M4 Pro(ARM)에서 잰 속도를 EC2(x86_64)의
                #    속도라고 말하면 안 된다.
                qconfig = AutoQuantizationConfig.avx512_vnni(
                    is_static=False, per_channel=QUANT_PER_CHANNEL[variant]
                )
                print(f"   {variant}: per_channel={QUANT_PER_CHANNEL[variant]}")
                quantizer.quantize(save_dir=out_dir, quantization_config=qconfig)
                # 토크나이저도 입력 fp32 변형에서 가져온다(원본 저장소에서 다시 받지 않는다).
                AutoTokenizer.from_pretrained(parent_dir).save_pretrained(out_dir)

    print("③ 등가 검증 (내보낸 ONNX 가 그 변형의 PyTorch 원본과 같은 출력을 내는가)")
    _verify_equivalence([v for v, ok in artifact_status().items() if ok])
```

- [ ] **Step 5: `config.py` 주석을 고친다**

`reranker_provider` 설명의 `"local_int8_pc"` 문단 바로 아래에 더한다:

```python
    #   "local_ft"       리랭커 파인튜닝 실험(2026-10-01)의 파인튜닝 모델, ONNX fp32
    #   "local_ft_int8"  그것을 local_int8 과 같은 설정으로 양자화한 것
    #                    근거는 docs/superpowers/specs/2026-10-01-reranker-finetune-design.md §3-3.
    #                    실제 등록은 export_reranker.py 의 세 표이고 export_reranker_check 가 일치를 본다.
```

- [ ] **Step 6: 점검이 통과하는지 본다**

Run: `cd ai-service && .venv/bin/python -m app.export_reranker_check && .venv/bin/python -m app.local_reranker_check`
Expected: `6가지 전부 통과.` 그리고 `local_reranker_check` 의 통과 줄.

변이 시험: `FP32_PARENT` 의 `"local_ft_int8": "local_ft"` 를 잠시 `"local"` 로 바꿔 `export_reranker_check` 를 돌린다.
Expected: `AssertionError: local_ft_int8 의 입력이 local 이다. local_ft 여야 한다`. 확인 뒤 되돌린다.

- [ ] **Step 7: 커밋한다**

```bash
git add ai-service/app/export_reranker.py ai-service/app/export_reranker_check.py ai-service/app/config.py
git commit -m "feat: export_reranker 가 파인튜닝 모델을 변형별 원본과 입력으로 내보내게 한다"
```

---

### Task 13: 내보내고 시험용 봇에서 B, C, D, E 를 비교한다

**Files:**
- Create: `ai-service/testdata/finetune/compare_test.json`

- [ ] **Step 1: 파인튜닝 모델을 내보낸다**

Run: `cd ai-service && .venv/bin/python -m app.export_reranker --variants local_ft,local_ft_int8 | tee <스크래치>/export.log`
Expected: `① ONNX 변환: local_ft ← .../models/bge-reranker-base-ft`, `② 동적 INT8 양자화: local_ft_int8 ← local_ft`, 등가 검증에서 `[local 계열]` 과 `[local_ft 계열]` 이 따로 찍히고 `local_ft` 의 최대 오차가 1e-4 이하. `--variants` 로 좁혔으므로 기존 `local`, `local_int8`, `local_int8_pc` 산출물은 다시 만들지 않는다(등가 검증 표에는 함께 찍힌다). `--force` 를 쓰지 않는다(대조군 B, C 보존).

- [ ] **Step 2: 네 모델을 비교한다**

Run:
```bash
cd ai-service && .venv/bin/python -m app.rank_trace --bot-id $TEST_BOT \
  --compare local,local_int8,local_ft,local_ft_int8 \
  --pair local:local_ft --pair local_ft:local_ft_int8 --pair local:local_int8 \
  --out testdata/finetune/compare_test.json | tee <스크래치>/compare_test.log
```

Expected: 변형별 표, 따로 세는 문제, 세 짝의 좋아짐, 나빠짐, p 값, 판정. 판정의 주 결과는 `local → local_ft` 줄이다.

- [ ] **Step 3: 재현을 확인한다**

같은 명령을 `--out` 없이 한 번 더 돌린다. Expected: 표와 판정이 첫 실행과 글자까지 같다(검색과 로컬 리랭커는 결정적이다, 스펙 §5-3). 다르면 멈추고 보고한다.

- [ ] **Step 4: 판정을 사용자에게 보고하고 멈춘다**

보고할 것: `local → local_ft` 의 판정, 좋아짐과 나빠짐 수, p 값, 나빠진 문제 목록 전부, 상위 5개 진입률(B, C, D, E), `local_ft → local_ft_int8` 의 양자화 손실. 판정이 **효과 있음**이 아니면 태스크 14 를 하고, 효과 있음이면 태스크 14 를 건너뛴다.

```bash
git add ai-service/testdata/finetune/compare_test.json
git commit -m "feat: 시험용 봇에서 리랭커 파인튜닝 전후를 비교한 결과를 남긴다"
```

---

### Task 14: (효과 있음이 아닐 때만) 예비 시험 문제로 원인을 가른다

**Files:**
- Create: `ai-service/testdata/finetune/compare_holdout.json`

- [ ] **Step 1: 학습용 봇에서 B 와 D 를 비교한다**

학습용 봇의 활성 평가 질문은 예비 시험 문제뿐이다(태스크 5 Step 4).

Run:
```bash
cd ai-service && .venv/bin/python -m app.rank_trace --bot-id $TRAIN_BOT --compare local,local_ft \
  --pair local:local_ft --out testdata/finetune/compare_holdout.json | tee <스크래치>/compare_holdout.log
```

- [ ] **Step 2: 원인을 가른다 (스펙 §5-5)**

| 예비 시험 문제 | 시험 문제 | 원인 |
|---|---|---|
| 효과 있음 | 효과 있음 아님 | 파인튜닝은 됐지만 처음 보는 문서까지 일반화되지 않았다 |
| 효과 있음 아님 | 효과 있음 아님 | 파인튜닝 자체가 실패했다(학습 데이터가 부족하거나 나쁘다) |

예비 시험 문제는 약 30개라 갈린 문제가 6개 미만이면 결과와 관계없이 구별되지 않음이다. 이 경우 "가를 수 없었다" 고 그대로 적는다. 사용자에게 보고하고 커밋한다.

```bash
git add ai-service/testdata/finetune/compare_holdout.json
git commit -m "feat: 예비 시험 문제로 리랭커 파인튜닝의 원인을 가른 결과를 남긴다"
```

---

### Task 15: 전체충실성을 B 와 D 로 1회씩 잰다 (보조 자료)

**Files:** 없음(로컬 DB 의 `eval_runs`, `eval_results`)

시험 문제 60개 기준 1회 약 3,000 뉴런, 두 번에 약 6,000 뉴런이다(스펙 §5-6). 하루 무료 한도는 10,000 이므로 **그날 다른 평가를 돌리지 않았는지 먼저 확인한다.** 한도 리셋 시각은 대시보드 카운터로 예측하지 말고 실제 호출로 확인한다(AGENTS.md 평가 규칙).

- [ ] **Step 1: B 로 평가한다**

```bash
cd ai-service && RERANKER_PROVIDER=local .venv/bin/uvicorn app.main:app --port 8001   # 기존 8001 을 내리고 다시 띄운다
curl -s -X POST localhost:8001/internal/bots/$TEST_BOT/eval/runs
```

평가가 끝나면(`eval_runs.status` 가 `running` 이 아니게 되면):

```bash
docker exec -i alldap-db psql -U alldap alldap -c "
SELECT id, config->>'reranker_provider' AS provider, avg_faithfulness, scored_count, question_count,
       round(avg_faithfulness * scored_count / question_count, 3) AS overall_faithfulness,
       (SELECT count(*) FROM eval_results r WHERE r.run_id = e.id AND r.generated_answer IS NULL) AS broken
  FROM eval_runs e WHERE bot_id = $TEST_BOT ORDER BY id;"
```

Expected: `provider = local`, `broken = 0`. `broken` 이 0 이 아니면 오염된 실행이다(처리 실패). 그 실행은 표에 싣지 않고 원인을 보고한다.

- [ ] **Step 2: D 로 평가한다**

`RERANKER_PROVIDER=local_ft` 로 서버를 다시 띄우고 Step 1 과 같은 명령을 돈다. Expected: 새 행의 `provider = local_ft`, `broken = 0`.

- [ ] **Step 3: 서버를 기본값으로 되돌린다**

`RERANKER_PROVIDER` 없이 서버를 다시 띄운다(기본값 `cloudflare`). 두 실행의 `overall_faithfulness` 를 결과 문서에 적되, 1회씩이고 편차 폭이 0.032 라 이것으로 판정하지 않는다고 함께 적는다.

---

### Task 16: 기록하고 PR 2 를 연다

**Files:**
- Create: `docs/superpowers/plans/2026-10-01-reranker-finetune-results.md`
- Modify: `docs/decisions.md`
- Modify: `docs/BACKLOG.md` (§5 리랭커 파인튜닝 행)
- Create: `docs/superpowers/handoff-<날짜>.md`
- Modify: `AGENTS.md` ("다음 세션은 여기서 시작한다" 의 최신 핸드오프 링크 한 줄만)

- [ ] **Step 1: 결과 문서를 쓴다**

`docs/superpowers/plans/2026-10-01-reranker-finetune-results.md` 의 절(스펙 작성 규칙을 따른다: 용어 하나로 고정, 개수 선언과 항목 수 일치, em dash 없음):

1. 이 문서가 답하는 질문 (스펙 §1-4 의 주장 그대로)
2. 실험 조건: 봇 번호, 청크 수, 문제 수(연습, 시험, 예비 시험), 버린 연습 문제와 이유별 개수, 오답 예시 1~4개 문제 수, 학습 기록(`training_log.json` 전체, 고른 에폭과 검증 성적)
3. 관문 결과 (`gate_B.json`)
4. 대표 결과: B, C, D, E 표(상위 5개 진입률, 고칠 수 있는 문제 기준, 평균 순위), 따로 세는 문제, `local → local_ft` 의 좋아짐, 나빠짐, p 값, 판정
5. 나빠진 문제 목록 전부(문항, 순위 변화, 정답 문서)
6. 양자화 손실(`local_ft → local_ft_int8`)과 2026-09-17 의 `local → local_int8` 손실 비교
7. (했다면) 예비 시험 문제 결과와 원인 판정
8. 전체충실성 B, D 1회씩(보조 자료이고 판정하지 않는다는 문장 포함)
9. 한계: 스펙 §9 의 9개를 이 실행 기준으로 다시 적고, 실행 중 새로 안 것을 더한다(예: 라이브러리 API 를 계획과 다르게 고친 자리, GPU 재현성)

- [ ] **Step 2: `decisions.md`, `BACKLOG.md` 를 고친다**

`docs/decisions.md` 에 한 줄씩(형식: `날짜 | 무엇을 | 왜 그렇게 | 검토한 대안`): 문서 단위 분할, 판정을 부호 검정으로, 학습 전 관문, 출제자 Claude 하나, 기준을 로컬 fp32 로. `docs/BACKLOG.md` §5 의 리랭커 파인튜닝 행에 판정과 결과 문서 링크를 적는다. **AGENTS.md 에는 결과를 적지 않는다.**

- [ ] **Step 3: 핸드오프를 쓴다**

`docs/superpowers/handoff-<날짜>.md`: 무엇을 끝냈나, 판정, 다음 후보. 메모리 약속에 따라 다음 후보 맨 앞에 "채점, 생성 모델 셀프호스팅 검토(파인튜닝 뒤에 다시 꺼내기로 한 약속)" 를 둔다. AGENTS.md 의 "가장 최신 상태는 ..." 링크만 새 핸드오프로 바꾼다.

- [ ] **Step 4: 전체 점검을 돌리고 PR 을 연다**

```bash
cd ai-service && for m in finetune_split_check eval_set_io_check rank_trace_check finetune_data_check \
  eval_set_check export_reranker_check local_reranker_check; do .venv/bin/python -m app.$m || break; done
cd .. && git add docs/ AGENTS.md && git commit -m "docs: 리랭커 파인튜닝 전후 비교 결과를 기록한다"
git push -u origin feat/reranker-finetune
gh pr create --title "feat: 리랭커 파인튜닝과 처음 보는 문서에서의 전후 비교" --body-file <스크래치>/pr2.md
```

PR 본문은 템플릿을 채운다. "어떻게 해결했나요" 에 `compare_test.json` 을 만든 명령과 출력(판정 줄 포함)을 붙인다. "한계 & 트레이드오프" 에 결과 문서 §9 를 요약한다. "검토한 대안" 에 스펙 핸드오프 §3 의 기각한 대안을 옮긴다. CI 는 기다리지 않는다.

---

## 실행 기록

(태스크 4 Step 6 에서 봇 번호와 청크 수를 여기에 적는다.)
