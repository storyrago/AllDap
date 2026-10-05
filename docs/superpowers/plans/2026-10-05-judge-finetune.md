# 채점 모델 M3 파인튜닝 구현 계획

> **#160(`feat/judge-selfhost-v2`)은 2026-10-05 에 머지됨.** 이 브랜치(`feat/judge-finetune`)는 #160 의 브랜치에서 땄다(스택 브랜치). 머지된 뒤 같은 날 `git rebase origin/main` 으로 기준을 옮겼고 충돌은 없었다. 그래서 이 브랜치에는 이 실험의 커밋만 남아 있다. PR 은 태스크 E18 에서 연다.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 채점 모델 M3(`Unbabel/M-Prometheus-14B`)를 ⑧ 다른 대상의 규정 끌어오기 모양의 학습 문항으로 LoRA 파인튜닝하고, 학습에 쓰지 않은 분야의 새 시험지와 v2 의 동결 시험지에서 학습 전과 후를 비교한다.

**Architecture:** 설계는 [`specs/2026-10-05-judge-finetune-design.md`](../specs/2026-10-05-judge-finetune-design.md)(이하 스펙)에 있다. 이 계획은 v2 계획 [`2026-10-05-judge-selfhost-v2.md`](2026-10-05-judge-selfhost-v2.md)(이하 v2 계획)의 구조를 따른다. 일은 두 종류다. 코드 태스크(태스크 1~12)는 `ai-service/tools/` 아래 도구와 코랩 노트북을 만들고, 실행 태스크(태스크 E1~E18)는 그 도구로 문서를 올리고, 문항과 학습 데이터를 만들고, 검수하고, 학습하고, 모델을 돌린다. 서비스 코드(`ai-service/app/`)와 v2 의 파일은 바꾸지 않는다.

**Tech Stack:** Python 3.12, 표준 라이브러리(`random`, `hashlib`, `string`, `unittest.mock`), 기존 `app.retriever`, `app.cf`, `tools.judge5`, `tools.judge5v2_*`(가져다 쓰기만), Spring API(봇 생성과 업로드에만), 코랩 T4(torch, transformers 4.57.6, bitsandbytes 0.50.2, peft 0.17.1, accelerate 1.10.1).

## 모든 태스크가 지키는 것

모든 태스크가 아래를 지킨다. 값은 스펙에서 그대로 옮겼다.

- 작업 위치는 워크트리 `/Users/cheonjamin/projects/AllDap-judge-ft`(브랜치 `feat/judge-finetune`)다. 여러 세션이 같은 워크트리를 쓴다. 커밋은 **`git add <경로들>` 뒤에 `git commit -m "..." -- <같은 경로들>`** 꼴로 한다. `git add -A`, `git add .` 를 쓰지 않는다. 이유는 v2 계획과 같다: 워크트리 하나에는 index 가 하나뿐이라, 경로 없이 커밋하면 다른 세션이 add 한 파일이 섞인다. 경로를 변수 하나에 모아 넘기지 않는다(zsh 는 따옴표 없는 변수를 공백에서 나누지 않는다. v2 결과 7-3절).
- 이 계획에서 **파이썬** 은 메인 저장소의 가상환경 `/Users/cheonjamin/projects/AllDap/ai-service/.venv/bin/python` 이다. 워크트리에는 `.venv` 가 없다. 명령은 늘 워크트리의 `ai-service` 에서 실행한다. 그래야 `tools` 와 `app` 을 워크트리의 코드로 불러온다. 아래 명령에서는 `PY=/Users/cheonjamin/projects/AllDap/ai-service/.venv/bin/python` 으로 줄여 쓴다.
- push 하지 않는다. PR 은 태스크 E18 에서, #160 이 머지된 뒤에만 연다.
- 서비스 코드(`ai-service/app/`)를 고치지 않는다. **v2 의 파일(`tools/judge5*.py`, `testdata/judge5v2/`, `notebooks/judge5*_colab.ipynb`)을 한 글자도 고치지 않는다**(스펙 2-2절). v2 의 점검(`judge5_check` 44가지, `judge5v2_check` 66가지)은 이 계획의 모든 태스크 뒤에 그대로 통과해야 한다.
- 봇 1번(데모 봇), 7번, 8번(리랭커 실험), v2 의 봇 9~12번은 건드리지 않는다(스펙 3-4절).
- 분야 후보는 넷이다: `hospital`(병원 안내), `school`(학교 학칙), `travel`(여행 약관), `telecom`(통신 요금제). 시험용, 학습용, 예비 분야는 시드 `20261006` 으로 정한다(스펙 3-2절, 태스크 E1).
- 대응표: ①과 ② 5점, ③ 4점, ④ 3점, ⑤ 2점, ⑥과 ⑦과 ⑧ 1점(v2 스펙 3-2절). 코드에서는 유형을 정수 1~8 로 쓴다(①이 1).
- 학습 데이터 할당량: ① 35, ② 35, ③ 34, ④ 34, ⑤ 34, ⑥ 34, ⑦ 34, ⑧ 240, 짝 문항 120. 합쳐 600(스펙 4-4절).
- 새 시험지 할당량: ① 10, ② 10, ③ 10, ④ 10, ⑤ 7, ⑥ 8, ⑦ 5, ⑧ 60. 합쳐 120. ①과 ② 중 각 6문항은 대상이 둘인 질문에서 먼저 뽑는다(스펙 4-4절).
- 분야를 늘리는 기준: 시험용 ⑧ 자격 질문 72개 미만, 학습용 합계 240개 미만. 시험용 2개, 학습용 3개까지(스펙 3-3절).
- 검수 뒤 새 시험지 조건: ⑧ 54 이상, ①과 ② 합쳐 15 이상, 대상이 둘인 질문의 ①과 ② 10 이상(스펙 4-4절).
- 학습 설정: LoRA rank 16, alpha 32, dropout 0.05, 일곱 projection, 학습률 0.0002, cosine, warmup 3%, 2바퀴, 배치 1, 기울기 누적 8, paged AdamW 8비트, float16 혼합 정밀도와 loss scaling, LoRA 가중치 float32, 최대 길이 자르지 않음, loss 는 모범 답안과 끝 토큰만, 채점에는 마지막 체크포인트, 체크포인트는 최근 둘만 보관(스펙 6절).
- 관문 (a): 학습 전 M3 의 새 시험지 ⑧(정답 점수가 1 인 문항) 심각한 놓침이 (그 수에서 못 읽음을 뺀 수)의 10% 이상. 실행이 여럿이면 비율이 가장 낮은 실행으로 판정(스펙 7-1절). 보고서의 ⑧ 심각한 놓침과 ⑧ 만의 짝 부호 검정도 같은 범위다.
- 교체 후보 기준 넷과 실행이 여럿일 때의 규칙(학습 후 M3 는 가장 나쁜 값, 비교 상대는 가장 좋은 값)은 스펙 8-4절 그대로다. 결과를 본 뒤 규칙이나 코드를 바꾸지 않는다.
- **새 시험지의 문항별 결과는 학습이 끝날 때까지 열어 보지 않는다**(스펙 6-5절). 관문 (a) 의 도구는 개수만 낸다. 결과 zip 은 풀어서 커밋할 뿐 줄을 읽지 않는다.
- 공통 지시문, 채점표, 생성 설정(탐욕적 디코딩, 최대 출력 512 토큰, repetition_penalty 1.0)은 `tools/judge5.py` 와 v2 노트북의 것을 그대로 쓴다.
- 문서와 주석과 커밋 메시지에 em dash 문자를 쓰지 않는다. 쉼표, 콜론, 괄호로 대신한다.
- 커밋 메시지는 `<타입>: <한국어 요약>` 뒤에 빈 줄, 그리고 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` 한 줄이다.
- Python 코드에는 왜 그렇게 썼는지 한국어 주석을 붙인다(AGENTS.md). 아래 코드의 주석이 그 기준이다.

---

## 스펙과 다른 점과 그 이유

이 계획을 쓰면서 정한 것 중 스펙의 글과 다른 것이 다섯 있었다. 모두 측정 규칙(스펙 8절)은 건드리지 않는다. 2026-10-05 에 사용자가 승인해 1~3 번은 스펙(2-2절, 4-5절, 6-2절, 9-3절)에, 5 번은 스펙 3-3절에 반영했다. 아래는 그 경위로 남긴다.

1. **v2 도구에 인자를 더하지 않고, 새 모듈(`tools/judgeft_*.py`)을 만들어 v2 의 함수를 가져다 쓴다.** 스펙 2-2절과 9-3절은 "v2 도구에 인자를 더하고 기본값은 v2 그대로" 라고 적었다. 그런데 v2 도구의 분야(`DOMAINS`), 할당량(`QUOTA`), 경로는 모듈 수준의 상수라서 인자로 바꾸려면 v2 의 함수 여러 개의 본문을 고쳐야 한다. 고친 함수가 v2 의 보고서와 점검(44가지, 66가지)을 그대로 통과하는지는 고친 뒤에야 안다. 새 모듈이 v2 의 순수 함수(검색 한 건, 자격 조건, ⑥과 ⑧ 의 글자 확인, 검수 반영, 점수 읽기, 부호 검정, 세 오류 수)만 불러 쓰면 v2 파일은 한 글자도 바뀌지 않으므로, 앞 실험의 결과가 바뀔 수 없다. 검색과 채점의 규칙을 두 번 적지 않으므로 한쪽만 고쳐지는 위험도 없다. 이 결정은 `docs/decisions.md` 에 태스크 1 과 함께 적는다.
2. **trl 을 쓰지 않는다. 그래서 고정하는 판은 transformers, bitsandbytes, peft, accelerate 넷이다.** 스펙 6-2절은 trl 의 판도 고정한다고 적었다. 학습 반복문을 노트북에 직접 짜면(태스크 11) 모범 답안 위치에서만 logits 를 계산하는 것(스펙 6-2절), 체크포인트에 난수 상태까지 넣어 이어 하는 것(스펙 6-4절)을 모두 코드로 읽을 수 있다. trl 을 쓰면 이 둘이 라이브러리 안에 숨고, 판이 바뀌면 동작이 바뀐다. accelerate 는 transformers 가 모델을 GPU 에 올릴 때(`device_map='auto'`) 필요해서 고정한다. torch 는 코랩에 깔린 것을 쓰고 판을 적는다(다시 깔면 약 2GB 를 받는다). torch 판이 v2 와 다르면 스펙 8-1절의 규칙대로 v2 의 결과를 섞지 않는다.
3. **⑦ 의 지어낸 내용과 ③, ④, ⑤ 의 더한 주장도 따옴표 안 한국어로 모범 답안에 들어간다.** 스펙 4-5절은 "근거의 값과 대상의 이름만 한국어로" 라고 적었다. 이 둘은 근거가 아니라 답변에서 인용하는 구절이지만, 영어로 옮기면 모델이 답변의 어느 글을 가리키는지 대조할 수 없다. 그래서 답변의 구절도 원문 그대로 따옴표 안에 넣는다. 문장 틀 자체에는 한글이 없다(스펙 5-3절 확인 3).
4. **학습 문항의 근거 머리표는 지시문과 같은 `[근거 i]` 다.** 모범 답안이 근거를 가리킬 때 `"월 10GB" ([근거 1])` 꼴로 쓴다. v2 에서 학습 전 M3 가 쓴 출력도 `근거 1` 로 근거를 가리켰다.
5. **분야를 여는 조건을 "⑧ 자격 질문의 합계" 에서 "합계, 그리고 첫 배정을 같은 시드와 순서로 돌려 본 결과" 로 넓혔다.** 배정은 ④ 를 ⑧ 보다 먼저 뽑고, 주장이 2 인 ⑧ 자격 질문은 ④ 의 자격도 있어 ④ 가 일부를 가져간다. 그래서 합계가 기준(72, 240)을 넘어도 배정이 모자랄 수 있다. `judgeft_assign count` 가 첫 배정을 저장하지 않고 돌려 본다(태스크 4, 계획 E5).

---

## 파일 구조

### 새로 만드는 코드

| 파일 | 맡는 일 | 태스크 |
|---|---|---|
| `ai-service/tools/judgeft_files.py` | 경로, 분야 후보, 할당량, 기준 수치, 학습 설정, 라이브러리 판. v2 의 읽고 쓰는 함수를 다시 내보낸다 | 2 |
| `ai-service/tools/judgeft_fields.py` | 분야 순서를 시드로 정하고, 분야를 연다(스펙 3-2절, 3-3절) | 2 |
| `ai-service/tools/judgeft_search.py` | 질문마다 실제 검색으로 근거 청크 전문을 뽑는다. 검색 한 건은 v2 의 `search_one` | 3 |
| `ai-service/tools/judgeft_assign.py` | ⑧ 자격 세기, 시험용과 학습용 배정, 보충 | 4 |
| `ai-service/testdata/judgeft/templates.json` | 모범 답안의 영어 문장 틀. 묶음 아홉, 묶음마다 셋 | 5 |
| `ai-service/tools/judgeft_rationale.py` | 변경 기록과 문장 틀로 모범 답안을 만든다 | 5 |
| `ai-service/tools/judgeft_export.py` | 새 시험지(검수 전, 불일치 목록, 최종, 보충 뒤 검수할 문항만 뽑기와 검수 결과 덧붙이기)와 학습 데이터, 누출 확인(글 전체, 20자 이상 문장의 두 방향, 금지 값) | 6 |
| `ai-service/tools/judgeft_labels.py` | 학습 문항 하나를 토큰으로 바꾸는 함수. 노트북이 글자 그대로 담는다 | 7 |
| `ai-service/tools/judgeft_tokcheck.py` | 실제 M3 토크나이저로 끝 토큰 위치를 확인하고, loss 계산 방식이 같은 값을 내는지 작은 모델로 확인한다(CI 밖) | 7 |
| `ai-service/tools/judgeft_determinism.py` | 결정성 확인과 모델마다 쓸 결과 파일 목록 | 8 |
| `ai-service/tools/judgeft_gate.py` | 검수 뒤 세 조건, 학습 전 관문 (a) | 8 |
| `ai-service/tools/judgeft_cloudflare.py` | M1 으로 새 시험지를 실행 번호 1~3 으로 채점한다. 관문 (a), (b) 를 모두 통과한 뒤에만 돈다 | 9 |
| `ai-service/tools/judgeft_report.py` | 스펙 7절의 관문 결과, 학습 기록, 8절의 수치(혼동행렬, 유형별 표, 못 읽음의 원인), 비교, 기준, 9-3절의 검수 결과. 관문에서 끝나도 만든다 | 10 |
| `ai-service/tools/judgeft_notebooks.py` | 학습 노트북과 채점 노트북을 만든다 | 11 |
| `ai-service/notebooks/judgeft_train_colab.ipynb` | 관문 (b), 학습, 체크포인트 이어 하기 | 11 |
| `ai-service/notebooks/judgeft_eval_colab.ipynb` | 학습 전 M3, 학습 후 M3 채점 | 11 |
| `ai-service/tools/judgeft_*_check.py` 아홉, `judgeft_check.py` | 도구마다의 점검과 그것을 묶는 입구 | 2~12 |

### 고치는 코드와 문서

| 파일 | 고치는 곳 | 태스크 |
|---|---|---|
| `AGENTS.md` | 작업 규칙 7번에 세 번째 항목(채점 모델의 학습을 실험 용도로), 같은 범위를 말하는 두 줄 | 1 |
| `docs/decisions.md` | 2026-10-05 항목 하나(작업 규칙 7번 확장과 v2 를 고치지 않는 구조) | 1 |
| `.github/workflows/ci.yml` | `python -m tools.judgeft_check` 한 줄과 설명 주석 한 줄 | 12 |

### 실행 태스크가 만드는 데이터 (`ai-service/testdata/judgeft/`)

| 파일 | 만드는 태스크 | 모양 |
|---|---|---|
| `fields.json` | E1, E5 | `{"seed", "order", "test": [...], "train": [...], "reserve": [...], "opened": [...]}` |
| `corpus/<분야>/` | E1, E4 | 분야마다 약 25개 문서와 `README.md`(올리지 않는다) |
| `bots.json` | E2, E4 | `{"<분야>": 봇 번호}` |
| `run_log.md` | E2 이후 모든 태스크 | 뉴런, 시각, 검수 모델, 관문 결과, 코랩 시간, 끊긴 횟수 |
| `questions.jsonl` | E3, E4 | v2 계획 형식 1 과 같다. `domain` 칸에 분야 이름을 쓴다 |
| `retrieved.jsonl` | E3, E4 | v2 계획 형식 2 와 같다(`nondefault` 는 생기지 않는다) |
| `excluded.json` | E3, E4 | v2 와 같다 |
| `assignment.json` | E6, E9, E10 | 아래 형식 A |
| `variants.jsonl` | E7 | 아래 형식 B(v2 형식 4 에 변경 기록을 더함) |
| `cases.jsonl`, `cases.sha256`, `answer_key.json` | E8, E9 | v2 형식 5, 6 과 같다. 정답 키의 문항마다 `two_targets` 를 더한다 |
| `review.jsonl`, `mismatches.md` | E8, E9 | v2 형식 7 과 같다 |
| `gate.md` | E9 | 검수 뒤 세 조건 |
| `train.jsonl`, `val.jsonl`, `train_dropped.json`, `train.sha256` | E10 | 아래 형식 C |
| `determinism.json` | E12, E16 | 아래 형식 D |
| `gate_a.json` | E13 | 아래 형식 E |
| `results/new/`, `results/frozen/` | E12, E13, E16, E17 | `<모델>_run<번호>.jsonl` 과 `.env.json`. 모델 이름은 `M1`, `M3pre`(학습 전 M3), `M3ft`(학습 후 M3) |
| `gate_b.json`, `training_log.jsonl`, `train_done.json`, `train_env.json` | E14, E15 | 학습 노트북이 Drive 에 쓴 것을 옮긴다 |
| `report.md` | E18 | 보고서 |

### 데이터 형식

v2 계획의 형식 1~7 을 그대로 쓰고, 아래 다섯을 더한다.

**형식 A. `assignment.json`**

```json
{"seed": 20261006,
 "rounds": [
   {"round": 0, "sheet": "test", "questions_sha256": "...", "retrieved_sha256": "...", "excluded_sha256": null,
    "pool": ["school-001", "..."], "needs": {"1": 10, "...": 0}, "contrast_needs": {"1": 6, "2": 6},
    "types": {"school-004": 4, "...": 1}, "contrast_five": ["school-012", "..."], "pairs": [], "unused": ["..."]},
   {"round": 0, "sheet": "train", "...": "...", "pair_needs": 120, "pair_from": [], "pairs": ["travel-031", "..."]}
 ]}
```

- 시험용(`test`)과 학습용(`train`)은 회차 번호를 따로 센다. 난수는 `random.Random(f"{seed}:{sheet}:{round}")` 다.
- `contrast_five` 는 대상이 둘인 질문에서 먼저 뽑은 ①과 ② 의 질문이다. `pairs` 는 짝 문항을 만들 ⑧ 질문이다.
- 점검(태스크 12)이 회차마다 `pool` 과 `needs` 로 다시 돌려 같은 결과가 나오는지 본다.

**형식 B. `variants.jsonl`** (v2 형식 4 에 변경 기록을 더한다. 스펙 4-3절)

```json
{"qid": "travel-031", "type": 8, "answer": "베이직 요금제는 데이터를 월 30GB 줍니다.", "note": "베이직 값을 프리미엄 값으로 바꿨다",
 "target": "베이직", "evidence": [{"source": 1, "quote": "월 10GB"}],
 "other": {"target": "프리미엄", "source": 1, "quote": "월 30GB"}}
{"qid": "travel-044", "type": 6, "answer": "...", "target": "베이직", "evidence": [{"source": 2, "quote": "월 10GB"}],
 "new_value": "월 20GB", "old_value": "월 10GB"}
{"qid": "travel-050", "type": 3, "answer": "...", "evidence": [{"source": 1, "quote": "..."}], "added": ["남은 데이터는 이월됩니다"]}
{"qid": "travel-061", "type": 7, "answer": "...", "gist": "매장 방문 예약 절차"}
```

- `target`: 질문의 대상. 대상이 따로 없으면 `null`. ⑧ 은 `questions.jsonl` 의 `contrast.asked.target` 과 같아야 한다.
- `evidence`: 근거에 있는 주장마다 근거 번호(`source`, 지시문의 `[근거 i]` 와 같이 1 부터)와 근거 원문의 구절(`quote`). 구절은 그 근거 청크의 전문에 글자 그대로 있어야 한다(스펙 5-2절 확인 1). ⑦ 은 비워도 된다. ⑥ 은 바꾸기 전 값이 적힌 구절이다. **⑧ 은 멀쩡한 답변의 주장마다 하나씩, 질문의 `claims` 수만큼 적고, 첫째는 질문의 대상의 값(`contrast.asked.value`)이 적힌 구절이다.** ⑧ 의 모범 답안은 첫째만 인용하고, 짝 문항의 5점 모범 답안은 모두를 인용한다("every claim" 이라고 쓰므로 인용이 주장마다 있어야 한다). 둘 다 `record_problems` 가 확인한다.
- `other`: ⑧ 에만. 바꿔 넣은 값이 원래 붙어 있는 다른 대상의 이름, 근거 번호, 구절.
- `added`: ③, ④, ⑤ 에만. 더하거나 바꿔 넣은 근거에 없는 주장을 답변의 글자 그대로.
- `gist`: ⑦ 에만. 지어낸 내용의 요지를 답변에서 옮긴 짧은 구절.
- 시험용 문항도 같은 칸을 적는다. 시험용의 변경 기록은 모범 답안에 쓰지 않고, 보고서에서 문항을 다시 볼 때만 쓴다.

**형식 C. `train.jsonl`, `val.jsonl`** (E10)

```json
{"id": "3fa1c09b2d7e", "qid": "travel-031", "domain": "travel", "kind": "main", "type": 8, "score": 1,
 "messages": [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}],
 "target": "The question asks about \"베이직\". ... So the overall score is 1. [RESULT] 1"}
```

- `kind` 는 `main`(배정된 유형의 문항) 또는 `pair`(짝 문항, `type` 1). `messages` 는 `judge5.build_messages` 로 만든 공통 지시문이다.
- `train_dropped.json` 은 `{"main": {qid: [이유]}, "pair": {qid: [이유]}}`. `train.sha256` 은 `train.jsonl`, `val.jsonl`, `templates.json`, 공통 지시문의 해시를 한 줄씩 적는다.

**형식 D. `determinism.json`** (E12, E16)

```json
{"pre": {"env_same": true, "env_diff": {}, "vs_v2": {"same": 231, "diff": 0}, "compared": ["frozen M3pre_run1", "v2 M3_run1"],
         "same": 231, "diff": 0, "diff_ids": [], "use_v2": true, "runs": 1},
 "post": {"compared": ["new M3ft_run1", "new M3ft_run2"], "same": 118, "diff": 0, "diff_ids": [], "runs": 1}}
```

`runs` 가 1 이면 코랩 모델을 시험지마다 한 번, 3 이면 세 번 돌린다(스펙 8-1절). 어느 파일을 쓰는지는 `judgeft_determinism.runs_for` 가 정한다. `use_v2` 는 학습 전 M3 의 동결 시험지 값에 v2 의 `M3_run1` 을 쓰는가다. 판(GPU, torch, transformers, bitsandbytes)이 v2 와 같고 v2 의 run1 과 줄마다 같을 때만 `true` 다. 판이 같은데 다르면 새 환경의 run2 와 대조해 `compared` 에 적고, `vs_v2` 에 v2 와의 차이를 남긴다.

**형식 E. `gate_a.json`** (E13)

```json
{"threshold": 0.1, "runs": [{"run": 1, "eighth": 58, "unread": 0, "severe": 9, "ratio": 0.155}], "pass": true}
```

---

## 태스크 사이의 의존 관계

| 태스크 | 종류 | 먼저 끝나야 하는 것 | 뉴런 | 사람 |
|---|---|---|---|---|
| 1 작업 규칙 7번과 결정 로그 | 문서 | 없음 | 없음 | |
| 2 공통 상수와 분야 도구 | 코드 | 없음 | 없음 | |
| 3 검색 도구 | 코드 | 2 | 없음 | |
| 4 배정 도구 | 코드 | 2 | 없음 | |
| 5 문장 틀과 모범 답안 | 코드 | 2 | 없음 | |
| 6 내보내기 도구 | 코드 | 4, 5 | 없음 | |
| 7 토큰화와 loss 확인 | 코드 | 2 | 없음 | |
| 8 결정성과 관문 | 코드 | 2 | 없음 | |
| 9 M1 채점 도구 | 코드 | 2 | 없음 | |
| 10 보고서 도구 | 코드 | 8 | 없음 | |
| 11 노트북 생성 | 코드 | 7 | 없음 | |
| 12 점검 묶기와 CI | 코드 | 2~11 | 없음 | |
| E1 분야 순서, 첫 학습용 분야의 문서 | 실행 | 2 | 없음 | |
| E2 첫 학습용 분야의 봇과 업로드 | 실행 | E1 | **쓴다** | |
| E3 첫 학습용 분야의 질문, 검색, 답변, ⑧ 비율 | 실행 | 3, 4, E2 | **쓴다** | |
| E4 나머지 분야의 문서, 봇, 질문, 검색, 답변 | 실행 | E3 | **쓴다** | |
| E5 ⑧ 자격을 세고 분야를 늘린다 | 실행 | E4 | 늘리면 **쓴다** | 분야 한도를 넘으면 **사용자** |
| E6 배정 | 실행 | E5 | 없음 | |
| E7 변형 답변과 변경 기록 | 실행 | E6 | 없음 | |
| E8 새 시험지와 검수 | 실행 | 6, E7 | 없음 | **사용자**(Codex) |
| E9 불일치 판단, 최종 새 시험지, 검수 뒤 조건 | 실행 | 8, E8 | 없음 | **사용자** |
| E10 학습 데이터, 토큰 확인, 누출 확인 | 실행 | 6, 7, E9 | 없음 | |
| E11 동결 커밋 | 실행 | 11, 12, E10 | 없음 | |
| E12 학습 전 M3 의 결정성 | 실행 | E11 | 없음 | **사용자**(코랩) |
| E13 학습 전 관문 (a) | 실행 | 8, E12 | 없음 | **사용자**(코랩) |
| E14 학습 전 관문 (b) | 실행 | E13 통과 | 없음 | **사용자**(코랩) |
| E15 학습 | 실행 | E14 통과 | 없음 | **사용자**(코랩) |
| E16 학습 후 M3 채점과 결정성 | 실행 | E15 | 없음 | **사용자**(코랩) |
| E17 M1 의 새 시험지 채점 세 번 | 실행 | 9, E13 통과, E14 통과 | **쓴다**(회당 약 4,500) | |
| E18 보고서, 결과 문서, PR | 실행 | 10, E16, E17 | 없음 | PR 은 #160 머지 뒤 |

**순서에 담긴 규칙 셋.**
1. **동결 커밋(E11)이 학습 전 관문 (a)(E13)보다 먼저다.** 새 시험지, 정답 파일, 학습 데이터, 문장 틀, 학습 설정이 담긴 노트북을 모두 커밋한 뒤에 처음으로 모델을 돌린다. 관문 (a) 의 결과를 본 뒤 학습 데이터를 고치는 일을 막는다(스펙 6-5절).
2. **관문 (a) 를 통과하지 못하면 E14 부터 E17 까지 하지 않는다.** E18 의 짧은 판(관문에서 끝난 결과 문서)으로 간다. M1 의 뉴런도 쓰지 않는다. **M1(E17)은 관문 (b)(E14)까지 통과한 뒤에 돌린다.** (b) 에서 메모리가 모자라면 사용자가 새 실험으로 돌릴 수 있고, 그러면 이 실험의 M1 결과는 쓰이지 않는다. `judgeft_cloudflare` 가 `gate_a.json` 과 `gate_b.json` 을 모두 확인한다.
3. **새 시험지의 문항별 결과는 E16 이 끝날 때까지 아무도 열지 않는다.** E13 과 E16 의 결과 파일은 zip 을 풀어 커밋할 뿐이고, 개수는 도구가 낸다. 보고서(E18)가 처음으로 문항별 결과를 읽는다.

### 세션에 나누는 제안

| 세션 | 맡는 태스크(순서대로) | 비고 |
|---|---|---|
| 가 (출제) | E1 의 문서, E3, E4 의 질문과 답변, E7, 보충 때 E7 다시 | **출제 세션은 이 세션 하나다.** 문서, 질문, 멀쩡한 답변, 변형 답변, 변경 기록을 모두 쓴다. 기준이 한 세션 안에서 일관되게 하기 위해서다(v2 와 같다) |
| 나 | 1, 2, 4, 6, 10 | 2 는 작은 태스크다. 커밋되면 세션 다가 3, 5, 7 을 시작한다 |
| 다 | 3, 5, 7, 8, 9, 11, 12 | |
| 오케스트레이터 | E1 의 시드, E2, E3 과 E4 의 검색, E5, E6, E8 의 폴더 준비, E9~E13, E16~E18 의 정리 | 사용자와 이야기하는 세션이다. 코랩 실행(E12~E16)은 사용자가 돌리고 오케스트레이터가 결과를 받는다 |
| 검수 세션 | E8 의 채점 | **Codex(OpenAI) 세션이다.** 사용자가 저장소 밖의 전용 폴더에서 새로 연다(v2 스펙 4절과 같다) |

각 코드 태스크가 끝나면 다른 세션이 리뷰한다(나의 태스크는 다가, 다의 태스크는 나가). 태스크마다 **리뷰 포인트** 를 적어 두었다.

### 날짜와 뉴런

- **업로드와 검색(E2~E5):** 질문 약 750개와 문서 약 75~125개. v2 의 실측(검색 질문당 약 1.14 뉴런, 문서 131개 업로드 81.77 뉴런)으로 합쳐 약 1,000 뉴런으로 어림한다(스펙 9-2절). 단계마다 `cf-stats` 의 차이를 `run_log.md` 에 적는다.
- **M1 의 새 시험지 채점(E17):** 회당 약 4,500 뉴런(문항당 약 37.8, v2 결과 6-1절). **한 번에 하루 하나**, 한도가 초기화된 뒤에 돌린다. 세 번이면 사흘이다. 업로드나 검색을 한 날에는 돌리지 않는다.
- 이 계획에서 **다음 날** 은 한도가 한 번 초기화된 뒤를 뜻한다(v2 계획과 같다). 그날 첫 호출(`judge5_cloudflare --smoke`)이 성공하는지로 확인한다.

---

## 코드 태스크

### Task 1: 작업 규칙 7번을 넓히고 결정 로그를 남긴다

스펙 2-1절대로 첫 태스크다. 채점 모델의 학습은 지금 작업 규칙 7번이 연 범위 밖이다(v2 결과 9-1절). 이 태스크가 커밋되기 전에는 학습에 관한 어떤 실행 태스크도 시작하지 않는다.

**Files:**
- Modify: `AGENTS.md` (작업 규칙 7번)
- Modify: `docs/decisions.md` (맨 끝에 항목 하나)

**Interfaces:**
- Consumes: 없음
- Produces: 없음(문서)

- [ ] **Step 1: 작업 규칙 7번의 제목 줄을 고친다**

`AGENTS.md` 에서 아래 줄을 찾는다.

```
7. **범위를 넓히지 말 것 (2026-09-16 에 리랭커 추론에 한해 열었고, 2026-10-02 에 채점 모델 추론을 실험 용도로 열었다).**
```

아래로 바꾼다.

```
7. **범위를 넓히지 말 것 (2026-09-16 에 리랭커 추론에 한해 열었고, 2026-10-02 에 채점 모델 추론을, 2026-10-05 에 채점 모델 학습을 실험 용도로 열었다).**
```

- [ ] **Step 2: 연 것의 개수와 세 번째 항목을 고친다**

`✅ **연 것은 둘이다.**` 를 `✅ **연 것은 셋이다.**` 로 바꾸고, ② 항목의 마지막 줄(`Cloudflare 를 그대로 쓴다. 근거는 \`docs/superpowers/specs/2026-10-02-judge-selfhost-design.md\`.`) 바로 뒤에 아래 세 줄을 더한다.

```
   ③ 채점 모델(M3, `Unbabel/M-Prometheus-14B`)을 **실험 용도로** 학습(LoRA 파인튜닝)하는 것(코랩).
   서비스의 채점 모델은 바꾸지 않고, LoRA 산출물은 git 에 넣지 않는다(해시와 Drive 위치만 기록).
   근거는 `docs/superpowers/specs/2026-10-05-judge-finetune-design.md` 와 `docs/decisions.md` 2026-10-05 항목.
```

AGENTS.md 에는 규칙과 안내만 적는다. 실측 수치나 결과는 넣지 않는다.

- [ ] **Step 2-1: 규칙 7번의 범위를 말하는 다른 두 줄도 맞춘다**

규칙 7번만 고치면 같은 파일의 두 곳이 "추론만 열었다" 로 남아 서로 어긋난다.

"개발자에 대해" 절의 아래 줄을

```
  🔴 **단, 2026-09-16 에 리랭커 추론을, 2026-10-02 에 실험용 채점 모델 추론을 열었다** (아래 "작업 규칙" 7번 참고).
```

아래로 바꾼다(기존 줄의 🔴 는 그대로 둔다).

```
  🔴 **단, 2026-09-16 에 리랭커 추론을, 2026-10-02 에 실험용 채점 모델 추론을, 2026-10-05 에 실험용 채점 모델 학습을 열었다** (아래 "작업 규칙" 7번 참고).
```

"알려진 한계" 절의 아래 줄을

```
- 임베딩·답변 생성·채점은 외부 API(Cloudflare)다. 직접 돌리는 것은 리랭커 추론과 실험용 채점 모델 추론뿐이다(작업 규칙 7번).
```

아래로 바꾼다.

```
- 임베딩·답변 생성·채점은 외부 API(Cloudflare)다. 직접 돌리는 것은 리랭커 추론과 실험용 채점 모델의 추론과 학습뿐이다(작업 규칙 7번).
```

- [ ] **Step 3: 결정 로그에 항목을 더한다**

`docs/decisions.md` 맨 끝에 아래를 더한다.

```markdown
## 2026-10-05 | 채점 모델 M3 의 학습을 실험 용도로 열고, v2 도구를 고치지 않고 새 모듈에서 가져다 쓴다

**무엇을**: AGENTS.md 작업 규칙 7번에 세 번째 항목(채점 모델의 학습을 실험 용도로)을 더했다. M3 를 ⑧ 다른 대상의 규정 끌어오기 모양의 학습 문항으로 LoRA 파인튜닝하는 실험(설계 `docs/superpowers/specs/2026-10-05-judge-finetune-design.md`)의 전제다. 실험의 도구는 v2 의 `tools/judge5*.py` 를 고치지 않고 `tools/judgeft_*.py` 로 새로 두며, v2 의 순수 함수만 불러 쓴다.

**왜 그렇게**
- v2 에서 M3 는 M1 과 구별되지 않았지만 심각한 놓침이 5 대 1 이라 교체 후보 기준 4에서 떨어졌고, 그중 4개가 ⑧ 이었다. M1 한 번이 Cloudflare 하루 무료 한도의 약 87% 를 쓰므로 M3 의 약점을 줄이는 쪽을 택했다.
- 서비스의 채점 모델은 바꾸지 않는다. 학습은 코랩에서만 하고, 산출물은 git 에 넣지 않는다.
- v2 도구의 분야, 할당량, 경로는 모듈 수준의 상수라 인자로 바꾸려면 v2 함수의 본문을 고쳐야 한다. 새 모듈이 v2 의 함수만 부르면 v2 파일이 바뀌지 않으므로 앞 실험의 보고서와 점검(44가지, 66가지)이 바뀔 수 없고, 검색과 채점의 규칙을 두 번 적지 않는다.

**검토한 대안**
① 공통 지시문에 대상을 대조하라는 단계를 넣는 프롬프트 수정 실험을 먼저 한다 → 사용자가 건너뛰기로 결정했다. 같은 효과를 프롬프트로 얻을 수 있었는지는 이 실험으로 알 수 없다.
② v2 도구에 인자를 더하고 기본값을 v2 그대로 둔다(스펙의 처음 글) → 기각. 고친 함수가 v2 를 그대로 재현하는지는 고친 뒤에야 확인할 수 있고, 확인에 실패하면 앞 실험의 결과가 흔들린다.
③ 작업 규칙 7번을 넓히지 않고 학습을 진행한다 → 기각. 규칙 7번은 추론만 열었다. 범위를 넓히는 일은 규칙에 먼저 적는다.
```

- [ ] **Step 4: 문서 규칙을 확인한다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft
git diff -U0 -- AGENTS.md docs/decisions.md | grep '^+' | grep -c "$(printf '\342\200\224')"
grep -n "연 것은 셋이다\|③ 채점 모델(M3\|2026-10-05 에 실험용 채점 모델 학습을\|채점 모델의 추론과 학습뿐" AGENTS.md
```

Expected: 첫 명령은 `0`(이 태스크가 더한 줄에 em dash 가 없다. `printf` 의 여덟 진수는 em dash 의 UTF-8 바이트다. AGENTS.md 의 기존 줄에는 em dash 가 있으므로 파일 전체가 아니라 더한 줄만 센다). 둘째 명령은 네 줄.

- [ ] **Step 5: 커밋한다**

```bash
git add AGENTS.md docs/decisions.md
git commit -m "docs: 작업 규칙 7번에 채점 모델 학습을 실험 용도로 열고 결정을 남긴다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- AGENTS.md docs/decisions.md
```

**리뷰 포인트:** 7번의 ⬜ 범위 밖 목록(생성 모델, 임베딩 모델 셀프호스팅, 온디바이스 추론 일반)이 그대로인가. AGENTS.md 에 수치나 결과가 들어가지 않았는가.

---

### Task 2: 공통 상수와 분야 도구

**Files:**
- Create: `ai-service/tools/judgeft_files.py`, `ai-service/tools/judgeft_fields.py`, `ai-service/tools/judgeft_fields_check.py`

**Interfaces:**
- Consumes: `tools.judge5v2_files` 의 `TABLE_SCORE`, `TYPE_NAMES`, `read_jsonl`, `write_jsonl`, `append_jsonl`, `read_json`, `write_json`, `latest_by_qid`, `value_in`, 그리고 v2 경로 `ANSWER_KEY`, `BOTS`, `CASES`, `QUESTIONS`, `RESULTS_DIR`
- Produces: `judgeft_files` 의 경로 상수(`FIELDS`, `BOTS`, `QUESTIONS`, `RETRIEVED`, `EXCLUDED`, `ASSIGNMENT`, `VARIANTS`, `TEMPLATES`, `TRAIN`, `VAL`, `TRAIN_DROPPED`, `TRAIN_SHA`, `REVIEW`, `CASES`, `CASES_SHA`, `ANSWER_KEY`, `MISMATCHES`, `GATE`, `GATE_A`, `DETERMINISM`, `RESULTS_DIR`, `REPORT`, `RUN_LOG`, `CORPUS`), v2 경로(`V2_ANSWER_KEY`, `V2_BOTS`, `V2_CASES`, `V2_QUESTIONS`, `V2_RESULTS_DIR`, `V2_ENV`), `SHEETS = ("new", "frozen")`, `FROZEN_SHA256`, `FIELD_CANDIDATES`, `SEED = 20261006`, `PROTECTED_BOTS`, `TRAIN_QUOTA`, `PAIRS`, `TEST_QUOTA`, `CONTRAST_FIVE`, `TEST_MIN_QUALIFIED`, `TRAIN_MIN_QUALIFIED`, `MAX_TEST_FIELDS`, `MAX_TRAIN_FIELDS`, `VAL_FRACTION`, `MIN_EIGHTH_AFTER_REVIEW`, `MIN_FIVE_AFTER_REVIEW`, `MIN_CONTRAST_FIVE_AFTER_REVIEW`, `GATE_A_RATIO`, `M3_REPO`, `M3_REVISION`, LoRA 와 학습 상수, `PINS`, `MODEL_KEYS`, `result_path(sheet, model, run) -> Path`, `fields_doc() -> dict`, `test_fields()`, `train_fields()`, `sheet_of(field) -> str`. `judgeft_fields` 의 `initial_order(seed) -> dict`, `open_field(doc, sheet, new) -> dict`

- [ ] **Step 1: 점검을 먼저 쓴다**

```python
"""tools.judgeft_files, tools.judgeft_fields 의 점검. DB 도 외부 API 도 쓰지 않는다.

실행:  cd ai-service && python -m tools.judgeft_fields_check
"""
from __future__ import annotations

from .judgeft_fields import initial_order, open_field
from .judgeft_files import (
    CONTRAST_FIVE, FIELD_CANDIDATES, PAIRS, TEST_MIN_QUALIFIED, TEST_QUOTA, TRAIN_MIN_QUALIFIED, TRAIN_QUOTA,
)


def check_quotas_match_spec() -> None:
    """스펙 4-4절의 표: 학습 600(⑧ 240, 짝 120), 새 시험지 120(⑧ 60), 대상이 둘인 ①② 12, 확장 기준 72와 240."""
    assert sum(TRAIN_QUOTA.values()) + PAIRS == 600 and TRAIN_QUOTA[8] == 240 and PAIRS == 120
    assert sum(TEST_QUOTA.values()) == 120 and TEST_QUOTA[8] == 60
    assert sum(CONTRAST_FIVE.values()) == 12 and all(CONTRAST_FIVE[t] <= TEST_QUOTA[t] for t in CONTRAST_FIVE)
    assert TEST_MIN_QUALIFIED == 72 and TRAIN_MIN_QUALIFIED == 240


def check_order_is_seeded_and_complete() -> None:
    a, b = initial_order(), initial_order()
    assert a == b                                            # 같은 시드면 같은 순서
    assert sorted(a["order"]) == sorted(FIELD_CANDIDATES)
    assert a["test"] + a["train"] + a["reserve"] == a["order"] and len(a["train"]) == 2
    assert initial_order(seed=1)["order"] != a["order"] or initial_order(seed=2)["order"] != a["order"]


def check_open_follows_rules() -> None:
    doc = initial_order()
    t = open_field(doc, "test")
    assert len(t["test"]) == 2 and t["reserve"] == [] and doc["reserve"]   # 원래 doc 은 그대로
    for bad in (lambda: open_field(t, "test"),                 # 시험용 셋째는 없다
                lambda: open_field(t, "train"),                # 예비가 없으면 --new 가 필요하다
                lambda: open_field(t, "train", "hr"),          # v2 의 분야는 쓰지 않는다
                lambda: open_field(t, "train", "Pharmacy"),    # 영어 소문자만
                lambda: open_field(doc, "train", "pharmacy")):  # 예비가 남았으면 예비를 쓴다
        try:
            bad()
        except ValueError:
            continue
        raise AssertionError("규칙을 어긴 분야 열기가 통과했다")
    tr = open_field(t, "train", "pharmacy")
    assert tr["train"][-1] == "pharmacy" and tr["opened"][-1] == {"sheet": "train", "field": "pharmacy"}
    try:
        open_field(tr, "train", "insurance")                   # 학습용 넷째는 없다
    except ValueError:
        return
    raise AssertionError("학습용 넷째 분야가 열렸다")


CHECKS = [check_quotas_match_spec, check_order_is_seeded_and_complete, check_open_follows_rules]


def main() -> None:
    for fn in CHECKS:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(CHECKS)}가지 전부 통과.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 점검이 실패하는지 본다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft/ai-service
$PY -m tools.judgeft_fields_check
```

Expected: `ModuleNotFoundError: No module named 'tools.judgeft_fields'`

- [ ] **Step 3: 공통 상수를 쓴다**

```python
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
```

- [ ] **Step 4: 분야 도구를 쓴다**

```python
"""분야 순서를 시드로 정하고, 필요할 때 분야를 연다(스펙 3-2절, 3-3절).

실행:
    cd ai-service
    $PY -m tools.judgeft_fields order               # 처음 한 번. fields.json 이 없어야 한다
    $PY -m tools.judgeft_fields open test           # 예비 분야를 두 번째 시험용 분야로 연다(스펙 3-3절 1)
    $PY -m tools.judgeft_fields open train          # 세 번째 학습용 분야를 연다. 예비 분야가 남아 있으면 그것
    $PY -m tools.judgeft_fields open train --new pharmacy   # 예비 분야가 이미 쓰였으면 새 분야 이름을 준다

어느 분야가 시험용인지를 시드로 정하는 이유: 출제 세션이 ⑧ 을 만들기 쉬운 분야를 시험용으로 고르면
시험이 학습 데이터와 비슷한 쪽으로 치우칠 수 있다(스펙 3-2절).
"""
from __future__ import annotations

import argparse
import random
import re
import sys

from .judgeft_files import (
    FIELD_CANDIDATES, FIELDS, MAX_TEST_FIELDS, MAX_TRAIN_FIELDS, SEED, read_json, write_json,
)
from .judge5v2_files import DOMAINS as V2_DOMAINS


def initial_order(seed: int = SEED) -> dict:
    """네 후보를 시드로 섞는다. 첫째가 시험용, 둘째와 셋째가 학습용, 넷째가 예비 분야다.

    sorted 로 먼저 줄 세우는 이유: FIELD_CANDIDATES 의 적힌 순서가 바뀌어도 같은 시드에서 같은 결과가 나오게 한다.
    """
    order = sorted(FIELD_CANDIDATES)
    random.Random(f"{seed}:fields").shuffle(order)
    return {"seed": seed, "order": order, "test": [order[0]], "train": order[1:3], "reserve": [order[3]],
            "opened": []}


def open_field(doc: dict, sheet: str, new: str | None = None) -> dict:
    """분야 하나를 연다. 원래 doc 은 고치지 않고 새 dict 를 돌려준다. 규칙을 어기면 ValueError."""
    doc = {k: (list(v) if isinstance(v, list) else v) for k, v in doc.items()}
    used = set(doc["test"]) | set(doc["train"])
    if sheet == "test":
        if new is not None:
            raise ValueError("시험용 분야는 예비 분야만 연다(스펙 3-3절 1). --new 를 주지 않는다")
        if len(doc["test"]) >= MAX_TEST_FIELDS:
            raise ValueError(f"시험용 분야는 {MAX_TEST_FIELDS}개까지다(스펙 3-3절 3). 멈추고 사용자에게 보인다")
        if not doc["reserve"]:
            raise ValueError("예비 분야가 이미 쓰였다. 멈추고 사용자에게 보인다")
        field = doc["reserve"].pop()
        doc["test"].append(field)
    elif sheet == "train":
        if len(doc["train"]) >= MAX_TRAIN_FIELDS:
            raise ValueError(f"학습용 분야는 {MAX_TRAIN_FIELDS}개까지다(스펙 3-3절 3). 멈추고 사용자에게 보인다")
        if doc["reserve"]:
            if new is not None:
                raise ValueError("예비 분야가 남아 있으면 예비 분야를 쓴다(스펙 3-3절 2). --new 를 주지 않는다")
            field = doc["reserve"].pop()
        else:
            # 새 분야 이름은 폴더 이름과 qid 앞머리가 되므로 영어 소문자만 받는다.
            if not new or not re.fullmatch(r"[a-z]+", new):
                raise ValueError("예비 분야가 이미 쓰였다. --new 로 새 분야 이름(영어 소문자)을 준다")
            if new in used or new in FIELD_CANDIDATES or new in V2_DOMAINS:
                raise ValueError(f"{new} 는 이미 쓴 분야이거나 v2 의 분야다(스펙 3-3절 2)")
            field = new
        doc["train"].append(field)
    else:
        raise ValueError("sheet 는 test 또는 train 이다")
    doc["opened"].append({"sheet": sheet, "field": field})
    return doc


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="분야 순서를 정하고 분야를 연다")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("order")
    o = sub.add_parser("open")
    o.add_argument("sheet", choices=("test", "train"))
    o.add_argument("--new", default=None)
    args = p.parse_args(argv)
    if args.cmd == "order":
        if FIELDS.exists():
            print("fields.json 이 이미 있습니다. 순서는 한 번만 정합니다.")
            return 1
        doc = initial_order()
    else:
        try:
            doc = open_field(read_json(FIELDS), args.sheet, args.new)
        except ValueError as e:
            print(f"분야를 열지 않았습니다: {e}")
            return 1
    write_json(FIELDS, doc)
    print(f"시험용 {doc['test']}, 학습용 {doc['train']}, 예비 {doc['reserve']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: 점검이 통과하는지 본다**

```bash
$PY -m tools.judgeft_fields_check | tail -1
$PY -m tools.judge5_check | tail -1 && $PY -m tools.judge5v2_check | tail -1
```

Expected: `3가지 전부 통과.`, `44가지 전부 통과.`, `66가지 전부 통과.`

- [ ] **Step 6: 커밋한다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft
git add ai-service/tools/judgeft_files.py ai-service/tools/judgeft_fields.py ai-service/tools/judgeft_fields_check.py
git commit -m "feat: 파인튜닝 실험의 경로, 상수, 분야 순서 도구를 더한다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/tools/judgeft_files.py ai-service/tools/judgeft_fields.py ai-service/tools/judgeft_fields_check.py
```

**리뷰 포인트:** `M3_REVISION` 이 v2 결과 1절의 `f790ee74` 로 시작하는 전체 해시인가(`huggingface_hub.model_info` 로 확인할 수 있다). 할당량의 합이 600, 120 이고 스펙 4-4절의 표와 같은가. `FROZEN_SHA256` 이 v2 결과 1절의 해시와 같은가.

---

### Task 3: 검색 도구

**Files:**
- Create: `ai-service/tools/judgeft_search.py`, `ai-service/tools/judgeft_search_check.py`

**Interfaces:**
- Consumes: 태스크 2 의 `BOTS`, `PROTECTED_BOTS`, `QUESTIONS`, `RETRIEVED`, `V2_BOTS`, `fields_doc`. `tools.judge5v2_search` 의 `search_one`, `search_settings`, `nondefault_settings`, `settings_conflicts`, `settled_qids`
- Produces: `parse_bots(items, fields, protected) -> dict[str, int]`, `protected_bots() -> frozenset[int]`, 명령 `python -m tools.judgeft_search --bot <분야>=<번호> ...`

검색 한 건의 동작(임베딩, 서비스 검색, 근거 청크 전문 다시 읽기, 리랭커와 키워드 검색 실패 감지, 빈 결과의 원인)은 v2 의 `search_one` 을 그대로 쓴다. v2 의 점검(`judge5v2_search_check` 14가지)이 이미 그 동작을 본다. v2 와 다른 점은 셋이다: 분야가 `fields.json` 에서 오고, v2 의 봇 넷도 막으며, `--allow-nondefault` 를 두지 않는다.

- [ ] **Step 1: 점검을 먼저 쓴다**

```python
"""tools.judgeft_search 의 점검. DB 도 외부 API 도 쓰지 않는다.

실행:  cd ai-service && python -m tools.judgeft_search_check

검색 한 건의 동작은 v2 의 judge5v2_search_check 가 이미 본다. 여기서는 이 실험에서 달라진 것만 본다.
"""
from __future__ import annotations

from .judgeft_search import parse_bots


def _refused(fn) -> bool:
    try:
        fn()
    except SystemExit:
        return True
    return False


def check_parse_bots_accepts_open_fields() -> None:
    assert parse_bots(["travel=13", "school=15"], ["school", "travel"], frozenset({1})) == {"travel": 13, "school": 15}


def check_parse_bots_refuses_protected_and_unknown() -> None:
    fields, prot = ["school", "travel"], frozenset({1, 7, 8, 9})
    assert _refused(lambda: parse_bots(["travel=9"], fields, prot))       # v2 의 봇
    assert _refused(lambda: parse_bots(["hospital=13"], fields, prot))    # 열지 않은 분야(예비)
    assert _refused(lambda: parse_bots(["travel=13", "school=13"], fields, prot))
    assert _refused(lambda: parse_bots(["travel=x"], fields, prot))


CHECKS = [check_parse_bots_accepts_open_fields, check_parse_bots_refuses_protected_and_unknown]


def main() -> None:
    for fn in CHECKS:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(CHECKS)}가지 전부 통과.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 점검이 실패하는지 본다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft/ai-service
$PY -m tools.judgeft_search_check
```

Expected: `ModuleNotFoundError: No module named 'tools.judgeft_search'`

- [ ] **Step 3: 검색 도구를 쓴다**

```python
"""질문마다 실제 검색으로 근거 청크 전문을 뽑는다(스펙 3-4절, v2 스펙 2-3절).

실행:
    cd ai-service
    $PY -m tools.judgeft_search --bot travel=13 --bot telecom=14 [--limit N]

검색 한 건의 일(임베딩, 검색, 전문 다시 읽기, 리랭커와 키워드 검색 실패 감지, 빈 결과의 원인)은 v2 의
judge5v2_search.search_one 을 그대로 쓴다. 이 파일은 경로, 분야, 봇 번호 확인만 다르다. 같은 검색 규칙을
두 번 적으면 한쪽만 고쳐지기 때문이다.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter

from app import cf

from .judgeft_files import (
    BOTS, PROTECTED_BOTS, QUESTIONS, RETRIEVED, V2_BOTS, append_jsonl, fields_doc, read_json, read_jsonl,
)
from .judge5v2_search import nondefault_settings, search_one, search_settings, settings_conflicts, settled_qids


def protected_bots() -> frozenset[int]:
    """건드리지 않는 봇: 데모 봇, 리랭커 실험 봇, v2 의 봇 넷(스펙 3-4절)."""
    v2 = set(read_json(V2_BOTS).values()) if V2_BOTS.exists() else set()
    return PROTECTED_BOTS | frozenset(v2)


def parse_bots(items: list[str], fields: list[str], protected: frozenset[int]) -> dict[str, int]:
    """--bot travel=13 꼴을 {"travel": 13} 으로 바꾼다. 열지 않은 분야, 막은 봇, 겹친 분야와 번호를 거절한다."""
    out: dict[str, int] = {}
    for item in items:
        field, _, num = item.partition("=")   # partition 은 첫 "=" 에서 셋으로 자른다
        if field not in fields or not num.isdigit():
            raise SystemExit(f"--bot 은 분야=번호 꼴입니다. 열린 분야는 {', '.join(fields)}. 받은 값: {item}")
        bot_id = int(num)
        if bot_id in protected:
            raise SystemExit(f"봇 {bot_id}번은 이 실험에서 쓰지 않습니다(데모, 리랭커 실험, v2 의 봇). "
                             f"testdata/judgeft/bots.json 의 번호를 주세요.")
        if field in out or bot_id in out.values():
            raise SystemExit(f"--bot 에 같은 분야나 같은 번호가 두 번 있습니다: {item}")
        out[field] = bot_id
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="파인튜닝 실험의 질문마다 근거 청크 전문을 뽑는다")
    p.add_argument("--bot", action="append", required=True, help="분야=봇 번호. 분야마다 한 번씩")
    p.add_argument("--limit", type=int, default=None, help="이번 실행에서 검색할 최대 질문 수")
    args = p.parse_args(argv)
    doc = fields_doc()
    bots = parse_bots(args.bot, doc["test"] + doc["train"], protected_bots())
    if not BOTS.exists():
        print("testdata/judgeft/bots.json 이 없습니다. 계획 E2 가 봇을 만들고 남기는 파일입니다.")
        return 1
    recorded = read_json(BOTS)
    if wrong := [f"{f}={n}(기록은 {recorded.get(f)})" for f, n in bots.items() if recorded.get(f) != n]:
        print(f"--bot 이 bots.json 과 다릅니다: {', '.join(wrong)}")
        return 1
    settings = search_settings()
    # 이 실험은 기본 설정만 쓴다. v2 처럼 --allow-nondefault 를 두지 않는다(쓸 일이 없는 문을 열어 두지 않는다).
    if diff := nondefault_settings(settings):
        print("검색 설정이 config.py 의 기본값과 다릅니다. 셸의 환경변수나 .env 를 확인하세요:")
        for k, d in diff.items():
            print(f"  - {k}: 기본값 {d['default']!r}, 지금 {d['actual']!r}")
        return 1
    questions = read_jsonl(QUESTIONS)
    if dup := [k for k, n in Counter(q["qid"] for q in questions).items() if n > 1]:
        print(f"questions.jsonl 에 같은 qid 가 두 번 있습니다: {dup[:5]}")
        return 1
    existing = read_jsonl(RETRIEVED)
    if conflicts := settings_conflicts(existing, settings):
        print(f"retrieved.jsonl 에 지금과 다른 검색 설정의 줄이 {len(conflicts)}개 있습니다. 멈춥니다: {conflicts[:3]}")
        return 1
    done = settled_qids(existing)
    todo = [q for q in questions if q["domain"] in bots and q["qid"] not in done][: args.limit]
    counts: Counter = Counter()
    for q in todo:
        row = search_one(bots[q["domain"]], q["question"])
        append_jsonl(RETRIEVED, {"qid": q["qid"], "domain": q["domain"], "bot_id": bots[q["domain"]],
                                 "settings": settings, **row})
        counts[(q["domain"], row["drop_reason"] or "ok")] += 1
    for (field, reason), n in sorted(counts.items()):
        print(f"{field}: {reason} {n}")
    print(f"이번 실행의 뉴런: {cf.neurons_used()}")
    rows = read_jsonl(RETRIEVED)
    tried, done = {r["qid"] for r in rows}, settled_qids(rows)
    mine = [q["qid"] for q in questions if q["domain"] in bots]
    if failed := sum(1 for qid in mine if qid in tried and qid not in done):
        print(f"호출 실패로 버린 질문 {failed}개. 같은 명령을 다시 실행하면 그 질문만 다시 검색합니다(v2 스펙 2-3절).")
    if never := sum(1 for qid in mine if qid not in tried):
        print(f"아직 검색하지 않은 질문 {never}개. 같은 명령을 다시 실행하면 이어서 합니다.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 점검이 통과하는지 본다**

```bash
$PY -m tools.judgeft_search_check | tail -1
```

Expected: `2가지 전부 통과.`

- [ ] **Step 5: 커밋한다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft
git add ai-service/tools/judgeft_search.py ai-service/tools/judgeft_search_check.py
git commit -m "feat: 파인튜닝 실험의 검색 도구를 v2 의 검색 함수 위에 더한다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/tools/judgeft_search.py ai-service/tools/judgeft_search_check.py
```

**리뷰 포인트:** 검색 결과 줄의 모양이 v2 계획 형식 2 와 같은가(배정 도구가 `latest_by_qid` 로 마지막 줄을 본다). 검색 설정이 기본값과 다르면 호출 전에 멈추는가.

---

### Task 4: 배정 도구

**Files:**
- Create: `ai-service/tools/judgeft_assign.py`, `ai-service/tools/judgeft_assign_check.py`

**Interfaces:**
- Consumes: 태스크 2 의 상수. `tools.judge5v2_assign` 의 `eligible3`, `eligible4`, `eligible6`, `eligible8`, `excluded_problems`, `valid_contrast`. 보충에서 태스크 6 의 `kept_test`, `kept_train`(늦은 import)
- Produces: `pools_by_sheet(questions, retrieved, excluded, doc) -> {"test": [...], "train": [...]}`, `qualified_counts(pools) -> {분야: {"pool", "qualified"}}`, `assign_test(pool, needs, contrast, rng) -> dict`, `assign_train(pool, needs, n_pairs, pair_from, rng) -> dict`, `run_round(sheet, pool, rnd, seed) -> dict`, `replay(assignment, questions_by_id) -> list[str]`, `assigned(assignment, sheet) -> (types, pairs, contrast_five)`, `supplement_needs(...)`, `Shortfall`, 명령 `count`, `first`, `supplement test|train`

v2 의 배정 함수를 쓰지 않는 이유는 모듈 머리말에 적었다(⑧ 이 모자라면 ⑥ 으로 돌리는 v2 의 규칙 대신 이 실험은 분야를 늘리고, 짝 문항과 대상이 둘인 ①② 를 더 뽑는다).

- [ ] **Step 1: 점검을 먼저 쓴다**

```python
"""tools.judgeft_assign 의 점검. DB 도 외부 API 도 쓰지 않는다.

실행:  cd ai-service && python -m tools.judgeft_assign_check
"""
from __future__ import annotations

import random

from .judge5v2_assign import eligible3, eligible4, eligible6, eligible8
from .judgeft_assign import (
    Shortfall, assign_test, assign_train, dry_run, pools_by_sheet, qualified_counts, replay, run_round, supplement_needs,
)
from .judgeft_files import CONTRAST_FIVE, PAIRS, SEED, TEST_QUOTA, TRAIN_QUOTA

DOC = {"test": ["school"], "train": ["travel", "telecom"], "reserve": ["hospital"]}


def _q(field: str, i: int, *, two: bool, claims: int, contrast: bool) -> tuple[dict, dict]:
    """(질문 줄, 검색 줄) 한 쌍. contrast 이면 근거 청크에 값이 다른 두 대상이 함께 있다."""
    qid = f"{field}-{i:03d}"
    text = "일반석 20,000원, 비즈니스석 50,000원" if contrast else "수수료는 3,000원"
    c = ({"asked": {"target": "일반석", "value": "20,000원"}, "other": {"target": "비즈니스석", "value": "50,000원"},
          "chunk_ids": [i]} if contrast else None)
    q = {"qid": qid, "domain": field, "question": f"질문 {qid}", "two_part": two, "answer": f"답 {qid}",
         "claims": claims, "contrast": c}
    r = {"qid": qid, "domain": field, "status": "ok", "drop_reason": None,
         "sources": [{"chunk_id": i, "filename": "a.md", "content": text}]}
    return q, r


def _data(n_test: int = 150, n_train: int = 620) -> tuple[list[dict], list[dict]]:
    """시험용 150, 학습용 620 질문. 셋 중 하나는 답이 두 가지(주장 2), 나머지는 답이 하나이고 ⑧ 조건을 만족한다."""
    qs, rs = [], []
    for field, n, base in (("school", n_test, 0), ("travel", n_train // 2, 10_000), ("telecom", n_train // 2, 20_000)):
        for i in range(n):
            two = i % 3 == 0
            q, r = _q(field, base + i, two=two, claims=2 if two or i % 3 == 1 else 1,
                      contrast=not two)
            qs.append(q)
            rs.append(r)
    return qs, rs


def check_pools_split_by_sheet_and_skip_reserve() -> None:
    qs, rs = _data()
    extra_q, extra_r = _q("hospital", 99_999, two=False, claims=1, contrast=False)   # 예비 분야의 질문
    pools = pools_by_sheet(qs + [extra_q], rs + [extra_r], {}, DOC)
    assert {q["domain"] for q in pools["test"]} == {"school"}
    assert {q["domain"] for q in pools["train"]} == {"travel", "telecom"}
    assert all(q["domain"] != "hospital" for p in pools.values() for q in p)
    counts = qualified_counts(pools)
    assert counts["school"]["qualified"] == sum(1 for q in pools["test"] if eligible8(q))


def check_test_assignment_meets_quota_and_eligibility() -> None:
    qs, rs = _data()
    pool = pools_by_sheet(qs, rs, {}, DOC)["test"]
    res = assign_test(pool, TEST_QUOTA, CONTRAST_FIVE, random.Random(f"{SEED}:test:0"))
    got = {t: sum(1 for v in res["types"].values() if v == t) for t in TEST_QUOTA}
    assert got == TEST_QUOTA, got
    by = {q["qid"]: q for q in pool}
    rules = {4: eligible4, 8: eligible8, 3: eligible3, 6: eligible6}
    assert all(rules[t](by[q]) for q, t in res["types"].items() if t in rules)
    assert len(res["contrast_five"]) == 12 and all(eligible8(by[q]) and res["types"][q] in (1, 2)
                                                   for q in res["contrast_five"])


def check_train_assignment_has_pairs_from_eighth() -> None:
    qs, rs = _data()
    pool = pools_by_sheet(qs, rs, {}, DOC)["train"]
    res = assign_train(pool, TRAIN_QUOTA, PAIRS, [], random.Random(f"{SEED}:train:0"))
    got = {t: sum(1 for v in res["types"].values() if v == t) for t in TRAIN_QUOTA}
    assert got == TRAIN_QUOTA, got
    assert len(res["pairs"]) == PAIRS and all(res["types"][q] == 8 for q in res["pairs"])


def check_shortfall_stops_instead_of_moving() -> None:
    """⑧ 이 모자라면 v2 처럼 ⑥ 으로 돌리지 않고 멈춘다(스펙 3-3절은 분야를 늘린다)."""
    qs, rs = _data(n_test=60)
    pool = pools_by_sheet(qs, rs, {}, DOC)["test"]
    try:
        assign_test(pool, TEST_QUOTA, CONTRAST_FIVE, random.Random(0))
    except Shortfall as e:
        assert "8" in e.short or "contrast1" in e.short
        return
    raise AssertionError("⑧ 이 모자란데 배정이 통과했다")


def check_replay_reproduces_and_catches_tampering() -> None:
    qs, rs = _data()
    pools = pools_by_sheet(qs, rs, {}, DOC)
    rounds = []
    for sheet, quota, extra in (("test", TEST_QUOTA, {"contrast_needs": {str(t): n for t, n in CONTRAST_FIVE.items()}}),
                                ("train", TRAIN_QUOTA, {"pair_needs": PAIRS, "pair_from": []})):
        rnd = {"round": 0, "sheet": sheet, "pool": sorted(q["qid"] for q in pools[sheet]),
               "needs": {str(t): n for t, n in quota.items()}, **extra}
        rnd.update(run_round(sheet, pools[sheet], rnd, SEED))
        rounds.append(rnd)
    by = {q["qid"]: q for q in qs}
    assert replay({"seed": SEED, "rounds": rounds}, by) == []
    first = next(iter(rounds[0]["types"]))
    rounds[0]["types"][first] = 7 if rounds[0]["types"][first] != 7 else 5
    assert replay({"seed": SEED, "rounds": rounds}, by) == ["test 회차 0"]


def check_supplement_needs_refill_to_quota() -> None:
    kept = {f"t{i}": t for i, t in enumerate([8] * 50 + [1] * 8 + [2] * 10)}
    five = {f"t{i}" for i in range(50, 54)}        # 대상이 둘인 ① 넷만 남았다
    plan = supplement_needs("test", {}, kept, set(), five)
    assert plan["needs"][8] == 10 and plan["contrast_needs"] == {"1": 2, "2": 6}
    assert plan["needs"][1] == 2 and plan["needs"][2] == 6 and 4 not in plan["needs"]   # ④ 는 보충하지 않는다
    train_kept = {f"r{i}": 8 for i in range(238)}
    tp = supplement_needs("train", {}, train_kept, {f"r{i}" for i in range(118)}, set())
    assert tp["needs"][8] == 2 and tp["pair_needs"] == 2 and len(tp["pair_from"]) == 120


def check_count_runs_first_assignment_not_just_qualified_total() -> None:
    """⑧ 자격이 기준(72)과 같아도, 주장 2 인 ⑧ 자격을 ④ 가 먼저 가져가면 첫 배정은 모자란다.
    count 의 판정(dry_run)은 첫 배정을 그대로 돌려 보므로 이 모자람을 미리 낸다. 결과는 first 와 같아야 한다."""
    qs, rs = [], []
    for i in range(150):
        if i < 72:                                   # ⑧ 자격 72, 그중 24 는 주장 2 라 ④ 의 자격도 있다
            q, r = _q("school", i, two=False, claims=2 if i < 24 else 1, contrast=True)
        elif i < 112:                                # 답이 두 가지(④, ③ 후보)
            q, r = _q("school", i, two=True, claims=2, contrast=False)
        else:                                        # 답이 하나, ⑧ 조건 없음(⑥ 후보)
            q, r = _q("school", i, two=False, claims=1, contrast=False)
        qs.append(q)
        rs.append(r)
    pool = pools_by_sheet(qs, rs, {}, DOC)["test"]
    assert sum(1 for q in pool if eligible8(q)) == 72
    d = dry_run("test", pool, SEED)
    assert d["eighth_left"] < 72 and set(d["short"]) & {"8", "contrast1", "contrast2"}, d
    try:
        assign_test(pool, TEST_QUOTA, CONTRAST_FIVE, random.Random(f"{SEED}:test:0"))
    except Shortfall as e:
        assert e.short == d["short"], (e.short, d["short"])
    else:
        raise AssertionError("dry_run 은 모자란다고 했는데 첫 배정이 통과했다")
    qs2, rs2 = _data()                               # 넉넉한 입력에서는 모자람이 없다
    assert dry_run("test", pools_by_sheet(qs2, rs2, {}, DOC)["test"], SEED)["short"] == {}


CHECKS = [check_pools_split_by_sheet_and_skip_reserve, check_test_assignment_meets_quota_and_eligibility,
          check_train_assignment_has_pairs_from_eighth, check_shortfall_stops_instead_of_moving,
          check_replay_reproduces_and_catches_tampering, check_supplement_needs_refill_to_quota,
          check_count_runs_first_assignment_not_just_qualified_total]


def main() -> None:
    for fn in CHECKS:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(CHECKS)}가지 전부 통과.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 점검이 실패하는지 본다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft/ai-service
$PY -m tools.judgeft_assign_check
```

Expected: `ModuleNotFoundError: No module named 'tools.judgeft_assign'`

- [ ] **Step 3: 배정 도구를 쓴다**

```python
"""파인튜닝 실험의 변형 유형 배정(스펙 4-2절, 4-4절).

실행:
    cd ai-service
    $PY -m tools.judgeft_assign count                 # ⑧ 자격 수를 세고 첫 배정을 돌려 본다(스펙 3-3절, 계획 E3, E5)
    $PY -m tools.judgeft_assign first                 # 첫 배정. 시험용과 학습용을 한 번에 한다
    $PY -m tools.judgeft_assign supplement test       # 검수 뒤 조건(스펙 4-4절)을 채우지 못했을 때
    $PY -m tools.judgeft_assign supplement train      # 글자 확인으로 학습 문항이 빠졌을 때(스펙 4-4절)

v2 의 judge5v2_assign 을 고치지 않고 자격 조건 함수(eligible3, 4, 6, 8), ⑧ 조건 확인(valid_contrast),
제외 확인(excluded_problems)만 가져다 쓴다. v2 의 배정 함수는 분야 넷과 ⑧ 이 모자라면 ⑥ 으로 돌리는 규칙에
묶여 있고, 이 실험은 짝 문항과 대상이 둘인 ①② 를 더 뽑아야 해서 순서가 다르다.

배정을 출제 세션의 판단이 아니라 시드로 정하는 이유는 v2 와 같다: 망가뜨리기 쉬운 질문에 어려운 유형이 몰리지 않게 한다.
"""
from __future__ import annotations

import argparse
import random
import sys
from collections import Counter

from .judge5 import sha256_file
from .judge5v2_assign import eligible3, eligible4, eligible6, eligible8, excluded_problems, valid_contrast
from .judgeft_files import (
    ASSIGNMENT, CONTRAST_FIVE, EXCLUDED, PAIRS, QUESTIONS, RETRIEVED, SEED, TEST_MIN_QUALIFIED, TEST_QUOTA,
    TRAIN_MIN_QUALIFIED, TRAIN_QUOTA, fields_doc, latest_by_qid, read_json, read_jsonl, write_json,
)

REST_ORDER = (1, 2, 5, 7)   # 자격 조건이 없는 유형을 채우는 순서(v2 스펙 3-3절과 같다)


class Shortfall(Exception):
    """할당량을 채우지 못했다. short 는 {이름: 모자란 수} 다. 이름은 유형 번호 문자열, "contrast1" 등, "pairs"."""

    def __init__(self, short: dict[str, int]) -> None:
        super().__init__(short)
        self.short = short


def _file_sha(path) -> str | None:
    return sha256_file(path) if path.exists() else None


def pools_by_sheet(questions: list[dict], retrieved: list[dict], excluded: dict, doc: dict) -> dict[str, list[dict]]:
    """검색을 통과했고 제외하지 않았으며 답변 칸이 제대로 적힌 질문을 시험용(test)과 학습용(train)으로 나눈다.

    열지 않은 분야(예비 분야)의 질문은 넣지 않는다. 칸이 하나라도 잘못되면 ValueError 로 전부 알린다.
    """
    if bad := excluded_problems(excluded, questions, retrieved):
        raise ValueError("excluded.json 을 고친다:\n  - " + "\n  - ".join(bad))
    ok = {r["qid"]: r for r in latest_by_qid(retrieved) if r["status"] == "ok"}
    sheet_of = {f: "test" for f in doc["test"]} | {f: "train" for f in doc["train"]}   # | 는 두 dict 를 합친다
    out: dict[str, list[dict]] = {"test": [], "train": []}
    problems = []
    for q in questions:
        r = ok.get(q["qid"])
        if r is None or q["qid"] in excluded or q["domain"] not in sheet_of:
            continue
        # type(x) is int: bool 도 int 의 하위형이라 isinstance 로는 true 가 1 로 통과한다. 정확히 int 만 받는다.
        if not q.get("answer") or type(q.get("claims")) is not int or q["claims"] < 1:
            problems.append(f"{q['qid']}: answer 또는 claims 가 비었다")
        elif not isinstance(q.get("two_part"), bool):
            problems.append(f"{q['qid']}: two_part 가 true 나 false 가 아니다")
        elif q["two_part"] and q.get("contrast") is not None:
            problems.append(f"{q['qid']}: 답이 두 가지인 질문에는 contrast 를 적지 않는다")
        elif q.get("contrast") is not None and (why := valid_contrast(q["contrast"], r["sources"])):
            problems.append(f"{q['qid']}: ⑧ 조건이 잘못됐다({why})")
        else:
            out[sheet_of[q["domain"]]].append(q)
    if problems:
        raise ValueError("questions.jsonl 을 고친다:\n  - " + "\n  - ".join(problems))
    return out


def qualified_counts(pools: dict[str, list[dict]]) -> dict[str, dict[str, int]]:
    """분야마다 {"pool": 후보 수, "qualified": ⑧ 자격 질문 수}. 스펙 3-3절의 분야 늘리기와 계획 E3 의 비율에 쓴다."""
    out: dict[str, dict[str, int]] = {}
    for qs in pools.values():
        for q in qs:
            c = out.setdefault(q["domain"], {"pool": 0, "qualified": 0})
            c["pool"] += 1
            c["qualified"] += int(eligible8(q))
    return out


class _Picker:
    """한 배정 회차의 뽑기. 질문은 qid 순으로 먼저 줄 세운다(입력 순서와 무관하게 같은 시드에서 같은 결과)."""

    def __init__(self, pool: list[dict], rng: random.Random) -> None:
        self.pool = sorted(pool, key=lambda q: q["qid"])
        self.rng = rng
        self.types: dict[str, int] = {}
        self.short: dict[str, int] = {}

    def take(self, t: int, n: int, ok, name: str | None = None) -> list[str]:
        """자격(ok)을 만족하고 아직 쓰지 않은 질문에서 n 개를 뽑아 유형 t 를 붙인다. 모자라면 short 에 적는다.
        rng.sample(목록, k) 는 목록에서 k 개를 중복 없이 뽑는다. 같은 시드의 Random 이면 늘 같은 k 개다."""
        cands = [q for q in self.pool if q["qid"] not in self.types and ok(q)]
        got = self.rng.sample(cands, min(n, len(cands)))
        for q in got:
            self.types[q["qid"]] = t
        if len(got) < n:
            self.short[name or str(t)] = n - len(got)
        return sorted(q["qid"] for q in got)

    def rest(self, needs: dict[int, int]) -> list[str]:
        """자격 조건이 없는 유형을 REST_ORDER 대로 남은 질문을 섞어 앞에서부터 채운다. 남은 질문을 돌려준다."""
        rest = [q for q in self.pool if q["qid"] not in self.types]
        self.rng.shuffle(rest)
        i = 0
        for t in REST_ORDER:
            chunk = rest[i:i + needs.get(t, 0)]
            if len(chunk) < needs.get(t, 0):
                self.short[str(t)] = needs[t] - len(chunk)
            for q in chunk:
                self.types[q["qid"]] = t
            i += len(chunk)
        return sorted(q["qid"] for q in rest[i:])


def assign_test(pool: list[dict], needs: dict[int, int], contrast: dict[int, int], rng: random.Random) -> dict:
    """새 시험지 배정. 순서: ④, ⑧, 대상이 둘인 ①②, ③, ⑥, 나머지(①, ②, ⑤, ⑦).

    ⑧ 다음에 대상이 둘인 ①② 를 뽑는 이유: 둘 다 ⑧ 자격 질문에서 나오므로, ③ 이나 나머지가 먼저 가져가면
    모자랄 수 있다. ⑧ 이 모자라도 ⑥ 으로 돌리지 않는다. 이 시험지의 목적이 ⑧ 이라 분야를 늘린다(스펙 3-3절).
    """
    p = _Picker(pool, rng)
    p.take(4, needs.get(4, 0), eligible4)
    p.take(8, needs.get(8, 0), eligible8)
    five = []
    for t in (1, 2):
        five += p.take(t, contrast.get(t, 0), eligible8, f"contrast{t}")
    p.take(3, needs.get(3, 0), eligible3)
    p.take(6, needs.get(6, 0), eligible6)
    rest_needs = {t: needs.get(t, 0) - contrast.get(t, 0) for t in REST_ORDER}
    unused = p.rest(rest_needs)
    if p.short:
        raise Shortfall(p.short)
    return {"types": p.types, "contrast_five": sorted(five), "pairs": [], "unused": unused}


def assign_train(pool: list[dict], needs: dict[int, int], n_pairs: int, pair_from: list[str],
                 rng: random.Random) -> dict:
    """학습 데이터 배정. 순서: ④, ⑧, ③, ⑥, 나머지. 그다음 짝 문항을 ⑧ 질문에서 뽑는다(스펙 4-2절).

    pair_from 은 앞 회차에서 ⑧ 을 받았지만 짝이 없는 질문이다(보충 회차에서만 쓴다). 이번 회차의 ⑧ 과 합쳐 뽑는다.
    """
    p = _Picker(pool, rng)
    p.take(4, needs.get(4, 0), eligible4)
    p.take(8, needs.get(8, 0), eligible8)
    p.take(3, needs.get(3, 0), eligible3)
    p.take(6, needs.get(6, 0), eligible6)
    unused = p.rest(needs)
    cands = sorted({q for q, t in p.types.items() if t == 8} | set(pair_from))
    pairs = sorted(rng.sample(cands, min(n_pairs, len(cands))))
    if len(pairs) < n_pairs:
        p.short["pairs"] = n_pairs - len(pairs)
    if p.short:
        raise Shortfall(p.short)
    return {"types": p.types, "contrast_five": [], "pairs": pairs, "unused": unused}


def run_round(sheet: str, pool: list[dict], rnd: dict, seed: int) -> dict:
    """회차 기록(rnd)의 needs 로 배정한다. 분야가 아니라 시험지(test, train)마다 Random 을 따로 둔다."""
    rng = random.Random(f"{seed}:{sheet}:{rnd['round']}")
    needs = {int(t): n for t, n in rnd["needs"].items()}
    if sheet == "test":
        return assign_test(pool, needs, {int(t): n for t, n in rnd["contrast_needs"].items()}, rng)
    return assign_train(pool, needs, rnd["pair_needs"], rnd.get("pair_from", []), rng)


def replay(assignment: dict, questions_by_id: dict[str, dict]) -> list[str]:
    """저장된 회차를 같은 입력으로 다시 돌려 같은 결과가 나오는지 본다. 다른 회차 번호 목록(빈 목록이면 통과)."""
    bad = []
    for rnd in assignment["rounds"]:
        got = run_round(rnd["sheet"], [questions_by_id[q] for q in rnd["pool"]], rnd, assignment["seed"])
        if any(got[k] != rnd[k] for k in ("types", "contrast_five", "pairs", "unused")):
            bad.append(f"{rnd['sheet']} 회차 {rnd['round']}")
    return bad


def assigned(assignment: dict, sheet: str) -> tuple[dict[str, int], set[str], set[str]]:
    """그 시험지의 (질문마다 유형, 짝 문항 질문, 대상이 둘인 ①② 질문). 모든 회차를 합친다."""
    types: dict[str, int] = {}
    pairs: set[str] = set()
    five: set[str] = set()
    for rnd in assignment["rounds"]:
        if rnd["sheet"] == sheet:
            types.update(rnd["types"])
            pairs |= set(rnd["pairs"])
            five |= set(rnd["contrast_five"])
    return types, pairs, five


def _round(no: int, sheet: str, pool: list[dict], needs: dict, extra: dict, excluded_sha: str | None) -> dict:
    return {"round": no, "sheet": sheet, "questions_sha256": _file_sha(QUESTIONS),
            "retrieved_sha256": _file_sha(RETRIEVED), "excluded_sha256": excluded_sha,
            "pool": sorted(q["qid"] for q in pool), "needs": {str(t): n for t, n in sorted(needs.items())}, **extra}


def _load() -> tuple[list[dict], dict, dict[str, list[dict]]]:
    questions = read_jsonl(QUESTIONS)
    excluded = read_json(EXCLUDED) if EXCLUDED.exists() else {}
    pools = pools_by_sheet(questions, read_jsonl(RETRIEVED), excluded, fields_doc())
    return questions, excluded, pools


FIELD_SHORT = ("8", "contrast1", "contrast2", "pairs")   # 분야를 늘려서 채우는 모자람(스펙 3-3절). 나머지는 질문을 더 쓴다


def dry_run(sheet: str, pool: list[dict], seed: int) -> dict:
    """첫 배정(회차 0)을 저장하지 않고 그대로 돌려 본다. {"short": 모자란 수, "eighth_left": ④ 를 뽑은 뒤 남은 ⑧ 자격 수}.

    ⑧ 자격 질문 수만 세면 모자람을 놓친다. 배정은 ④ 를 ⑧ 보다 먼저 뽑는데, 주장이 2 인 ⑧ 자격 질문은 ④ 의
    자격도 있어 ④ 가 먼저 가져갈 수 있기 때문이다. 그래서 같은 시드, 같은 순서로 배정을 끝까지 돌려
    first 가 성공할지를 그대로 본다. 같은 Random 을 같은 순서로 쓰므로 first 와 결과가 같다.
    """
    rnd = {"round": 0, "needs": {str(t): n for t, n in (TEST_QUOTA if sheet == "test" else TRAIN_QUOTA).items()},
           "contrast_needs": {str(t): n for t, n in CONTRAST_FIVE.items()}, "pair_needs": PAIRS, "pair_from": []}
    try:
        run_round(sheet, pool, rnd, seed)
        short: dict[str, int] = {}
    except Shortfall as e:
        short = e.short
    # ④ 가 가져간 뒤의 ⑧ 자격 수. run_round 와 같은 Random 으로 ④ 만 뽑아 본다(④ 가 늘 첫 뽑기다).
    p = _Picker(pool, random.Random(f"{seed}:{sheet}:0"))
    four = set(p.take(4, int(rnd["needs"].get("4", 0)), eligible4))
    left = sum(1 for q in pool if eligible8(q) and q["qid"] not in four)
    return {"short": short, "eighth_left": left}


def cmd_count() -> int:
    """분야마다 ⑧ 비율(계획 E3)과, 시험지마다 첫 배정을 돌려 본 판정(계획 E5)을 낸다.

    종료 코드: 0 둘 다 충분, 2 분야를 늘려야 한다, 3 질문을 더 써야 한다(④, ③, ⑥ 등). 분야와 질문이 둘 다 모자라면 2.
    """
    _, _, pools = _load()
    counts = qualified_counts(pools)
    doc = fields_doc()
    more_fields = more_questions = False
    for sheet, need in (("test", TEST_MIN_QUALIFIED), ("train", TRAIN_MIN_QUALIFIED)):
        fields = doc[sheet]
        total = sum(counts.get(f, {}).get("qualified", 0) for f in fields)
        for f in fields:
            c = counts.get(f, {"pool": 0, "qualified": 0})
            ratio = c["qualified"] / c["pool"] if c["pool"] else 0.0
            print(f"{sheet} {f}: 후보 {c['pool']}개, ⑧ 자격 {c['qualified']}개({ratio:.0%})")
        d = dry_run(sheet, pools[sheet], SEED)
        field_short = {k: v for k, v in d["short"].items() if k in FIELD_SHORT}
        other_short = {k: v for k, v in d["short"].items() if k not in FIELD_SHORT}
        print(f"{sheet} 합계 ⑧ 자격 {total}개(기준 {need}개 이상), ④ 를 뽑은 뒤 남은 ⑧ 자격 {d['eighth_left']}개")
        if total < need or field_short:
            more_fields = True
            verdict = f"모자람(스펙 3-3절대로 분야를 늘린다. 첫 배정을 돌려 본 모자람: {field_short})"
        elif other_short:
            more_questions = True
            verdict = f"모자람(그 분야의 질문을 더 쓴다. 첫 배정을 돌려 본 모자람: {other_short})"
        else:
            verdict = "충분(첫 배정을 그대로 돌려 봤다)"
        print(f"{sheet} 판정: {verdict}")
    return 2 if more_fields else 3 if more_questions else 0


def _report_short(e: Shortfall, sheet: str) -> int:
    print(f"{sheet} 배정을 하지 않았습니다. 모자란 수: {e.short}")
    print("④, ③, ⑥ 이 모자라면 그 분야의 질문을 더 쓴다. ⑧ 이나 대상이 둘인 ①②, 짝이 모자라면 "
          "스펙 3-3절대로 분야를 늘린다(계획 E5). 시드나 할당량을 바꾸지 않는다.")
    return 2


def cmd_first() -> int:
    if ASSIGNMENT.exists():
        print("assignment.json 이 이미 있습니다. 첫 배정은 한 번만 합니다. 보충은 supplement 로 합니다.")
        return 1
    _, excluded, pools = _load()
    ex_sha = _file_sha(EXCLUDED)
    rounds = []
    specs = (("test", TEST_QUOTA, {"contrast_needs": {str(t): n for t, n in CONTRAST_FIVE.items()}}),
             ("train", TRAIN_QUOTA, {"pair_needs": PAIRS, "pair_from": []}))
    for sheet, quota, extra in specs:
        rnd = _round(0, sheet, pools[sheet], quota, extra, ex_sha)
        try:
            rnd.update(run_round(sheet, pools[sheet], rnd, SEED))
        except Shortfall as e:
            return _report_short(e, sheet)
        rounds.append(rnd)
    write_json(ASSIGNMENT, {"seed": SEED, "rounds": rounds})
    for rnd in rounds:
        print(f"{rnd['sheet']}: {Counter(rnd['types'].values())}, 짝 {len(rnd['pairs'])}, "
              f"대상이 둘인 ①② {len(rnd['contrast_five'])}, 쓰지 않은 질문 {len(rnd['unused'])}")
    return 0


def supplement_needs(sheet: str, assignment: dict, kept_types: dict[str, int], kept_pairs: set[str],
                     kept_five: set[str]) -> dict:
    """보충할 수. 할당량에서 남은 문항 수를 뺀다. 같은 명령을 두 번 돌려도 이미 채운 만큼은 다시 요구하지 않는다.

    시험용은 검수 뒤 조건(스펙 4-4절)에 걸리는 ⑧, ①, ② 만 채운다. ④ 는 보충하지 않는다(스펙 4-4절).
    학습용은 일곱 유형과 짝을 모두 채운다. 짝이 없는 ⑧ 질문은 pair_from 으로 넘겨 짝 후보에 넣는다.
    """
    have = Counter(kept_types.values())
    if sheet == "test":
        five_have = Counter(kept_types[q] for q in kept_five if q in kept_types)
        needs = {t: max(0, TEST_QUOTA[t] - have[t]) for t in (1, 2, 8)}
        contrast = {t: max(0, CONTRAST_FIVE[t] - five_have[t]) for t in CONTRAST_FIVE}
        # ①② 의 needs 는 대상이 둘인 몫을 포함한 수다(assign_test 가 나머지 몫을 needs - contrast 로 계산한다).
        for t in contrast:
            needs[t] = max(needs[t], contrast[t])
        return {"needs": needs, "contrast_needs": {str(t): n for t, n in contrast.items()}}
    needs = {t: max(0, TRAIN_QUOTA[t] - have[t]) for t in TRAIN_QUOTA}
    eighth_without_pair = sorted(q for q, t in kept_types.items() if t == 8 and q not in kept_pairs)
    return {"needs": needs, "pair_needs": max(0, PAIRS - len(kept_pairs)), "pair_from": eighth_without_pair}


def cmd_supplement(sheet: str) -> int:
    """보충 회차를 덧붙인다. 남은 문항은 test 는 정답 파일(검수 반영), train 은 train_dropped.json 으로 정한다."""
    from .judgeft_export import kept_test, kept_train   # 늦은 import: export 가 이 모듈을 불러 순환을 피한다
    assignment = read_json(ASSIGNMENT)
    _, _, pools = _load()
    kept_types, kept_pairs, kept_five = kept_test() if sheet == "test" else kept_train()
    plan = supplement_needs(sheet, assignment, kept_types, kept_pairs, kept_five)
    if not any(plan["needs"].values()) and not plan.get("pair_needs"):
        print(f"{sheet}: 보충할 문항이 없습니다.")
        return 0
    used = set(assigned(assignment, sheet)[0])
    pool = [q for q in pools[sheet] if q["qid"] not in used]   # 앞 회차에서 유형을 받은 질문은 다시 쓰지 않는다
    no = 1 + max(r["round"] for r in assignment["rounds"] if r["sheet"] == sheet)
    extra = {k: v for k, v in plan.items() if k != "needs"}
    rnd = _round(no, sheet, pool, plan["needs"], extra, _file_sha(EXCLUDED))
    try:
        rnd.update(run_round(sheet, pool, rnd, assignment["seed"]))
    except Shortfall as e:
        return _report_short(e, sheet)
    assignment["rounds"].append(rnd)
    write_json(ASSIGNMENT, assignment)
    print(f"{sheet} 회차 {no}: {Counter(rnd['types'].values())}, 짝 {len(rnd['pairs'])}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="파인튜닝 실험의 변형 유형을 배정한다")
    p.add_argument("cmd", choices=("count", "first", "supplement"))
    p.add_argument("sheet", nargs="?", choices=("test", "train"))
    args = p.parse_args(argv)
    try:
        if args.cmd == "count":
            return cmd_count()
        if args.cmd == "first":
            return cmd_first()
        if args.sheet is None:
            print("supplement 에는 test 또는 train 을 준다.")
            return 1
        return cmd_supplement(args.sheet)
    except ValueError as e:
        print(f"배정하지 않았습니다. {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 점검이 통과하는지 본다**

```bash
$PY -m tools.judgeft_assign_check | tail -1
```

Expected: `7가지 전부 통과.`(보충 명령은 태스크 6 의 함수를 늦게 불러오므로, 태스크 6 전에는 `supplement` 명령만 쓸 수 없다. 점검은 그 함수를 부르지 않는다)

- [ ] **Step 5: 커밋한다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft
git add ai-service/tools/judgeft_assign.py ai-service/tools/judgeft_assign_check.py
git commit -m "feat: 파인튜닝 실험의 배정 도구를 더한다(대상이 둘인 ①② 와 짝 문항 포함)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/tools/judgeft_assign.py ai-service/tools/judgeft_assign_check.py
```

**리뷰 포인트:** 시험용 배정에서 ⑧ 다음에 대상이 둘인 ①② 를 뽑는가(③ 이나 나머지가 ⑧ 자격 질문을 먼저 가져가지 않게). ⑧ 이 모자랄 때 ⑥ 으로 돌리지 않고 멈추는가. 짝 문항이 모두 ⑧ 을 받은 질문인가. 보충의 needs 가 할당량에서 남은 수를 빼는 방식이라 두 번 돌려도 넘치지 않는가.

---

### Task 5: 문장 틀과 모범 답안

**Files:**
- Create: `ai-service/testdata/judgeft/templates.json`, `ai-service/tools/judgeft_rationale.py`, `ai-service/tools/judgeft_rationale_check.py`

**Interfaces:**
- Consumes: 태스크 2 의 `SEED`, `TABLE_SCORE`, `TEMPLATES`, `read_json`
- Produces: `SLOTS`, `template_problems(templates) -> list[str]`, `group_for(t, has_target) -> str`, `record_problems(t, rec, question, sources) -> list[str]`, `render(t, rec, question, item_id, templates, seed) -> str`, `load_templates() -> dict`

스펙 4-5절이 "문장 틀의 정확한 본문은 구현 계획에서 정한다" 고 적었다. 아래 `templates.json` 이 그 본문이다. 묶음은 아홉이다: 대상이 있는 5점(`five_target`), 대상이 없는 5점(`five_plain`), ③(`four`), ④(`three`), ⑤(`two`), 대상이 있는 ⑥(`six_target`), 대상이 없는 ⑥(`six_plain`), ⑦(`seven`), ⑧(`eight`). 묶음마다 셋이다. 끝맺음(`So the overall score is n. [RESULT] n`)은 틀에 적지 않고 `render` 가 붙인다. 그래야 `[RESULT]` 가 늘 한 번만, 정답 점수와 같은 값으로 나온다.

**점검 픽스처의 값은 스펙 4-5절의 예(OTP, 보안카드)를 쓰지 않는다.** 스펙이 그 값을 틀 파일, 학습 데이터, 시범 데이터에 넣지 말라고 했으므로 점검도 지어낸 요금제 값(베이직 월 10GB, 프리미엄 월 30GB)을 쓴다.

- [ ] **Step 1: 점검을 먼저 쓴다**

```python
"""tools.judgeft_rationale 의 점검. DB 도 외부 API 도 쓰지 않는다.

실행:  cd ai-service && python -m tools.judgeft_rationale_check
"""
from __future__ import annotations

from .judge5 import RULES_V2, parse_result
from .judgeft_files import TABLE_SCORE
from .judgeft_rationale import load_templates, record_problems, render, template_problems

SOURCES = [{"filename": "a.md", "content": "베이직 요금제는 데이터를 월 10GB 준다."},
           {"filename": "b.md", "content": "프리미엄 요금제는 데이터를 월 30GB 준다."}]
QUESTION = {"qid": "x-001", "contrast": {"asked": {"target": "베이직", "value": "월 10GB"},
                                         "other": {"target": "프리미엄", "value": "월 30GB"}, "chunk_ids": [1, 2]}}
REC8 = {"target": "베이직", "evidence": [{"source": 1, "quote": "월 10GB"}],
        "other": {"target": "프리미엄", "source": 2, "quote": "월 30GB"}}
RECS = {
    1: {"target": "베이직", "evidence": [{"source": 1, "quote": "월 10GB"}]},
    2: {"target": None, "evidence": [{"source": 1, "quote": "월 10GB"}]},
    3: {"evidence": [{"source": 1, "quote": "월 10GB"}], "added": ["남은 데이터는 이월됩니다"]},
    4: {"evidence": [{"source": 1, "quote": "월 10GB"}], "added": ["대리점에서만 바꿀 수 있습니다"]},
    5: {"evidence": [{"source": 1, "quote": "월 10GB"}], "added": ["가입비가 없습니다", "해외에서도 쓸 수 있습니다"]},
    6: {"target": "베이직", "evidence": [{"source": 1, "quote": "월 10GB"}], "new_value": "월 20GB",
        "old_value": "월 10GB"},
    7: {"gist": "매장 방문 예약 절차"},
    8: REC8,
}


def check_committed_templates_follow_rules() -> None:
    """커밋된 틀 파일: 묶음 아홉, 묶음마다 셋 이상, 빈칸 규칙, 한글 없음, 끝맺음 없음."""
    assert template_problems(load_templates()) == []


def check_template_problems_catch_broken_files() -> None:
    good = load_templates()
    assert template_problems({k: v for k, v in good.items() if k != "eight"})                   # 묶음 하나 빠짐
    assert template_problems({**good, "seven": good["seven"][:2]})                              # 둘뿐
    assert template_problems({**good, "seven": good["seven"] + ["The response says \"베이직\" 요금 {gist}."]})  # 한글
    assert template_problems({**good, "four": good["four"] + ["{evidence} only."]})             # added 빠짐
    assert template_problems({**good, "two": good["two"] + ["{evidence} {added} [RESULT] 2"]})   # 끝맺음


def check_every_type_renders_and_parses_to_table_score() -> None:
    """모범 답안을 v2 의 읽는 규칙으로 읽으면 정답 점수가 나온다(스펙 5-2절 확인 4)."""
    tpl = load_templates()
    for t, rec in RECS.items():
        assert record_problems(t, rec, QUESTION, SOURCES) == [], (t, record_problems(t, rec, QUESTION, SOURCES))
        out = render(t, rec, QUESTION, f"id-{t}", tpl)
        assert parse_result(out, "stop", rules=RULES_V2) == (TABLE_SCORE[t], "ok"), (t, out)
        assert out.count("[RESULT]") == 1 and "{" not in out
    eight = render(8, REC8, QUESTION, "id-8", tpl)
    assert "\"베이직\"" in eight and "\"프리미엄\"" in eight and "월 30GB" in eight and "[근거 2]" in eight


def check_render_is_seeded_by_item_id() -> None:
    tpl = load_templates()
    a = {render(8, REC8, QUESTION, f"id-{i}", tpl) for i in range(30)}
    assert len(a) == 3                                                       # 세 틀이 모두 쓰인다
    assert render(8, REC8, QUESTION, "id-1", tpl) == render(8, REC8, QUESTION, "id-1", tpl)


def check_record_problems_catch_bad_quotes_and_targets() -> None:
    assert record_problems(1, {"target": "베이직", "evidence": [{"source": 1, "quote": "월 70GB"}]}, QUESTION, SOURCES)
    assert record_problems(1, {"target": "베이직", "evidence": [{"source": 3, "quote": "월 10GB"}]}, QUESTION, SOURCES)
    assert record_problems(8, {**REC8, "target": "프리미엄"}, QUESTION, SOURCES)
    assert record_problems(8, {**REC8, "other": {"target": "프리미엄", "source": 1, "quote": "월 30GB"}},
                           QUESTION, SOURCES)
    assert record_problems(3, {"evidence": [{"source": 1, "quote": "월 10GB"}]}, QUESTION, SOURCES)
    assert record_problems(7, {}, QUESTION, SOURCES)
    swapped = {**REC8, "evidence": [{"source": 2, "quote": "월 30GB"}]}            # 첫째 인용이 다른 대상의 값
    assert any("첫째" in p for p in record_problems(8, swapped, QUESTION, SOURCES))
    two = dict(QUESTION, claims=2)                                                # 주장이 둘인데 인용이 하나
    assert any("2개 적는다" in p for p in record_problems(8, REC8, two, SOURCES))
    assert record_problems(8, {**REC8, "evidence": REC8["evidence"] + [{"source": 1, "quote": "데이터를"}]}, two,
                           SOURCES) == []


def check_eighth_cites_asked_value_and_pair_cites_all() -> None:
    """⑧ 의 모범 답안은 첫째 인용(질문 대상의 값)만, 짝 문항은 모든 인용을 쓴다."""
    tpl = load_templates()
    rec = {**REC8, "evidence": REC8["evidence"] + [{"source": 1, "quote": "데이터를"}]}
    eight = render(8, rec, QUESTION, "id-8", tpl)
    pair = render(1, {"target": rec["target"], "evidence": rec["evidence"]}, QUESTION, "id-p", tpl)
    assert "\"데이터를\"" not in eight and "\"데이터를\"" in pair and "\"월 10GB\"" in pair


CHECKS = [check_committed_templates_follow_rules, check_template_problems_catch_broken_files,
          check_every_type_renders_and_parses_to_table_score, check_render_is_seeded_by_item_id,
          check_record_problems_catch_bad_quotes_and_targets, check_eighth_cites_asked_value_and_pair_cites_all]


def main() -> None:
    for fn in CHECKS:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(CHECKS)}가지 전부 통과.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 점검이 실패하는지 본다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft/ai-service
$PY -m tools.judgeft_rationale_check
```

Expected: `ModuleNotFoundError: No module named 'tools.judgeft_rationale'`

- [ ] **Step 3: 문장 틀 파일을 쓴다**

```json
{
  "five_target": [
    "The question asks about \"{target}\". For \"{target}\", the evidence states {evidence}. The response gives the same information for \"{target}\", so every claim in the response is supported by the evidence for the item asked.",
    "The item the question asks about is \"{target}\". Each claim in the response matches what the evidence says about \"{target}\": {evidence}. The response adds nothing that the evidence does not state.",
    "First, the response must be checked against the evidence for \"{target}\", which is what the question asks about. The evidence states {evidence}, and the response says the same for \"{target}\". All claims are supported by the evidence."
  ],
  "five_plain": [
    "Every claim in the response is stated in the evidence: {evidence}. The response adds nothing beyond the evidence.",
    "The response matches the evidence, which states {evidence}. No claim in the response goes beyond what the evidence says.",
    "Checking each claim against the evidence: {evidence}. All claims in the response are supported by the evidence."
  ],
  "four": [
    "The core answer agrees with the evidence: {evidence}. However, the response also says {added}, which the evidence does not mention. This is one minor claim that is not supported by the evidence.",
    "Most of the response is supported by the evidence, which states {evidence}. The added remark {added} does not appear anywhere in the evidence, so the response contains one minor unsupported claim.",
    "The response answers the question in line with the evidence ({evidence}), but it adds {added}. The evidence says nothing about this, so there is one minor unsupported claim."
  ],
  "three": [
    "One part of the response is supported by the evidence: {evidence}. The other part, {added}, is not found in the evidence. Supported and unsupported claims are mixed in roughly equal measure.",
    "The response contains a claim backed by the evidence ({evidence}) and a claim that the evidence does not mention ({added}). Half of the response is supported and half is not.",
    "Comparing the response with the evidence, {evidence} is supported, while {added} does not appear in the evidence. The response is an even mix of supported and unsupported claims."
  ],
  "two": [
    "Only one claim in the response is supported by the evidence: {evidence}. The other claims, {added}, do not appear in the evidence. Most of the response is not supported by the evidence.",
    "The evidence supports {evidence}, but the rest of the response ({added}) is not stated anywhere in the evidence. The majority of the claims are unsupported.",
    "Apart from {evidence}, which the evidence states, the response adds {added}. None of these additional claims is found in the evidence, so most of the response is unsupported."
  ],
  "six_target": [
    "The question asks about \"{target}\". For \"{target}\", the evidence states {evidence}. The response instead gives \"{value}\", which does not appear anywhere in the evidence. The core answer contradicts the evidence.",
    "The response gives \"{value}\" for \"{target}\". The evidence, however, states {evidence} for \"{target}\", and \"{value}\" is not found in the evidence at all. The response contradicts the evidence on the main point.",
    "For the item asked about, \"{target}\", the evidence says {evidence}. The value in the response, \"{value}\", is different and is not supported anywhere in the evidence, so the core answer goes against the evidence."
  ],
  "six_plain": [
    "The evidence states {evidence}. The response instead gives \"{value}\", which does not appear anywhere in the evidence. The core answer contradicts the evidence.",
    "The response gives \"{value}\", but the evidence states {evidence}, and \"{value}\" is not found in the evidence at all. The response contradicts the evidence on the main point.",
    "According to the evidence, {evidence}. The value in the response, \"{value}\", differs from this and is not supported anywhere in the evidence, so the core answer goes against the evidence."
  ],
  "seven": [
    "The response says {gist}, but nothing like this appears in the evidence. The answer is made up rather than drawn from the evidence.",
    "None of the response is grounded in the evidence. It describes {gist}, which the evidence does not mention at all.",
    "The evidence does not support the response. The response claims {gist}, which has no basis in any part of the evidence."
  ],
  "eight": [
    "The question asks about \"{target}\". In the evidence, the value for \"{target}\" is {evidence}. The response states \"{value}\", which is the value the evidence gives for \"{other_target}\" ({other_evidence}), not for \"{target}\". The response therefore contradicts the evidence for the item asked.",
    "The response gives \"{value}\". This value does appear in the evidence, but it belongs to \"{other_target}\": {other_evidence}. For \"{target}\", which is what the question asks about, the evidence states {evidence}. Because the response attributes another item's value to the item asked, it contradicts the evidence.",
    "Two items appear side by side in the evidence: \"{target}\" and \"{other_target}\". The question asks about \"{target}\", for which the evidence states {evidence}. The response answers with \"{value}\", which is the value for \"{other_target}\" ({other_evidence}). This is the wrong item's value, so the response contradicts the evidence."
  ]
}
```

- [ ] **Step 4: 모범 답안 도구를 쓴다**

```python
"""변경 기록과 문장 틀로 모범 답안을 만든다(스펙 4-3절, 4-5절).

모범 답안은 판단 이유와 끝의 `So the overall score is n. [RESULT] n` 이다. 이유는 사람이나 다른 AI 가 쓰지 않고
변경 기록(무엇을 무엇으로 바꿨는지)에서 정해진 틀로 만든다. 그래서 이유와 정답 점수가 어긋나지 않는다.

문장 틀 파일(testdata/judgeft/templates.json)에는 빈칸만 있고 값이 없다. 근거의 값과 대상은 이 모듈이
변경 기록에서 채운다. 틀 파일에 한글이 있으면 어떤 문항의 값이 틀에 들어간 것이므로 점검이 막는다(스펙 5-3절).
외부 API 도 DB 도 부르지 않는다.
"""
from __future__ import annotations

import random
import re
import string

from .judgeft_files import SEED, TABLE_SCORE, TEMPLATES, read_json, value_in

# 틀 묶음마다 쓸 수 있는 빈칸과 반드시 있어야 하는 빈칸(스펙 4-5절의 "유형마다 담는 판단" 표).
SLOTS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "five_target": (frozenset({"target", "evidence"}), frozenset({"target", "evidence"})),
    "five_plain": (frozenset({"evidence"}), frozenset({"evidence"})),
    "four": (frozenset({"evidence", "added"}), frozenset({"evidence", "added"})),
    "three": (frozenset({"evidence", "added"}), frozenset({"evidence", "added"})),
    "two": (frozenset({"evidence", "added"}), frozenset({"evidence", "added"})),
    "six_target": (frozenset({"target", "evidence", "value"}), frozenset({"target", "evidence", "value"})),
    "six_plain": (frozenset({"evidence", "value"}), frozenset({"evidence", "value"})),
    "seven": (frozenset({"gist"}), frozenset({"gist"})),
    "eight": (frozenset({"target", "evidence", "value", "other_target", "other_evidence"}),
              frozenset({"target", "evidence", "value", "other_target", "other_evidence"})),
}
MIN_TEMPLATES = 3      # 스펙 4-5절: 유형마다 세 개 이상
HANGUL = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ]")


def template_problems(templates: dict) -> list[str]:
    """문장 틀 파일이 규칙대로인가. 문제 목록(빈 목록이면 통과)."""
    out = []
    if set(templates) != set(SLOTS):
        out.append(f"틀 묶음의 이름이 다르다: 있어야 할 것 {sorted(SLOTS)}, 있는 것 {sorted(templates)}")
    for key, texts in templates.items():
        allowed, required = SLOTS.get(key, (frozenset(), frozenset()))
        if len(texts) < MIN_TEMPLATES:
            out.append(f"{key}: 틀이 {len(texts)}개다. {MIN_TEMPLATES}개 이상 둔다")
        for i, text in enumerate(texts):
            # string.Formatter().parse 는 "{a} 와 {b}" 를 (앞 글자, 빈칸 이름, ...) 조각으로 나눈다.
            names = {name for _, name, _, _ in string.Formatter().parse(text) if name is not None}
            if names - allowed or required - names:
                out.append(f"{key}[{i}]: 빈칸 {sorted(names)} 가 규칙과 다르다(필요 {sorted(required)})")
            if HANGUL.search(text):
                out.append(f"{key}[{i}]: 틀에 한글이 있다. 값은 변경 기록에서 채운다(스펙 5-3절)")
            if "[RESULT]" in text or "overall score" in text:
                out.append(f"{key}[{i}]: 끝맺음은 이 모듈이 붙인다. 틀에 적지 않는다")
    return out


def group_for(t: int, has_target: bool) -> str:
    """유형 번호(짝 문항은 1)에서 틀 묶음 이름을 정한다. 대상이 없는 질문은 대상 문장이 없는 묶음을 쓴다."""
    if t in (1, 2):
        return "five_target" if has_target else "five_plain"
    if t == 6:
        return "six_target" if has_target else "six_plain"
    return {3: "four", 4: "three", 5: "two", 7: "seven", 8: "eight"}[t]


def _quote_list(items: list[dict]) -> str:
    """근거 인용 목록을 '"원문" ([근거 2]); "원문" ([근거 3])' 꼴로 쓴다. 근거 머리표는 지시문의 [근거 i] 와 같다."""
    return "; ".join(f"\"{e['quote']}\" ([근거 {e['source']}])" for e in items)


def record_problems(t: int, rec: dict, question: dict, sources: list[dict]) -> list[str]:
    """변경 기록이 모범 답안을 만들 만큼 갖춰졌고 근거와 글자로 맞는가(스펙 5-2절 확인 1). sources 는 근거 청크 목록."""
    out = []
    ev = rec.get("evidence") or []
    if t != 7 and not ev:
        out.append("evidence(근거 주장)가 비었다")
    quotes = list(ev) + ([rec["other"]] if t == 8 and isinstance(rec.get("other"), dict) else [])
    for e in quotes:
        i = e.get("source")
        # type(i) is int: bool 을 막는다. 근거 번호는 지시문과 같이 1 부터 센다.
        if type(i) is not int or not 1 <= i <= len(sources):
            out.append(f"근거 번호 {i!r} 가 근거 청크 범위(1~{len(sources)}) 밖이다")
        elif not e.get("quote") or e["quote"] not in sources[i - 1]["content"]:
            out.append(f"인용 {e.get('quote')!r} 가 [근거 {i}] 에 글자 그대로 있지 않다")
    if t in (1, 2, 6, 8) and rec.get("target") is not None and not isinstance(rec["target"], str):
        out.append("target 은 글자이거나 null 이다")
    if t == 8:
        c = question.get("contrast") or {}
        other = rec.get("other") or {}
        if rec.get("target") != (c.get("asked") or {}).get("target"):
            out.append("⑧ 의 target 이 질문의 대상(contrast.asked.target)과 다르다")
        # 첫째 인용은 질문 대상의 값이다. ⑧ 의 모범 답안은 이것만, 짝 문항의 모범 답안은 전부를 인용한다.
        asked_value = (c.get("asked") or {}).get("value")
        if ev and not (isinstance(ev[0].get("quote"), str) and asked_value and value_in(asked_value, ev[0]["quote"])):
            out.append("⑧ 의 evidence 첫째는 질문 대상의 값(contrast.asked.value)이 적힌 구절이다")
        # 짝 문항의 5점 모범 답안은 "모든 주장이 근거에 있다" 고 쓰므로, 인용이 멀쩡한 답변의 주장마다 있어야 한다(스펙 4-3절).
        if type(question.get("claims")) is int and len(ev) != question["claims"]:
            out.append(f"⑧ 의 evidence 는 멀쩡한 답변의 주장마다 하나씩, {question['claims']}개 적는다(지금 {len(ev)}개)")
        if other.get("target") != (c.get("other") or {}).get("target"):
            out.append("⑧ 의 other.target 이 contrast.other.target 과 다르다")
    if t in (3, 4, 5) and not rec.get("added"):
        out.append("③, ④, ⑤ 는 added(더하거나 바꾼 주장)를 적는다")
    if t == 7 and not rec.get("gist"):
        out.append("⑦ 은 gist(지어낸 답변의 요지)를 적는다")
    return out


def render(t: int, rec: dict, question: dict, item_id: str, templates: dict, seed: int = SEED) -> str:
    """모범 답안 하나. t 는 유형(짝 문항은 1), item_id 는 문항 id 다. 틀은 random.Random(f"{seed}:{item_id}") 로 고른다.

    문항 id 로 고르는 이유: 같은 입력이면 다시 만들어도 같은 틀이 나와야 학습 데이터의 해시가 재현된다.
    """
    group = group_for(t, rec.get("target") is not None)
    text = random.Random(f"{seed}:{item_id}").choice(templates[group])
    c = question.get("contrast") or {}
    values = {
        "target": rec.get("target"),
        # ⑧ 은 질문 대상의 값(첫째 인용)만 인용한다. 나머지 인용은 짝 문항이 쓴다.
        "evidence": _quote_list((rec.get("evidence") or [])[:1] if t == 8 else rec.get("evidence") or []),
        "value": rec.get("new_value") if t == 6 else (c.get("other") or {}).get("value"),
        "other_target": (rec.get("other") or {}).get("target"),
        "other_evidence": _quote_list([rec["other"]]) if rec.get("other") else None,
        "added": ", ".join(f"\"{a}\"" for a in rec.get("added") or []),
        "gist": f"\"{rec.get('gist')}\"",
    }
    score = TABLE_SCORE[t]
    # format(**values): 틀의 {이름} 자리에 같은 이름의 값을 넣는다. 틀에 없는 이름은 쓰이지 않는다.
    return f"{text.format(**values)} So the overall score is {score}. [RESULT] {score}"


def load_templates() -> dict:
    return read_json(TEMPLATES)
```

- [ ] **Step 5: 점검이 통과하는지 본다**

```bash
$PY -m tools.judgeft_rationale_check | tail -1
```

Expected: `6가지 전부 통과.`

- [ ] **Step 6: 커밋한다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft
git add ai-service/testdata/judgeft/templates.json ai-service/tools/judgeft_rationale.py ai-service/tools/judgeft_rationale_check.py
git commit -m "feat: 모범 답안의 문장 틀과 변경 기록으로 모범 답안을 만드는 도구를 더한다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/testdata/judgeft/templates.json ai-service/tools/judgeft_rationale.py ai-service/tools/judgeft_rationale_check.py
```

**리뷰 포인트:** 틀마다 스펙 4-5절의 표가 말하는 판단을 담는가(특히 ⑧ 은 질문의 대상, 그 대상의 값, 답변의 값, 그 값의 대상을 차례로 적는가. 5점 틀도 대상을 먼저 밝히는가). 같은 묶음의 세 틀이 말만 다르고 판단은 같은가. 틀에 한글과 `[RESULT]` 가 없는가.

---

### Task 6: 내보내기 도구

**Files:**
- Create: `ai-service/tools/judgeft_export.py`, `ai-service/tools/judgeft_export_check.py`

**Interfaces:**
- Consumes: 태스크 4 의 `assigned`, 태스크 5 의 `load_templates`, `record_problems`, `render`, `template_problems`. `tools.judge5v2_export` 의 `ExportProblem`, `apply_review`, `build_cases`, `case_id_of`, `fence_for`. `tools.judge5` 의 `RULES_V2`, `build_messages`, `parse_result`, `prompt_sha256`, `sha256_file`
- Produces: `build_test() -> (rows, key)`, `kept_test()`, `build_train(questions, retrieved, assignment, variants, templates) -> (items, dropped)`, `split_val(items, seed) -> (train, val)`, `leak_problems(items, questions, retrieved, test_texts) -> list[str]`, `test_texts() -> list[str]`, `kept_train()`, 명령 `test draft|mismatches|final`, `train`

새 시험지는 v2 와 같은 모양이라 v2 의 `build_cases`(⑥, ⑧ 의 글자 확인 포함)를 그대로 쓴다. 학습 데이터는 스펙 5-2절대로 어긋난 문항만 빼야 하므로, 질문 하나씩 `build_cases` 에 넣어 그 질문의 문제만 받는다.

- [ ] **Step 1: 점검을 먼저 쓴다**

```python
"""tools.judgeft_export 의 점검. DB 도 외부 API 도 쓰지 않는다.

실행:  cd ai-service && python -m tools.judgeft_export_check
"""
from __future__ import annotations

from .judge5 import RULES_V2, parse_result
from .judge5v2_export import apply_review
from .judge5 import build_messages
from .judgeft_export import (
    build_train, forbidden_problems, leak_problems, merge_reviews, overlap_problems, pending_rows, split_val,
    train_short,
)
from .judgeft_files import PAIRS, TRAIN_QUOTA
from .judgeft_rationale import load_templates

SRC = [{"chunk_id": 1, "filename": "plan.md", "content": "베이직 요금제는 데이터를 월 10GB 준다. 프리미엄 요금제는 데이터를 월 30GB 준다."},
       {"chunk_id": 2, "filename": "etc.md", "content": "요금제 변경은 한 달에 한 번 할 수 있다."}]
CONTRAST = {"asked": {"target": "베이직", "value": "월 10GB"}, "other": {"target": "프리미엄", "value": "월 30GB"},
            "chunk_ids": [1]}


def _fixture() -> tuple[list[dict], list[dict], dict, list[dict]]:
    """학습용 질문 넷: ⑧ 둘(하나는 짝), ⑥ 하나, ① 하나. ⑧ 하나(t-002)는 인용이 근거와 달라 빠져야 한다."""
    qs, rs, vs = [], [], []
    for i in range(1, 5):
        qid = f"travel-{i:03d}"
        qs.append({"qid": qid, "domain": "travel", "question": f"베이직 요금제의 데이터는 얼마인가요 {i}",
                   "two_part": False, "answer": "베이직 요금제는 데이터를 월 10GB 줍니다.", "claims": 1,
                   "contrast": CONTRAST})
        rs.append({"qid": qid, "domain": "travel", "status": "ok", "drop_reason": None, "settings": {},
                   "sources": SRC})
    ev = [{"source": 1, "quote": "월 10GB"}]
    other = {"target": "프리미엄", "source": 1, "quote": "월 30GB"}
    vs.append({"qid": "travel-001", "type": 8, "answer": "베이직 요금제는 데이터를 월 30GB 줍니다.", "target": "베이직",
               "evidence": ev, "other": other})
    vs.append({"qid": "travel-002", "type": 8, "answer": "베이직 요금제는 데이터를 월 30GB 줍니다. 참고", "target": "베이직",
               "evidence": [{"source": 1, "quote": "월 70GB"}], "other": other})
    vs.append({"qid": "travel-003", "type": 6, "answer": "베이직 요금제는 데이터를 월 20GB 줍니다.", "target": "베이직",
               "evidence": ev, "new_value": "월 20GB", "old_value": "월 10GB"})
    vs.append({"qid": "travel-004", "type": 1, "answer": "베이직 요금제는 데이터를 월 10GB 줍니다.", "target": "베이직",
               "evidence": ev})
    assignment = {"seed": 1, "rounds": [{"round": 0, "sheet": "train", "pool": [],
                                         "types": {"travel-001": 8, "travel-002": 8, "travel-003": 6, "travel-004": 1},
                                         "pairs": ["travel-001", "travel-002"], "contrast_five": [], "unused": []}]}
    return qs, rs, assignment, vs


def check_build_train_drops_only_broken_items_and_their_pairs() -> None:
    qs, rs, a, vs = _fixture()
    items, dropped = build_train(qs, rs, a, vs, load_templates())
    assert sorted((i["qid"], i["kind"]) for i in items) == [
        ("travel-001", "main"), ("travel-001", "pair"), ("travel-003", "main"), ("travel-004", "main")]
    assert set(dropped["main"]) == {"travel-002"} and set(dropped["pair"]) == {"travel-002"}
    for i in items:
        assert parse_result(i["target"], "stop", rules=RULES_V2) == (i["score"], "ok")
        assert i["messages"][0]["role"] == "system" and i["messages"][1]["role"] == "user"
    pair = next(i for i in items if i["kind"] == "pair")
    assert pair["score"] == 5 and "월 30GB" not in pair["messages"][1]["content"].split("###Response to evaluate:")[1]


def check_split_val_keeps_question_together_and_is_stable() -> None:
    qs, rs, a, vs = _fixture()
    items, _ = build_train(qs, rs, a, vs, load_templates())
    many = [dict(i, qid=f"{i['qid']}-{k}", id=f"{i['id']}{k}") for k in range(10) for i in items]
    train, val = split_val(many)
    assert len(train) + len(val) == len(many)
    assert {i["qid"] for i in train}.isdisjoint({i["qid"] for i in val})       # 같은 질문은 한쪽에만
    assert len({i["qid"] for i in val}) == round(0.1 * len({i["qid"] for i in many}))
    assert split_val(many) == (train, val)


def check_leak_problems_find_overlaps() -> None:
    qs, rs, a, vs = _fixture()
    items, _ = build_train(qs, rs, a, vs, load_templates())
    assert leak_problems(items, qs, rs, ["전혀 다른 시험지 글"]) == []
    assert leak_problems(items, qs, rs, ["... " + SRC[0]["content"] + " ..."])       # 근거 청크가 겹침
    assert leak_problems(items, qs, rs, [qs[0]["question"]])                       # 질문이 겹침
    assert leak_problems(items, qs, rs, [items[0]["target"]])                      # 모범 답안이 겹침


def check_sentence_overlap_both_ways_and_forbidden_values() -> None:
    """문장 하나만 겹쳐도 두 방향 모두에서 찾는다. 공통 지시문의 문장은 겹쳐도 세지 않는다."""
    template = "\n".join(m["content"] for m in build_messages("", [], ""))
    shared = "프리미엄 요금제는 해외 로밍 데이터를 하루 1GB 까지 무료로 준다."
    train = {"학습 문서 a": "첫 문장은 학습 쪽에만 있는 충분히 긴 문장이다. " + shared}
    test = {"시험 문서 b": "시험 쪽 문서의 첫 문장은 여기에만 있는 긴 문장이다.\n" + shared + " 뒤에 더 붙은 말"}
    found = overlap_problems(train, test, template)
    assert len(found) == 2 and any(f.startswith("학습 쪽") for f in found) and any(f.startswith("시험 쪽") for f in found)
    common = {"x": template + "\n학습 쪽 고유의 문장은 이렇게 충분히 길게 쓴다."}
    assert overlap_problems(common, {"y": template + "\n시험 쪽 고유의 문장도 이렇게 충분히 길게 쓴다."}, template) == []
    assert forbidden_problems({"문장 틀": "The response gives {asked_value}."}) == []
    assert forbidden_problems({"학습 문항 1": "이체 한도는 \"1일 5억 원\" 이다"}) == ["학습 문항 1: 금지 값 '1일 5억 원' 가 있다(스펙 4-5절)"]


def check_train_refuses_duplicate_variants_and_counts_quota() -> None:
    """같은 질문의 변형 줄이 둘이면 멈추고, 할당량 모자람은 남은 문항으로 센다."""
    qs, rs, a, vs = _fixture()
    try:
        build_train(qs, rs, a, vs + [dict(vs[2], answer="다른 답")], load_templates())
    except ValueError as e:
        assert "travel-003" in str(e)
    else:
        raise AssertionError("변형 줄이 둘인데 조용히 하나를 골랐다")
    full = [{"kind": "main", "type": t} for t, n in TRAIN_QUOTA.items() for _ in range(n)]
    full += [{"kind": "pair", "type": 1}] * PAIRS
    assert train_short(full) == {}                                           # 앞에서 빠졌어도 채웠으면 0
    assert train_short(full[1:-1]) == {"1": 1, "pairs": 1}


def check_pair_needs_asked_value_in_clean_answer() -> None:
    qs, rs, a, vs = _fixture()
    qs[0] = dict(qs[0], answer="베이직 요금제는 데이터를 넉넉하게 줍니다.")    # travel-001 의 멀쩡한 답변에 값이 없다
    items, dropped = build_train(qs, rs, a, vs, load_templates())
    assert ("travel-001", "pair") not in {(i["qid"], i["kind"]) for i in items}
    assert "값" in dropped["pair"]["travel-001"][0]


def check_supplement_review_flow_reviews_only_new_cases() -> None:
    """보충 뒤의 순서(계획 E9 Step 4): 검수하지 않은 문항만 뽑고, 그 결과를 덧붙이면 apply_review 가 멈추지 않는다.
    이미 검수한 문항을 다시 덧붙이면 merge_reviews 가 먼저 막는다(apply_review 의 "검수 줄이 두 개다" 를 피한다)."""
    key = {f"c{i}": {"qid": f"q{i}", "table_score": 1} for i in range(5)}
    rows = [{"case_id": c} for c in key]
    first = [{"case_id": f"c{i}", "review_score": 1} for i in range(3)]          # 첫 검수는 c0~c2
    todo = pending_rows(rows, first)
    assert [r["case_id"] for r in todo] == ["c3", "c4"]
    new = [{"case_id": "c3", "review_score": 1}, {"case_id": "c4", "review_score": 1}]
    merged, problems = merge_reviews(first, new, {r["case_id"] for r in todo})
    assert problems == [] and len(merged) == 5
    kept, dropped, bad = apply_review(key, merged)
    assert bad == [] and len(kept) == 5
    _, problems = merge_reviews(first, new + [{"case_id": "c0", "review_score": 1}], {"c3", "c4"})
    assert any("c0" in p for p in problems)                                          # 이미 검수한 문항
    _, problems = merge_reviews(first, new[:1], {"c3", "c4"})
    assert any("없는 문항 1개" in p for p in problems)                              # 검수가 빠진 문항


CHECKS = [check_build_train_drops_only_broken_items_and_their_pairs, check_split_val_keeps_question_together_and_is_stable,
          check_leak_problems_find_overlaps, check_supplement_review_flow_reviews_only_new_cases,
          check_sentence_overlap_both_ways_and_forbidden_values, check_train_refuses_duplicate_variants_and_counts_quota,
          check_pair_needs_asked_value_in_clean_answer]


def main() -> None:
    for fn in CHECKS:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(CHECKS)}가지 전부 통과.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 점검이 실패하는지 본다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft/ai-service
$PY -m tools.judgeft_export_check
```

Expected: `ModuleNotFoundError: No module named 'tools.judgeft_export'`

- [ ] **Step 3: 내보내기 도구를 쓴다**

```python
"""새 시험지와 학습 데이터를 만든다(스펙 4절, 5절).

실행:
    cd ai-service
    $PY -m tools.judgeft_export test draft        # 검수 전 새 시험지와 정답 파일
    $PY -m tools.judgeft_export test mismatches   # 검수 점수와 정답 점수가 다른 문항 목록(사용자 판단용)
    $PY -m tools.judgeft_export test final        # 검수를 반영한 최종 새 시험지
    # 검수 뒤 조건을 채우지 못해 보충했을 때(계획 E9 Step 4). 이 순서대로 한다.
    $PY -m tools.judgeft_export test draft --after-supplement    # 보충 회차의 문항을 더한 검수 전 시험지
    $PY -m tools.judgeft_export test pending --out <저장소 밖 폴더>/cases.jsonl   # 아직 검수하지 않은 문항만
    $PY -m tools.judgeft_export test append-review <검수 결과 파일>             # review.jsonl 에 덧붙인다
    $PY -m tools.judgeft_export train             # 학습 데이터(학습 묶음, 검증 묶음). 글자 확인과 누출 확인을 함께 한다

새 시험지는 v2 와 같은 모양이라 v2 의 build_cases(⑥, ⑧ 의 글자 확인 포함), apply_review, fence_for 를 그대로 쓴다.
시험지를 섞는 시드도 v2 의 build_cases 안의 값(20261005)을 그대로 쓴다. 섞는 순서는 결과에 영향이 없고,
v2 함수를 고치지 않으려는 것이다.
"""
from __future__ import annotations

import argparse
import random
import re
import sys
from collections import Counter
from pathlib import Path

from .judge5 import RULES_V2, build_messages, parse_result, prompt_sha256, sha256_file
from .judge5v2_export import ExportProblem, apply_review, build_cases, case_id_of, fence_for
from .judgeft_assign import assigned
from .judgeft_files import (
    ANSWER_KEY, ASSIGNMENT, CASES, CASES_SHA, CORPUS, FORBIDDEN_VALUES, GATE_A, MISMATCHES, QUESTIONS, RETRIEVED,
    PAIRS, REVIEW, ROOT, SEED, TABLE_SCORE, TEMPLATES, TRAIN_QUOTA, V2_CORPUS_DIRS, fields_doc, value_in,
    TRAIN, TRAIN_DROPPED, TRAIN_SHA, TYPE_NAMES, V2_CASES, VAL, VAL_FRACTION, VARIANTS, latest_by_qid, read_json,
    read_jsonl, write_json, write_jsonl,
)
from .judgeft_rationale import load_templates, record_problems, render, template_problems

MIN_LEAK_LEN = 20   # 이보다 짧은 근거 청크와 문장은 누출 확인에서 뺀다. "## 요금" 같은 제목이 우연히 겹칠 수 있다.
# 문장 경계: 마침표, 물음표, 느낌표 뒤의 공백, 또는 줄바꿈. (?<=...) 는 "바로 앞이 이 글자일 때" 만 맞는 조건이라
# 마침표 자체는 앞 문장에 남는다.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def _inputs() -> tuple[list[dict], list[dict], dict, list[dict]]:
    return read_jsonl(QUESTIONS), read_jsonl(RETRIEVED), read_json(ASSIGNMENT), read_jsonl(VARIANTS)


def build_test() -> tuple[list[dict], dict[str, dict]]:
    """새 시험지와 정답 키. 정답 키에는 v2 의 칸에 two_targets(대상이 둘인 질문인가)를 더한다(스펙 4-4절, 8-2절)."""
    questions, retrieved, assignment, variants = _inputs()
    types = assigned(assignment, "test")[0]
    rows, key = build_cases(questions, retrieved, types, variants)
    by = {q["qid"]: q for q in questions}
    for k in key.values():
        k["two_targets"] = by[k["qid"]].get("contrast") is not None
    return rows, key


def _write_test(rows: list[dict], doc: dict) -> str:
    write_jsonl(CASES, rows)
    sha = sha256_file(CASES)
    CASES_SHA.write_text(f"{sha}  cases.jsonl\n{prompt_sha256()}  prompt\n", encoding="utf-8")
    write_json(ANSWER_KEY, {**doc, "cases_sha256": sha, "prompt_sha256": prompt_sha256()})
    return sha


def kept_test() -> tuple[dict[str, int], set[str], set[str]]:
    """최종 새 시험지에 남은 (질문마다 유형, 빈 집합, 대상이 둘인 ①② 질문). 배정 도구의 보충이 쓴다."""
    ak = read_json(ANSWER_KEY)
    if ak.get("stage") != "final":
        raise ValueError("새 시험지의 보충은 test final 뒤에 한다(검수 결과가 반영돼야 남은 문항을 안다)")
    types = {k["qid"]: k["type"] for k in ak["cases"].values()}
    five = {k["qid"] for k in ak["cases"].values() if k["type"] in (1, 2) and k["two_targets"]}
    return types, set(), five


def pending_rows(rows: list[dict], reviews: list[dict]) -> list[dict]:
    """아직 검수 줄이 없는 문항. 보충 뒤에는 새 회차의 문항만 남는다(앞 회차의 문항은 이미 검수 줄이 있다)."""
    done = {r["case_id"] for r in reviews}
    return [r for r in rows if r["case_id"] not in done]


def merge_reviews(existing: list[dict], new: list[dict], pending_ids: set[str]) -> tuple[list[dict], list[str]]:
    """새 검수 결과를 기존 review.jsonl 뒤에 붙인다. (합친 목록, 문제 목록). 문제가 있으면 합친 목록을 쓰지 않는다.

    이미 검수한 문항을 다시 검수한 줄이 섞이면 apply_review 가 "검수 줄이 두 개다" 로 멈추므로 여기서 먼저 막는다.
    """
    problems = []
    seen: set[str] = set()
    for r in new:
        cid = r.get("case_id")
        if cid in seen:
            problems.append(f"{cid}: 새 검수 결과에 같은 문항이 두 번 있다")
        elif cid not in pending_ids:
            problems.append(f"{cid}: 검수할 문항(pending)이 아니다. 이미 검수했거나 시험지에 없다")
        seen.add(cid)
    if missing := sorted(pending_ids - seen):
        problems.append(f"검수 결과에 없는 문항 {len(missing)}개: {', '.join(missing[:5])}")
    return existing + new, problems


def _in_repo(path: Path) -> bool:
    """검수 폴더가 저장소 안이면 검수 세션이 변형 유형이 적힌 파일을 볼 수 있다(v2 계획 E8)."""
    return path.resolve().is_relative_to(ROOT.parent.resolve())


def cmd_test(stage: str, after_supplement: bool = False, path: str | None = None) -> int:
    final_now = ANSWER_KEY.exists() and read_json(ANSWER_KEY).get("stage") == "final"
    if stage == "draft" and final_now and not after_supplement:
        print("정답 파일이 이미 최종본입니다. draft 로 덮지 않습니다(v2 와 같은 이유: 검수 전 시험지로 모델을 돌리게 된다). "
              "보충 회차를 더한 것이면 --after-supplement 를 붙입니다(계획 E9 Step 4).")
        return 1
    if stage == "draft" and after_supplement and GATE_A.exists():
        print("관문 (a) 의 결과(gate_a.json)가 이미 있습니다. 모델이 돈 뒤에는 새 시험지를 바꾸지 않습니다(스펙 6-5절).")
        return 1
    try:
        rows, key = build_test()
    except ExportProblem as e:
        print("새 시험지를 만들지 않았습니다.\n  - " + "\n  - ".join(e.problems[:20]))
        return 1
    reviews = read_jsonl(REVIEW) if REVIEW.exists() else []
    if stage == "draft":
        if after_supplement and not pending_rows(rows, reviews):
            print("검수하지 않은 새 문항이 없습니다. 보충 회차(judgeft_assign supplement test)와 변형 답변을 먼저 씁니다.")
            return 1
        sha = _write_test(rows, {"stage": "draft", "seed": SEED, "cases": key, "dropped": {}})
        print(f"새 시험지 {len(rows)}문항(검수하지 않은 문항 {len(pending_rows(rows, reviews))}개), SHA-256 {sha}")
        return 0
    if stage == "pending":
        out = Path(path or "")
        if not path or _in_repo(out):
            print("--out 에 저장소 밖의 새 폴더 안 경로를 줍니다(검수 세션이 저장소의 파일을 보지 않게 한다).")
            return 1
        todo = pending_rows(rows, reviews)
        out.parent.mkdir(parents=True, exist_ok=True)
        write_jsonl(out, todo)
        print(f"검수할 문항 {len(todo)}개: {out}")
        return 0
    if stage == "append-review":
        new = read_jsonl(Path(path or ""))
        merged, problems = merge_reviews(reviews, new, {r["case_id"] for r in pending_rows(rows, reviews)})
        if problems:
            print("review.jsonl 에 덧붙이지 않았습니다.\n  - " + "\n  - ".join(problems[:20]))
            return 1
        write_jsonl(REVIEW, merged)
        print(f"review.jsonl 에 {len(new)}줄을 덧붙였습니다(모두 {len(merged)}줄).")
        return 0
    if stage == "mismatches":
        reviews = {r["case_id"]: r for r in reviews}
        notes = {v["qid"]: v.get("note", "") for v in read_jsonl(VARIANTS)}
        body_of = {r["case_id"]: r["messages"][1]["content"] for r in rows}
        out = ["# 검수 점수와 정답 점수가 다른 문항", "", "이 파일에는 변형 유형이 적혀 있다. 검수 세션에 주지 않는다.", ""]
        n = 0
        for cid, k in sorted(key.items()):
            r = reviews.get(cid)
            if r is None or r.get("review_score") == k["table_score"] or r.get("user_decision"):
                continue
            n += 1
            fence = fence_for(body_of[cid])
            out += [f"## {cid}", "", f"- 분야 {k['domain']}, {TYPE_NAMES[k['type']]}, 대응표 점수 {k['table_score']}, "
                    f"검수 점수 {r['review_score']}", f"- 검수 메모: {r.get('review_note', '')}",
                    f"- 출제 메모: {notes.get(k['qid'], '')}", "", fence, body_of[cid], fence, ""]
        MISMATCHES.write_text("\n".join(out) + "\n", encoding="utf-8")
        print(f"사용자 판단이 필요한 문항 {n}개: {MISMATCHES}")
        return 0
    kept, dropped, problems = apply_review(key, reviews)
    if problems:
        print("최종 새 시험지를 만들지 않았습니다.\n  - " + "\n  - ".join(problems[:20]))
        return 1
    rows = [r for r in rows if r["case_id"] in kept]
    sha = _write_test(rows, {"stage": "final", "seed": SEED, "cases": kept, "dropped": dropped})
    print(f"최종 새 시험지 {len(rows)}문항(버린 문항 {len(dropped)}개). SHA-256 {sha}")
    return 0


def build_train(questions: list[dict], retrieved: list[dict], assignment: dict, variants: list[dict],
                templates: dict) -> tuple[list[dict], dict[str, dict[str, list[str]]]]:
    """학습 문항 목록과 뺀 문항. 스펙 5-2절의 네 확인을 문항마다 하고, 하나라도 어긋나면 그 문항만 뺀다.

    v2 의 build_cases 는 문제가 하나라도 있으면 전체를 멈춘다. 학습 데이터는 어긋난 문항만 빼야 하므로(스펙 5-2절)
    질문 하나씩 build_cases 에 넣어 그 질문의 문제만 받는다. 확인 2, 3(⑥, ⑧ 의 글자)은 build_cases 안에 있다.
    """
    # 같은 질문의 변형 줄이 둘이면 dict 로 만들 때 뒤의 줄이 조용히 앞의 줄을 덮는다. 어느 쪽이 맞는지는 출제
    # 세션만 아므로 멈춘다. Counter 는 값마다 몇 번 나왔는지 센다.
    if dups := sorted(q for q, n in Counter(v["qid"] for v in variants).items() if n > 1):
        raise ValueError(f"variants.jsonl 에 같은 질문의 줄이 여러 개다: {', '.join(dups[:10])}. 하나만 남긴다")
    types, pairs, _ = assigned(assignment, "train")
    q_by = {q["qid"]: q for q in questions}
    r_by = {r["qid"]: r for r in latest_by_qid(retrieved)}
    v_by = {v["qid"]: v for v in variants}
    items: list[dict] = []
    dropped: dict[str, dict[str, list[str]]] = {"main": {}, "pair": {}}
    for qid, t in sorted(types.items()):
        q, r, v = q_by.get(qid), r_by.get(qid), v_by.get(qid)
        try:
            build_cases([q] if q else [], [r] if r else [], {qid: t}, [v] if v else [])   # 확인 2, 3
        except ExportProblem as e:
            dropped["main"][qid] = e.problems
            continue
        if bad := record_problems(t, v, q, r["sources"]):                                 # 확인 1
            dropped["main"][qid] = bad
            continue
        items.append(_item(q, r, v["answer"], t, v, "main", templates))
    kept_main = {i["qid"] for i in items}
    for qid in sorted(pairs):
        if qid not in kept_main:
            dropped["pair"][qid] = ["짝의 ⑧ 문항이 빠져서 짝도 뺀다"]
            continue
        q, r, v = q_by[qid], r_by[qid], v_by[qid]
        # 짝 문항은 멀쩡한 답변이 질문 대상의 값을 그대로 말해야 5점이다. 값이 없으면 ⑧ 과 짝이 대조가 되지 않는다.
        if not value_in(q["contrast"]["asked"]["value"], q["answer"]):
            dropped["pair"][qid] = ["멀쩡한 답변에 질문 대상의 값(contrast.asked.value)이 없다"]
            continue
        items.append(_item(q, r, q["answer"], 1, {"target": v["target"], "evidence": v["evidence"]}, "pair", templates))
    for it in list(items):                                                                 # 확인 4
        if parse_result(it["target"], "stop", rules=RULES_V2) != (it["score"], "ok"):
            items.remove(it)
            dropped[it["kind"]][it["qid"]] = ["모범 답안을 읽으면 정답 점수가 나오지 않는다"]
    return items, dropped


def _item(q: dict, r: dict, answer: str, t: int, rec: dict, kind: str, templates: dict) -> dict:
    sources = [{"filename": s["filename"], "content": s["content"]} for s in r["sources"]]
    item_id = case_id_of(q["domain"], q["question"], answer)
    return {"id": item_id, "qid": q["qid"], "domain": q["domain"], "kind": kind, "type": t,
            "score": TABLE_SCORE[t], "messages": build_messages(q["question"], sources, answer),
            "target": render(t, rec, q, item_id, templates)}


def split_val(items: list[dict], seed: int = SEED) -> tuple[list[dict], list[dict]]:
    """질문 단위로 약 10% 를 검증 묶음으로 뗀다. 같은 질문의 ⑧ 과 짝은 같은 쪽에 간다(스펙 6-3절).
    학습 묶음은 id 로 줄 세운 뒤 고정 시드로 섞는다. 같은 입력이면 같은 파일(같은 해시)이 나온다."""
    qids = sorted({i["qid"] for i in items})
    val_q = set(random.Random(f"{seed}:val").sample(qids, round(VAL_FRACTION * len(qids))))
    train = sorted((i for i in items if i["qid"] not in val_q), key=lambda i: i["id"])
    val = sorted((i for i in items if i["qid"] in val_q), key=lambda i: i["id"])
    random.Random(f"{seed}:train-order").shuffle(train)
    return train, val


def leak_problems(items: list[dict], questions: list[dict], retrieved: list[dict], test_texts: list[str]) -> list[str]:
    """스펙 5-3절의 확인 1, 2. 학습 문항의 질문, 근거 청크 본문, 모범 답안이 시험지의 입력 글에 나오지 않는가.
    test_texts 는 새 시험지와 동결 시험지의 user 메시지 전체다. 확인 3(틀의 한글)은 template_problems 가 본다."""
    q_by = {q["qid"]: q for q in questions}
    r_by = {r["qid"]: r for r in latest_by_qid(retrieved)}
    blob = "\n".join(test_texts)
    out = []
    for it in items:
        q, r = q_by[it["qid"]], r_by[it["qid"]]
        pieces = [("질문", q["question"]), ("모범 답안", it["target"])]
        pieces += [("근거 청크", s["content"]) for s in r["sources"] if len(s["content"]) >= MIN_LEAK_LEN]
        for name, text in pieces:
            if text in blob:
                out.append(f"{it['qid']}({it['kind']}): 학습 문항의 {name}이 시험지에 나온다")
    return out


def sentences(text: str, template: str) -> set[str]:
    """20자 이상 문장. 공통 지시문(template)에 들어 있는 문장은 뺀다. 모든 문항이 같은 지시문을 쓰므로 겹쳐도 누출이 아니다."""
    out = set()
    for s in _SENTENCE_SPLIT.split(text):
        s = s.strip()
        if len(s) >= MIN_LEAK_LEN and s not in template:
            out.add(s)
    return out


def overlap_problems(train: dict[str, str], test: dict[str, str], template: str) -> list[str]:
    """학습 쪽 글과 시험 쪽 글을 문장 단위로 양쪽에서 대조한다. 이름마다 한 줄만 낸다.

    leak_problems 는 학습 문항의 글 전체가 시험지에 들어 있는지만 본다. 문서의 한 문장만 옮겨 쓴 경우나
    시험 쪽 글이 학습 쪽에 들어간 경우는 놓친다. 그래서 문장으로 잘라 두 방향을 모두 본다.
    """
    out = []
    for name_a, side_a, side_b, where in (("학습", train, test, "시험"), ("시험", test, train, "학습")):
        blob = "\n".join(side_b.values())
        for name, text in side_a.items():
            if hit := next((s for s in sorted(sentences(text, template)) if s in blob), None):
                out.append(f"{name_a} 쪽 {name} 의 문장이 {where} 쪽에 나온다: {hit[:40]}")
    return out


def forbidden_problems(texts: dict[str, str]) -> list[str]:
    """스펙 4-5절의 금지 값(FORBIDDEN_VALUES)이 학습 데이터, 문장 틀, 노트북에 없는가."""
    return [f"{name}: 금지 값 {v!r} 가 있다(스펙 4-5절)" for name, text in texts.items() for v in FORBIDDEN_VALUES
            if v in text]


def _corpus_texts(dirs: list[Path]) -> dict[str, str]:
    return {f"문서 {p.parent.name}/{p.name}": p.read_text(encoding="utf-8")
            for d in dirs for p in sorted(d.glob("*.md"))}


def overlap_sides(items: list[dict], questions: list[dict], retrieved: list[dict]) -> tuple[dict, dict]:
    """(학습 쪽, 시험 쪽). 학습 쪽은 학습용 분야의 문서와 학습 문항, 시험 쪽은 시험용 분야와 v2 의 문서와 두 시험지다."""
    doc = fields_doc()
    q_by = {q["qid"]: q for q in questions}
    r_by = {r["qid"]: r for r in latest_by_qid(retrieved)}
    train = _corpus_texts([CORPUS / f for f in doc["train"]])
    for it in items:
        train[f"학습 문항 {it['id']}({it['qid']})"] = "\n".join(
            [q_by[it["qid"]]["question"], it["target"]] + [s["content"] for s in r_by[it["qid"]]["sources"]])
    test = _corpus_texts([CORPUS / f for f in doc["test"]] + list(V2_CORPUS_DIRS.values()))
    test["시험지"] = "\n".join(test_texts())
    return train, test


def test_texts() -> list[str]:
    """새 시험지(최종본)와 동결 시험지의 user 메시지. 시험지 파일이 없으면 멈춘다."""
    if not CASES.exists() or read_json(ANSWER_KEY).get("stage") != "final":
        raise SystemExit("새 시험지 최종본이 없습니다. 누출 확인은 test final 뒤에 합니다(계획 E10).")
    return [m["content"] for path in (CASES, V2_CASES) for row in read_jsonl(path)
            for m in row["messages"] if m["role"] == "user"]


def kept_train() -> tuple[dict[str, int], set[str], set[str]]:
    """학습 데이터에 남은 (⑧ 등 본 문항의 질문마다 유형, 짝 문항 질문, 빈 집합). 배정 도구의 보충이 쓴다."""
    items = read_jsonl(TRAIN) + read_jsonl(VAL)
    if not items:
        raise ValueError("학습 데이터가 아직 없다. 먼저 `judgeft_export train` 을 한다")
    return ({i["qid"]: i["type"] for i in items if i["kind"] == "main"},
            {i["qid"] for i in items if i["kind"] == "pair"}, set())


def train_short(items: list[dict]) -> dict[str, int]:
    """할당량(스펙 4-4절)에 모자란 수. {유형 번호 문자열 또는 "pairs": 모자란 수}. 빈 dict 면 할당량을 다 채웠다."""
    have = Counter(i["type"] for i in items if i["kind"] == "main")
    short = {str(t): n - have[t] for t, n in TRAIN_QUOTA.items() if have[t] < n}
    if (n_pairs := sum(1 for i in items if i["kind"] == "pair")) < PAIRS:
        short["pairs"] = PAIRS - n_pairs
    return short


def cmd_train() -> int:
    templates = load_templates()
    if bad := template_problems(templates):
        print("문장 틀 파일이 규칙과 다릅니다.\n  - " + "\n  - ".join(bad))
        return 1
    questions, retrieved, assignment, variants = _inputs()
    try:
        items, dropped = build_train(questions, retrieved, assignment, variants, templates)
    except ValueError as e:
        print(f"학습 데이터를 만들지 않았습니다. {e}")
        return 1
    template = "\n".join(m["content"] for m in build_messages("", [], ""))
    leaks = leak_problems(items, questions, retrieved, test_texts())
    leaks += overlap_problems(*overlap_sides(items, questions, retrieved), template)
    leaks += forbidden_problems({f"학습 문항 {i['id']}": i["target"] + "".join(m["content"] for m in i["messages"])
                                 for i in items} | {"문장 틀": TEMPLATES.read_text(encoding="utf-8")})
    if leaks:
        print("학습 데이터가 시험지와 겹치거나 금지 값이 있습니다. 학습하지 않고 사용자에게 보입니다(스펙 5-3절).\n  - "
              + "\n  - ".join(leaks[:20]))
        return 1
    train, val = split_val(items)
    write_jsonl(TRAIN, train)
    write_jsonl(VAL, val)
    write_json(TRAIN_DROPPED, dropped)
    TRAIN_SHA.write_text("".join(f"{sha256_file(p)}  {p.name}\n" for p in (TRAIN, VAL, TEMPLATES))
                         + f"{prompt_sha256()}  prompt\n", encoding="utf-8")
    n_drop = sum(len(v) for v in dropped.values())
    print(f"학습 묶음 {len(train)}문항, 검증 묶음 {len(val)}문항, 뺀 문항 {n_drop}개"
          f"(본 문항 {len(dropped['main'])}, 짝 {len(dropped['pair'])})")
    # 종료 코드는 뺀 문항이 있었는가가 아니라 남은 문항이 할당량에 닿았는가로 정한다. 앞 회차에서 빠진
    # 문항은 train_dropped.json 에 계속 남으므로, 보충으로 채운 뒤에도 "뺀 문항 n개" 는 0 이 되지 않는다.
    if short := train_short(items):
        print(f"할당량에 모자랍니다: {short}. `judgeft_assign supplement train` 으로 채운 뒤 출제 세션이 변형 답변을 쓰고 "
              "이 명령을 다시 한다.")
        return 2
    if n_drop:
        print("뺀 문항은 보충 회차로 이미 채웠습니다. 할당량을 모두 채웠습니다.")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="새 시험지와 학습 데이터를 만든다")
    p.add_argument("what", choices=("test", "train"))
    p.add_argument("stage", nargs="?", choices=("draft", "mismatches", "final", "pending", "append-review"))
    p.add_argument("path", nargs="?", help="append-review 의 검수 결과 파일")
    p.add_argument("--after-supplement", action="store_true", help="보충 회차를 더해 draft 를 다시 만든다")
    p.add_argument("--out", help="pending 이 쓸 파일(저장소 밖)")
    args = p.parse_args(argv)
    if args.what == "train":
        return cmd_train()
    if args.stage is None:
        print("test 에는 draft, mismatches, final, pending, append-review 중 하나를 준다.")
        return 1
    # argparse 는 --after-supplement 를 after_supplement 로 바꿔 담는다(- 는 이름에 쓸 수 없어서).
    return cmd_test(args.stage, args.after_supplement, args.out if args.stage == "pending" else args.path)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 점검이 통과하는지 본다**

```bash
$PY -m tools.judgeft_export_check | tail -1 && $PY -m tools.judgeft_assign_check | tail -1
```

Expected: `7가지 전부 통과.`, `7가지 전부 통과.`

- [ ] **Step 5: 커밋한다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft
git add ai-service/tools/judgeft_export.py ai-service/tools/judgeft_export_check.py
git commit -m "feat: 새 시험지와 학습 데이터를 만들고 글자와 누출을 확인하는 도구를 더한다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/tools/judgeft_export.py ai-service/tools/judgeft_export_check.py
```

**리뷰 포인트:** ⑧ 이 빠지면 그 질문의 짝도 빠지는가. 짝 문항의 답변이 멀쩡한 답변(질문의 대상의 값)인가. 검증 묶음이 질문 단위로 나뉘어 같은 질문이 두 묶음에 걸치지 않는가. 학습 데이터 파일이 같은 입력에서 같은 바이트로 다시 만들어지는가(정렬과 고정 시드). 누출 확인이 새 시험지와 동결 시험지를 모두 보는가.

---

### Task 7: 토큰화와 loss 확인

**Files:**
- Create: `ai-service/tools/judgeft_labels.py`, `ai-service/tools/judgeft_labels_check.py`, `ai-service/tools/judgeft_tokcheck.py`

**Interfaces:**
- Consumes: 태스크 2 의 `M3_REPO`, `M3_REVISION`, `TRAIN`, `VAL`, `read_jsonl`
- Produces: `build_example(apply_template, encode, messages, target, end_id) -> (ids, n_target)`. 태스크 11 의 학습 노트북이 이 함수의 본문을 글자 그대로 담는다. `judgeft_tokcheck` 의 `check_rows(tok, rows) -> (가장 긴 토큰 수, 문항 id)`, `check_logits_to_keep()`

`judgeft_labels` 는 torch 도 transformers 도 import 하지 않는다. CI 는 `requirements.txt` 만 깔려 있어 torch 가 없을 수 있기 때문이다(CI 설정의 늦은 import 주석). 실제 토크나이저와 작은 모델로 보는 확인은 `judgeft_tokcheck` 가 하고, 그 도구는 CI 에서 돌지 않는다(E10 에서 로컬로 돈다).

- [ ] **Step 1: 점검을 먼저 쓴다**

```python
"""tools.judgeft_labels 의 점검. 가짜 토크나이저로 본다. DB 도 외부 API 도 모델도 쓰지 않는다.

실행:  cd ai-service && python -m tools.judgeft_labels_check
"""
from __future__ import annotations

from .judgeft_labels import build_example

END = 999


def _apply(messages: list[dict]) -> str:
    return "".join(f"<{m['role']}>{m['content']}" for m in messages) + "<assistant>"


def _encode(text: str) -> list[int]:
    return [ord(c) for c in text]      # 글자 하나가 토큰 하나인 가짜 토크나이저


def check_end_token_is_last_and_inside_target() -> None:
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "질문"}]
    ids, n = build_example(_apply, _encode, msgs, "Fine. [RESULT] 5", END)
    assert ids[-1] == END                                   # 끝 토큰이 맨 뒤
    assert n == len("Fine. [RESULT] 5") + 1                  # 정답 쪽 길이에 끝 토큰이 들어간다
    assert "".join(chr(i) for i in ids[:-n]) == _apply(msgs)  # 입력 쪽은 대화 틀 그대로(시스템 메시지 포함)


CHECKS = [check_end_token_is_last_and_inside_target]


def main() -> None:
    for fn in CHECKS:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(CHECKS)}가지 전부 통과.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 점검이 실패하는지 본다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft/ai-service
$PY -m tools.judgeft_labels_check
```

Expected: `ModuleNotFoundError: No module named 'tools.judgeft_labels'`

- [ ] **Step 3: 토큰화 함수를 쓴다**

```python
"""학습 문항 하나를 토큰으로 바꾸고, loss 를 계산할 부분의 길이를 정한다(스펙 4-5절, 6-2절).

이 파일은 torch 도 transformers 도 import 하지 않는다. 토크나이저는 함수 두 개로 받는다. 그래서 CI 에서는 가짜
토크나이저로 점검하고(judgeft_labels_check), 실제 토크나이저로는 계획 E10 의 judgeft_tokcheck 가 확인한다.
학습 노트북은 아래 build_example 의 본문을 글자 그대로 담는다(judgeft_notebooks 가 이 파일에서 옮겨 넣는다).
"""
from __future__ import annotations


def build_example(apply_template, encode, messages, target, end_id):
    """(토큰 id 목록, 정답 쪽 길이). 정답 쪽은 모범 답안의 토큰과 끝 토큰(<|im_end|>)이다. 끝 토큰은 맨 뒤에 있다.

    apply_template(messages) 는 대화 틀을 씌운 글(시스템 메시지 포함, 끝에 assistant 차례의 시작)을 돌려준다.
    채점 노트북이 generate 앞에서 만드는 글과 같아야 한다(v2 노트북의 add_generation_prompt=True).
    encode(text) 는 특수 토큰을 더하지 않고 토큰 id 목록을 돌려준다(틀이 이미 특수 토큰을 넣는다).
    입력과 정답을 따로 토큰으로 바꿔 잇는 이유: 채점할 때도 모델은 입력을 따로 토큰으로 바꾼 뒤 그 뒤를 생성한다.
    정답을 입력에 붙여 한꺼번에 바꾸면 경계의 글자가 다르게 묶여, 학습한 토큰 열과 채점 때 생성하는 토큰 열이 달라질 수 있다.
    """
    prompt_ids = list(encode(apply_template(messages)))
    target_ids = list(encode(target)) + [end_id]
    return prompt_ids + target_ids, len(target_ids)
```

- [ ] **Step 4: 실제 토크나이저 확인 도구를 쓴다**

```python
"""실제 토크나이저로 학습 문항을 토큰화해, 끝 토큰이 정답 쪽 맨 뒤에 있는지 확인한다(스펙 4-5절).

실행:  cd ai-service && $PY -m tools.judgeft_tokcheck            # M3 의 토크나이저를 내려받는다(수 MB, 가중치는 받지 않는다)

CI 에서 돌지 않는다. 토크나이저를 내려받아야 하기 때문이다. CI 는 같은 함수를 가짜 토크나이저로 본다(judgeft_labels_check).
가장 긴 문항의 토큰 수도 찍는다. 학습 전 관문 (b) 가 그 문항으로 메모리를 잰다(스펙 7-2절).
"""
from __future__ import annotations

import argparse
import sys

from .judgeft_files import M3_REPO, M3_REVISION, TRAIN, VAL, read_jsonl
from .judgeft_labels import build_example

END_TOKEN = "<|im_end|>"


def check_rows(tok, rows: list[dict]) -> tuple[int, str]:
    """모든 문항을 확인하고 (가장 긴 토큰 수, 그 문항 id) 를 돌려준다. 어긋나면 AssertionError."""
    end_id = tok.convert_tokens_to_ids(END_TOKEN)
    assert isinstance(end_id, int) and end_id != tok.unk_token_id, f"{END_TOKEN} 가 어휘에 없다"

    def apply(m):
        return tok.apply_chat_template(m, add_generation_prompt=True, tokenize=False)

    def encode(s):
        return tok(s, add_special_tokens=False)["input_ids"]

    longest = (0, "")
    for r in rows:
        ids, n = build_example(apply, encode, r["messages"], r["target"], end_id)
        assert ids[-1] == end_id, f"{r['id']}: 끝 토큰이 맨 뒤가 아니다"
        tail = tok.decode(ids[-n:])
        assert tail == r["target"] + END_TOKEN, f"{r['id']}: 정답 쪽이 모범 답안과 끝 토큰이 아니다: {tail[-60:]!r}"
        assert apply(r["messages"]).startswith("<|im_start|>system\n"), f"{r['id']}: 시스템 메시지가 틀에 없다"
        longest = max(longest, (len(ids), r["id"]))
    return longest


def check_logits_to_keep() -> None:
    """학습 노트북의 loss(모범 답안 위치의 logits 만 계산)가 전체 logits 에 입력을 가린 loss 와 같은지 본다(스펙 6-2절).
    작은 무작위 Qwen2 모델로 CPU 에서 본다. 같아야 "계산 방법만 다르고 학습 결과는 같다" 는 스펙의 말이 맞다."""
    import torch
    from transformers import Qwen2Config, Qwen2ForCausalLM
    torch.manual_seed(0)
    m = Qwen2ForCausalLM(Qwen2Config(vocab_size=50, hidden_size=32, intermediate_size=64, num_hidden_layers=2,
                                     num_attention_heads=4, num_key_value_heads=2)).eval()
    ids, n = torch.randint(0, 50, (10,)), 3
    with torch.no_grad():
        ours = torch.nn.functional.cross_entropy(m(input_ids=ids[None], logits_to_keep=n + 1).logits[0, :-1], ids[-n:])
        labels = ids.clone()
        labels[:-n] = -100          # -100 은 loss 에서 빼는 자리다(transformers 의 약속)
        ref = m(input_ids=ids[None], labels=labels[None]).loss
    assert torch.allclose(ours, ref, atol=1e-6), (float(ours), float(ref))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="학습 문항의 토큰화와 끝 토큰을 확인한다")
    p.add_argument("--repo", default=M3_REPO)
    p.add_argument("--revision", default=M3_REVISION)
    args = p.parse_args(argv)
    from transformers import AutoTokenizer   # 늦은 import: CI 의 requirements.txt 만으로도 이 모듈을 불러올 수 있게
    check_logits_to_keep()
    print("모범 답안 위치만 계산한 loss 가 입력을 가린 전체 loss 와 같습니다.")
    tok = AutoTokenizer.from_pretrained(args.repo, revision=args.revision)
    rows = read_jsonl(TRAIN) + read_jsonl(VAL)
    if not rows:
        print("train.jsonl 이 비었습니다. `judgeft_export train` 을 먼저 하세요.")
        return 1
    n, rid = check_rows(tok, rows)
    print(f"{len(rows)}문항 모두 끝 토큰이 정답 쪽 맨 뒤에 있습니다. 가장 긴 문항 {rid}: {n}토큰")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: 점검과 loss 확인을 돌린다**

```bash
$PY -m tools.judgeft_labels_check | tail -1
$PY -c "from tools.judgeft_tokcheck import check_logits_to_keep; check_logits_to_keep(); print('같다')"
```

Expected: `1가지 전부 통과.`, `같다`. 둘째 명령은 작은 무작위 Qwen2 모델을 CPU 에서 만든다(몇 초). 모범 답안 위치의 logits 만 계산한 loss 가 입력을 가린 전체 loss 와 같다는 뜻이고, 스펙 6-2절의 "계산 방법이라 학습 결과는 같다" 의 근거다(2026-10-05 계획 작성 때 로컬 transformers 4.57.6 으로 같은 값 3.98037 을 확인했다).

- [ ] **Step 6: 커밋한다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft
git add ai-service/tools/judgeft_labels.py ai-service/tools/judgeft_labels_check.py ai-service/tools/judgeft_tokcheck.py
git commit -m "feat: 학습 문항의 토큰화 함수와 끝 토큰, loss 계산 확인 도구를 더한다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/tools/judgeft_labels.py ai-service/tools/judgeft_labels_check.py ai-service/tools/judgeft_tokcheck.py
```

**리뷰 포인트:** `build_example` 의 입력 쪽이 채점 노트북이 `generate` 앞에서 만드는 글(`add_generation_prompt=True`, 시스템 메시지 포함)과 같은가. 끝 토큰이 정답 쪽 길이에 들어가는가.

---

### Task 8: 결정성과 관문

**Files:**
- Create: `ai-service/tools/judgeft_determinism.py`, `ai-service/tools/judgeft_gate.py`, `ai-service/tools/judgeft_gate_check.py`

**Interfaces:**
- Consumes: 태스크 2 의 상수와 `result_path`. `tools.judge5` 의 `RULES_V2`, `parse_result`. `tools.judge5v2_gate` 의 `fake_within1`
- Produces: `env_path(results) -> Path`, `env_diff(env, ref) -> dict`, `compare_runs(a, b) -> dict`, `runs_for(model, sheet, det) -> list[Path]`, 명령 `judgeft_determinism pre|post`. `review_conditions(cases) -> list[Condition]`, `gate_a(runs, cases) -> dict`, 명령 `judgeft_gate review|a`

`runs_for` 가 스펙 8-1절의 표를 코드로 옮긴 것이다. 보고서(태스크 10)와 관문 (a) 가 이 함수 하나로 어느 결과 파일을 쓸지 정한다.

- [ ] **Step 1: 점검을 먼저 쓴다**

```python
"""tools.judgeft_gate, tools.judgeft_determinism 의 점검. DB 도 외부 API 도 쓰지 않는다.

실행:  cd ai-service && python -m tools.judgeft_gate_check
"""
from __future__ import annotations

from .judgeft_determinism import compare_runs, decide_pre_from, env_diff, runs_for
from .judgeft_files import V2_RESULTS_DIR, result_path
from .judgeft_gate import gate_a, review_conditions


def _cases(n8: int = 60, n5: int = 20, two: int = 12) -> dict[str, dict]:
    c = {f"e{i}": {"type": 8, "score": 1, "two_targets": True} for i in range(n8)}
    c |= {f"f{i}": {"type": 1 + i % 2, "score": 5, "two_targets": i < two} for i in range(n5)}
    return c


def _run(severe: int, unread: int, n8: int = 60) -> list[dict]:
    rows = []
    for i in range(n8):
        out = "x [RESULT] 5" if i < severe else ("양식 없음" if i < severe + unread else "x [RESULT] 1")
        rows.append({"case_id": f"e{i}", "output": out, "finish": "stop"})
    return rows


def check_review_conditions_pass_and_fail() -> None:
    assert all(c.ok for c in review_conditions(_cases()))
    assert {c.no for c in review_conditions(_cases(n8=53, n5=14, two=9)) if not c.ok} == {1, 2, 3}


def check_gate_a_threshold_and_unread_denominator() -> None:
    cases = _cases()
    assert gate_a([_run(6, 0)], cases)["pass"]                      # 6/60 = 10%
    assert not gate_a([_run(5, 0)], cases)["pass"]                  # 5/60
    r = gate_a([_run(6, 4)], cases)["runs"][0]                      # 못 읽음 4개는 분모에서 빠진다: 6/56
    assert r["unread"] == 4 and abs(r["ratio"] - 6 / 56) < 1e-9
    assert not gate_a([_run(9, 0), _run(5, 0), _run(9, 0)], cases)["pass"]   # 비율이 가장 낮은 실행으로 판정
    over = dict(cases, e0={"type": 8, "score": 3, "two_targets": True})      # 사용자가 3점으로 바꾼 ⑧ 은 세지 않는다
    assert gate_a([_run(6, 0)], over)["runs"][0]["eighth"] == 59


def check_compare_runs_and_env() -> None:
    a = [{"case_id": "c1", "output": "x [RESULT] 5", "finish": "stop"}]
    assert compare_runs(a, [dict(a[0])])["diff"] == 0
    assert compare_runs(a, [dict(a[0], output="y [RESULT] 5")])["diff"] == 1     # 점수가 같아도 본문이 다르면 다르다
    assert env_diff({"torch": "2.11.0+cu130", "transformers": "4.57.6", "bitsandbytes": "0.50.2"},
                    {"torch": "2.11.0+cu130", "transformers": "4.57.6", "bitsandbytes": "0.50.2"}) == {}
    assert set(env_diff({"torch": "2.12.0"}, {"torch": "2.11.0"})) >= {"torch"}
    assert "gpu" in env_diff({"gpu": "NVIDIA L4"}, {"gpu": "Tesla T4"})


def check_decide_pre_separates_causes() -> None:
    """판이 같아도 v2 와 다르면 새 환경의 run2 를 요구하고, run1 과 run2 로 실행 수를 정한다."""
    a = [{"case_id": "c1", "output": "x [RESULT] 5", "finish": "stop"}]
    b = [dict(a[0], output="y [RESULT] 5")]
    r = decide_pre_from(a, a, None, {})
    assert r["use_v2"] and r["runs"] == 1
    try:
        decide_pre_from(a, b, None, {})
    except SystemExit as e:
        assert "run2" in str(e)
    else:
        raise AssertionError("판이 같은데 v2 와 다르면 run2 를 요구해야 한다")
    r = decide_pre_from(a, b, a, {})                 # 새 환경의 두 실행은 같다: v2 와의 차이는 코드나 환경 쪽
    assert not r["use_v2"] and r["runs"] == 1 and r["vs_v2"]["diff"] == 1
    r = decide_pre_from(a, b, b, {})                 # 새 환경의 두 실행도 다르다: 생성이 실행마다 다르다
    assert not r["use_v2"] and r["runs"] == 3
    r = decide_pre_from(a, a, a, {"torch": {"v2": "2.11.0", "now": "2.12.0"}})   # 판이 다르면 v2 와 대조하지 않는다
    assert not r["use_v2"] and "vs_v2" not in r


def check_runs_for_follows_spec_table() -> None:
    v2 = V2_RESULTS_DIR / "M3_run1.jsonl"
    same1 = {"pre": {"use_v2": True, "runs": 1}, "post": {"runs": 1}}
    assert runs_for("M3pre", "frozen", same1) == [v2]
    assert runs_for("M3pre", "frozen", {"pre": {"use_v2": True, "runs": 3}}) == [
        v2, result_path("frozen", "M3pre", 1), result_path("frozen", "M3pre", 2)]
    assert runs_for("M3pre", "frozen", {"pre": {"use_v2": False, "runs": 1}}) == [result_path("frozen", "M3pre", 1)]
    assert runs_for("M1", "new", same1) == [result_path("new", "M1", n) for n in (1, 2, 3)]
    assert runs_for("M1", "frozen", same1) == [V2_RESULTS_DIR / "M1_run1.jsonl"]
    assert runs_for("M3ft", "frozen", {"post": {"runs": 3}})[2] == result_path("frozen", "M3ft", 3)


CHECKS = [check_review_conditions_pass_and_fail, check_gate_a_threshold_and_unread_denominator,
          check_compare_runs_and_env, check_runs_for_follows_spec_table, check_decide_pre_separates_causes]


def main() -> None:
    for fn in CHECKS:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(CHECKS)}가지 전부 통과.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 점검이 실패하는지 본다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft/ai-service
$PY -m tools.judgeft_gate_check
```

Expected: `ModuleNotFoundError: No module named 'tools.judgeft_determinism'`

- [ ] **Step 3: 결정성 도구를 쓴다**

```python
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
```

- [ ] **Step 4: 관문 도구를 쓴다**

```python
"""새 시험지의 검수 뒤 조건(스펙 4-4절)과 학습 전 관문 (a)(스펙 7-1절).

실행:
    cd ai-service
    $PY -m tools.judgeft_gate review     # 최종 새 시험지의 세 조건과 가짜 모델 수치. gate.md 를 쓴다
    $PY -m tools.judgeft_gate a          # 학습 전 M3 의 새 시험지 결과로 관문 (a). gate_a.json 을 쓴다

관문 (a) 는 ⑧ 의 심각한 놓침 수, ⑧ 의 못 읽음 수, 통과 여부만 낸다. 문항별 점수나 출력은 찍지 않는다.
학습이 끝날 때까지 새 시험지의 문항별 결과를 보지 않기 위해서다(스펙 6-5절).
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from .judge5 import RULES_V2, parse_result
from .judge5v2_gate import fake_within1
from .judgeft_determinism import runs_for
from .judgeft_files import (
    ANSWER_KEY, DETERMINISM, GATE, GATE_A, GATE_A_RATIO, MIN_CONTRAST_FIVE_AFTER_REVIEW, MIN_EIGHTH_AFTER_REVIEW,
    MIN_FIVE_AFTER_REVIEW, read_json, read_jsonl, write_json,
)


@dataclass(frozen=True)
class Condition:
    no: int
    ok: bool
    text: str


def review_conditions(cases: dict[str, dict]) -> list[Condition]:
    """검수 뒤 세 조건. cases 는 정답 파일의 cases(문항 id 마다 type, score, two_targets)."""
    n8 = sum(1 for k in cases.values() if k["type"] == 8)
    five = [k for k in cases.values() if k["type"] in (1, 2)]
    two = sum(1 for k in five if k["two_targets"])
    return [
        Condition(1, n8 >= MIN_EIGHTH_AFTER_REVIEW, f"⑧ {n8}문항(기준 {MIN_EIGHTH_AFTER_REVIEW} 이상)"),
        Condition(2, len(five) >= MIN_FIVE_AFTER_REVIEW, f"①과 ② {len(five)}문항(기준 {MIN_FIVE_AFTER_REVIEW} 이상)"),
        Condition(3, two >= MIN_CONTRAST_FIVE_AFTER_REVIEW,
                  f"대상이 둘인 질문의 ①과 ② {two}문항(기준 {MIN_CONTRAST_FIVE_AFTER_REVIEW} 이상)"),
    ]


def gate_a(runs: list[list[dict]], cases: dict[str, dict]) -> dict:
    """관문 (a). runs 는 학습 전 M3 의 새 시험지 결과(실행마다 줄 목록). 실행마다 분모는 ⑧ 수에서 못 읽음을 뺀 수다.
    통과는 비율이 가장 낮은 실행으로 판정한다(스펙 7-1절: 속는다고 말하려면 매번 속아야 한다. 못 읽음이 실행마다
    달라 분모가 다를 수 있으므로 수가 아니라 비율로 고른다).

    ⑧ 은 정답 점수가 1 인 문항만 센다. 검수에서 사용자가 점수를 바꾼(override) ⑧ 은 심각한 놓침의 정의(정답 1,
    모델 4 이상)가 맞지 않는다. 보고서의 severe8 과 같은 범위다."""
    eighth = {cid for cid, k in cases.items() if k["type"] == 8 and k["score"] == 1}
    out = []
    for i, rows in enumerate(runs, 1):
        got = {r["case_id"]: parse_result(r["output"], r.get("finish"), rules=RULES_V2)[0] for r in rows}
        if missing := eighth - set(got):
            raise SystemExit(f"실행 {i} 에 ⑧ 문항 {len(missing)}개의 결과가 없습니다. 마저 채점한 뒤 다시 하세요.")
        unread = sum(1 for c in eighth if got[c] is None)
        severe = sum(1 for c in eighth if got[c] is not None and got[c] >= 4)
        denom = len(eighth) - unread
        out.append({"run": i, "eighth": len(eighth), "unread": unread, "severe": severe,
                    "ratio": severe / denom if denom else 0.0})
    return {"threshold": GATE_A_RATIO, "runs": out, "pass": bool(out) and min(r["ratio"] for r in out) >= GATE_A_RATIO}


def _final_cases() -> dict[str, dict]:
    ak = read_json(ANSWER_KEY)
    if ak.get("stage") != "final":
        raise SystemExit("새 시험지 최종본이 아닙니다. `judgeft_export test final` 을 먼저 하세요.")
    return ak["cases"]


def cmd_review() -> int:
    cases = _final_cases()
    conds = review_conditions(cases)
    fakes = fake_within1([k["score"] for k in cases.values()])
    n4 = sum(1 for k in cases.values() if k["type"] == 4)
    lines = ["# 새 시험지의 검수 뒤 조건", ""] + [f"- 조건 {c.no}: {'통과' if c.ok else '실패'}. {c.text}" for c in conds]
    lines += ["", f"- ④ 는 보충하지 않는다(스펙 4-4절). 남은 ④ {n4}문항",
              "- 가짜 모델의 거리 1 이하 비율: " + ", ".join(f"늘 {k}점 {v:.1%}" for k, v in sorted(fakes.items(), reverse=True))]
    GATE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0 if all(c.ok for c in conds) else 2


def cmd_a() -> int:
    cases = _final_cases()
    det = read_json(DETERMINISM)
    res = gate_a([read_jsonl(p) for p in runs_for("M3pre", "new", det)], cases)
    write_json(GATE_A, res)
    for r in res["runs"]:
        print(f"실행 {r['run']}: ⑧ {r['eighth']}문항, 못 읽음 {r['unread']}, 심각한 놓침 {r['severe']}, 비율 {r['ratio']:.1%}")
    print(f"관문 (a): {'통과' if res['pass'] else '통과하지 못함'}(기준 {GATE_A_RATIO:.0%} 이상, 비율이 가장 낮은 실행으로 판정)")
    return 0 if res["pass"] else 2


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="검수 뒤 조건과 학습 전 관문 (a)")
    p.add_argument("which", choices=("review", "a"))
    return cmd_review() if p.parse_args(argv).which == "review" else cmd_a()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: 점검이 통과하는지 본다**

```bash
$PY -m tools.judgeft_gate_check | tail -1
```

Expected: `5가지 전부 통과.`

- [ ] **Step 6: 커밋한다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft
git add ai-service/tools/judgeft_determinism.py ai-service/tools/judgeft_gate.py ai-service/tools/judgeft_gate_check.py
git commit -m "feat: 결정성 확인, 검수 뒤 조건, 학습 전 관문 (a) 도구를 더한다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/tools/judgeft_determinism.py ai-service/tools/judgeft_gate.py ai-service/tools/judgeft_gate_check.py
```

**리뷰 포인트:** 관문 (a) 가 문항별 점수나 출력을 찍지 않는가. 분모에서 못 읽음을 빼는가. 판이 v2 와 다를 때 v2 결과와 대조하지 않는가. 판이 같아도 v2 와 다르면 새 환경의 run2 를 요구하고 v2 결과를 섞지 않는가(`use_v2`). 관문 (a) 가 ⑧ 중 정답 1점인 문항만 세는가. `runs_for` 가 스펙 8-1절의 표(M1 은 동결 시험지에서 v2 결과, 새 시험지에서 3회)와 같은가.

---

### Task 9: M1 채점 도구

**Files:**
- Create: `ai-service/tools/judgeft_cloudflare.py`, `ai-service/tools/judgeft_cloudflare_check.py`

**Interfaces:**
- Consumes: 태스크 2 의 `CASES`, `CASES_SHA`, `GATE_A`, `result_path`. `tools.judge5_cloudflare` 의 `MODEL_KEY`, `_call`, `_log_failure`, `done_ids`, `foreign_lines`, `result_line`
- Produces: `gate_passed() -> bool`, `run(n, limit) -> int`, 명령 `judgeft_cloudflare --run 1|2|3 [--limit N]`

- [ ] **Step 1: 점검을 먼저 쓴다**

```python
"""tools.judgeft_cloudflare 의 점검. Cloudflare 를 부르지 않는다.

실행:  cd ai-service && python -m tools.judgeft_cloudflare_check
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest import mock

from . import judgeft_cloudflare


def check_refuses_before_gates() -> None:
    """관문 (a), (b) 의 기록이 없거나 하나라도 통과하지 못했으면 호출하기 전에 멈춘다(스펙 8-1절)."""
    with tempfile.TemporaryDirectory() as d:
        gate, gate_b = Path(d) / "gate_a.json", Path(d) / "gate_b.json"
        # mock.patch.object: with 블록 안에서만 모듈의 이름을 바꿔 끼운다. 실제 gate_a.json 을 건드리지 않는다.
        with mock.patch.object(judgeft_cloudflare, "GATE_A", gate), mock.patch.object(judgeft_cloudflare, "GATE_B", gate_b), \
             mock.patch.object(judgeft_cloudflare, "_call", side_effect=AssertionError("부르면 안 된다")):
            assert judgeft_cloudflare.run(1, None) == 1
            gate.write_text(json.dumps({"pass": False}), encoding="utf-8")
            assert judgeft_cloudflare.run(1, None) == 1
            gate.write_text(json.dumps({"pass": True}), encoding="utf-8")
            assert judgeft_cloudflare.run(1, None) == 1          # (a) 만 통과, (b) 기록 없음
            gate_b.write_text(json.dumps({"finite": False}), encoding="utf-8")
            assert not judgeft_cloudflare.gate_passed()
            gate_b.write_text(json.dumps({"finite": True}), encoding="utf-8")
            assert judgeft_cloudflare.gate_passed()


CHECKS = [check_refuses_before_gates]


def main() -> None:
    for fn in CHECKS:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(CHECKS)}가지 전부 통과.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 점검이 실패하는지 본다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft/ai-service
$PY -m tools.judgeft_cloudflare_check
```

Expected: `ImportError` 또는 `ModuleNotFoundError`(`tools.judgeft_cloudflare` 가 없다)

- [ ] **Step 3: M1 채점 도구를 쓴다**

```python
"""M1(Cloudflare)으로 새 시험지를 채점한다. 실행 번호(1, 2, 3)를 받는다(스펙 8-1절).

실행:
    cd ai-service
    $PY -m tools.judge5_cloudflare --smoke              # 연결과 오늘의 한도 확인(v2 도구 그대로)
    $PY -m tools.judgeft_cloudflare --run 1 [--limit 10]

v2 의 judge5_cloudflare 는 실행 번호가 1 로 고정돼 있다. 그 파일을 고치지 않고 호출, 결과 줄, 이어 하기 함수를
가져다 쓴다. 학습 전 관문 (a) 와 (b) 를 모두 통과하기 전에는 돌지 않는다. 관문에서 끝나면 뉴런을 쓰지 않기 위해서다
(스펙 8-1절). (b) 에서 메모리가 모자라 사용자가 새 실험으로 돌리면 이 실험의 M1 결과는 쓰이지 않는다.
"""
from __future__ import annotations

import argparse
import json
import sys

from app import cf

from .judge5 import MODELS, sha256_file
from .judge5_cloudflare import MODEL_KEY, _call, _log_failure, done_ids, foreign_lines, result_line
from .judgeft_files import CASES, CASES_SHA, GATE_A, GATE_B, read_json, read_jsonl, result_path


def gate_passed() -> bool:
    """관문 (a) 는 pass, 관문 (b) 는 loss 가 숫자였는가(finite). (b) 가 메모리 부족이면 gate_b.json 자체가 없다."""
    a = GATE_A.exists() and bool(read_json(GATE_A).get("pass"))
    b = GATE_B.exists() and bool(read_json(GATE_B).get("finite"))
    return a and b


def run(n: int, limit: int | None) -> int:
    if not gate_passed():
        print("학습 전 관문 (a), (b) 를 모두 통과하지 않았습니다(gate_a.json, gate_b.json). "
              "M1 은 두 관문을 통과한 뒤에 돌립니다(스펙 8-1절, 계획 E17).")
        return 1
    actual = sha256_file(CASES)
    if actual != CASES_SHA.read_text(encoding="utf-8").split()[0]:
        print("새 시험지의 해시가 cases.sha256 과 다릅니다. 동결 커밋의 시험지인지 확인하세요.")
        return 1
    out = result_path("new", "M1", n)
    failures = out.with_name(f"M1_run{n}_failures.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    if foreign_lines(out, actual):
        print(f"{out.name} 에 다른 시험지로 채점한 줄이 있습니다. 섞이지 않게 멈춥니다(옮기고 다시 하세요).")
        return 1
    rows = read_jsonl(CASES)
    done = done_ids(out)
    failed = 0
    for r in [r for r in rows if r["case_id"] not in done][:limit]:
        try:
            text, finish = _call(r["messages"])
        except Exception as e:  # noqa: BLE001 - 한 건의 호출 실패가 나머지를 막지 않게 한다
            failed += 1
            _log_failure(failures, r["case_id"], "exception", f"{type(e).__name__}: {e}", None)
            continue
        if not text.strip():
            failed += 1     # 빈 응답은 API 쪽 이상이라 결과로 쓰지 않는다(v2 와 같다)
            _log_failure(failures, r["case_id"], "empty", "", finish)
            continue
        line = result_line(r["case_id"], MODEL_KEY, MODELS[MODEL_KEY], "cloudflare", n, text, finish, actual,
                           r.get("domain"))
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    total = len(done_ids(out))
    print(f"{out.name}: {total}/{len(rows)}건. 이번 호출 실패 {failed}건. 뉴런 {cf.neurons_used()}")
    return 0 if total == len(rows) else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="M1 으로 새 시험지를 채점한다")
    p.add_argument("--run", type=int, choices=(1, 2, 3), required=True)
    p.add_argument("--limit", type=int, default=None)
    args = p.parse_args(argv)
    return run(args.run, args.limit)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 점검이 통과하는지 본다**

```bash
$PY -m tools.judgeft_cloudflare_check | tail -1
```

Expected: `1가지 전부 통과.`

- [ ] **Step 5: 커밋한다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft
git add ai-service/tools/judgeft_cloudflare.py ai-service/tools/judgeft_cloudflare_check.py
git commit -m "feat: 관문 (a), (b) 통과 뒤에만 도는 M1 새 시험지 채점 도구를 더한다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/tools/judgeft_cloudflare.py ai-service/tools/judgeft_cloudflare_check.py
```

**리뷰 포인트:** 관문 (a), (b) 의 기록이 없거나 하나라도 통과가 아니면 호출 전에 멈추는가. 결과 줄이 v2 와 같은 키에 실행 번호만 다른가.

---

### Task 10: 보고서 도구

**Files:**
- Create: `ai-service/tools/judgeft_report.py`, `ai-service/tools/judgeft_report_check.py`

**Interfaces:**
- Consumes: 태스크 2 의 `ASSIGNMENT`, `TRAIN_DROPPED`, 태스크 8 의 `runs_for`. `tools.judge5` 의 `Comparison`, `compare`, `parse_result`, `sign_test_p`, `summarize`, `RULES_V2`. `tools.judge5v2_report` 의 `error_counts`. `tools.judge5v2_gate` 의 `fake_within1`
- Produces: `Metrics`, `keys()`, `scores_of(rows)`, `metrics(key, scores) -> Metrics`, `pipeline_lines(assignment, dropped) -> list[str]`(보충 회차에서 채운 수와 학습 데이터에서 뺀 수, 스펙 4-4절, 5-2절), `criteria(m) -> list[(번호, 통과, 설명)]`, `eighth_change(key, pre, post) -> Comparison`, `build() -> str`, 명령 `judgeft_report`

이 도구는 v2 의 결과 파일로 v2 결과 문서의 수치를 그대로 다시 낸다(2026-10-05 계획 작성 때 확인: 동결 시험지에서 M1 은 거리 1 이하 209, 헛경보 4(대상 둘 4, 그 밖 0), 심각한 놓침 1. M3 는 216, 10(3, 7), 5. M4 는 208, 17, 5, 못 읽음 1). 이 값이 v2 결과 5-1절과 같아야 점수 읽기와 세는 방식이 v2 와 같다는 뜻이다.

- [ ] **Step 1: 점검을 먼저 쓴다**

```python
"""tools.judgeft_report 의 점검. DB 도 외부 API 도 쓰지 않는다.

실행:  cd ai-service && python -m tools.judgeft_report_check
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest import mock

from . import judgeft_files, judgeft_report
from .judgeft_files import V2_RESULTS_DIR, read_jsonl, write_json, write_jsonl
from .judgeft_report import Metrics, criteria, eighth_change, metrics, pipeline_lines, training_summary, unread_kinds

KEY = {"e1": {"type": 8, "score": 1, "two_targets": True}, "e2": {"type": 8, "score": 1, "two_targets": True},
       "a1": {"type": 1, "score": 5, "two_targets": True}, "a2": {"type": 2, "score": 5, "two_targets": False},
       "t3": {"type": 4, "score": 3, "two_targets": False}}


def _m(**kw) -> Metrics:
    base = dict(within1=0, exact=0, mean_distance=None, unread=0, miss=0, false_alarm=0, severe=0, severe8=0,
                within1_ex8=10, fa_two=1, fa_one=1)
    return Metrics(**(base | kw))


def check_metrics_split_eighth_and_false_alarms() -> None:
    x = metrics(KEY, {"e1": 5, "e2": 1, "a1": 4, "a2": 5, "t3": 1})
    assert (x.severe, x.severe8, x.false_alarm, x.fa_two, x.fa_one) == (1, 1, 1, 1, 0)
    assert x.within1_ex8 == 2                         # a1(4), a2(5) 는 거리 1 이하, t3(1) 은 아니다. ⑧ 은 세지 않는다
    assert metrics(KEY, {"e1": None, "e2": 1, "a1": 5, "a2": 5, "t3": 3}).unread == 1


def check_criteria_use_worst_post_and_best_comparator() -> None:
    def table(post_sev_new: list[int], m1_sev_new: list[int]) -> dict:
        return {"M3ft": {"new": [_m(severe=s) for s in post_sev_new], "frozen": [_m(severe=1)]},
                "M3pre": {"new": [_m()], "frozen": [_m()]},
                "M1": {"new": [_m(severe=s) for s in m1_sev_new], "frozen": [_m(severe=1)]}}
    assert all(ok for _, ok, _ in criteria(table([2], [2, 3, 4])))           # 2 <= 가장 좋은 M1 2
    assert not criteria(table([1, 3], [2, 2, 2]))[0][1]                      # 학습 후 가장 나쁜 실행 3 > 2
    t = table([1], [2])
    t["M3ft"]["frozen"] = [_m(severe=1, fa_two=2)]                           # 대상이 둘인 질문의 헛경보가 늘었다
    assert not criteria(t)[2][1]
    t = table([1], [2])
    t["M3ft"]["new"] = [_m(severe=1, within1_ex8=9)]                         # ⑧ 뺀 거리 1 이하가 줄었다
    assert not criteria(t)[2][1]
    t = table([1], [2])
    t["M3ft"]["new"] = [_m(severe=1, unread=1)]                              # 못 읽음이 M1 보다 많다
    assert not criteria(t)[3][1]


def check_eighth_change_counts_fixed_and_new_misses() -> None:
    c = eighth_change(KEY, {"e1": 5, "e2": 1, "a1": 5, "a2": 5, "t3": 3}, {"e1": 1, "e2": 1, "a1": 5, "a2": 5, "t3": 3})
    assert (c.a_closer, c.b_closer, c.ties) == (1, 0, 1)
    six = {f"e{i}": {"type": 8, "score": 1, "two_targets": True} for i in range(6)}
    c6 = eighth_change(six, {k: 5 for k in six}, {k: 1 for k in six})
    assert abs(c6.p_value - 0.03125) < 1e-9                                  # 스펙 7-1절의 근거: 6개 모두 고쳐지면 약 0.03


def check_pipeline_lines_count_supplements_and_drops() -> None:
    a = {"rounds": [{"sheet": "test", "types": {"a": 1}, "pairs": []}, {"sheet": "test", "types": {"b": 8, "c": 1}, "pairs": []},
                    {"sheet": "train", "types": {"d": 8}, "pairs": ["d"]}]}
    out = pipeline_lines(a, {"main": {"x": ["인용이 없다"], "y": ["인용이 없다"]}, "pair": {"x": ["짝의 ⑧ 이 빠졌다"]}})
    assert out[0] == "- test: 배정 회차 2개, 보충 회차에서 채운 문항 2개"
    assert out[1] == "- train: 배정 회차 1개, 보충 회차에서 채운 문항 0개"
    assert "본 문항 2개, 짝 1개" in out[2] and "  - 인용이 없다: 2" in out


def check_unread_kinds_and_training_log_last_line() -> None:
    rows = [{"output": "x [RESULT] 5", "finish": "stop"}, {"output": "잘림", "finish": "length"},
            {"output": "[RESULT] 3 [RESULT] 4", "finish": "stop"}, {"output": "[RESULT] 9", "finish": "stop"}]
    assert unread_kinds(rows) == {"missing": 1, "conflict": 1, "out_of_range": 1, "length": 1}
    log = [{"session_start": 1, "mode": "train"}, {"step": 1, "train_loss": 2.0, "scale": 65536.0, "skipped": True},
           {"step": 2, "train_loss": 1.9, "scale": 32768.0, "skipped": False},
           {"session_start": 2, "mode": "train"}, {"resumed_from": 1}, {"step": 2, "train_loss": 1.5, "scale": 32768.0,
                                                                         "skipped": False, "val_loss": 1.4}]
    out = "\n".join(training_summary(log))
    assert "학습 단계 2개" in out and "학습 세션 2번" in out and "[1]" in out
    assert "마지막 단계 1.5000" in out and "2단계 1.4000" in out and "건너뛴 단계 1개 [1]" in out   # 단계마다 마지막 줄


def _write_fixture(d: Path, gate_pass: bool) -> dict:
    """새 시험지 4문항(⑧ 둘), 학습 전 M3 의 새 시험지 결과, 관문 기록. 동결 시험지는 v2 의 실제 파일을 쓴다."""
    cases = {f"e{i}": {"type": 8, "score": 1, "two_targets": True, "decision": "match"} for i in range(2)}
    cases |= {"a0": {"type": 1, "score": 5, "two_targets": True, "decision": "keep"},
              "b0": {"type": 4, "score": 3, "two_targets": False, "decision": "override"}}
    paths = {"ANSWER_KEY": d / "answer_key.json", "ASSIGNMENT": d / "assignment.json", "GATE_A": d / "gate_a.json",
             "GATE_B": d / "gate_b.json", "TRAIN_DONE": d / "train_done.json", "TRAINING_LOG": d / "training_log.jsonl",
             "TRAIN_DROPPED": d / "train_dropped.json", "DETERMINISM": d / "determinism.json"}
    write_json(paths["ANSWER_KEY"], {"stage": "final", "cases": cases,
                                     "dropped": {"x0": {"type": 6, "reason": "검수 메모"}}})
    write_json(paths["ASSIGNMENT"], {"rounds": [{"sheet": "test", "types": {}, "pairs": []}]})
    write_json(paths["GATE_A"], {"threshold": 0.1, "pass": gate_pass,
                                 "runs": [{"run": 1, "eighth": 2, "unread": 0, "severe": 1 if gate_pass else 0,
                                           "ratio": 0.5 if gate_pass else 0.0}]})
    write_json(paths["DETERMINISM"], {"pre": {"use_v2": True, "runs": 1}})
    out = [{"case_id": c, "output": "x [RESULT] 1", "finish": "stop"} for c in cases]
    write_jsonl(d / "results" / "new" / "M3pre_run1.jsonl", out)
    return paths


def check_report_builds_when_ended_at_gate_a() -> None:
    """관문 (a) 에서 끝나도 보고서가 나오고, 하지 않은 것은 하지 않음으로 적힌다."""
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        paths = _write_fixture(d, gate_pass=False)
        patches = [mock.patch.object(judgeft_report, k, v) for k, v in paths.items()]
        patches.append(mock.patch.object(judgeft_files, "RESULTS_DIR", d / "results"))
        for x in patches:
            x.start()
        try:
            text = judgeft_report.build()
            assert "판정: 통과하지 못함" in text and "관문 (b)" in text and "하지 않음(gate_b.json 이 없다" in text
            assert "버린 문항 1개: ⑥" in text and "사용자가 정답 점수 유지 1" in text and "검수 뒤 조건 1: 실패" in text
            assert "| 학습 후 M3 | 하지 않음(관문에서 끝났거나 채점하지 않았다. 없는 것: determinism.json 의 post) |" in text
            assert "new/M1_run1.jsonl, new/M1_run2.jsonl, new/M1_run3.jsonl" in text and "판정하지 않음" in text
            assert "#### 학습 전 M3 (첫 실행)" in text and "### 유형별 (시험지 new" in text   # 혼동행렬과 유형별 표
            assert "| 늘 1점 |" in text
            # 관문을 통과했는데 학습이 끝나지 않았으면 만들지 않는다(스펙 6-5절)
            write_json(paths["GATE_A"], {**json.loads(paths["GATE_A"].read_text()), "pass": True})
            try:
                judgeft_report.build()
            except SystemExit as e:
                assert "학습이 끝나지 않았습니다" in str(e)
            else:
                raise AssertionError("학습 전에 새 시험지 결과로 보고서를 만들었다")
        finally:
            for x in patches:
                x.stop()


def check_report_builds_full_with_criteria() -> None:
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        paths = _write_fixture(d, gate_pass=True)
        write_json(paths["GATE_B"], {"longest_id": "r1", "longest_tokens": 900, "peak_gb": 12.1, "step_seconds": 60.0,
                                     "total_steps": 135, "est_hours": 2.2, "save_every": 30, "finite": True,
                                     "losses": [1.2, 1.1]})
        write_json(paths["TRAIN_DONE"], {"adapter_sha256": "ab" * 32})
        write_jsonl(paths["TRAINING_LOG"], [{"session_start": 1, "mode": "train"},
                                            {"step": 1, "train_loss": 1.0, "scale": 65536.0, "skipped": False}])
        write_json(paths["DETERMINISM"], {"pre": {"use_v2": True, "runs": 1}, "post": {"runs": 1}})
        new_rows = read_jsonl(d / "results" / "new" / "M3pre_run1.jsonl")
        for n in (1, 2, 3):
            write_jsonl(d / "results" / "new" / f"M1_run{n}.jsonl", new_rows)
        write_jsonl(d / "results" / "new" / "M3ft_run1.jsonl", new_rows)
        write_jsonl(d / "results" / "frozen" / "M3ft_run1.jsonl", read_jsonl(V2_RESULTS_DIR / "M1_run1.jsonl"))
        patches = [mock.patch.object(judgeft_report, k, v) for k, v in paths.items()]
        patches.append(mock.patch.object(judgeft_files, "RESULTS_DIR", d / "results"))
        for x in patches:
            x.start()
        try:
            text = judgeft_report.build()
        finally:
            for x in patches:
                x.stop()
        assert "가장 긴 문항 r1(900토큰)" in text and "어댑터 SHA-256 abab" in text
        assert "- 기준 1:" in text and "- 기준 4:" in text and "⑧ 만의 짝 부호 검정(보고 항목)" in text
        # 세 실행 중 하나만 빠지면 그 파일 이름이 표에 나오고 기준은 판정하지 않는다
        (d / "results" / "new" / "M1_run2.jsonl").unlink()
        for x in patches:
            x.start()
        try:
            text = judgeft_report.build()
        finally:
            for x in patches:
                x.stop()
        assert "없는 것: new/M1_run2.jsonl) |" in text and "판정하지 않음" in text


CHECKS = [check_metrics_split_eighth_and_false_alarms, check_pipeline_lines_count_supplements_and_drops, check_criteria_use_worst_post_and_best_comparator,
          check_eighth_change_counts_fixed_and_new_misses, check_unread_kinds_and_training_log_last_line,
          check_report_builds_when_ended_at_gate_a, check_report_builds_full_with_criteria]


def main() -> None:
    for fn in CHECKS:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(CHECKS)}가지 전부 통과.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 점검이 실패하는지 본다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft/ai-service
$PY -m tools.judgeft_report_check
```

Expected: `ImportError: cannot import name 'judgeft_report' from 'tools'`(점검이 `from . import judgeft_report` 로 모듈을 불러 바꿔 끼우므로 `ModuleNotFoundError` 가 아니라 이 오류다)

- [ ] **Step 3: 보고서 도구를 쓴다**

```python
"""스펙 7절의 관문 결과, 8절의 수치, 비교, 교체 후보 기준, 9-3절의 검수 결과를 낸다.

실행:  cd ai-service && $PY -m tools.judgeft_report      # testdata/judgeft/report.md 를 쓴다

관문 (a) 에서 끝나도 보고서를 만든다. 그때 있는 결과만 내고, 돌리지 않은 모델과 비교는 "하지 않음" 으로 적는다.
관문 (a) 를 통과했는데 학습이 끝나지 않았으면(train_done.json 이 없으면) 만들지 않는다. 새 시험지의 학습 전 M3 결과를
학습이 끝나기 전에 열지 않기 위해서다(스펙 6-5절).

동결 시험지의 정답은 v2 의 정답 파일, 대상이 둘인 질문인지는 v2 의 질문 파일에서 읽는다. 모델마다 몇 번 돌린
결과를 쓰는지는 determinism.json 으로 정한다(judgeft_determinism.runs_for). 점수 읽기, 대조 수치, 부호 검정,
세 오류 수는 v2 의 함수(judge5, judge5v2_report)를 그대로 쓴다. 판정 문장은 v2 와 같은 세 가지뿐이다.
"""
from __future__ import annotations

import sys
from collections import Counter
from dataclasses import dataclass

from .judge5 import RULES_V2, SCALE, Comparison, compare, parse_result, sign_test_p, summarize
from .judge5v2_gate import fake_within1
from .judge5v2_report import _breakdown, error_counts
from .judgeft_determinism import runs_for
from .judgeft_files import (
    ANSWER_KEY, ASSIGNMENT, DETERMINISM, GATE_A, GATE_B, REPORT, SHEETS, TRAIN_DONE, TRAIN_DROPPED, TRAINING_LOG,
    TYPE_NAMES, V2_ANSWER_KEY, V2_QUESTIONS, read_json, read_jsonl,
)
from .judgeft_gate import review_conditions

DISPUTED = "3909377dbed6"   # 동결 시험지에서 M1 의 유일한 심각한 놓침. 정답 해석이 갈리는 문항(스펙 1-2절, 8-4절 기준 2)
NAMES = {"M1": "M1", "M3pre": "학습 전 M3", "M3ft": "학습 후 M3"}
BASIS = "대응표"


@dataclass(frozen=True)
class Metrics:
    within1: int
    exact: int
    mean_distance: float | None
    unread: int
    miss: int
    false_alarm: int
    severe: int
    severe8: int        # ⑧ 문항만의 심각한 놓침
    within1_ex8: int    # ⑧ 을 뺀 문항의 거리 1 이하(기준 3)
    fa_two: int         # ⑧ 을 뺀 문항 중 대상이 둘인 질문의 헛경보(기준 3)
    fa_one: int         # ⑧ 을 뺀 문항 중 그 밖의 질문의 헛경보(기준 3)


def keys() -> dict[str, dict[str, dict]]:
    """시험지마다 {문항 id: {type, score, two_targets}}."""
    new = {cid: {"type": k["type"], "score": k["score"], "two_targets": k["two_targets"]}
           for cid, k in read_json(ANSWER_KEY)["cases"].items()}
    contrast = {q["qid"]: q.get("contrast") is not None for q in read_jsonl(V2_QUESTIONS)}
    frozen = {cid: {"type": k["type"], "score": k["score"], "two_targets": contrast[k["qid"]]}
              for cid, k in read_json(V2_ANSWER_KEY)["cases"].items()}
    return {"new": new, "frozen": frozen}


def scores_of(rows: list[dict]) -> dict[str, int | None]:
    return {r["case_id"]: parse_result(r["output"], r.get("finish"), rules=RULES_V2)[0] for r in rows}


def unread_kinds(rows: list[dict]) -> dict[str, int]:
    """못 읽음을 원인별로 센다. missing, conflict, out_of_range 는 parse_result 의 상태이고,
    length 는 그중 512 토큰에서 잘린 것이다. 원인이 다르면 고칠 곳이 다르다(양식이 무너짐, 끝을 모름, 값이 틀림)."""
    out: Counter = Counter()
    for r in rows:
        score, state = parse_result(r["output"], r.get("finish"), rules=RULES_V2)
        if score is None:
            out[state] += 1
            out["length"] += r.get("finish") == "length"
    return {k: out[k] for k in ("missing", "conflict", "out_of_range", "length")}


def _kinds_text(k: dict[str, int]) -> str:
    return f"missing {k['missing']}(그중 잘림 {k['length']}), conflict {k['conflict']}, out_of_range {k['out_of_range']}"


def metrics(key: dict[str, dict], scores: dict[str, int | None]) -> Metrics:
    if missing := set(key) - set(scores):
        raise SystemExit(f"결과에 없는 문항이 {len(missing)}개 있습니다. 보고서를 만들지 않습니다(v2 스펙 6-5절).")
    pairs = [(k["score"], scores[c]) for c, k in key.items()]
    s, e = summarize(pairs), error_counts(pairs)
    ex8 = {c: k for c, k in key.items() if k["type"] != 8}
    within_ex8 = sum(1 for c, k in ex8.items() if scores[c] is not None and abs(scores[c] - k["score"]) <= 1)

    def fa(two: bool) -> int:
        return sum(1 for c, k in ex8.items() if k["score"] == 5 and k["two_targets"] == two
                   and scores[c] is not None and scores[c] <= 4)
    severe8 = sum(1 for c, k in key.items() if k["type"] == 8 and k["score"] == 1
                  and scores[c] is not None and scores[c] >= 4)
    return Metrics(s.within1, s.exact, s.mean_distance, s.unread, e.miss, e.false_alarm, e.severe_miss, severe8,
                   within_ex8, fa(True), fa(False))


def criteria(m: dict[str, dict[str, list[Metrics]]]) -> list[tuple[int, bool, str]]:
    """스펙 8-4절의 네 기준. 학습 후 M3 는 실행 중 가장 나쁜 값, 비교 상대는 가장 좋은 값을 쓴다."""
    post, pre, m1 = m["M3ft"], m["M3pre"], m["M1"]

    def worst(xs, f, high_is_bad=True):
        return (max if high_is_bad else min)(f(x) for x in xs)

    def best(xs, f, high_is_bad=True):
        return (min if high_is_bad else max)(f(x) for x in xs)
    out = []
    for no, sheet in ((1, "new"), (2, "frozen")):
        a, b = worst(post[sheet], lambda x: x.severe), best(m1[sheet], lambda x: x.severe)
        out.append((no, a <= b, f"{sheet}: 심각한 놓침 학습 후 M3 {a}, M1 {b}"))
    ok3, txt3 = True, []
    for sheet in SHEETS:
        w = (worst(post[sheet], lambda x: x.within1_ex8, False), best(pre[sheet], lambda x: x.within1_ex8, False))
        f2 = (worst(post[sheet], lambda x: x.fa_two), best(pre[sheet], lambda x: x.fa_two))
        f1 = (worst(post[sheet], lambda x: x.fa_one), best(pre[sheet], lambda x: x.fa_one))
        ok3 &= w[0] >= w[1] and f2[0] <= f2[1] and f1[0] <= f1[1]
        txt3.append(f"{sheet}: ⑧ 뺀 거리 1 이하 {w[0]} 대 {w[1]}, 헛경보(대상 둘) {f2[0]} 대 {f2[1]}, "
                    f"헛경보(그 밖) {f1[0]} 대 {f1[1]}")
    out.append((3, ok3, "; ".join(txt3) + " (학습 후 대 학습 전)"))
    ok4, txt4 = True, []
    for sheet in SHEETS:
        a, b = worst(post[sheet], lambda x: x.unread), best(m1[sheet], lambda x: x.unread)
        ok4 &= a <= b
        txt4.append(f"{sheet}: 못 읽음 학습 후 M3 {a}, M1 {b}")
    out.append((4, ok4, "; ".join(txt4)))
    return out


def eighth_change(key: dict[str, dict], pre: dict[str, int | None], post: dict[str, int | None]) -> Comparison:
    """⑧ 만의 짝 부호 검정(스펙 8-3절). a 는 학습 후 M3 가 나은 문항(학습 전에 심각하게 놓쳤고 학습 후에 놓치지 않음)."""
    excluded = fixed = broken = same = 0
    for c, k in key.items():
        if k["type"] != 8 or k["score"] != 1:   # severe8, 관문 (a) 와 같은 범위
            continue
        x, y = pre[c], post[c]
        if x is None or y is None:
            excluded += 1
        elif x >= 4 > y:
            fixed += 1
        elif y >= 4 > x:
            broken += 1
        else:
            same += 1
    return Comparison(excluded, fixed, broken, same, sign_test_p(fixed, fixed + broken))


def _fmt(x: float | None) -> str:
    return "-" if x is None else f"{x:.3f}"


def pipeline_lines(assignment: dict, dropped: dict) -> list[str]:
    """보충 회차에서 채운 수와 학습 데이터에서 뺀 수(스펙 4-4절, 5-2절). 보고서 맨 앞에 적는다."""
    out = []
    for sheet in ("test", "train"):
        rounds = [r for r in assignment["rounds"] if r["sheet"] == sheet]
        added = sum(len(r["types"]) + len(r["pairs"]) for r in rounds[1:])
        out.append(f"- {sheet}: 배정 회차 {len(rounds)}개, 보충 회차에서 채운 문항 {added}개")
    reasons: Counter = Counter(why for part in dropped.values() for whys in part.values() for why in whys)
    out.append(f"- 학습 데이터에서 뺀 문항: 본 문항 {len(dropped.get('main', {}))}개, 짝 {len(dropped.get('pair', {}))}개")
    out += [f"  - {why}: {n}" for why, n in reasons.most_common()]
    return out


def training_summary(lines: list[dict]) -> list[str]:
    """학습 기록(training_log.jsonl)을 요약한다. 단계마다 마지막 줄을 쓴다.

    끊긴 뒤 이어 하면 마지막 체크포인트 뒤의 단계를 다시 하므로 같은 단계의 줄이 두 번 적힐 수 있다.
    채점에 쓰는 어댑터는 다시 한 쪽의 결과이므로 마지막 줄이 맞는 값이다.
    """
    steps: dict[int, dict] = {}
    for line in lines:
        if "step" in line:
            steps[line["step"]] = line   # 같은 단계면 뒤의 줄이 앞의 줄을 덮는다
    sessions = sum(1 for line in lines if "session_start" in line and line.get("mode") == "train")
    resumed = [line["resumed_from"] for line in lines if "resumed_from" in line]
    bad = [(line["bad_checkpoint"], line["reason"]) for line in lines if "bad_checkpoint" in line]
    if not steps:
        return ["- 학습 기록에 단계가 없다"]
    order = sorted(steps)
    vals = [(n, steps[n]["val_loss"]) for n in order if "val_loss" in steps[n]]
    skipped = [n for n in order if steps[n].get("skipped")]
    out = [f"- 학습 단계 {len(order)}개(마지막 {order[-1]}), 학습 세션 {sessions}번, 이어 한 체크포인트 {resumed or '없음'}",
           f"- 학습 loss: 첫 단계 {steps[order[0]]['train_loss']:.4f}, 마지막 단계 {steps[order[-1]]['train_loss']:.4f}",
           "- 검증 loss(체크포인트마다): " + (", ".join(f"{n}단계 {v:.4f}" for n, v in vals) or "없음"),
           f"- loss scaling 으로 건너뛴 단계 {len(skipped)}개{(' ' + str(skipped)) if skipped else ''}, "
           f"마지막 scale {steps[order[-1]].get('scale')}"]
    if bad:
        out.append("- 깨져서 건너뛴 체크포인트: " + ", ".join(f"{n}단계({why})" for n, why in bad))
    return out


def review_lines(ak: dict) -> list[str]:
    """검수 결과(스펙 5-1절, 9-3절). 사용자 판단별 수, 버린 문항의 유형별 수, 검수 뒤 세 조건."""
    decisions = Counter(k["decision"] for k in ak["cases"].values())
    dropped = Counter(TYPE_NAMES[k["type"]] for k in ak["dropped"].values())
    out = [f"- 남은 문항 {len(ak['cases'])}개: 검수 점수와 같음 {decisions['match']}, 사용자가 정답 점수 유지 "
           f"{decisions['keep']}, 사용자가 점수를 바꿈 {decisions['override']}",
           f"- 버린 문항 {len(ak['dropped'])}개" + (": " + ", ".join(f"{t} {n}" for t, n in sorted(dropped.items()))
                                                   if dropped else "")]
    out += [f"- 검수 뒤 조건 {c.no}: {'통과' if c.ok else '실패'}. {c.text}" for c in review_conditions(ak["cases"])]
    return out


def gate_lines(gate_a: dict | None, gate_b: dict | None) -> list[str]:
    """학습 전 관문 결과(스펙 7절). 통과 여부와 관계없이 적는다. 기록이 없으면 하지 않았다고 적는다."""
    out = ["### 관문 (a): 학습 전 M3 가 새 시험지의 ⑧ 에서 속는가", ""]
    if gate_a is None:
        out.append("- 하지 않음(gate_a.json 이 없다)")
    else:
        out += [f"- 실행 {r['run']}: ⑧(정답 1점) {r['eighth']}문항, 못 읽음 {r['unread']}, 심각한 놓침 {r['severe']}, "
                f"비율 {r['ratio']:.1%}" for r in gate_a["runs"]]
        out.append(f"- 판정: {'통과' if gate_a['pass'] else '통과하지 못함'}(기준 {gate_a['threshold']:.0%} 이상, "
                   "비율이 가장 낮은 실행으로 판정)")
    out += ["", "### 관문 (b): 코랩 T4 에서 학습이 메모리에 올라가는가", ""]
    if gate_b is None:
        out.append("- 하지 않음(gate_b.json 이 없다. 관문 (a) 에서 끝났거나 메모리가 모자라 기록을 남기지 못했다)")
    else:
        out += [f"- 가장 긴 문항 {gate_b['longest_id']}({gate_b['longest_tokens']}토큰), GPU 메모리 최대 {gate_b['peak_gb']}GB",
                f"- 학습 단계 하나 {gate_b['step_seconds']}초, 전체 {gate_b['total_steps']}단계 어림 {gate_b['est_hours']}시간"
                f"(가장 긴 문항으로 잰 값이라 실제보다 길다), 체크포인트 간격 {gate_b['save_every']}단계",
                f"- loss 가 숫자였는가: {gate_b['finite']}({gate_b['losses']})"]
    return out


def available(model: str, sheet: str, det: dict) -> tuple[list[list[dict]] | None, list[str]]:
    """(그 모델과 시험지의 결과 줄(실행마다), 없는 것의 이름). 하나라도 없으면 결과는 None(하지 않음)이다.

    없는 것의 이름을 함께 돌려주는 이유: 세 실행 중 하나만 빠진 것과 아예 돌리지 않은 것이 표에서 같은
    "하지 않음" 으로 보이면, 마저 채점하면 되는 일을 실험이 끝난 것으로 읽게 된다.
    """
    try:
        paths = runs_for(model, sheet, det)
    except KeyError:   # det 에 pre 나 post 가 없다: 그 확인까지 가지 않았다
        return None, ["determinism.json 의 " + ("post" if model == "M3ft" else "pre")]
    # 이름은 "폴더/파일" 로 적는다. 새 실험의 결과는 new/ 와 frozen/, v2 의 결과는 v2 의 results/ 아래다.
    if missing := [f"{p.parent.name}/{p.name}" for p in paths if not p.exists()]:
        return None, missing
    return [read_jsonl(p) for p in paths], []


def _confusion(name: str, key: dict[str, dict], scores: dict[str, int | None]) -> list[str]:
    s = summarize([(k["score"], scores[c]) for c, k in key.items()])
    out = [f"#### {name} (첫 실행)", "", "| 정답 점수 \\ 모델 | " + " | ".join(str(v) for v in SCALE) + " |",
           "|---" * (len(SCALE) + 1) + "|"]
    return out + [f"| {h} | " + " | ".join(str(s.confusion[(h, v)]) for v in SCALE) + " |" for h in SCALE] + [""]


def build() -> str:
    gate_a = read_json(GATE_A) if GATE_A.exists() else None
    if gate_a is None:
        raise SystemExit("관문 (a) 의 결과(gate_a.json)가 없습니다. 보고서는 관문 (a) 뒤에 만듭니다.")
    if gate_a["pass"] and not TRAIN_DONE.exists():
        raise SystemExit("관문 (a) 를 통과했는데 학습이 끝나지 않았습니다(train_done.json 이 없다). 새 시험지의 결과를 "
                         "학습이 끝나기 전에 열지 않습니다(스펙 6-5절).")
    ks = keys()
    det = read_json(DETERMINISM) if DETERMINISM.exists() else {}
    found = {mod: {sh: available(mod, sh, det) for sh in SHEETS} for mod in NAMES}
    rows = {mod: {sh: found[mod][sh][0] for sh in SHEETS} for mod in NAMES}
    absent = {mod: {sh: found[mod][sh][1] for sh in SHEETS} for mod in NAMES}
    raw = {mod: {sh: [scores_of(r) for r in rows[mod][sh]] if rows[mod][sh] else None for sh in SHEETS} for mod in NAMES}
    m = {mod: {sh: [metrics(ks[sh], x) for x in raw[mod][sh]] if raw[mod][sh] else None for sh in SHEETS} for mod in NAMES}
    dropped = read_json(TRAIN_DROPPED) if TRAIN_DROPPED.exists() else {}
    lines = ["# 채점 모델 파인튜닝 실험 보고서", "", f"결정성: {det or '확인하지 않음'}", "",
             "## 문항과 학습 데이터의 경위", ""]
    lines += pipeline_lines(read_json(ASSIGNMENT), dropped) + ["", "## 새 시험지의 검수 결과 (스펙 5-1절)", ""]
    lines += review_lines(read_json(ANSWER_KEY)) + ["", "## 학습 전 관문 (스펙 7절)", ""]
    lines += gate_lines(gate_a, read_json(GATE_B) if GATE_B.exists() else None) + ["", "## 학습 기록 (스펙 6-3절, 6-4절)", ""]
    if TRAINING_LOG.exists():
        lines += training_summary(read_jsonl(TRAINING_LOG))
        if TRAIN_DONE.exists():
            lines.append(f"- 어댑터 SHA-256 {read_json(TRAIN_DONE)['adapter_sha256']}")
    else:
        lines.append("- 하지 않음(학습하지 않았다)")
    lines.append("")
    for sh in SHEETS:
        lines += [f"## 시험지 {sh} ({len(ks[sh])}문항)", "",
                  "| 모델 | 실행 | 거리 1 이하 | ⑧ 뺀 거리 1 이하 | 놓침 | 헛경보 | 헛경보(대상 둘) | 헛경보(그 밖) "
                  "| 심각한 놓침 | ⑧ 심각한 놓침 | 정확히 같음 | 평균 거리 | 못 읽음 | 못 읽음의 원인 |", "|" + "---|" * 14]
        for mod, name in NAMES.items():
            if m[mod][sh] is None:
                lines.append(f"| {name} | 하지 않음(관문에서 끝났거나 채점하지 않았다. 없는 것: "
                             f"{', '.join(absent[mod][sh])}) |" + " |" * 12)
                continue
            for i, (x, r) in enumerate(zip(m[mod][sh], rows[mod][sh]), 1):
                lines.append(f"| {name} | {i} | {x.within1} | {x.within1_ex8} | {x.miss} | {x.false_alarm} | {x.fa_two} "
                             f"| {x.fa_one} | {x.severe} | {x.severe8} | {x.exact} | {_fmt(x.mean_distance)} | {x.unread} "
                             f"| {_kinds_text(unread_kinds(r)) if x.unread else '-'} |")
        for v in sorted(SCALE, reverse=True):   # 다섯 가짜 모델(스펙 8-2절)
            x = metrics(ks[sh], {c: v for c in ks[sh]})
            lines.append(f"| 늘 {v}점 | - | {x.within1} | {x.within1_ex8} | {x.miss} | {x.false_alarm} | {x.fa_two} "
                         f"| {x.fa_one} | {x.severe} | {x.severe8} | {x.exact} | {_fmt(x.mean_distance)} | 0 | - |")
        fakes = fake_within1([k["score"] for k in ks[sh].values()])
        lines += ["", "가짜 모델의 거리 1 이하 비율: "
                  + ", ".join(f"늘 {k}점 {v:.1%}" for k, v in sorted(fakes.items(), reverse=True)), ""]
        human = {c: k["score"] for c, k in ks[sh].items()}
        for a, b in (("M3ft", "M3pre"), ("M3ft", "M1")):
            if raw[a][sh] is None or raw[b][sh] is None:
                lines.append(f"- {NAMES[a]} 와 {NAMES[b]}: 하지 않음. 결과가 없는 모델이 있다")
                continue
            c = compare(human, raw[a][sh][0], raw[b][sh][0])
            lines.append(f"- {NAMES[a]} 와 {NAMES[b]}(첫 실행): {NAMES[a]} 가 더 가까움 {c.a_closer}, "
                         f"{NAMES[b]} 가 더 가까움 {c.b_closer}, 같음 {c.ties}, 제외 {c.excluded}, p = {c.p_value:.4f}, "
                         f"판정 **{c.verdict(NAMES[a], NAMES[b], BASIS)}**")
        if sh == "new" and raw["M3pre"][sh] and raw["M3ft"][sh]:
            e = eighth_change(ks[sh], raw["M3pre"][sh][0], raw["M3ft"][sh][0])
            lines.append(f"- ⑧ 만의 짝 부호 검정(보고 항목): 학습 후 고쳐진 놓침 {e.a_closer}, 새로 생긴 놓침 "
                         f"{e.b_closer}, 제외 {e.excluded}, p = {e.p_value:.4f}, 판정 **{e.verdict(NAMES['M3ft'], NAMES['M3pre'], BASIS)}**")
        elif sh == "new":
            lines.append("- ⑧ 만의 짝 부호 검정: 하지 않음. 학습 후 M3 의 결과가 없다")
        else:
            lines.append(f"- {DISPUTED}(정답 해석이 갈리는 문항): " + ", ".join(
                f"{NAMES[mod]} {raw[mod][sh][0].get(DISPUTED)}점" for mod in NAMES if raw[mod][sh]))
        have = {NAMES[mod]: raw[mod][sh][0] for mod in NAMES if raw[mod][sh]}
        lines += ["", f"### 혼동행렬 (시험지 {sh}, 행은 정답 점수, 열은 모델 점수)", ""]
        for name, sc in have.items():
            lines += _confusion(name, ks[sh], sc)
        by_type = {TYPE_NAMES[t]: [c for c, k in ks[sh].items() if k["type"] == t]
                   for t in sorted({k["type"] for k in ks[sh].values()})}
        lines += _breakdown(f"유형별 (시험지 {sh}, 첫 실행, 판정에 쓰지 않는다)", by_type, human, have)
    lines += ["## 교체 후보의 기준 (스펙 8-4절)", ""]
    if any(m[mod][sh] is None for mod in NAMES for sh in SHEETS):
        lines.append("- 판정하지 않음. 결과가 없는 모델이 있다(관문에서 끝났거나 학습 후 채점을 하지 않았다)")
        return "\n".join(lines) + "\n"
    crit = criteria(m)
    lines += [f"- 기준 {no}: {'통과' if ok else '실패'}. {txt}" for no, ok, txt in crit]
    lines += ["", f"**학습 후 M3 는 교체 후보{'다' if all(ok for _, ok, _ in crit) else '가 아니다'}.**"]
    return "\n".join(lines) + "\n"


def main() -> int:
    REPORT.write_text(build(), encoding="utf-8")
    print(f"보고서: {REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 점검이 통과하고 v2 수치가 다시 나오는지 본다**

```bash
$PY -m tools.judgeft_report_check | tail -1
$PY - <<'EOF'
from tools.judgeft_files import V2_ANSWER_KEY, V2_QUESTIONS, V2_RESULTS_DIR, read_json, read_jsonl
from tools.judgeft_report import metrics, scores_of, unread_kinds
contrast = {q["qid"]: q.get("contrast") is not None for q in read_jsonl(V2_QUESTIONS)}
key = {c: {"type": k["type"], "score": k["score"], "two_targets": contrast[k["qid"]]}
       for c, k in read_json(V2_ANSWER_KEY)["cases"].items()}
for m in ("M1", "M3", "M4"):
    rows = read_jsonl(V2_RESULTS_DIR / f"{m}_run1.jsonl")
    x = metrics(key, scores_of(rows))
    print(m, x.within1, x.false_alarm, x.fa_two, x.fa_one, x.severe, x.unread, unread_kinds(rows))
EOF
```

Expected: `7가지 전부 통과.` 그리고

```
M1 209 4 4 0 1 0 {'missing': 0, 'conflict': 0, 'out_of_range': 0, 'length': 0}
M3 216 10 3 7 5 0 {'missing': 0, 'conflict': 0, 'out_of_range': 0, 'length': 0}
M4 208 17 7 10 5 1 {'missing': 1, 'conflict': 0, 'out_of_range': 0, 'length': 0}
```

- [ ] **Step 5: 커밋한다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft
git add ai-service/tools/judgeft_report.py ai-service/tools/judgeft_report_check.py
git commit -m "feat: 파인튜닝 실험의 수치, 학습 전후 비교, 교체 후보 기준을 내는 보고서 도구를 더한다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/tools/judgeft_report.py ai-service/tools/judgeft_report_check.py
```

**리뷰 포인트:** 기준 3 이 ⑧ 을 뺀 문항에서 세는가, 헛경보를 대상이 둘인 질문과 그 밖으로 나눠 각각 보는가. 실행이 여럿일 때 학습 후 M3 는 가장 나쁜 값, 비교 상대는 가장 좋은 값을 쓰는가. 판정 문장이 v2 와 같은 세 가지뿐인가. `3909377dbed6` 을 따로 표시하는가.

---

### Task 11: 노트북 생성

**Files:**
- Create: `ai-service/tools/judgeft_notebooks.py`, `ai-service/notebooks/judgeft_train_colab.ipynb`, `ai-service/notebooks/judgeft_eval_colab.ipynb`

**Interfaces:**
- Consumes: 태스크 2 의 학습 상수, `PINS`, `M3_REPO`, `M3_REVISION`, `FROZEN_SHA256`, `CASES_SHA`, `TRAIN_SHA`. 태스크 7 의 `build_example`(본문을 `inspect.getsource` 로 옮긴다). `tools.judge5` 의 `MAX_NEW_TOKENS`, `smoke_messages`
- Produces: `TRAIN_NB`, `EVAL_NB`, `train_notebook()`, `eval_notebook()`, `expected() -> {경로: 글}`, 명령 `judgeft_notebooks`

노트북을 손으로 고치지 않고 이 도구로 만든다. 이유는 모듈 머리말의 셋이다. 동결 커밋(E11) 전에는 해시 파일이 없어 노트북의 기대 해시가 빈 글자이고, 노트북은 빈 해시를 받으면 멈춘다. E11 에서 이 도구를 다시 돌리면 해시가 채워진다.

**학습 노트북이 하는 일**(스펙 6절, 7-2절):
- 첫 칸에서 `transformers==4.57.6`, `bitsandbytes==0.50.2`, `peft==0.17.1`, `accelerate==1.10.1` 을 깔고, 둘째 칸에서 깔린 판이 고정한 판과 다르면 멈춘다. 둘째 칸의 `MODE` 는 비어 있고, 비운 채 실행하면 멈춘다. 체크포인트가 이미 있으면 `gate_b` 를 거절한다. 세션마다 `training_log.jsonl` 에 `session_start` 줄을 쓴다.
- 환경(GPU, torch 와 라이브러리 판)은 `gate_b` 에서는 `gate_b.json` 의 `env` 에, 학습에서는 첫 세션에 `train_env.json` 으로 적는다. 이어 하는 세션은 `train_env.json` 과 비교해 다르면 멈춘다.
- `MODE = 'gate_b'`: 먼저 `model.train()` 을 부르고 층마다 gradient checkpointing 이 켜졌는지 확인한다. 그다음 가장 긴 학습 문항(토큰 수 기준)으로 학습 단계 둘을 돌려 GPU 최대 메모리, 단계 하나의 시간, loss 가 숫자인지를 `gate_b.json` 에 적는다. 단계 시간에 전체 단계 수를 곱해 학습 시간을 어림하고, 약 30분마다 체크포인트가 되는 간격(`save_every`)을 정한다.
- `MODE = 'train'`: 바퀴마다 시드로 섞은 순서로 학습한다. `save_every` 단계마다 검증 loss 를 재고 체크포인트(어댑터, 옵티마이저, 스케줄러, loss scaler, 단계 번호, 세 난수 상태)를 저장한다. 저장의 마지막에 두 파일(어댑터, 상태)의 SHA-256 을 담은 `done` 파일을 써서, 저장 도중 끊긴 체크포인트는 이어 하기에서 건너뛴다. 다시 실행하면 가장 최근 체크포인트부터 해시를 확인하고, 맞지 않으면 기록(`bad_checkpoint`)하고 지운 뒤 하나 앞의 것에서 이어 한다. 가장 최근 둘만 남긴다. 단계마다 loss scaling 의 `scale` 과 그 단계를 건너뛰었는지(`skipped`)를, 저장할 때마다 Drive 의 남은 용량(`drive_free_gb`)을 학습 기록에 적는다. 끝나면 마지막 단계의 어댑터를 `adapter/` 에 저장하고 SHA-256 을 `train_done.json` 에 적는다.
- loss 가 숫자가 아니면 그 자리에서 멈춘다(스펙 6-5절).
- `prepare_model_for_kbit_training` 을 쓰지 않는다. 그 함수는 4비트가 아닌 층을 float32 로 바꿔 임베딩과 lm_head 만 약 6GB 가 된다. gradient checkpointing 과 입력 기울기 경로만 직접 켠다.

**채점 노트북이 하는 일**(스펙 8-1절): v2 노트북의 `load` 와 `generate`(탐욕적 디코딩, `use_model_defaults=False`, 처음부터 만든 생성 설정)를 그대로 따르고, `SHEET`(new, frozen), `MODEL`(M3pre, M3ft), `RUN`(1~3)을 칸 맨 위의 값으로 받는다. 학습 후 M3 는 어댑터 해시를 확인한 뒤 `PeftModel.from_pretrained` 로 얹는다(합치지 않는다). 결과는 Drive 의 `results/<시험지>/<모델>_run<번호>.jsonl` 과 `.env.json` 이다. `M3pre` 인데 `ADAPTER_SHA256` 이 채워져 있거나 `M3ft` 인데 비어 있으면 멈춘다. 이어 할 때는 `.env.json` 과 환경을 비교해 다르면 멈추고, 쓰다가 끊긴 마지막 줄은 버리고 `<모델>_run<번호>_resume.log` 에 적는다. **문항마다 점수를 찍지 않는다.** 학습이 끝날 때까지 새 시험지의 결과를 보지 않기 위해서다.

- [ ] **Step 1: 노트북 생성 도구를 쓴다**

```python
"""학습 노트북과 채점 노트북을 만든다(스펙 6절, 8-1절).

실행:  cd ai-service && $PY -m tools.judgeft_notebooks       # notebooks/judgeft_train_colab.ipynb, judgeft_eval_colab.ipynb

노트북을 손으로 고치지 않고 이 파일에서 만든다. 이유는 셋이다.
1. 상수(LoRA 설정, 라이브러리 판, 시험지 해시)를 judgeft_files 한 곳에서 가져와, 노트북과 도구의 값이 어긋나지 않게 한다.
2. 토큰화 함수(judgeft_labels.build_example)의 본문을 글자 그대로 옮긴다. CI 가 점검한 함수와 코랩이 쓰는 함수가 같다.
3. 점검(judgeft_check)이 이 파일로 노트북을 다시 만들어 커밋된 노트북과 바이트까지 같은지 본다. 손으로 고친 곳이 있으면 걸린다.
"""
from __future__ import annotations

import inspect
import json
import sys

from . import judgeft_files as F
from .judge5 import MAX_NEW_TOKENS, smoke_messages
from .judgeft_labels import build_example

TRAIN_NB = F.ROOT / "notebooks" / "judgeft_train_colab.ipynb"
EVAL_NB = F.ROOT / "notebooks" / "judgeft_eval_colab.ipynb"
DRIVE_DIR = "/content/drive/MyDrive/alldap_judgeft"


def _hashes() -> dict[str, str]:
    """동결 커밋 전에는 해시 파일이 없어 빈 글자다. 노트북은 빈 해시를 받으면 멈춘다(동결 전 실행을 막는다)."""
    out = {"cases_new": "", "train": "", "val": ""}
    if F.CASES_SHA.exists():
        out["cases_new"] = F.CASES_SHA.read_text(encoding="utf-8").split()[0]
    if F.TRAIN_SHA.exists():
        lines = dict(reversed(line.split()) for line in F.TRAIN_SHA.read_text(encoding="utf-8").splitlines())
        out["train"], out["val"] = lines.get("train.jsonl", ""), lines.get("val.jsonl", "")
    return out


def _md(text: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": text}


def _code(text: str) -> dict:
    return {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": text}


def _nb(cells: list[dict]) -> dict:
    return {"cells": cells, "metadata": {"accelerator": "GPU", "colab": {"provenance": []},
                                         "kernelspec": {"display_name": "Python 3", "name": "python3"}},
            "nbformat": 4, "nbformat_minor": 0}


# 사용자 안내(두 노트북 공통). 사용자는 파이썬과 코랩에 익숙하지 않다.
GUIDE = """**처음 여는 법:** colab.research.google.com 에서 파일 > 노트북 업로드 로 이 `.ipynb` 파일을 고른다.

**허용 창:** 첫 실행에서 두 창이 뜬다. "이 노트북에 보안 비밀 액세스 권한을 부여하시겠습니까?" 에는 **액세스 권한 부여**, "이 노트북에서 Google Drive 파일에 액세스하도록 허용하시겠습니까?" 에는 **Google Drive에 연결** 을 누르고 계정을 고른 뒤 모두 허용한다. `HF_TOKEN` 이 목록에 있으면 그 줄의 "노트북 액세스" 스위치를 켠다.

**오류가 나면:** 모두 실행이 그 칸에서 멈추고 zip 도 내려받아지지 않는다. 빨간 오류 글의 **마지막 다섯 줄쯤** 을 복사해 그대로 알려 준다. 칸을 고치거나 값을 바꾸지 않는다.

**오래 걸리는 동안:** 브라우저 탭을 닫지 않고 열어 둔다. 컴퓨터의 잠자기를 끈다(맥: 시스템 설정 > 디스플레이 또는 배터리 > 잠자기 방지). 무료 GPU 한도에 걸려 "GPU 백엔드에 연결할 수 없습니다" 가 뜨면 몇 시간 뒤(보통 다음 날) 다시 연다. 이미 한 일은 Drive 에 남아 이어 한다."""

PIP = "!pip install -q " + " ".join(f'"{k}=={v}"' for k, v in F.PINS.items()) + " huggingface_hub\n"

COMMON = f'''import gc, glob, hashlib, json, math, os, platform, random, shutil, time
import torch, transformers, bitsandbytes, peft, accelerate
from google.colab import drive, userdata, files
from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig, GenerationConfig

drive.mount('/content/drive')
DIR = {DRIVE_DIR!r}
HF_TOKEN = userdata.get('HF_TOKEN')
M3_REPO = {F.M3_REPO!r}
M3_REVISION = {F.M3_REVISION!r}   # v2 와 같은 리비전으로 고정한다(스펙 6-1절)
PINS = {F.PINS!r}

def sha_of(path):
    return hashlib.sha256(open(path, 'rb').read()).hexdigest()

def env_record():
    # 판이 하나라도 다르면 같은 설정에서도 출력이 달라질 수 있다(스펙 6-2절). torch 는 코랩에 깔린 것을 적기만 한다.
    env = {{'gpu': torch.cuda.get_device_name(0), 'torch': torch.__version__, 'python': platform.python_version(),
           'transformers': transformers.__version__, 'bitsandbytes': bitsandbytes.__version__,
           'peft': peft.__version__, 'accelerate': accelerate.__version__}}
    wrong = {{k: (v, env[k]) for k, v in PINS.items() if env[k] != v}}
    assert not wrong, f'고정한 판과 다르게 깔렸습니다: {{wrong}}. 런타임을 다시 시작하고 첫 칸부터 다시 실행하세요.'
    return env

def check_env(saved_path):
    # 이어 할 때는 처음 세션과 판이 같아야 한다. 다르면 이어 붙인 결과가 한 환경의 결과가 아니게 된다.
    if os.path.exists(saved_path):
        old = json.load(open(saved_path))
        diff = {{k: (old.get(k), ENV.get(k)) for k in set(old) | set(ENV) if old.get(k) != ENV.get(k)}}
        assert not diff, f'처음 세션과 환경이 다릅니다: {{diff}}. 멈추고 이 줄을 그대로 알려 주세요.'
    else:
        json.dump(ENV, open(saved_path, 'w'), indent=2)

QUANT = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type='nf4',
                           bnb_4bit_compute_dtype=torch.float16)  # v2 와 같다. T4 는 bf16 을 지원하지 않는다

def load_base():
    tok = AutoTokenizer.from_pretrained(M3_REPO, revision=M3_REVISION, token=HF_TOKEN)
    # dtype=float16: 4비트로 바뀌지 않는 부분(임베딩, lm_head, 정규화층)의 정밀도. v2 노트북과 같다(스펙 6-1절).
    model = AutoModelForCausalLM.from_pretrained(M3_REPO, revision=M3_REVISION, quantization_config=QUANT,
                                                 dtype=torch.float16, device_map='auto', token=HF_TOKEN)
    return tok, model
'''


def train_notebook() -> dict:
    h = _hashes()
    header = """# AllDap 채점 모델 파인튜닝: 학습 (M3 + LoRA)

설계: `docs/superpowers/specs/2026-10-05-judge-finetune-design.md` (6절, 7-2절)

**실행 방법**
1. 런타임 > 런타임 유형 변경 > **T4 GPU**. 왼쪽 열쇠 아이콘(보안 비밀)에 이름 `HF_TOKEN` 으로 Hugging Face 토큰을 넣는다.
2. Drive 의 `MyDrive/alldap_judgeft/` 에 `train.jsonl`, `val.jsonl` 을 올린다.
3. **관문 (b)**: 둘째 칸 맨 위를 `MODE = 'gate_b'` 로 고치고 **모두 실행**. 끝나면 `gate_b.json` 이 생긴다. 메모리 부족이나 loss 가 숫자가 아니면 멈추고 알린다(스펙 7-2절).
4. **학습**: 런타임 > 세션 다시 시작 뒤 `MODE = 'train'` 으로 바꾸고 **모두 실행**. 관문 (b) 에서 만든 LoRA 를 이어 쓰지 않도록 반드시 세션을 다시 시작한다. 체크포인트가 하나라도 생긴 뒤에는 `gate_b` 를 다시 돌릴 수 없다.
5. 끊기면 세션을 다시 시작하고 `MODE = 'train'` 그대로 **모두 실행** 한다. 가장 최근의 온전한 체크포인트에서 이어 한다.
6. 끝나면 마지막 칸이 `alldap_judgeft_train.zip`(학습 기록, 어댑터 해시)을 내려받는다. 어댑터 파일은 Drive 의 `adapter/` 에 남는다.

**Drive 휴지통:** 이 노트북은 오래된 체크포인트(하나에 약 0.4GB, 재지 않은 어림)를 지운다. 지운 파일은 Drive 휴지통으로 가서 용량을 계속 차지한다. 학습 기록에 찍히는 `drive_free_gb` 가 3 아래로 내려가면 drive.google.com 의 휴지통에서 **휴지통 비우기** 를 누른다.

설정은 한 번만 학습한다(스펙 6-5절). 이 노트북의 설정 값을 바꾸지 않는다. 시험지는 이 노트북에 없다.

""" + GUIDE
    setup = '''MODE = ''   # 'gate_b' 또는 'train'. 비워 두면 멈춘다(실수로 다른 단계를 돌리지 않게)
assert MODE in ('gate_b', 'train'), "MODE 를 'gate_b' 또는 'train' 으로 고치고 다시 모두 실행하세요."
''' + COMMON + f'''
TRAIN = f'{{DIR}}/train.jsonl'
VAL = f'{{DIR}}/val.jsonl'
EXPECTED = {{'train': {h["train"]!r}, 'val': {h["val"]!r}}}
assert EXPECTED['train'] and EXPECTED['val'], '동결 커밋 전의 노트북입니다. 계획 E11 뒤의 노트북을 쓰세요.'
assert sha_of(TRAIN) == EXPECTED['train'] and sha_of(VAL) == EXPECTED['val'], '올린 학습 데이터의 해시가 다릅니다.'
TRAIN_ROWS = [json.loads(l) for l in open(TRAIN, encoding='utf-8') if l.strip()]
VAL_ROWS = [json.loads(l) for l in open(VAL, encoding='utf-8') if l.strip()]
CKPT = f'{{DIR}}/checkpoints'
ADAPTER = f'{{DIR}}/adapter'
LOG = f'{{DIR}}/training_log.jsonl'
os.makedirs(CKPT, exist_ok=True)
ENV = env_record()

def checkpoints():
    # 완성 표시(done 파일)가 있는 체크포인트만 센다. 저장 도중 끊긴 체크포인트는 done 이 없어 건너뛴다(스펙 6-4절).
    return sorted((int(p.rsplit('-', 1)[1]), p) for p in glob.glob(f'{{CKPT}}/step-*') if os.path.exists(f'{{p}}/done'))

def log(rec):
    open(LOG, 'a').write(json.dumps(rec) + '\\n')

if MODE == 'gate_b':
    assert not checkpoints(), '학습 체크포인트가 이미 있습니다. 관문 (b) 는 학습 전에만 돌립니다. MODE 를 확인하세요.'
else:
    check_env(f'{{DIR}}/train_env.json')   # 첫 학습 세션이면 적고, 이어 하는 세션이면 처음과 비교한다
# 세션마다 한 줄. 읽는 쪽은 단계마다 마지막 줄을 쓴다(끊긴 뒤 다시 한 단계가 두 번 적힐 수 있다).
log({{'session_start': time.time(), 'mode': MODE, 'env': ENV}})
print(len(TRAIN_ROWS), len(VAL_ROWS), ENV)
'''
    model_cell = f'''from peft import LoraConfig, get_peft_model, set_peft_model_state_dict
from safetensors.torch import load_file

LORA_R, LORA_ALPHA, LORA_DROPOUT = {F.LORA_R}, {F.LORA_ALPHA}, {F.LORA_DROPOUT}
LORA_TARGETS = {list(F.LORA_TARGETS)!r}
LEARNING_RATE, EPOCHS, GRAD_ACCUM, WARMUP_RATIO = {F.LEARNING_RATE}, {F.EPOCHS}, {F.GRAD_ACCUM}, {F.WARMUP_RATIO}
KEEP_CHECKPOINTS, TRAIN_SEED = {F.KEEP_CHECKPOINTS}, {F.TRAIN_SEED}

{inspect.getsource(build_example)}
random.seed(TRAIN_SEED); torch.manual_seed(TRAIN_SEED)   # LoRA 초기값을 고정한다
tok, model = load_base()
END_ID = tok.convert_tokens_to_ids('<|im_end|>')
eos = model.generation_config.eos_token_id
assert END_ID in (eos if isinstance(eos, list) else [eos]), '끝 토큰이 생성의 멈춤 토큰이 아니다'
# prepare_model_for_kbit_training 을 쓰지 않는다. 그 함수는 4비트가 아닌 층을 float32 로 바꾸는데, 임베딩과 lm_head 만
# 약 6GB 가 되어 T4 에 들어가지 않을 수 있다. 메모리를 줄이는 두 설정만 직접 켠다.
model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={{'use_reentrant': False}})
model.enable_input_require_grads()   # gradient checkpointing 에서 입력 쪽 기울기 경로를 연다(LoRA 만 학습해도 필요하다)
model.config.use_cache = False
model = get_peft_model(model, LoraConfig(r=LORA_R, lora_alpha=LORA_ALPHA, lora_dropout=LORA_DROPOUT,
                                         target_modules=LORA_TARGETS, task_type='CAUSAL_LM'))
for n, p in model.named_parameters():
    if p.requires_grad:
        p.data = p.data.float()   # LoRA 가중치는 float32 로 둔다. float16 으로 고치면 작은 갱신이 0 이 된다(스펙 6-2절)
model.print_trainable_parameters()

def encode_row(row):
    ids, n = build_example(lambda m: tok.apply_chat_template(m, add_generation_prompt=True, tokenize=False),
                           lambda s: tok(s, add_special_tokens=False)['input_ids'], row['messages'], row['target'], END_ID)
    return torch.tensor(ids, device='cuda'), n

def row_loss(row):
    ids, n = encode_row(row)
    with torch.autocast('cuda', dtype=torch.float16):
        # logits_to_keep=n+1: 마지막 n+1 위치의 logits 만 계산한다. 모범 답안의 토큰 n 개를 맞히는 데 필요한 것이
        # 그 앞 위치들이기 때문이다. 입력 위치의 logits(약 15만 어휘 곱하기 입력 길이)를 만들지 않아 메모리가 준다.
        out = model(input_ids=ids[None], logits_to_keep=n + 1)
    logits = out.logits[0, :-1].float()   # n 개 위치. float32 로 바꿔 loss 를 계산한다
    return torch.nn.functional.cross_entropy(logits, ids[-n:])

TOTAL_STEPS = EPOCHS * math.ceil(len(TRAIN_ROWS) / GRAD_ACCUM)
WARMUP = max(1, round(WARMUP_RATIO * TOTAL_STEPS))
opt = bitsandbytes.optim.PagedAdamW8bit([p for p in model.parameters() if p.requires_grad], lr=LEARNING_RATE)
sched = transformers.get_cosine_schedule_with_warmup(opt, WARMUP, TOTAL_STEPS)
scaler = torch.amp.GradScaler('cuda')   # float16 혼합 정밀도의 loss scaling(스펙 6-2절)
print('학습 단계', TOTAL_STEPS, 'warmup', WARMUP)

def batches():
    """학습 단계마다 문항 묶음. 바퀴마다 시드로 순서를 섞는다. 같은 시드면 끊겼다 이어 해도 같은 순서다."""
    for e in range(EPOCHS):
        order = random.Random(f'{{TRAIN_SEED}}:{{e}}').sample(range(len(TRAIN_ROWS)), len(TRAIN_ROWS))
        for i in range(0, len(order), GRAD_ACCUM):
            yield [TRAIN_ROWS[j] for j in order[i:i + GRAD_ACCUM]]

def train_step(batch):
    losses = []
    for row in batch:
        loss = row_loss(row) / len(batch)
        if not torch.isfinite(loss):
            raise RuntimeError(f'loss 가 숫자가 아니다({{loss.item()}}). 설정을 바꾸지 않고 멈춘다(스펙 6-5절).')
        scaler.scale(loss).backward()
        losses.append(loss.item() * len(batch))
    scale = scaler.get_scale()
    scaler.step(opt); scaler.update(); sched.step(); opt.zero_grad(set_to_none=True)
    # 기울기에 inf, NaN 이 있으면 scaler 는 그 단계의 갱신을 건너뛰고 scale 을 줄인다. 줄었으면 건너뛴 것이다.
    # 약 135단계 중 warmup 이 4단계라 앞쪽 건너뜀이 많으면 학습이 덜 된 채 끝날 수 있어 기록한다.
    return sum(losses) / len(losses), scale, scaler.get_scale() < scale
'''
    gate_cell = '''if MODE == 'gate_b':
    # from_pretrained 는 모델을 eval 모드로 돌려주고 get_peft_model 은 바깥 껍데기만 training=True 로 둔다.
    # 층이 eval 이면 gradient checkpointing 이 꺼져(층의 조건이 gradient_checkpointing and training) 메모리를 더 쓴다.
    # 그러면 관문이 메모리 부족으로 거짓 실패하거나 step_seconds, est_hours, save_every 가 학습과 다르게 나온다.
    model.train()
    layers = model.base_model.model.model.layers
    assert all(l.gradient_checkpointing and l.training for l in layers), 'gradient checkpointing 이 켜지지 않았습니다'
    lengths = [(len(encode_row(r)[0]), r['id']) for r in TRAIN_ROWS + VAL_ROWS]
    longest_tokens, longest_id = max(lengths)
    row = next(r for r in TRAIN_ROWS + VAL_ROWS if r['id'] == longest_id)
    torch.cuda.reset_peak_memory_stats()
    times, losses = [], []
    for _ in range(2):   # 학습 단계 둘. 첫 단계는 준비 시간이 섞이므로 둘째 단계의 시간을 쓴다
        t = time.time(); losses.append(train_step([row] * GRAD_ACCUM)[0]); torch.cuda.synchronize(); times.append(time.time() - t)
        assert all(l.gradient_checkpointing and l.training for l in layers), '첫 단계 뒤 gradient checkpointing 이 꺼졌습니다'
    step_seconds = times[-1]
    res = {'longest_id': longest_id, 'longest_tokens': longest_tokens, 'losses': losses, 'env': ENV,
           'finite': all(math.isfinite(x) for x in losses),
           'peak_gb': round(torch.cuda.max_memory_allocated() / 1024**3, 2), 'step_seconds': round(step_seconds, 1),
           'total_steps': TOTAL_STEPS, 'est_hours': round(step_seconds * TOTAL_STEPS / 3600, 1),
           'save_every': max(1, int(1800 // step_seconds))}
    json.dump(res, open(f'{DIR}/gate_b.json', 'w'), indent=2)
    print(res)
    assert res['finite'], 'loss 가 숫자가 아니다. 멈추고 사용자에게 알린다(스펙 7-2절)'
'''
    train_cell = '''def val_loss():
    model.eval()
    with torch.no_grad():
        v = sum(row_loss(r).item() for r in VAL_ROWS) / len(VAL_ROWS)
    model.train()
    return v

FILES = ('adapter_model.safetensors', 'state.pt')

def drive_free_gb():
    # Drive 를 붙인 폴더의 남은 용량. Drive 가 알려 주는 값이라 휴지통이 차지한 몫이 빠져 있을 수 있다(재지 않음).
    return round(shutil.disk_usage(DIR).free / 1024**3, 1)

def save(step):
    p = f'{CKPT}/step-{step}'
    shutil.rmtree(p, ignore_errors=True)   # 같은 번호의 깨진 체크포인트가 남아 있으면 그 done 이 새 것으로 보이지 않게 지운다
    os.makedirs(p)
    model.save_pretrained(p)
    torch.save({'opt': opt.state_dict(), 'sched': sched.state_dict(), 'scaler': scaler.state_dict(), 'step': step,
                'py': random.getstate(), 'torch': torch.get_rng_state(), 'cuda': torch.cuda.get_rng_state()}, f'{p}/state.pt')
    # done 은 마지막에 쓴다. 이 파일이 있어야 완성된 체크포인트다. 두 파일의 해시를 적어 이어 할 때 깨졌는지 본다.
    json.dump({f: sha_of(f'{p}/{f}') for f in FILES}, open(f'{p}/done', 'w'))
    for _, old in checkpoints()[:-KEEP_CHECKPOINTS]:
        shutil.rmtree(old)   # 가장 최근 둘만 남긴다(Drive 15GB, 스펙 6-4절). 지운 파일은 Drive 휴지통으로 간다

def load_checkpoint(p):
    """해시가 맞고 읽히면 단계 번호를, 아니면 None 을 돌려준다. 읽다가 실패하면 모델이 반쯤 바뀌었을 수 있어 멈춘다."""
    want = json.load(open(f'{p}/done'))
    got = {f: sha_of(f'{p}/{f}') for f in FILES}
    if got != want:
        return None
    set_peft_model_state_dict(model, load_file(f'{p}/adapter_model.safetensors'))
    s = torch.load(f'{p}/state.pt', weights_only=False)
    opt.load_state_dict(s['opt']); sched.load_state_dict(s['sched']); scaler.load_state_dict(s['scaler'])
    random.setstate(s['py']); torch.set_rng_state(s['torch']); torch.cuda.set_rng_state(s['cuda'])
    return s['step']

if MODE == 'train':
    SAVE_EVERY = json.load(open(f'{DIR}/gate_b.json'))['save_every']
    start = 0
    # 가장 최근 것부터 본다. 해시가 맞지 않거나 파일을 읽지 못하면 기록하고 지운 뒤 하나 앞의 것으로 간다.
    # 최근 둘을 남기는 이유(스펙 6-4절)를 코드가 실제로 쓰는 자리다.
    for n, p in reversed(checkpoints()):
        try:
            got = load_checkpoint(p)
            why = None if got is not None else '해시가 done 에 적힌 것과 다르다'
        except Exception as e:   # 파일이 잘려 safetensors 나 torch.load 가 실패한 경우
            raise RuntimeError(f'체크포인트 {p} 를 읽다가 멈췄습니다({e}). 모델 상태가 섞였을 수 있어 세션을 다시 시작하고 '
                               f'이 체크포인트 폴더를 지운 뒤 다시 모두 실행하세요.') from e
        if why is None:
            start = got
            log({'resumed_from': start, 'at': time.time(), 'env': ENV})
            print('이어 한다:', p)
            break
        log({'bad_checkpoint': n, 'reason': why, 'at': time.time()})
        print('깨진 체크포인트를 건너뛴다:', p, why)
        shutil.rmtree(p)
    model.train()
    for step, batch in enumerate(batches(), 1):
        if step <= start:
            continue   # 이미 한 단계는 건너뛴다. batches() 는 시드로 순서가 정해져 있어 같은 자리에서 이어진다
        loss, scale, skipped = train_step(batch)
        rec = {'step': step, 'train_loss': loss, 'lr': sched.get_last_lr()[0], 'scale': scale, 'skipped': skipped,
               'at': time.time()}
        if step % SAVE_EVERY == 0 or step == TOTAL_STEPS:
            rec['val_loss'] = val_loss()
            save(step)
            rec['drive_free_gb'] = drive_free_gb()
        log(rec)
        print(rec)
    model.save_pretrained(ADAPTER)   # 채점에 쓰는 어댑터는 마지막 단계의 것이다(스펙 6-3절). 검증 loss 로 고르지 않는다
    sha = sha_of(f'{ADAPTER}/adapter_model.safetensors')
    json.dump({'adapter_sha256': sha, 'steps': TOTAL_STEPS, 'env': ENV}, open(f'{DIR}/train_done.json', 'w'), indent=2)
    print('어댑터 SHA-256:', sha)
'''
    zip_cell = '''os.makedirs('/content/train_out', exist_ok=True)
for name in ('gate_b.json', 'training_log.jsonl', 'train_done.json', 'train_env.json'):
    if os.path.exists(f'{DIR}/{name}'):
        shutil.copy(f'{DIR}/{name}', '/content/train_out/')
shutil.make_archive('/content/alldap_judgeft_train', 'zip', '/content/train_out')
files.download('/content/alldap_judgeft_train.zip')
'''
    return _nb([_md(header), _code(PIP), _code(setup), _code(model_cell), _code(gate_cell), _code(train_cell),
                _code(zip_cell)])


def eval_notebook() -> dict:
    h = _hashes()
    header = f"""# AllDap 채점 모델 파인튜닝: 채점 (학습 전 M3, 학습 후 M3)

설계: `docs/superpowers/specs/2026-10-05-judge-finetune-design.md` (8-1절)

**실행 방법**
1. 런타임 > 런타임 유형 변경 > **T4 GPU**. 왼쪽 열쇠 아이콘(보안 비밀)에 이름 `HF_TOKEN` 으로 Hugging Face 토큰을 넣는다.
2. Drive 의 `MyDrive/alldap_judgeft/` 에 `cases_new.jsonl`(새 시험지 `testdata/judgeft/cases.jsonl`)과 `cases_frozen.jsonl`(동결 시험지 `testdata/judge5v2/cases.jsonl`)을 올린다. 학습 후 M3 를 돌릴 때는 학습 노트북이 만든 `adapter/` 가 같은 폴더에 있어야 한다.
3. 둘째 칸의 `SHEET`, `MODEL`, `RUN` 을 오케스트레이터가 알려 준 값으로 바꾼다. 학습 후 M3 이면 오케스트레이터가 준 `ADAPTER_SHA256 = '...'` 한 줄을 그 자리에 그대로 붙여 넣는다. 학습 전 M3 이면 `ADAPTER_SHA256` 을 비워 둔다.
4. **모두 실행**. 끊기면 세션을 다시 시작하고 같은 값으로 모두 실행한다. 이미 채점한 문항은 건너뛴다(반쯤 쓴 마지막 줄은 버리고 그 문항부터 다시 한다).
5. 끝나면 마지막 칸이 결과 파일 둘(`<모델>_run<번호>.jsonl`, `.env.json`)을 담은 zip 을 내려받는다.

**학습이 끝날 때까지 새 시험지의 결과 파일을 열어 보지 않는다**(스펙 6-5절). 내려받은 zip 은 그대로 오케스트레이터에 넘긴다.
생성 설정은 v2 와 같다(탐욕적 디코딩, 최대 출력 {MAX_NEW_TOKENS} 토큰, repetition_penalty 1.0).

""" + GUIDE
    setup = '''SHEET = 'frozen'      # 'new' 또는 'frozen'
MODEL = 'M3pre'       # 'M3pre'(학습 전) 또는 'M3ft'(학습 후)
RUN = 1               # 1, 2, 3
ADAPTER_SHA256 = ''   # MODEL 이 'M3ft' 일 때 학습 노트북의 어댑터 해시
''' + COMMON + f'''
assert SHEET in ('new', 'frozen') and MODEL in ('M3pre', 'M3ft') and RUN in (1, 2, 3)
# 학습 전 M3 에 해시가 적혀 있으면 어느 쪽을 돌리려던 것인지 알 수 없다. 결과 줄의 adapter_sha256 도 거짓이 된다.
assert (MODEL == 'M3pre') == (ADAPTER_SHA256 == ''), 'M3pre 이면 ADAPTER_SHA256 을 비우고, M3ft 이면 채웁니다.'
EXPECTED = {{'new': {h["cases_new"]!r}, 'frozen': {F.FROZEN_SHA256!r}}}
MAX_NEW_TOKENS = {MAX_NEW_TOKENS}
SMOKE_MESSAGES = {json.dumps(smoke_messages(), ensure_ascii=False)}
CASES = f'{{DIR}}/cases_{{SHEET}}.jsonl'
assert EXPECTED[SHEET], '동결 커밋 전의 노트북입니다. 계획 E11 뒤의 노트북을 쓰세요.'
sha = sha_of(CASES)
assert sha == EXPECTED[SHEET], f'시험지 해시가 다릅니다: {{sha}}'
CASE_ROWS = [json.loads(l) for l in open(CASES, encoding='utf-8') if l.strip()]
OUT = f'{{DIR}}/results/{{SHEET}}'
os.makedirs(OUT, exist_ok=True)
PATH = f'{{OUT}}/{{MODEL}}_run{{RUN}}.jsonl'
ENV = env_record()
check_env(PATH.replace('.jsonl', '.env.json'))   # 첫 세션이면 적고, 이어 하는 세션이면 처음과 비교한다
print(len(CASE_ROWS), '문항', ENV)
'''
    run_cell = '''tok, model = load_base()
if MODEL == 'M3ft':
    from peft import PeftModel
    assert ADAPTER_SHA256 and sha_of(f'{DIR}/adapter/adapter_model.safetensors') == ADAPTER_SHA256, '어댑터 해시가 다릅니다'
    model = PeftModel.from_pretrained(model, f'{DIR}/adapter')   # 어댑터를 바탕 모델 위에 얹는다(합치지 않는다)
model.eval()
# 생성 설정은 v2 노트북과 같게 처음부터 만든다. 저장소 기본값의 repetition_penalty 1.05 가 섞이지 않게 한다.
eos = model.generation_config.eos_token_id
pad = tok.pad_token_id if tok.pad_token_id is not None else (eos[0] if isinstance(eos, list) else eos)
gen = GenerationConfig(max_new_tokens=MAX_NEW_TOKENS, do_sample=False, repetition_penalty=1.0,
                       eos_token_id=eos, pad_token_id=pad)

def generate(messages):
    text = tok.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)
    enc = tok(text, return_tensors='pt', add_special_tokens=False).to(model.device)
    with torch.no_grad():
        out = model.generate(**enc, generation_config=gen, use_model_defaults=False)
    new = out[0, enc['input_ids'].shape[1]:]
    finish = 'length' if new.shape[0] >= MAX_NEW_TOKENS else 'stop'
    return tok.decode(new, skip_special_tokens=True), finish

text, finish = generate(SMOKE_MESSAGES)
assert text.strip(), '가짜 문항의 출력이 비었다. 멈추고 알린다'
json.dump({'model': MODEL, 'output': text, 'finish': finish, 'generation': gen.to_dict()},
          open(f'{OUT}/{MODEL}_run{RUN}_smoke.json', 'w'), ensure_ascii=False, indent=2)
def resume_lines():
    """이미 쓴 줄. 마지막 줄이 쓰다가 끊겨 JSON 이 아니면 버리고 파일을 다시 쓴다. 버린 것은 기록한다."""
    if not os.path.exists(PATH):
        return []
    raw = [l for l in open(PATH, encoding='utf-8').read().split('\\n') if l.strip()]
    good = []
    for i, l in enumerate(raw):
        try:
            good.append(json.loads(l))
        except json.JSONDecodeError:
            assert i == len(raw) - 1, f'{PATH} 의 {i + 1}번째 줄이 깨졌습니다. 마지막 줄이 아니라 멈춥니다.'
            open(PATH, 'w', encoding='utf-8').write(''.join(json.dumps(g, ensure_ascii=False) + '\\n' for g in good))
            open(f'{OUT}/{MODEL}_run{RUN}_resume.log', 'a').write(json.dumps({'dropped_partial_line': l[:200], 'at': time.time()}) + '\\n')
            print('반쯤 쓴 마지막 줄을 버리고 이어 한다')
    return good

done = {g['case_id'] for g in resume_lines()}
for i, row in enumerate(CASE_ROWS):
    if row['case_id'] in done:
        continue
    text, finish = generate(row['messages'])
    line = {'case_id': row['case_id'], 'model': MODEL, 'repo': M3_REPO, 'revision': M3_REVISION, 'run': RUN,
            'output': text, 'finish': finish, 'cases_sha256': sha, 'domain': row['domain'],
            'adapter_sha256': ADAPTER_SHA256 or None}
    with open(PATH, 'a', encoding='utf-8') as f:
        f.write(json.dumps(line, ensure_ascii=False) + '\\n')
    print(i + 1, '/', len(CASE_ROWS), finish)   # 점수는 찍지 않는다. 학습이 끝날 때까지 결과를 보지 않는다
'''
    zip_cell = '''name = f'alldap_judgeft_{SHEET}_{MODEL}_run{RUN}'
os.makedirs(f'/content/{name}', exist_ok=True)
for p in glob.glob(f'{OUT}/{MODEL}_run{RUN}*'):
    shutil.copy(p, f'/content/{name}/')
shutil.make_archive(f'/content/{name}', 'zip', f'/content/{name}')
files.download(f'/content/{name}.zip')
'''
    return _nb([_md(header), _code(PIP), _code(setup), _code(run_cell), _code(zip_cell)])


def render(nb: dict) -> str:
    return json.dumps(nb, ensure_ascii=False, indent=1) + "\n"


def expected() -> dict:
    return {TRAIN_NB: render(train_notebook()), EVAL_NB: render(eval_notebook())}


def main() -> int:
    for path, text in expected().items():
        path.write_text(text, encoding="utf-8")
        print(f"썼다: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 노트북을 만들고 칸마다 문법을 확인한다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft/ai-service
$PY -m tools.judgeft_notebooks
$PY - <<'EOF'
import ast, json
for name in ("judgeft_train_colab", "judgeft_eval_colab"):
    nb = json.load(open(f"notebooks/{name}.ipynb", encoding="utf-8"))
    for c in nb["cells"]:
        if c["cell_type"] == "code":
            ast.parse("\n".join(l for l in c["source"].splitlines() if not l.startswith("!")))
    print(name, "문법 확인", len(nb["cells"]), "칸")
EOF
```

Expected: `썼다:` 두 줄, 그리고 `judgeft_train_colab 문법 확인 7 칸`, `judgeft_eval_colab 문법 확인 5 칸`. 노트북의 실제 동작(GPU 메모리, peft 와 bitsandbytes 의 호출)은 이 단계에서 확인할 수 없다. 학습 전 관문 (b)(E14)의 첫 실행이 그 확인이다.

- [ ] **Step 3: 커밋한다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft
git add ai-service/tools/judgeft_notebooks.py ai-service/notebooks/judgeft_train_colab.ipynb ai-service/notebooks/judgeft_eval_colab.ipynb
git commit -m "feat: 학습 노트북(관문 b, 체크포인트 이어 하기)과 채점 노트북을 만드는 도구를 더한다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/tools/judgeft_notebooks.py ai-service/notebooks/judgeft_train_colab.ipynb ai-service/notebooks/judgeft_eval_colab.ipynb
```

**리뷰 포인트:** 학습 노트북의 `row_loss` 가 `logits_to_keep=n+1` 과 `logits[0, :-1]` 로 모범 답안 n 개 토큰만 맞히는가(태스크 7 의 `check_logits_to_keep` 과 같은 계산인가). LoRA 가중치를 float32 로 바꾸는가. 이어 하기가 단계 번호, 옵티마이저, 스케줄러, scaler, 난수 상태를 모두 되돌리는가. 관문 칸이 `model.train()` 을 부르고 층마다 gradient checkpointing 이 켜졌는지 확인하는가(`from_pretrained` 는 eval 모드로 돌려주고 `get_peft_model` 은 바깥만 training 으로 둔다. 층이 eval 이면 checkpointing 이 꺼져 관문이 메모리 부족으로 거짓 실패하거나 시간이 학습과 다르게 나온다). 체크포인트의 완성 표시에 두 파일의 해시를 적고, 이어 할 때 해시가 맞지 않으면 기록하고 하나 앞의 것으로 가는가. 이어 할 때 처음 세션의 환경과 비교해 다르면 멈추는가. `MODE` 가 비어 있으면 멈추고, 체크포인트가 있으면 `gate_b` 를 거절하는가. 채점 노트북이 `M3pre` 에 해시가 있으면 멈추고, 반쯤 쓴 마지막 줄을 버리고 기록하는가. 채점 노트북의 생성 설정이 v2 노트북과 같은가. 두 노트북 어디에도 문항별 점수를 찍는 줄이 없는가.

---

### Task 12: 점검 묶기와 CI

**Files:**
- Create: `ai-service/tools/judgeft_check.py`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: 태스크 2~11 의 점검과 함수
- Produces: 명령 `python -m tools.judgeft_check`

- [ ] **Step 1: 점검 입구를 쓴다**

```python
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
```

- [ ] **Step 2: 모든 점검을 돌린다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft/ai-service
$PY -m tools.judgeft_check | tail -1
$PY -m tools.judge5_check | tail -1 && $PY -m tools.judge5v2_check | tail -1
git -C /Users/cheonjamin/projects/AllDap-judge-ft diff --stat f52a1a6 -- 'ai-service/tools/judge5*.py' ai-service/testdata/judge5v2 'ai-service/notebooks/judge5*_colab.ipynb' ai-service/app
```

Expected: `46가지 전부 통과.`, `44가지 전부 통과.`, `66가지 전부 통과.`, 그리고 마지막 명령의 출력이 비어 있다(v2 파일과 서비스 코드가 하나도 바뀌지 않았다). `*` 가 든 경로를 작은따옴표로 감싸는 이유: zsh 는 따옴표 없는 `*` 를 지금 폴더(`ai-service`)에서 먼저 펼치려 하고, 맞는 파일이 없으면 `no matches found` 로 명령 전체를 멈춘다. 감싸면 git 이 저장소 기준으로 펼친다. `f52a1a6` 은 이 브랜치를 딴 `feat/judge-selfhost-v2` 의 커밋이다. 브랜치 이름으로 비교하지 않는 이유: #160 에 커밋이 더해지면 그 차이가 이 브랜치의 변경처럼 보인다.

- [ ] **Step 3: CI 에 한 줄을 더한다**

`.github/workflows/ci.yml` 에서 아래 주석 줄을 찾는다.

```
      #    ✅ tools.judge5v2_check 는 채점 모델 비교 v2 의 도구(검색은 가짜 함수로), 노트북 대조, 커밋된 시험지와 배정만 본다.
```

그 바로 아래에 아래 줄을 더한다.

```
      #    ✅ tools.judgeft_check 는 채점 모델 파인튜닝 실험의 도구, 노트북과 생성 도구의 대조, 커밋된 배정과 학습 데이터의 재현을 본다. torch 를 import 하지 않는다.
```

그리고 `          python -m tools.judge5v2_check` 줄 바로 아래에 `          python -m tools.judgeft_check` 를 더한다.

- [ ] **Step 4: 커밋한다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft
git add ai-service/tools/judgeft_check.py .github/workflows/ci.yml
git commit -m "chore: 파인튜닝 실험의 점검을 하나로 묶어 CI 에서 돌린다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/tools/judgeft_check.py .github/workflows/ci.yml
```

**리뷰 포인트:** 점검 입구가 torch 와 transformers 를 import 하지 않는가(`judgeft_tokcheck` 를 부르지 않는가). 커밋된 파일을 보는 점검이 파일이 없을 때 통과하고, 있을 때 실제로 대조하는가.

---

## 실행 태스크

실행 태스크는 코드를 쓰지 않는다. 끝나면 만든 데이터 파일만 이름으로 add 해서 커밋한다. 리뷰는 다른 세션이 결과 파일을 열어 본다(단, 새 시험지의 모델 결과는 E18 전에는 열지 않는다).

### Task E1: 분야 순서를 정하고 첫 학습용 분야의 문서를 쓴다

**Files:**
- Create: `ai-service/testdata/judgeft/fields.json`, `ai-service/testdata/judgeft/corpus/<첫 학습용 분야>/`

- [ ] **Step 1: 분야 순서를 시드로 정한다** (오케스트레이터)

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft/ai-service
$PY -m tools.judgeft_fields order
```

Expected: `시험용 [...], 학습용 [..., ...], 예비 [...]`. 계획을 쓸 때 같은 시드로 미리 돌려 본 결과는 `시험용 ['school'], 학습용 ['travel', 'telecom'], 예비 ['hospital']` 이다. 다르게 나오면 `judgeft_files.SEED` 나 `FIELD_CANDIDATES` 가 바뀐 것이므로 멈추고 알린다. 이 결과를 보고 다시 돌리지 않는다(스펙 3-2절).

- [ ] **Step 2: 첫 학습용 분야(학습용 목록의 첫째)의 문서를 쓴다** (출제 세션)

`testdata/judgeft/corpus/<분야>/` 에 가상 문서 약 25개를 쓴다. 조건은 스펙 3-1절이다.
- 실존하는 회사, 상품, 사람의 이름을 쓰지 않는다.
- **비슷한 항목이 나란히 적히고 항목마다 값이 다른 규정** 을 많이 넣는다(요금표, 등급별 규정, 일수별 수수료). ⑧ 은 근거 청크에 값이 서로 다른 두 대상이 함께 있어야 만들 수 있다. 청크는 소제목마다 잘리므로(v2 결과 7-2절), 비교할 항목은 같은 소제목 아래 표나 목록으로 둔다.
- 개정 전의 옛 값을 적은 문서는 넣지 않는다. v2 에서 그런 문서는 ⑥ 을 만들 수 없는 근거가 됐다(v2 스펙 3-2절).
- 폴더에 `README.md` 를 두어 문서 목록과 각 문서의 대상별 규정 표를 적는다. 올리지 않는 메모다.

- [ ] **Step 3: 커밋한다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft
git add ai-service/testdata/judgeft/fields.json ai-service/testdata/judgeft/corpus/<분야>
git commit -m "test: 파인튜닝 실험의 분야 순서를 정하고 첫 학습용 분야의 문서를 쓴다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/testdata/judgeft/fields.json ai-service/testdata/judgeft/corpus/<분야>
```

**리뷰 포인트:** 시험용 분야의 문서를 이 단계에서 쓰지 않았는가(첫 학습용 분야로 ⑧ 비율을 먼저 잰다. 스펙 9-1절 3). 실존 이름이 없는가.

---

### Task E2: 첫 학습용 분야의 봇을 만들고 문서를 올린다

**뉴런을 쓴다.** 문서 약 25개의 청크 임베딩.

**Files:**
- Create: `ai-service/testdata/judgeft/bots.json`, `ai-service/testdata/judgeft/run_log.md`

- [ ] **Step 1: 실행 환경을 확인한다**

```bash
docker ps --format '{{.Names}}' | grep alldap-db
git -C /Users/cheonjamin/projects/AllDap diff --stat main feat/judge-finetune -- ai-service/app api
git -C /Users/cheonjamin/projects/AllDap status --porcelain -- ai-service/app api
ln -s /Users/cheonjamin/projects/AllDap/ai-service/.env /Users/cheonjamin/projects/AllDap-judge-ft/ai-service/.env
git -C /Users/cheonjamin/projects/AllDap-judge-ft check-ignore ai-service/.env
```

둘째와 셋째 명령이 비어 있어야 한다. 그래야 메인 저장소에서 띄운 서비스가 이 브랜치와 같은 코드로 검색한다(v2 계획 E1 과 같은 이유). 마지막 명령은 출력이 있어야 한다(`.env` 가 커밋되지 않는다).

- [ ] **Step 2: 서비스를 띄우고 업로드 전 뉴런을 적는다**

v2 계획 E1 Step 2, 3 과 같다(`localhost:8080` 이 401, `localhost:8001/internal/debug/cf-stats` 가 200 이면 이미 떠 있다). `cf-stats` 를 세션의 스크래치 폴더에 저장한다.

- [ ] **Step 3: 실험용 계정과 봇을 만든다**

```bash
API=http://localhost:8080
curl -s -X POST $API/api/auth/signup -H 'Content-Type: application/json' \
  -d '{"email":"judgeft@example.com","password":"judgeft-local","name":"파인튜닝실험"}'
TOKEN=$(curl -s -X POST $API/api/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"judgeft@example.com","password":"judgeft-local"}' | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')
curl -s -X POST $API/api/bots -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"name":"judgeft-<분야>"}'
```

응답의 `id` 를 `testdata/judgeft/bots.json` 에 `{"<분야>": N}` 으로 적는다. 1, 7, 8, 9, 10, 11, 12 가 나오면 멈춘다.

- [ ] **Step 4: 문서를 올리고 처리를 확인한다. README.md 는 올리지 않는다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft/ai-service
find testdata/judgeft/corpus/<분야> -maxdepth 1 -name '*.md' ! -name README.md | sort | while read -r f; do
  curl -s -o /dev/null -w "%{http_code} $f\n" -X POST "$API/api/bots/<번호>/documents" -H "Authorization: Bearer $TOKEN" -F "file=@$f"; done
docker exec alldap-db psql -U alldap -d alldap -c "SELECT status, count(*) FROM documents WHERE bot_id = <번호> GROUP BY 1;"
```

Expected: 모든 줄이 `202`, 상태는 `ready` 하나.

- [ ] **Step 5: 뉴런을 적고 커밋한다**

`cf-stats` 의 차이, 봇 번호, 문서 수, 청크 수를 `run_log.md` 의 "업로드 (날짜, 분야)" 절에 적는다.

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft
git add ai-service/testdata/judgeft/bots.json ai-service/testdata/judgeft/run_log.md
git commit -m "test: 파인튜닝 실험의 첫 학습용 분야 봇을 만들고 문서를 올린다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/testdata/judgeft/bots.json ai-service/testdata/judgeft/run_log.md
```

**리뷰 포인트:** README.md 가 올라가지 않았는가. 보호한 봇의 문서 수가 바뀌지 않았는가.

---

### Task E3: 첫 학습용 분야의 질문, 검색, 답변을 마치고 ⑧ 비율을 잰다

**뉴런을 쓴다.** 질문 임베딩과 리랭커.

**Files:**
- Create: `ai-service/testdata/judgeft/questions.jsonl`, `retrieved.jsonl`, `excluded.json`(뺄 질문이 있을 때)

- [ ] **Step 1: 질문을 쓴다** (출제 세션)

학습용 분야 하나에 필요한 질문은 약 300개다(학습 질문 약 480개의 절반에 25% 여유. 스펙 11절). 쓰는 방법은 v2 스펙 3-1절과 같다: 약 40% 는 답이 두 가지인 질문, 나머지는 답이 하나인 질문. 답이 하나인 질문은 되도록 대상이 둘인 근거가 나오도록, 나란히 적힌 항목 중 하나를 묻는다. 줄 모양은 v2 계획 형식 1 이고 `answer`, `claims`, `contrast` 는 아직 `null` 이다. qid 는 `<분야>-<세 자리 번호>` 다.

- [ ] **Step 2: 검색한다** (오케스트레이터)

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft/ai-service
curl -s localhost:8001/internal/debug/cf-stats > "$SCRATCH/cf-before-search.json"
$PY -m tools.judgeft_search --bot <분야>=<번호>
```

Expected: `<분야>: ok N` 꼴의 줄. 호출 실패가 있으면 같은 명령을 한 번 더 돌린다(v2 스펙 2-3절). 뉴런 차이와 시각을 `run_log.md` 에 적는다.

- [ ] **Step 3: 멀쩡한 답변, 주장 수, ⑧ 조건을 쓴다** (출제 세션)

v2 계획 E4 와 같다. 말투 견본은 `testdata/judge5v2/style_samples.json` 이다(말투만 따르고 견본을 문항으로 쓰지 않는다. 스펙 5-3절). `contrast` 는 v2 계획 형식 1 대로 두 값이 근거 청크에 글자 그대로 있고 서로 다를 때만 적는다. 근거 5청크에 답이 없는 질문은 `excluded.json` 에 v2 와 같은 꼴로 적는다.

- [ ] **Step 4: ⑧ 비율을 잰다** (오케스트레이터)

```bash
$PY -m tools.judgeft_assign count
```

Expected: `train <분야>: 후보 N개, ⑧ 자격 M개(R%)` 줄이 있다. 이 단계에서는 이 줄만 본다(판정 줄은 분야가 다 모인 E5 에서 본다. 지금은 종료 코드 2 가 나와도 정상이다). 이 분야 하나로 학습용 ⑧ 240 의 절반(120) 이상이 나오는지 본다. 120 에 크게 못 미치면 나머지 분야의 문서를 쓰기 전에 출제 세션에 알려, 나란히 적는 규정을 늘리게 한다(스펙 9-1절 3). 비율과 그 판단을 `run_log.md` 에 적는다.

- [ ] **Step 5: 커밋한다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft
git add ai-service/testdata/judgeft/questions.jsonl ai-service/testdata/judgeft/retrieved.jsonl ai-service/testdata/judgeft/run_log.md
git commit -m "test: 첫 학습용 분야의 질문, 검색, 멀쩡한 답변과 ⑧ 비율을 남긴다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/testdata/judgeft/questions.jsonl ai-service/testdata/judgeft/retrieved.jsonl ai-service/testdata/judgeft/run_log.md
```

`excluded.json` 이 생겼으면 두 명령의 경로 끝에 더한다.

**리뷰 포인트:** `contrast` 를 적은 질문이 모두 답이 하나인 질문인가. `count` 가 오류 없이 도는가(답변 칸이 잘못되면 멈춘다).

---

### Task E4: 나머지 분야를 마친다

E1 Step 2, E2, E3 Step 1~3 을 **시험용 분야** 와 **두 번째 학습용 분야** 에 대해 한다. 시험용 분야의 질문은 약 150개다(새 시험지 120 에 25% 여유). 시험용 분야에는 ⑧ 자격 질문이 72개 이상 필요하므로(⑧ 60, 대상이 둘인 ①② 12), 답이 하나인 질문의 다수가 나란히 적힌 항목을 묻도록 쓴다.

봇을 만들 때 `bots.json` 에 분야를 더하고, 검색은 `--bot` 을 분야마다 준다. 이미 검색한 질문은 다시 검색하지 않는다(`settled_qids`). 업로드와 검색의 뉴런을 단계마다 `run_log.md` 에 적고, 한도에 가까우면 날을 나눈다.

커밋은 분야마다 E2, E3 과 같은 꼴로 한다.

**리뷰 포인트:** 시험용 분야의 문서에 학습용 분야의 문서와 같은 문장이 없는가(분야를 나눈 이유가 사라진다). 출제 세션이 시험용 분야를 쓸 때 문항의 유형을 미리 정하지 않았는가(유형은 E6 의 시드가 정한다).

---

### Task E5: ⑧ 자격을 세고 필요하면 분야를 늘린다

- [ ] **Step 1: 센다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft/ai-service
$PY -m tools.judgeft_assign count
```

Expected: `test 판정: 충분(첫 배정을 그대로 돌려 봤다)` 과 `train 판정: 충분(첫 배정을 그대로 돌려 봤다)`, 종료 코드 0. 합계 줄에는 ⑧ 자격 수와 함께 **④ 를 뽑은 뒤 남은 ⑧ 자격 수** 가 나온다. 판정은 합계가 아니라 E6 의 첫 배정을 같은 시드, 같은 순서로 저장하지 않고 돌려 본 결과다. 배정은 ④ 를 ⑧ 보다 먼저 뽑는데 주장이 2 인 ⑧ 자격 질문은 ④ 의 자격도 있어서, 합계가 기준을 넘어도 첫 배정이 모자랄 수 있기 때문이다. 종료 코드 2 는 분야를 늘려야 한다(⑧, 대상이 둘인 ①②, 짝이 모자람), 3 은 그 시험지의 분야에 질문을 더 써야 한다(④, ③, ⑥ 등이 모자람)는 뜻이다.

- [ ] **Step 2: 모자라면 분야를 연다**

- 종료 코드 3 이면 분야를 늘리지 않고, 모자란 유형이 나온 시험지의 분야에 출제 세션이 질문을 더 쓴다(E4 의 질문, 검색, 답변). 그다음 Step 1 을 다시 한다.
- 시험용이 모자라면 `$PY -m tools.judgeft_fields open test` 로 예비 분야를 연다.
- 학습용이 모자라면 `$PY -m tools.judgeft_fields open train` 으로 연다. 예비 분야가 이미 시험용으로 쓰였으면 도구가 거절하고, 그때는 출제 세션이 새 분야 하나(스펙 3-1절의 조건, 이미 쓴 분야와 v2 의 네 분야와 겹치지 않는 영어 소문자 이름)를 정해 `--new <이름>` 으로 연다.
- 연 분야마다 E4 를 한다. 뉴런을 쓴다.
- 도구가 "시험용 분야는 2개까지", "학습용 분야는 3개까지" 로 거절하면 멈추고 사용자에게 보인다(스펙 3-3절 3).

- [ ] **Step 3: 커밋한다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft
git add ai-service/testdata/judgeft/fields.json ai-service/testdata/judgeft/run_log.md
git commit -m "test: ⑧ 자격 질문 수를 세고 분야를 늘린 기록을 남긴다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/testdata/judgeft/fields.json ai-service/testdata/judgeft/run_log.md
```

분야를 늘리지 않았으면 `run_log.md` 만 커밋한다.

**리뷰 포인트:** 분야를 늘린 순서가 스펙 3-3절(시험용 먼저, 그다음 학습용)과 같은가.

---

### Task E6: 배정한다

- [ ] **Step 1: 배정한다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft/ai-service
$PY -m tools.judgeft_assign first
```

Expected: `test: Counter({8: 60, 1: 10, 2: 10, 3: 10, 4: 10, 6: 8, 5: 7, 7: 5}), 짝 0, 대상이 둘인 ①② 12, ...` 와 `train: Counter({8: 240, 1: 35, 2: 35, ...}), 짝 120, ...`. E5 의 `count` 가 같은 배정을 이미 돌려 봤으므로 여기서 모자람이 나오면 E5 뒤에 입력(질문, 검색, 제외)이 바뀐 것이다. 종료 코드 2 로 멈추면 출력의 모자란 수를 보고, ④, ③, ⑥ 이면 그 시험지의 분야에 질문을 더 써서(E4) 다시 하고, ⑧ 이나 대상이 둘인 ①②, 짝이면 E5 로 돌아간다. 시드나 할당량을 바꾸지 않는다.

- [ ] **Step 2: 점검하고 커밋한다**

```bash
$PY -m tools.judgeft_check | tail -1
cd /Users/cheonjamin/projects/AllDap-judge-ft
git add ai-service/testdata/judgeft/assignment.json
git commit -m "test: 파인튜닝 실험의 시험용과 학습용 유형을 시드로 배정한다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/testdata/judgeft/assignment.json
```

Expected: `46가지 전부 통과.`(배정 재현 점검이 이제 실제 파일을 본다)

**리뷰 포인트:** 이 커밋 뒤로 회차의 `pool` 에 든 질문의 `questions.jsonl` 줄을 고치지 않는다(v2 계획 E6 의 규칙. 배정 재현 점검이 그 줄을 입력으로 쓴다).

---

### Task E7: 변형 답변과 변경 기록을 쓴다 (출제 세션)

**Files:**
- Create: `ai-service/testdata/judgeft/variants.jsonl`

- [ ] **Step 1: 배정된 질문마다 한 줄을 쓴다**

시험용과 학습용 모두, `assignment.json` 의 `types` 에 있는 질문마다 v2 스펙 3-2절의 방법으로 변형 답변을 쓰고, 위 형식 B 의 변경 기록 칸을 채운다. 짝 문항은 따로 줄을 쓰지 않는다(짝은 그 질문의 ⑧ 줄의 `target` 과 `evidence` 를 쓰고, 답변은 멀쩡한 답변이다).

- `evidence` 의 `quote` 는 근거 청크 전문에서 그대로 복사한다. 한 글자라도 다르면 그 학습 문항은 빠진다(스펙 5-2절 확인 1).
- ⑧ 의 `target` 과 `other.target` 은 `questions.jsonl` 의 `contrast` 와 같은 글자로 적는다.
- 학습용 문항이라도 "어차피 검수하지 않는다" 고 대충 쓰지 않는다. 모범 답안은 이 기록에서 그대로 만들어진다.

- [ ] **Step 2: 커밋한다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft
git add ai-service/testdata/judgeft/variants.jsonl
git commit -m "test: 파인튜닝 실험의 변형 답변과 변경 기록을 쓴다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/testdata/judgeft/variants.jsonl
```

**리뷰 포인트:** 출제 세션이 시험용 문항의 변형을 쓸 때 학습용 모범 답안의 틀을 보며 쓰지 않았는가(쓰는 사람은 같지만 시험 답변의 모양이 틀에 맞춰지면 안 된다).

---

### Task E8: 새 시험지를 만들고 검수한다

- [ ] **Step 1: 검수 전 새 시험지를 만든다** (오케스트레이터)

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft/ai-service
$PY -m tools.judgeft_export test draft
```

Expected: `새 시험지 120문항, SHA-256 ...`. 문제 목록이 나오면 출제 세션에 넘겨 `variants.jsonl` 을 고친다.

- [ ] **Step 2: 검수 폴더를 준비한다** (오케스트레이터)

v2 계획 E8 과 같은 방법이다. 저장소 밖의 새 폴더(예: `/Users/cheonjamin/judgeft_review/r1/`)에 `cases.jsonl` 의 사본 하나만 둔다. 지시문은 v2 의 검수 지시문(v2 계획 E8)을 그대로 쓴다. 지시문에 저장소 경로, 변형 유형, 이 실험이 파인튜닝이라는 말을 적지 않는다.

- [ ] **Step 3: 검수한다** (사용자, Codex)

사용자가 그 폴더에서 Codex 를 새로 열고 지시문을 붙여 넣는다. 끝나면 오케스트레이터가 결과 파일의 형식을 확인해 `testdata/judgeft/review.jsonl` 로 옮긴다. 검수 모델의 이름과 판, Codex CLI 의 판을 `run_log.md` 의 검수 절에 적는다.

- [ ] **Step 4: 커밋한다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft
git add ai-service/testdata/judgeft/review.jsonl ai-service/testdata/judgeft/run_log.md
git commit -m "test: 새 시험지를 Codex 로 검수한 결과를 옮긴다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/testdata/judgeft/review.jsonl ai-service/testdata/judgeft/run_log.md
```

검수 전 시험지(`cases.jsonl`, `answer_key.json` 의 draft)는 커밋하지 않는다(v2 와 같다. E9 의 최종본을 커밋한다).

**리뷰 포인트:** 검수 폴더에 시험지 사본 말고 다른 파일이 없었는가.

---

### Task E9: 불일치를 판단하고 최종 새 시험지와 검수 뒤 조건을 확인한다

- [ ] **Step 1: 불일치 목록을 만든다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft/ai-service
$PY -m tools.judgeft_export test mismatches
```

- [ ] **Step 2: 사용자가 판단한다** (사용자)

오케스트레이터가 `mismatches.md` 의 문항을 사용자에게 보이고, 판단(`keep`, `override`, `drop`)과 이유를 `review.jsonl` 의 그 줄에 적는다(v2 계획 E9 와 같다).

- [ ] **Step 3: 최종 새 시험지를 만들고 조건을 확인한다**

```bash
$PY -m tools.judgeft_export test final
$PY -m tools.judgeft_gate review
```

Expected: `최종 새 시험지 N문항(버린 문항 M개)`, 그리고 조건 셋이 모두 `통과` 이고 종료 코드 0. 하나라도 `실패` 이면(종료 코드 2) 아래 Step 4 로 간다.

- [ ] **Step 4: 조건을 채우지 못했으면 보충한다**

```bash
$PY -m tools.judgeft_assign supplement test
```

보충할 질문이 모자라 멈추면(종료 코드 2) 사용자에게 보인다. 채웠으면 아래 순서대로 한다. 정답 파일이 이미 최종본이라 E8 의 `test draft` 를 그대로 다시 하면 거절되고, 시험지 전체를 다시 검수하면 `review.jsonl` 에 같은 문항의 줄이 두 개가 되어 `test final` 이 멈추기 때문이다.

1. 출제 세션이 새 회차에 배정된 질문만 E7 처럼 변형 답변과 변경 기록을 쓴다.
2. 보충 문항을 더한 검수 전 시험지를 만든다.

   ```bash
   $PY -m tools.judgeft_export test draft --after-supplement
   ```

   Expected: `새 시험지 N문항(검수하지 않은 문항 K개), SHA-256 ...`. K 는 새 회차의 문항 수다. 관문 (a) 의 결과가 이미 있으면 도구가 거절한다(모델이 돈 뒤에는 시험지를 바꾸지 않는다).
3. 검수하지 않은 문항만 담은 파일을 저장소 밖의 새 폴더에 만든다.

   ```bash
   $PY -m tools.judgeft_export test pending --out /Users/cheonjamin/judgeft_review/r2/cases.jsonl
   ```

   Expected: `검수할 문항 K개: ...`. 폴더 이름은 회차마다 새로 정한다(`r2`, `r3`). 저장소 안의 경로를 주면 거절한다.
4. 사용자가 그 폴더에서 Codex 를 새로 열고 E8 Step 3 과 같은 지시문으로 검수한다.
5. 검수 결과를 `review.jsonl` 에 덧붙인다.

   ```bash
   $PY -m tools.judgeft_export test append-review /Users/cheonjamin/judgeft_review/r2/<결과 파일>
   ```

   Expected: `review.jsonl 에 K줄을 덧붙였습니다(모두 M줄).`. 이미 검수한 문항, 시험지에 없는 문항, 검수가 빠진 문항이 있으면 덧붙이지 않고 목록을 낸다.
6. 이 태스크의 Step 1~3(`test mismatches`, 사용자 판단, `test final`, `judgeft_gate review`)을 다시 한다. 앞 회차에서 이미 판단한 문항은 불일치 목록에 다시 나오지 않는다.

- [ ] **Step 5: 커밋한다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft
git add ai-service/testdata/judgeft/cases.jsonl ai-service/testdata/judgeft/cases.sha256 ai-service/testdata/judgeft/answer_key.json ai-service/testdata/judgeft/review.jsonl ai-service/testdata/judgeft/mismatches.md ai-service/testdata/judgeft/gate.md
git commit -m "test: 검수를 반영한 최종 새 시험지와 검수 뒤 조건을 남긴다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/testdata/judgeft/cases.jsonl ai-service/testdata/judgeft/cases.sha256 ai-service/testdata/judgeft/answer_key.json ai-service/testdata/judgeft/review.jsonl ai-service/testdata/judgeft/mismatches.md ai-service/testdata/judgeft/gate.md
```

보충 회차가 있었으면 `assignment.json`, `variants.jsonl` 도 두 명령의 경로 끝에 더한다.

**리뷰 포인트:** `gate.md` 에 가짜 모델 수치와 남은 ④ 수가 적혔는가. 늘 1점을 주는 가짜 모델의 비율이 약 67% 근처인가(스펙 4-4절이 v2 의 관문 5를 적용하지 않는다고 적은 이유).

---

### Task E10: 학습 데이터를 만들고 토큰과 누출을 확인한다

- [ ] **Step 1: 학습 데이터를 만든다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft/ai-service
$PY -m tools.judgeft_export train
```

Expected: `학습 묶음 약 540문항, 검증 묶음 약 60문항, 뺀 문항 0개` 와 종료 코드 0. 종료 코드는 뺀 문항이 있었는가가 아니라 **남은 문항이 할당량(스펙 4-4절)에 닿았는가** 로 정한다. 앞 회차에서 뺀 문항은 `train_dropped.json` 에 계속 남으므로, 보충으로 채운 뒤에는 `뺀 문항 n개` 와 함께 `뺀 문항은 보충 회차로 이미 채웠습니다.` 가 나오고 종료 코드는 0 이다. 할당량에 모자라면 `할당량에 모자랍니다: {...}` 와 종료 코드 2 다. 누출이 나오면(종료 코드 1) 학습하지 않고 사용자에게 보인다(스펙 5-3절). 누출 확인은 셋이다: 학습 문항의 글 전체가 시험지에 있는가, 학습 쪽(학습용 분야의 문서와 학습 문항)과 시험 쪽(시험용 분야와 v2 의 문서, 두 시험지)의 20자 이상 문장이 서로에게 나오는가(두 방향), 스펙 4-5절의 금지 값(`FORBIDDEN_VALUES`)이 학습 문항과 문장 틀에 있는가. 같은 질문의 변형 줄이 둘이면 종료 코드 1 로 멈춘다(출제 세션이 하나만 남긴다).

- [ ] **Step 2: 뺀 문항이 있으면 보충한다**

종료 코드 2(할당량에 모자람)이면 `train_dropped.json` 의 이유를 출제 세션에 보여 원인을 알린 뒤 보충한다.

```bash
$PY -m tools.judgeft_assign supplement train
```

새 회차의 질문만 출제 세션이 변형 답변과 변경 기록을 쓰고, Step 1 을 다시 한다. 앞에서 뺀 문항은 고치지 않는다(고치면 "글자 확인에 걸린 문항을 빼고 채운다" 는 스펙 4-4절의 규칙이 "걸린 문항을 고쳐 넣는다" 로 바뀐다). 뺀 수와 채운 수를 `run_log.md` 에 적는다.

- [ ] **Step 3: 실제 토크나이저로 확인한다**

```bash
$PY -m tools.judgeft_tokcheck
```

Expected: `모범 답안 위치만 계산한 loss 가 입력을 가린 전체 loss 와 같습니다.` 와 `N문항 모두 끝 토큰이 정답 쪽 맨 뒤에 있습니다. 가장 긴 문항 <id>: T토큰`. 토크나이저 파일(수 MB)만 내려받는다. T 를 `run_log.md` 에 적는다(관문 (b) 가 이 문항으로 메모리를 잰다).

- [ ] **Step 4: 점검하고 커밋한다**

```bash
$PY -m tools.judgeft_check | tail -1
cd /Users/cheonjamin/projects/AllDap-judge-ft
git add ai-service/testdata/judgeft/train.jsonl ai-service/testdata/judgeft/val.jsonl ai-service/testdata/judgeft/train_dropped.json ai-service/testdata/judgeft/train.sha256 ai-service/testdata/judgeft/run_log.md
git commit -m "test: 파인튜닝 실험의 학습 데이터를 만들고 토큰과 누출을 확인한다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/testdata/judgeft/train.jsonl ai-service/testdata/judgeft/val.jsonl ai-service/testdata/judgeft/train_dropped.json ai-service/testdata/judgeft/train.sha256 ai-service/testdata/judgeft/run_log.md
```

보충 회차가 있었으면 `assignment.json`, `variants.jsonl` 도 더한다.

**리뷰 포인트:** 학습 묶음과 검증 묶음의 유형 구성이 스펙 4-4절의 표(⑧ 40%, 짝 120)와 비슷한가. 모범 답안 몇 개를 열어 판단이 변경 기록과 맞는지 본다(검수가 아니라 틀이 의도대로 채워졌는지의 확인이다).

---

### Task E11: 동결 커밋

**이 커밋 뒤에 처음으로 모델을 돌린다**(스펙 9-1절 10). 이 커밋 뒤로 새 시험지, 정답 파일, 학습 데이터, 문장 틀, 노트북을 바꾸지 않는다.

- [ ] **Step 1: 노트북에 해시를 채운다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft/ai-service
$PY -m tools.judgeft_notebooks
grep -c "EXPECTED = {'train': ''" notebooks/judgeft_train_colab.ipynb
```

Expected: `썼다:` 두 줄, 그리고 `0`(학습 데이터 해시가 빈 글자가 아니다).

- [ ] **Step 2: 모든 점검을 돌린다**

```bash
$PY -m tools.judgeft_check | tail -1 && $PY -m tools.judge5_check | tail -1 && $PY -m tools.judge5v2_check | tail -1
```

Expected: `46가지 전부 통과.`, `44가지 전부 통과.`, `66가지 전부 통과.`

- [ ] **Step 3: 동결 커밋을 한다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft
git add ai-service/notebooks/judgeft_train_colab.ipynb ai-service/notebooks/judgeft_eval_colab.ipynb
git commit -m "test: 파인튜닝 실험의 새 시험지, 학습 데이터, 학습 설정을 모델을 돌리기 전에 동결한다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/notebooks/judgeft_train_colab.ipynb ai-service/notebooks/judgeft_eval_colab.ipynb
git log -1 --format=%H
```

마지막 해시를 `run_log.md` 와 결과 문서에 동결 커밋으로 적는다. 새 시험지와 학습 데이터는 E9, E10 에서 이미 커밋됐으므로 이 커밋은 그 해시를 담은 노트북을 고정하는 커밋이다. 이 커밋 뒤에 `git diff --stat <동결 커밋> HEAD -- ai-service/testdata/judgeft/{cases.jsonl,answer_key.json,train.jsonl,val.jsonl,templates.json} ai-service/notebooks/judgeft_*` 가 비어 있어야 한다(E18 에서 확인한다).

**리뷰 포인트:** 노트북의 기대 해시가 `cases.sha256`, `train.sha256` 의 값과 같은가(점검 `check_notebooks_match_generator` 가 본다).

---

### Task E12: 학습 전 M3 의 결정성을 확인한다 (사용자, 코랩)

**Files:**
- Create: `ai-service/testdata/judgeft/results/frozen/M3pre_run1.jsonl`, `.env.json`, `_smoke.json`(판이 다르거나 v2 의 run1 과 다르면 `run2` 도), `determinism.json`

- [ ] **Step 1: 사용자에게 안내한다**

사용자는 파이썬과 코랩에 익숙하지 않다. 오케스트레이터가 먼저 올릴 파일을 이름을 바꿔 한 폴더에 모은다.

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft/ai-service
mkdir -p ~/Desktop/alldap_judgeft_upload
cp testdata/judgeft/cases.jsonl ~/Desktop/alldap_judgeft_upload/cases_new.jsonl
cp testdata/judge5v2/cases.jsonl ~/Desktop/alldap_judgeft_upload/cases_frozen.jsonl
cp testdata/judgeft/train.jsonl testdata/judgeft/val.jsonl ~/Desktop/alldap_judgeft_upload/
cp notebooks/judgeft_eval_colab.ipynb notebooks/judgeft_train_colab.ipynb ~/Desktop/alldap_judgeft_upload/
ls ~/Desktop/alldap_judgeft_upload
```

Expected: 여섯 파일. 그다음 사용자에게 아래를 그대로 안내한다.

1. drive.google.com 의 내 드라이브에 `alldap_judgeft` 폴더를 만들고, 바탕화면의 `alldap_judgeft_upload` 폴더에서 `.jsonl` 네 파일(`cases_new.jsonl`, `cases_frozen.jsonl`, `train.jsonl`, `val.jsonl`)을 끌어 넣는다. 이름을 바꾸지 않는다.
2. colab.research.google.com 에서 파일 > 노트북 업로드 로 `judgeft_eval_colab.ipynb` 를 연다. 런타임 > 런타임 유형 변경 에서 **T4 GPU** 를 고른다.
3. 왼쪽 열쇠 아이콘(보안 비밀)에 이름 `HF_TOKEN` 으로 Hugging Face 토큰을 넣고 "노트북 액세스" 스위치를 켠다.
4. 둘째 칸 맨 위를 `SHEET = 'frozen'`, `MODEL = 'M3pre'`, `RUN = 1`, `ADAPTER_SHA256 = ''` 로 두고 런타임 > 모두 실행 을 누른다(약 78분, v2 결과 6-2절). "보안 비밀 액세스 권한" 창에는 **액세스 권한 부여**, "Google Drive 파일에 액세스" 창에는 **Google Drive에 연결** 을 누르고 모두 허용한다.
5. 오류로 멈추면 zip 이 내려받아지지 않는다. 빨간 오류 글의 마지막 다섯 줄쯤을 복사해 알려 준다. 칸을 고치지 않는다.
6. 끝나면 내려받아진 zip 의 경로(보통 `~/Downloads/alldap_judgeft_frozen_M3pre_run1.zip`)를 알려 준다.

- [ ] **Step 2: 결과를 풀고 결정성을 판정한다** (오케스트레이터)

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft/ai-service
unzip -o <zip 경로> -d testdata/judgeft/results/frozen
$PY -m tools.judgeft_determinism pre
```

Expected: `pre: frozen M3pre_run1 와 v2 M3_run1 를 대조. 같은 문항 231, 다른 문항 0. 쓸 실행 수 1`. 도구가 "frozen/M3pre_run2.jsonl 을 만든 뒤 다시 하세요" 로 멈추는 경우는 둘이다: 판(GPU, torch, transformers, bitsandbytes)이 v2 와 다를 때, 그리고 **판은 같은데 v2 의 run1 과 한 줄이라도 다를 때**. 뒤의 경우는 생성이 실행마다 다른지, v2 와 노트북 코드나 accelerate 판(v2 는 적지 않았다)이 달라서인지를 가르려고 새 환경의 run2 와 대조한다. 어느 경우든 Step 3 으로 간다.

- [ ] **Step 3: 판이 다르면 새 환경에서 한 번 더 돈다** (사용자)

같은 노트북을 `RUN = 2` 로 돌려 결과를 같은 폴더에 풀고 `judgeft_determinism pre` 를 다시 한다. run1 과 run2 가 같으면 생성은 결정적이고 v2 와의 차이는 환경이나 코드 쪽이다(쓸 실행 수 1). 다르면 생성이 실행마다 다르다(쓸 실행 수 3). 어느 쪽이든 v2 의 run1 은 섞지 않는다(`use_v2` 가 `false`). 판의 차이와 v2 와 다른 줄 수(`vs_v2`)를 `run_log.md` 에 적는다.

- [ ] **Step 4: 쓸 실행 수가 3 이면 실행을 채운다** (사용자)

`determinism.json` 의 `pre.runs` 가 3 이면, `use_v2` 가 `true` 일 때는 `RUN = 2` 를 한 번 더(v2 결과와 함께 3회), `false` 일 때는 `RUN = 3` 을 한 번 더 돌린다(`runs_for` 의 규칙). 이 경우 E13 과 E16 의 코랩 실행도 세 번씩이다.

- [ ] **Step 5: 커밋한다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft
git add ai-service/testdata/judgeft/results/frozen ai-service/testdata/judgeft/determinism.json ai-service/testdata/judgeft/run_log.md
git commit -m "test: 학습 전 M3 로 동결 시험지를 다시 채점해 결정성을 확인한다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/testdata/judgeft/results/frozen ai-service/testdata/judgeft/determinism.json ai-service/testdata/judgeft/run_log.md
```

**리뷰 포인트:** 결과 줄의 `revision` 이 `f790ee74...` 이고 `cases_sha256` 이 동결 시험지의 해시인가. 동결 시험지의 결과는 v2 에서 이미 공개된 것이므로 열어 봐도 된다. 새 시험지의 결과와 다르다.

---

### Task E13: 학습 전 관문 (a) (사용자, 코랩)

**새 시험지의 문항별 결과를 열지 않는다.** 이 태스크는 개수만 본다.

- [ ] **Step 1: 학습 전 M3 로 새 시험지를 채점한다** (사용자)

채점 노트북을 `SHEET = 'new'`, `MODEL = 'M3pre'`, `RUN = 1` 로 돌린다(약 40분). `pre.runs` 가 3 이면 `RUN = 2`, `3` 도 돌린다.

- [ ] **Step 2: 관문을 판정한다** (오케스트레이터)

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft/ai-service
unzip -o <zip 경로> -d testdata/judgeft/results/new
$PY -m tools.judgeft_gate a
```

Expected: 실행마다 `⑧ N문항, 못 읽음 U, 심각한 놓침 S, 비율 R%` 한 줄과 `관문 (a): 통과` 또는 `통과하지 못함`(비율이 가장 낮은 실행으로 판정). N 은 정답 점수가 1 인 ⑧ 이다(검수에서 사용자가 점수를 바꾼 ⑧ 은 심각한 놓침의 정의가 맞지 않아 세지 않는다). 결과 파일을 `cat`, `head`, `jq` 로 열지 않는다.

- [ ] **Step 3: 커밋한다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft
git add ai-service/testdata/judgeft/results/new ai-service/testdata/judgeft/gate_a.json ai-service/testdata/judgeft/run_log.md
git commit -m "test: 학습 전 관문 (a) 의 결과를 남긴다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/testdata/judgeft/results/new ai-service/testdata/judgeft/gate_a.json ai-service/testdata/judgeft/run_log.md
```

- [ ] **Step 4: 통과하지 못했으면 끝낸다**

E14 부터 E17 까지 하지 않고 E18 의 짧은 판으로 간다. 결과 문서에는 스펙 7-1절의 문장(이 새 시험지에서는 학습으로 줄일 자리가 기준만큼 없었다)을 그대로 쓴다. M1 은 돌리지 않는다.

**리뷰 포인트:** 이 태스크의 출력과 커밋 메시지에 문항 id 나 문항별 점수가 없는가.

---

### Task E14: 학습 전 관문 (b) (사용자, 코랩)

- [ ] **Step 1: 메모리와 시간을 잰다** (사용자)

`notebooks/judgeft_train_colab.ipynb` 를 코랩에서 열고(파일 > 노트북 업로드), 둘째 칸 맨 위의 `MODE = ''` 를 `MODE = 'gate_b'` 로 고쳐 모두 실행한다. 노트북 머리말의 안내(허용 창, 오류가 났을 때)를 따른다. `MODE` 를 비운 채 실행하면 둘째 칸에서 멈춘다(실수로 다른 단계를 돌리지 않게 한 것이다).

- [ ] **Step 2: 판정한다** (오케스트레이터)

내려받은 zip 의 `gate_b.json` 을 `testdata/judgeft/` 로 옮기고 본다. 노트북이 오류로 멈췄으면 zip 이 없다. 사용자가 복사해 준 오류 글의 마지막 줄로 아래 셋 중 어디인지 가른다.

- **메모리 부족(`OutOfMemoryError`)으로 멈췄으면** 학습하지 않고 사용자에게 보인다. 7B 로 내리기, 설정 바꾸기는 사용자가 정하고, 정하면 새 실험이다(스펙 7-2절).
- **`finite` 가 `false` 이거나 노트북이 "loss 가 숫자가 아니다" 로 멈췄으면** 같은 처리다.
- 그 밖의 오류(라이브러리 호출 오류 등)로 멈췄으면 노트북 코드의 문제다. 오류를 오케스트레이터가 받아 `judgeft_notebooks.py` 를 고치고 E11 의 Step 1~3 을 다시 한다(동결 커밋이 하나 더 생긴다). 스펙 6-5절의 네 조건을 모두 지킨다.
  - (a) 호출 오류를 고치는 것만 한다. 학습 데이터, 문장 틀, 학습 설정 값은 바꾸지 않는다.
  - (b) 무엇을 왜 고쳤는지와 새 동결 커밋의 해시를 커밋 메시지와 `run_log.md` 에 남긴다.
  - (c) 새 시험지의 문항별 결과를 열기 전이므로 결과에 맞춘 조정이 아니라는 근거를 `run_log.md` 에 적는다.
  - (d) 학습이 한 단계라도 진행된 뒤에 난 오류는 이 경우가 아니다. 고치지 않고 사용자에게 넘긴다.
  - **고친 곳이 채점 노트북과 함께 쓰는 칸(`judgeft_notebooks.py` 의 `COMMON`, `GUIDE`, `PIP`)이면 E12 와 E13 을 다시 한다.** 학습 전 M3 의 결과가 고치기 전의 코드로 나왔기 때문이다. 다시 한 결과는 앞의 것을 덮지 않고 `run_log.md` 에 두 결과를 함께 적는다. 학습 노트북에만 있는 칸(`setup`, `model_cell`, `gate_cell`, `train_cell`)만 고쳤으면 다시 하지 않는다.
- 통과했으면 `peak_gb`, `step_seconds`, `est_hours`, `save_every` 를 `run_log.md` 에 적고, **어림한 학습 시간을 사용자에게 알린다**(스펙 7-2절).

- [ ] **Step 3: 커밋한다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft
git add ai-service/testdata/judgeft/gate_b.json ai-service/testdata/judgeft/run_log.md
git commit -m "test: 학습 전 관문 (b) 의 메모리와 시간을 남긴다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/testdata/judgeft/gate_b.json ai-service/testdata/judgeft/run_log.md
```

**리뷰 포인트:** `longest_id` 가 E10 Step 3 의 가장 긴 문항과 같은가. `gate_b.json` 의 `env` 가 E12 의 `.env.json` 과 같은 판인가(다르면 `run_log.md` 에 적는다). 관문 칸이 `model.train()` 뒤 층마다 gradient checkpointing 이 켜졌는지 확인하고 지나갔는가(꺼진 채로 재면 메모리와 시간이 학습과 다르다).

---

### Task E15: 학습한다 (사용자, 코랩)

- [ ] **Step 1: 학습한다** (사용자)

런타임 > 세션 다시 시작 뒤 `MODE = 'train'` 으로 바꿔 모두 실행한다. 끊기면 세션을 다시 시작하고 그대로 모두 실행한다(가장 최근의 온전한 체크포인트에서 이어 한다). 학습 중에 다른 노트북으로 새 시험지를 채점하지 않는다. 오케스트레이터는 E14 에서 알린 어림 시간과 함께 아래를 사용자에게 다시 알린다.

- 학습하는 동안 브라우저 탭을 닫지 않고, 컴퓨터의 잠자기를 끈다(맥: 시스템 설정 > 디스플레이 또는 배터리 > 잠자기 방지).
- 무료 GPU 한도에 걸려 "GPU 백엔드에 연결할 수 없습니다" 가 뜨면 몇 시간 뒤(보통 다음 날) 다시 열고 `MODE = 'train'` 으로 모두 실행한다. 한 일은 Drive 에 남아 있다.
- 출력 줄의 `drive_free_gb` 가 3 아래로 내려가면 drive.google.com 의 휴지통에서 **휴지통 비우기** 를 누른다. 노트북이 지운 오래된 체크포인트(하나에 약 0.4GB, 재지 않은 어림)가 휴지통에서 용량을 차지한다.
- 이어 할 때 처음 세션과 판(GPU, torch, 라이브러리)이 다르면 노트북이 멈춘다. 그 줄을 그대로 알려 받는다(설정을 바꾸지 않고 사용자에게 보인다. 스펙 6-5절).
- 오류로 멈추면 빨간 오류 글의 마지막 다섯 줄쯤을 복사해 받는다. 학습이 한 단계라도 진행된 뒤의 오류이므로 노트북을 고치지 않고 사용자에게 보인다(스펙 6-5절의 (d)).

- [ ] **Step 2: 산출물을 기록한다** (오케스트레이터)

내려받은 zip 의 `training_log.jsonl`, `train_done.json`, `train_env.json` 을 `testdata/judgeft/` 로 옮긴다. `run_log.md` 에 적는다:
- 어댑터 SHA-256 과 Drive 경로(`MyDrive/alldap_judgeft/adapter/`). 어댑터 파일은 git 에 넣지 않는다(스펙 2-2절).
- 끊긴 횟수(`training_log.jsonl` 의 `resumed_from` 줄 수)와 이어 한 체크포인트, 깨져서 건너뛴 체크포인트(`bad_checkpoint` 줄). 같은 단계의 줄이 둘이면 마지막 줄이 맞는 값이다(끊긴 뒤 다시 한 단계다. 보고서 도구도 마지막 줄을 쓴다).
- loss scaling 으로 건너뛴 단계(`skipped` 가 `true` 인 줄)의 수와 위치.
- 마지막 학습 loss 와 검증 loss 의 흐름. 검증 loss 로 체크포인트를 고르지 않는다(스펙 6-3절).

- [ ] **Step 3: 커밋한다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft
git add ai-service/testdata/judgeft/training_log.jsonl ai-service/testdata/judgeft/train_done.json ai-service/testdata/judgeft/train_env.json ai-service/testdata/judgeft/run_log.md
git commit -m "test: M3 의 LoRA 학습 기록과 어댑터 해시를 남긴다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/testdata/judgeft/training_log.jsonl ai-service/testdata/judgeft/train_done.json ai-service/testdata/judgeft/train_env.json ai-service/testdata/judgeft/run_log.md
```

**리뷰 포인트:** `train_done.json` 의 `steps` 가 학습 단계 수와 같은가(학습이 끝까지 갔는가). 학습 도중 설정을 바꾼 흔적이 없는가.

---

### Task E16: 학습 후 M3 로 채점하고 결정성을 확인한다 (사용자, 코랩)

- [ ] **Step 1: 새 시험지를 두 번 채점한다** (사용자)

오케스트레이터가 `train_done.json` 에서 붙여 넣을 줄을 만들어 사용자에게 준다.

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft/ai-service
$PY -c "import json; print(\"ADAPTER_SHA256 = '\" + json.load(open('testdata/judgeft/train_done.json'))['adapter_sha256'] + \"'\")"
```

사용자는 채점 노트북 둘째 칸의 `ADAPTER_SHA256 = ''` 줄을 받은 줄로 통째로 바꾸고, `MODEL = 'M3ft'`, `SHEET = 'new'` 로 `RUN = 1`, `RUN = 2` 를 돌린다. `MODEL = 'M3pre'` 인데 해시가 있거나 `M3ft` 인데 비어 있으면 노트북이 멈춘다.

- [ ] **Step 2: 결정성을 판정한다** (오케스트레이터)

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft/ai-service
unzip -o <zip 경로들> -d testdata/judgeft/results/new
$PY -m tools.judgeft_determinism post
```

Expected: `post: new M3ft_run1 와 new M3ft_run2 를 대조. 같은 문항 N, 다른 문항 D. 쓸 실행 수 1 또는 3`. 결과 파일은 열지 않는다(대조는 도구가 한다).

- [ ] **Step 3: 동결 시험지를 채점하고, 3회이면 나머지를 채운다** (사용자)

`SHEET = 'frozen'` 으로 `RUN = 1` 을 돌린다. `post.runs` 가 3 이면 새 시험지 `RUN = 3`, 동결 시험지 `RUN = 2`, `3` 도 돌린다.

- [ ] **Step 4: 커밋한다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft
git add ai-service/testdata/judgeft/results ai-service/testdata/judgeft/determinism.json ai-service/testdata/judgeft/run_log.md
git commit -m "test: 학습 후 M3 로 두 시험지를 채점하고 결정성을 확인한다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/testdata/judgeft/results ai-service/testdata/judgeft/determinism.json ai-service/testdata/judgeft/run_log.md
```

**리뷰 포인트:** 결과 줄마다 `adapter_sha256` 이 E15 의 해시인가. 코랩 시간을 `run_log.md` 에 적었는가(학습 후 M3 는 어댑터 계산 때문에 더 느릴 수 있다. 스펙 9-2절).

---

### Task E17: M1 으로 새 시험지를 세 번 채점한다

**뉴런을 쓴다(회당 약 4,500).** 관문 (a) 와 (b) 를 모두 통과한 뒤(E14 뒤), 하루에 한 번씩 사흘에 나눈다. E15 의 학습과 E16 과는 순서가 상관없다. 도구가 `gate_a.json` 의 `pass` 와 `gate_b.json` 의 `finite` 를 확인하고, 하나라도 없거나 거짓이면 부르기 전에 멈춘다.

- [ ] **Step 1: 그날의 한도를 확인한다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft/ai-service
$PY -m tools.judge5_cloudflare --smoke
```

- [ ] **Step 2: 열 문항으로 먼저 잰다** (첫날만)

```bash
$PY -m tools.judgeft_cloudflare --run 1 --limit 10
```

출력의 뉴런을 10 으로 나눠 문항당 뉴런을 `run_log.md` 에 적고, 그날 남은 한도로 나머지가 들어가는지 본다.

- [ ] **Step 3: 채점한다**

```bash
$PY -m tools.judgeft_cloudflare --run <1, 2, 3 중 그날의 번호>
```

Expected: `M1_run<n>.jsonl: N/N건. 이번 호출 실패 0건. 뉴런 {...}`. 빠진 문항이 있으면 같은 명령을 다시 한다(빠진 문항만 부른다). 시작과 끝 시각(한국 시각), 뉴런, `finish` 값의 분포를 `run_log.md` 에 적는다.

- [ ] **Step 4: 날마다 커밋한다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft
git add ai-service/testdata/judgeft/results/new/M1_run<n>.jsonl ai-service/testdata/judgeft/run_log.md
git commit -m "test: M1 으로 새 시험지를 채점한다(실행 <n>)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/testdata/judgeft/results/new/M1_run<n>.jsonl ai-service/testdata/judgeft/run_log.md
```

실패 기록(`M1_run<n>_failures.jsonl`)이 생겼으면 두 명령의 경로 끝에 더한다.

**리뷰 포인트:** 같은 날에 실행 둘을 돌리지 않았는가. 업로드나 검색을 한 날과 겹치지 않는가.

---

### Task E18: 보고서, 결과 문서, PR

- [ ] **Step 1: 동결이 깨지지 않았는지 본다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft
git diff --stat <동결 커밋> HEAD -- ai-service/testdata/judgeft/cases.jsonl ai-service/testdata/judgeft/answer_key.json ai-service/testdata/judgeft/train.jsonl ai-service/testdata/judgeft/val.jsonl ai-service/testdata/judgeft/templates.json ai-service/notebooks/judgeft_train_colab.ipynb ai-service/notebooks/judgeft_eval_colab.ipynb
```

Expected: 비어 있다(E14 에서 노트북을 고쳐 동결 커밋을 다시 했다면 마지막 동결 커밋을 기준으로 본다).

- [ ] **Step 2: 보고서를 만든다**

```bash
cd ai-service
$PY -m tools.judgeft_report
```

Expected: `보고서: .../report.md`. 결과에 없는 문항이 있다고 멈추면 그 실행을 마저 채점한다. 결과 파일을 손으로 고쳐 맞추지 않는다. 보고서에는 문항과 학습 데이터의 경위, 검수 결과(사용자 판단별 수, 버린 문항의 유형별 수, 검수 뒤 세 조건), 관문 (a), (b) 의 결과(통과 여부와 관계없이), 학습 기록 요약, 시험지마다 수치 표(실행마다, 다섯 가짜 모델 포함, 못 읽음의 원인을 missing, conflict, out_of_range, 잘림으로 나눠), 혼동행렬, 유형별 표, 비교, 교체 후보 기준이 들어간다(스펙 7절, 8-2절, 9-3절). **관문 (a) 에서 끝났어도** 이 단계를 그대로 한다. 그때 있는 결과(학습 전 M3 의 두 시험지, v2 의 M1)만 내고, 돌리지 않은 모델과 비교와 기준은 `하지 않음` 으로 적힌다. 관문 (a) 를 통과했는데 `train_done.json` 이 없으면 도구가 거절한다(학습이 끝나기 전에 새 시험지의 결과를 열지 않는다. 스펙 6-5절).

- [ ] **Step 3: 결과 문서를 쓴다**

`docs/superpowers/plans/2026-10-05-judge-finetune-results.md`. v2 결과 문서의 구조를 따른다. 반드시 담는 것:

1. 결론(스펙 8-3절, 8-4절의 판정 문장 그대로). "사람과 비슷하다" 는 쓰지 않는다.
2. 동결 커밋, 두 시험지 해시, 학습 데이터 해시, 어댑터 해시와 Drive 위치.
3. 분야 순서와 늘린 분야, ⑧ 비율(E3), 문항이 줄어든 경위(검색, 제외, 검수, 학습 데이터에서 뺀 문항과 채운 문항).
4. 검수 모델과 판, 검수 뒤 조건, 결정성 확인(환경의 판 비교 포함).
5. 관문 (a), (b) 의 결과와 학습 기록(단계 수, 끊긴 횟수, loss 흐름).
6. 보고서의 수치, 학습 전후의 부호 검정, ⑧ 만의 짝 부호 검정(보고 항목), 교체 후보 기준 넷, `3909377dbed6` 의 점수.
7. 뉴런(업로드, 검색, M1 세 번)과 코랩 시간(채점, 학습)의 실측.
8. 스펙 11절의 한계와, 실행하면서 새로 알게 된 한계.

- [ ] **Step 4: 결정 로그, 핸드오프, AGENTS.md 의 안내를 고친다**

- `docs/decisions.md` 에 결론 항목 하나(`날짜 | 무엇을 | 왜 그렇게 | 검토한 대안`).
- `docs/superpowers/handoff-<날짜>.md` 를 새로 쓰고, AGENTS.md 의 "다음 세션은 여기서 시작한다" 가 그 파일을 가리키게 한다. AGENTS.md 에는 결과 수치를 넣지 않는다.

- [ ] **Step 5: 커밋한다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-ft
git add ai-service/testdata/judgeft/report.md docs/superpowers/plans/2026-10-05-judge-finetune-results.md docs/decisions.md docs/superpowers/handoff-<날짜>.md AGENTS.md
git commit -m "docs: 채점 모델 파인튜닝 실험의 결과와 결정을 남긴다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/testdata/judgeft/report.md docs/superpowers/plans/2026-10-05-judge-finetune-results.md docs/decisions.md docs/superpowers/handoff-<날짜>.md AGENTS.md
```

- [ ] **Step 6: #160 이 머지됐는지 보고, 머지됐으면 PR 을 연다**

```bash
gh pr view 160 --json state -q .state
```

`MERGED` 가 아니면 PR 을 열지 않고 여기서 멈춘다(계획 맨 위의 이유). `MERGED` 이면:

```bash
git fetch origin
git rebase origin/main
cd ai-service && $PY -m tools.judgeft_check | tail -1 && $PY -m tools.judge5_check | tail -1 && $PY -m tools.judge5v2_check | tail -1 && cd ..
git push -u origin feat/judge-finetune
gh pr create --title "채점 모델 M3 를 ⑧ 다른 대상 규정 문항으로 파인튜닝한다" --body-file <PR 템플릿을 채운 파일>
```

PR 본문은 `.github/PULL_REQUEST_TEMPLATE.md` 를 채운다. **한계와 트레이드오프** 칸과 **검토한 대안** 칸을 비우지 않는다. 본문 끝에 `🤖 Generated with [Claude Code](https://claude.com/claude-code)` 를 붙인다. CI 를 기다리지 않는다.

**리뷰 포인트:** 결과 문서의 모든 숫자가 `report.md`, `run_log.md`, `gate_a.json`, `gate_b.json` 에 있는 숫자인가. 관문에서 끝났으면 `report.md` 의 `하지 않음` 이 실제로 하지 않은 것과 맞는가. 판정 문장이 정해진 세 가지 중 하나인가. 교체 후보가 나왔어도 서비스의 채점 모델을 바꾸지 않았는가.
