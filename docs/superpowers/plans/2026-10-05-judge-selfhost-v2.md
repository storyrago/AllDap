# 채점 모델 비교 v2 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 정답 점수가 미리 정해진 시험 문제 240문항을 만들고, 그 시험 문제로 채점 모델 M1, M3, M4 가 대응표와 얼마나 맞는지 비교한다.

**Architecture:** 설계는 [`specs/2026-10-05-judge-selfhost-v2-design.md`](../specs/2026-10-05-judge-selfhost-v2-design.md)(이하 스펙)에 있다. 이 계획은 앞 실험 계획 [`plans/2026-10-02-judge-selfhost.md`](2026-10-02-judge-selfhost.md)(이하 앞 계획)의 구조를 따른다. 일은 두 종류다. 코드 태스크(태스크 1~10)는 `ai-service/tools/` 아래 도구를 만들고, 실행 태스크(태스크 E1~E14)는 그 도구로 문서를 올리고, 문항을 만들고, 검수하고, 모델을 돌린다. 서비스 코드(`ai-service/app/`)는 바꾸지 않는다.

**Tech Stack:** Python 3.12, 표준 라이브러리(`random`, `hashlib`, `logging`, `unittest.mock`), 기존 `app.retriever`, `app.cf`, `tools.judge5`, Spring API(봇 생성과 업로드에만), 코랩 T4.

## 리뷰 반영으로 바뀐 것

코드 태스크 1~10 은 모두 끝났다. 끝난 뒤 리뷰를 반영하면서 코드가 처음 계획과 달라졌다. 이 계획의 코드 블록과 기대 출력은 리뷰 반영 뒤의 커밋된 파일에 맞춰 고쳤다. 따라서 코드 태스크의 코드 블록은 구현 지시가 아니라 구현 기록이다. 바뀐 것과 그 커밋은 아래와 같다.

| 커밋 | 바뀐 것 | 영향을 받는 곳 |
|---|---|---|
| `adc2aea`, `4aca1d7` | v2 대괄호 끝 규칙을 `finish` 가 `stop` 일 때만 적용한다. `length` 와 `None`(잘렸는지 모른다)은 missing 이다. 스펙 6-4절 세부 규칙 2 도 같게 고쳤다 | 태스크 2, E12 |
| `e228b67` | 검색 도구가 검색 설정이 `config.py` 의 기본값과 다르면 멈춘다(`--allow-nondefault` 로 돌리면 결과 줄에 `nondefault` 가 생긴다). `--bot` 을 `bots.json` 과 대조한다. 노트북 머리말에 두 문장, 주석 한 줄. 검색 점검 9가지에서 12가지 | 형식 2, 태스크 4, 9, E3 |
| `71a99ae` | 점검 입구가 회차 0 의 후보가 검색을 통과한 질문 전부인지, 회차마다 후보에 앞 회차에서 쓴 질문이 없는지 본다. 최종 시험지를 입력에서 다시 만들어 바이트 대조한다. draft 시험지의 키도 본다. 자체 점검 8가지에서 11가지 | 태스크 10, E3, E5, E11 |
| `f17877a` | ⑥ 줄에 `old_value`(바꾸기 전 값)를 적는다. `first` 는 ⑧ 을 ⑥ 으로 돌린 분야가 있으면 종료 코드 2 로 멈춘다. 보충 후보를 `supplement_pools` 로 꺼냈다. `draft` 는 정답 파일이 이미 최종본이면 거절한다. 배정 점검 9가지에서 13가지, 내보내기 점검 7가지에서 10가지 | 형식 4, 태스크 5, 6, E5, E6 |
| `1a84798` | E1 이 끝나 봇 번호가 정해졌다: 인사 규정 9, 쇼핑몰 10, 설명서 11, 금융 12 | 데이터 표, E1 |

아래는 `198db57`(위 표를 계획에 반영한 커밋) 뒤의 것이다. 코드 태스크의 도구 파일 코드 블록(`judge5v2_*.py` 열둘)은 `85cbb89` 의 커밋된 파일과 글자까지 같게 다시 맞췄다. 그 뒤의 커밋은 이 계획에 아직 반영하지 않았다.

| 커밋 | 바뀐 것 | 영향을 받는 곳 |
|---|---|---|
| `4980edf`, `217048d` | 검색 도구가 이미 있는 줄의 `settings` 를 지금 설정과 대조해 다르면 멈춘다(`settings_conflicts`). `--allow-nondefault` 를 줘도 멈춘다. 멈출 때 줄을 옮기라고 권하지 않는다(옮기면 다시 검색해 뉴런을 쓰고, E5 뒤라면 배정 점검이 깨진다). 기본값을 `get_default(call_default_factory=True)` 로 꺼낸다. 검색 점검 12가지에서 14가지 | 태스크 4, E3 |
| `d368ba5` | `supplement` 도 그 회차에서 ⑧ 을 ⑥ 으로 돌린 분야가 있으면 종료 코드 2 로 멈춘다(회차는 파일에 붙는다. 다루는 단계는 E10). ⑥ 의 `new_value`, `old_value` 가 글자가 아니면 traceback 대신 문제 목록에 적는다. 배정 점검 13가지에서 14가지 | 태스크 5, 6, E10 |
| `3b494c5`, `02c4b5e` | 점검 입구의 회차 0 후보 대조를 지금 `retrieved.jsonl` 전체가 아니라, 회차에 기록된 `retrieved_sha256` 과 같은 해시를 내는 지금 파일의 앞부분으로 한다. 옛 판이 거짓 실패한 경로는 `1e35626` 행에 적었다. 고장 점검의 픽스처를 다른 점검 파일에서 빌리지 않고 이 파일 안에 둔다. 최종 시험지의 검색 설정이 한 가지인지 본다. 자체 점검 11가지에서 12가지 | 태스크 10, E5, E11 |
| `0ccf49c`, `02c4b5e` | 보고서의 못 읽음 내역에 512 잘림과 나란히 finish 기록 없음, finish 가 그 밖의 값을 센다. "문항이 줄어든 경위" 머리에 nondefault 검색 줄 수와 최종 시험지의 검색 설정 종류 수를 적는다(문항마다 마지막 검색 줄 기준). 보고서 점검 3가지에서 5가지 | 태스크 8, E14 |
| `5d781e4` | 스펙 6-4절 세부 규칙 2 를 "`stop` 이 아니면(`length`, 기록 없음 등 그 밖의 값 포함) missing" 으로 넓혔다. 코드는 `adc2aea` 부터 그렇게 동작한다 | 태스크 2 |
| `8a02646`, `e9afd8c` | E4 가 끝났다. 근거 5청크에 정답이 없는 질문 9개를 `excluded.json` 에 적었다(금융 7, 인사 1, 쇼핑몰 1) | 데이터 표, E4, E5 |
| `5cb9a46` | 스펙에 새 버림 원인을 더했다(2-3절, 3-3절 1, 9절): 검색은 통과했지만 정답이 근거 청크 밖인 질문은 배정 후보에서 뺀다. 서비스라면 `NO_ANSWER` fallback 쪽이라 채점 모델이 볼 일이 없다 | E4, E5, E14 |
| `a0557d2`, `85cbb89` | 배정 도구가 `excluded.json` 의 질문을 후보에서 빼고(`pool_for` 의 셋째 인자 `excluded`, 기본 없음), 회차마다 `excluded_sha256`, `excluded`, `excluded_counts` 를 적는다(형식 3). 원인 이름이 틀리거나, 없는 질문이거나, 검색하지 않았거나 검색에서 이미 버린 질문을 제외에 적으면 한국어 안내로 멈춘다. `supplement` 의 ⑧ 멈춤 안내는 E10 이고 되돌리는 명령을 함께 찍는다. 이미 배정된 질문을 제외에 적으면 `supplement` 가 종료 코드 1 로 멈춘다(그런 문항은 검수에서 `drop` 한다). ⑧ 의 값이 글자가 아니면 안내로 거절한다. 배정 점검 14가지에서 17가지 | 형식 3, 태스크 5, E5, E10 |
| `1e35626` | 점검 입구의 회차 0 후보 대조가 그 회차 기록의 `excluded` 를 정답에서 뺀다(빼지 않으면 실제 배정에서 제외한 9개가 "빠짐" 으로 실패한다). 옛 판이 거짓 실패한 경로를 고쳐 적었다: 회차 0 후보에 든 076 이후(E5 전 보충)와 회차 0 뒤에 ok 가 된 질문이고, 회차 0 뒤에 덧붙인 076 이후(E10 보충)는 통과했다. 두 경로를 점검으로 고정했다. 자체 점검 12가지에서 13가지. 뒤이어(리뷰 반영) 회차 0 의 `excluded` 기록 자체를 지금 `excluded.json` 과 대조한다: 기록의 `excluded_sha256` 이 지금 파일 해시와 같으면 `{qid: 원인}` 이 파일 내용과 같아야 하고, 다르면(파일이 나중에 바뀜) 기록의 질문마다 지금 파일에 같은 원인으로 있어야 한다. 해시가 `null` 이면 기록도 비어야 하고, 원인은 `EXCLUDE_REASONS` 안이다. 기록과 후보가 함께 질문을 더 빼면 후보 대조와 재현은 통과하기 때문이다. 자체 점검 13가지에서 14가지 | 태스크 10, E5 |
| `36fa197` | 보고서 "문항이 줄어든 경위" 에 정답이 근거 청크 밖이라 뺀 질문을 분야, 원인별로 센다. 회차의 `excluded_counts` 를 더하지 않고 모든 회차의 `excluded` 를 합쳐 한 번씩 센다(회차마다 그때의 파일 전체를 적기 때문). "쓰지 않은 질문" 에서 제외한 질문을 뺀다. 보고서 점검 5가지에서 6가지. 뒤이어(리뷰 반영) 합집합에서 `assigned_types` 의 질문을 뺀다(앞 회차가 제외했다가 뒤 회차에서 풀려 배정된 질문이 제외와 배정에 두 번 세어지지 않게). 보고서 점검 6가지에서 7가지 | 태스크 8, E14 |

점검 개수는 이렇다. `judge5_check` 44가지(태스크 3 뒤), `judge5v2_check` 65가지(도구 점검 51가지와 자체 점검 14가지. 도구 점검은 검색 14, 배정 17, 내보내기 10, 관문 3, 보고서 7).

## Global Constraints

모든 태스크가 아래를 지킨다. 값은 스펙에서 그대로 옮겼다.

- 작업 위치는 워크트리 `/Users/cheonjamin/projects/AllDap-judge-v2`(브랜치 `feat/judge-selfhost-v2`)다. 네 세션이 같은 워크트리를 쓴다. 커밋은 **`git add <경로들>` 뒤에 `git commit -m "..." -- <같은 경로들>`** 꼴로 한다. `git add -A`, `git add .` 를 쓰지 않는다. 이유: 워크트리 하나에는 index(커밋할 내용을 모아 두는 곳)가 하나뿐이다. 세션 A 가 `git add a` 를, 세션 B 가 `git add b` 를 한 뒤 A 가 경로 없이 `git commit` 하면 b 도 A 의 커밋에 들어간다. `git commit -- <경로들>` 은 index 에 올라간 다른 내용과 관계없이 적은 경로만 커밋한다. 앞의 `git add` 는 새 파일 때문에 필요하다. git 이 아직 모르는 파일은 `git commit -- <경로>` 만으로는 커밋되지 않는다. `index.lock` 오류가 나면 몇 초 뒤 같은 명령을 다시 한다.
- 이 계획에서 **파이썬** 은 메인 저장소의 가상환경 `/Users/cheonjamin/projects/AllDap/ai-service/.venv/bin/python` 이다. 워크트리에는 `.venv` 가 없다. 명령은 늘 워크트리의 `ai-service` 에서 실행한다. 그래야 `tools` 와 `app` 을 워크트리의 코드로 불러온다. 아래 명령에서는 `PY=/Users/cheonjamin/projects/AllDap/ai-service/.venv/bin/python` 으로 줄여 쓴다.
- push 하지 않는다. PR 은 태스크 E14 에서만 연다.
- 서비스 코드(`ai-service/app/`)를 고치지 않는다. 앞 실험의 파일(`testdata/judge5/`, `testdata/judge_labels_5pt.json`, `notebooks/judge5_colab.ipynb`)을 고치지 않는다(스펙 8-3절).
- 봇 1번(데모 봇), 7번, 8번(리랭커 실험)은 건드리지 않는다(스펙 2-2절).
- 분야 키는 넷이다: `hr`(인사 규정), `shop`(쇼핑몰 고객센터), `manual`(제품 사용 설명서), `finance`(금융 상품 안내).
- 대응표: ①과 ② 5점, ③ 4점, ④ 3점, ⑤ 2점, ⑥과 ⑦과 ⑧ 1점(스펙 3-2절). 코드에서는 유형을 정수 1~8 로 쓴다(①이 1).
- 분야마다 할당량: ① 9, ② 9, ③ 9, ④ 9, ⑤ 6, ⑥ 7, ⑦ 5, ⑧ 6. 합쳐 60문항, 네 분야 240문항(스펙 7-1절).
- 분야마다 질문 75개(스펙 3-3절). 그중 약 30개는 답이 두 가지인 질문(스펙 3-1절).
- ⑥과 ⑧은 답이 하나인 질문(`two_part: false`)에만 만든다(스펙 3-2절).
- 배정 순서는 ④, ⑧, ③, ⑥, 나머지(①, ②, ⑤, ⑦)다(스펙 3-3절).
- 배정 시드는 `20261005` 하나다. 시험지를 섞는 시드도 같은 값이다.
- 공통 지시문, 채점표, 생성 설정(탐욕적 디코딩, 최대 출력 512 토큰)은 `tools/judge5.py` 의 것을 그대로 쓴다(스펙 5절).
- 6절의 판정 규칙(스펙)은 모델 출력을 보기 전에 커밋돼 있다. 결과를 본 뒤 규칙이나 코드를 바꾸지 않는다.
- 문서와 주석과 커밋 메시지에 em dash 문자를 쓰지 않는다. 쉼표, 콜론, 괄호로 대신한다.
- 커밋 메시지는 `<타입>: <한국어 요약>` 뒤에 빈 줄, 그리고 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` 한 줄이다.
- Python 코드에는 왜 그렇게 썼는지 한국어 주석을 붙인다(AGENTS.md). 아래 코드의 주석이 그 기준이다.

---

## 파일 구조

### 새로 만드는 코드

| 파일 | 맡는 일 | 태스크 |
|---|---|---|
| `ai-service/tools/judge5v2_files.py` | 경로, 분야, 대응표, 할당량, 시드, JSON 읽고 쓰기. 도구 여섯이 같은 상수를 읽게 하려고 한 곳에 둔다 | 1 |
| `ai-service/tools/judge5v2_search.py` | 질문마다 실제 검색으로 근거 청크 전문을 뽑아 `retrieved.jsonl` 에 쓴다 | 4 |
| `ai-service/tools/judge5v2_search_check.py` | 검색 도구 점검 | 4 |
| `ai-service/tools/judge5v2_assign.py` | 시드로 변형 유형을 배정한다. 보충 배정도 한다 | 5 |
| `ai-service/tools/judge5v2_assign_check.py` | 배정 도구 점검 | 5 |
| `ai-service/tools/judge5v2_export.py` | 시험지 파일과 정답 파일, 사용자 판단용 불일치 목록을 만든다 | 6 |
| `ai-service/tools/judge5v2_export_check.py` | 내보내기 도구 점검 | 6 |
| `ai-service/tools/judge5v2_gate.py` | 변별력 관문 다섯 조건과 가짜 모델 수치 | 7 |
| `ai-service/tools/judge5v2_gate_check.py` | 관문 점검 | 7 |
| `ai-service/tools/judge5v2_report.py` | 스펙 6절의 수치와 판정 | 8 |
| `ai-service/tools/judge5v2_report_check.py` | 보고서 점검 | 8 |
| `ai-service/notebooks/judge5v2_colab.ipynb` | 앞 노트북을 복사해 바꾼 코랩 노트북 | 9 |
| `ai-service/tools/judge5v2_check.py` | CI 에서 도는 점검의 입구. 위 다섯 점검과 노트북 대조, 커밋된 파일 점검을 묶는다 | 10 |

**스펙과 다른 점 둘.** 첫째, 스펙 8-3절은 점검 파일을 `judge5v2_check.py` 하나로 적었다. 이 계획은 도구마다 점검 파일을 따로 두고 `judge5v2_check.py` 가 그것들을 묶어 부르게 한다. 이유: 도구 다섯을 서로 다른 세션이 동시에 만든다. 점검 파일이 하나면 다섯 세션이 같은 파일을 동시에 고치게 된다. CI 가 부르는 입구는 스펙대로 `tools.judge5v2_check` 하나다. 둘째, 스펙 8-3절에 없는 `judge5v2_files.py` 를 더한다. 할당량이나 대응표가 도구마다 따로 적혀 있으면 한쪽만 바뀌기 때문이다.

### 고치는 코드

| 파일 | 고치는 곳 | 태스크 |
|---|---|---|
| `ai-service/tools/judge5.py` | 읽는 규칙 판(v1, v2), 판정 문구의 비교 기준 이름, 교체 후보 기준 4(심각한 놓침) | 2 |
| `ai-service/tools/judge5_cloudflare.py` | 시험지와 결과 폴더를 인자로 받는다. 결과 줄에 분야를 옮긴다 | 3 |
| `ai-service/tools/judge5_check.py` | 태스크 2, 3 의 점검을 더한다 | 2, 3 |
| `.github/workflows/ci.yml` | `python -m tools.judge5v2_check` 한 줄 | 10 |

### 실행 태스크가 만드는 데이터 (`ai-service/testdata/judge5v2/`)

| 파일 | 만드는 태스크 | 한 줄(또는 한 덩어리)의 모양 |
|---|---|---|
| `bots.json` | E1 | `{"hr": 9, "shop": 10, "manual": 11, "finance": 12}` (E1 커밋 `1a84798` 의 실제 번호) |
| `run_log.md` | E1, E3, E8, E10, E12 | 뉴런 기록, 검수 모델의 이름과 판, 관문 결과. 단계마다 한 절 |
| `hr_targets.md` | E2 | 인사 규정의 대상별 규정 표(다른 세 분야의 README 표에 해당) |
| `questions.jsonl` | E2, E4 | 아래 형식 1 |
| `excluded.json` | E4 | `{"<qid>": {"reason": "answer_not_in_top5" 또는 "partial_answer_not_in_top5", "note": "..."}}`. 검색은 통과했지만 정답이 근거 5청크 밖이라 배정 후보에서 빼는 질문(스펙 2-3절, `5cb9a46`) |
| `retrieved.jsonl` | E3 | 아래 형식 2 |
| `assignment.json` | E5 | 아래 형식 3 |
| `variants.jsonl` | E6 | 아래 형식 4 |
| `cases.jsonl`, `cases.sha256`, `answer_key.json` | E7, E11 | 아래 형식 5, 6 |
| `review.jsonl` | E8, E9 | 아래 형식 7. 검수 세션은 저장소 밖 폴더에서 쓰고, 오케스트레이터가 이 자리로 옮긴다 |
| `mismatches.md` | E9 | 사용자 판단용. 변형 유형이 적혀 있다. 검수 세션은 저장소 밖에서 일하므로 이 파일에 닿지 않는다 |
| `gate.md` | E10 | 관문 결과 |
| `results/` | E12, E13 | 앞 실험과 같은 결과 줄에 `domain` 을 더한 것 |
| `report.md` | E14 | 보고서 |

### 데이터 형식

모든 태스크가 아래 형식을 그대로 쓴다. 형식이 바뀌면 이 절을 먼저 고친다.

**형식 1. `questions.jsonl`** (E2 가 앞 넷을 쓰고, E4 가 뒤 넷을 채운다)

```json
{"qid": "shop-001", "domain": "shop", "question": "골드 등급은 얼마 이상 사면 배송비가 무료인가요?", "two_part": false,
 "answer": null, "claims": null, "contrast": null, "answer_note": null}
```

- `qid`: `<분야>-<세 자리 번호>`. 분야 안에서 001 부터 차례로 매긴다. 보충 질문은 이어서 076, 077 ... 이다.
- `two_part`: 답이 두 가지인 질문이면 `true`.
- `answer`: 멀쩡한 답변. `claims`: 멀쩡한 답변의 주장 수(1 이상 정수).
- `contrast`: ⑧ 조건을 만족하지 않으면 `null`. 만족하면 `{"asked": {"target": "골드", "value": "10,000원"}, "other": {"target": "실버", "value": "20,000원"}, "chunk_ids": [123]}`. `asked` 는 질문이 묻는 대상, `other` 는 근거 청크에 함께 있는 다른 대상이다. `chunk_ids` 는 두 값이 글자 그대로 적힌 근거 청크의 id 다. `two_part` 가 `true` 인 질문에는 적지 않는다(⑧ 은 답이 하나인 질문에만 만든다).
- `answer_note`: 출제 세션의 메모(선택).
- **값을 글자로 찾는 규칙.** 도구가 값(`contrast` 의 두 값, ⑥ 의 `new_value` 와 `old_value`)이 어떤 글 안에 있는지 볼 때는 단순 포함이 아니라 `judge5v2_files.value_in` 을 쓴다. 값의 첫 글자가 숫자이면 바로 앞에 숫자나 "숫자 + 쉼표/점" 이 오지 않아야 하고, 값의 끝 글자가 숫자이면 바로 뒤에 숫자나 "쉼표/점 + 숫자" 가 오지 않아야 한다. 이유: 단순 포함으로는 `10,000원` 이 `110,000원` 안에 있다고 판정된다. 금융 분야의 수수료처럼 자릿수만 다른 값이 실제로 있다.
- **E5 뒤로 고치지 않는 줄.** 어느 배정 회차의 `pool` 에 든 질문의 줄은 그 회차를 커밋한 뒤 고치지 않는다(E6 의 규칙). 배정을 다시 돌려 보는 점검(CI)이 이 줄들을 입력으로 쓰기 때문이다.

**형식 2. `retrieved.jsonl`** (E3)

```json
{"qid": "shop-001", "domain": "shop", "bot_id": 13, "settings": {"top_k": 5, "...": "..."},
 "status": "ok", "drop_reason": null, "top1_distance": 0.31, "warnings": [],
 "sources": [{"chunk_id": 123, "filename": "03_배송_안내.md", "content": "청크 전문"}]}
```

- `status` 는 `ok` 또는 `dropped`. `drop_reason` 은 `null`, `answerable`(근거 유무 판정), `max_distance`(검색용 컷), `rerank_failed`, `keyword_failed` 중 하나다.
- `nondefault` 는 검색 도구를 `--allow-nondefault` 로 돌렸을 때만 생긴다. `{키: {"default": 기본값, "actual": 실제 값}}` 꼴로, 검색 설정 중 `config.py` 의 기본값과 다른 것을 적는다. 이 키가 있는 줄로 만든 문항은 스펙 2-3절의 기본 설정으로 검색한 것이 아니다. 이 실험의 계획대로라면 이 키는 생기지 않는다.
- `keyword_failed` 는 스펙 2-3절에 없다. 키워드 검색이 실패해도 `search` 는 경고만 남기고 벡터 결과로 계속한다. 그러면 시험지에 하이브리드를 켠 설정이 적히지만 실제 순서는 벡터 순서다. 리랭커 실패와 같은 이유로 그 질문을 뺀다.
- **한 질문에 줄이 여럿일 수 있다.** 버림 원인은 두 종류다. `answerable`, `max_distance` 는 검색 결과가 정해진 원인이라 다시 검색해도 같다. `rerank_failed`, `keyword_failed` 는 호출 실패라서 다시 부르면 풀릴 수 있다. 그래서 검색 도구는 앞의 두 원인과 `ok` 인 질문만 끝난 것으로 보고, 호출 실패로 버린 질문은 다음 실행에서 다시 검색한다. 앞의 줄은 지우지 않고 시도 기록으로 남기며 새 줄을 덧붙인다. **질문마다 마지막 줄이 그 질문의 판정이다.** 이 파일을 읽는 도구는 모두 `judge5v2_files.latest_by_qid` 로 마지막 줄만 본다.

**형식 3. `assignment.json`** (E5, 보충 때 늘어난다)

```json
{"seed": 20261005,
 "rounds": [
   {"round": 0, "questions_sha256": "...", "retrieved_sha256": "...",
    "excluded_sha256": "...", "excluded": {"finance-007": "answer_not_in_top5", "...": "..."},
    "excluded_counts": {"hr": {"answer_not_in_top5": 1}, "shop": {"...": 0}, "manual": {}, "finance": {"...": 0}},
    "pool": {"hr": ["hr-001", "..."], "shop": ["..."], "manual": ["..."], "finance": ["..."]},
    "needs": {"hr": {"1": 9, "2": 9, "...": 0}, "...": {}},
    "domains": {"hr": {"types": {"hr-004": 4, "...": 1}, "unused": ["hr-070"], "eighth_to_sixth": 0}, "...": {}}}
 ]}
```

- `pool` 은 그 회차에서 뽑을 수 있었던 질문이다. 배정이 시드로 재현되는지 CI 가 이 목록으로 다시 돌려 본다.
- `eighth_to_sixth` 는 ⑧ 조건을 만족하는 질문이 모자라 ⑥ 으로 돌린 수다(스펙 3-3절 5).
- `excluded_sha256`, `excluded`, `excluded_counts` 는 그 회차가 `excluded.json` 으로 후보에서 뺀 질문이다(`a0557d2`). `excluded_sha256` 은 그때 파일의 해시(파일이 없었으면 `null`), `excluded` 는 `{qid: 원인}`, `excluded_counts` 는 `{분야: {원인: 수}}`(네 분야가 늘 있다)다. **회차마다 그때의 파일 전체를 적는다.** 그래서 회차의 `excluded_counts` 를 더하면 같은 질문을 회차 수만큼 센다. 보고서는 회차들의 `excluded` 를 합쳐 한 번씩 센다(`36fa197`). 점검 입구의 회차 0 후보 대조도 이 기록의 `excluded` 를 쓴다(`excluded.json` 을 다시 읽지 않는다). 대신 기록 자체를 지금 `excluded.json` 과 따로 대조한다(해시가 같으면 내용이 같아야 하고, 다르면 기록의 질문이 같은 원인으로 남아 있어야 한다). 보고서는 합친 제외에서 배정된 질문을 뺀다.

**형식 4. `variants.jsonl`** (E6)

```json
{"qid": "shop-001", "type": 8, "answer": "실버 등급은 20,000원 이상이면 무료입니다.", "note": "골드 값을 실버 값으로 바꿨다"}
{"qid": "shop-017", "type": 6, "answer": "골드 등급은 35,000원 이상이면 무료입니다.", "note": "핵심 값을 바꿨다", "new_value": "35,000원", "old_value": "10,000원"}
```

- `new_value`: ⑥ 줄에만 있다. 핵심 답 자리에 바꿔 넣은 값을 답변에 적힌 글자 그대로 적는다. 내보내기 도구가 이 값이 답변에 있고 그 질문의 근거 청크 전문 어디에도 없는지 확인한다(스펙 3-2절의 ⑥ 조건).
- `old_value`: ⑥ 줄에만 있다(`f17877a` 에서 더했다). 바꾸기 전의 핵심 값을 멀쩡한 답변에 적힌 글자 그대로 적는다. 내보내기 도구가 이 값이 멀쩡한 답변에는 있고 변형 답변에는 없는지 확인한다. 이유: 변형 답변에 옛 값이 남으면("35,000원 이상이면 무료입니다. 기존 기준은 10,000원입니다.") 근거와 맞는 주장과 반대인 주장이 함께 있는 답변이 된다. 그러면 정답 점수가 1점(반대)과 3점(섞임) 사이에서 하나로 정해지지 않는다.

**형식 5. `cases.jsonl`** (E7, E11). 키는 정확히 넷이다.

```json
{"case_id": "3fa1c09b2d7e", "domain": "shop", "messages": [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}],
 "search_settings": {"top_k": 5, "...": "..."}}
```

`cases.sha256` 은 앞 실험과 같다. 첫 줄 `<시험지 해시>  cases.jsonl`, 둘째 줄 `<공통 지시문 해시>  prompt`.

**형식 6. `answer_key.json`** (E7 은 `stage: draft`, E11 은 `stage: final`)

```json
{"stage": "final", "seed": 20261005, "cases_sha256": "...", "prompt_sha256": "...",
 "cases": {"3fa1c09b2d7e": {"qid": "shop-001", "domain": "shop", "type": 8, "table_score": 1,
                            "score": 1, "review_score": 1, "decision": "match"}},
 "dropped": {"9b0e...": {"qid": "...", "domain": "...", "type": 3, "table_score": 4, "review_score": 2, "reason": "..."}}}
```

- `table_score` 는 대응표의 점수, `score` 는 최종 정답 점수다. `decision` 은 `match`(검수 점수가 정답 점수와 같음), `keep`(달랐지만 사용자가 대응표대로 둠), `override`(사용자가 고침) 중 하나다. `keep` 과 `override` 에는 `reason` 이 있다.
- draft 단계에서는 `score`, `review_score`, `decision` 이 없다.

**형식 7. `review.jsonl`** (E8 이 앞 셋을 쓰고, E9 가 사용자 판단을 더한다)

```json
{"case_id": "3fa1c09b2d7e", "review_score": 2, "review_note": "근거에 없는 주장이 대부분",
 "user_decision": "override", "override_score": 2, "reason": "④로 만들었지만 바꾼 주장이 근거와 반대로 읽힌다"}
```

`user_decision` 은 `keep`, `override`, `drop` 중 하나다. 검수 점수가 정답 점수와 같은 문항에는 적지 않는다.

---

## 태스크 사이의 의존 관계

| 태스크 | 종류 | 먼저 끝나야 하는 것 | 뉴런 | 사람 |
|---|---|---|---|---|
| 1 공통 상수 | 코드 | 없음 | 없음 | |
| 2 judge5.py | 코드 | 없음 | 없음 | |
| 3 judge5_cloudflare.py | 코드 | 2 (같은 점검 파일) | 없음 | |
| 4 검색 도구 | 코드 | 1 | 없음 | |
| 5 배정 도구 | 코드 | 1 | 없음 | |
| 6 내보내기 도구 | 코드 | 1, 5 | 없음 | |
| 7 관문 도구 | 코드 | 1 (실행에는 6) | 없음 | |
| 8 보고서 도구 | 코드 | 2, 7 | 없음 | |
| 9 노트북 | 코드 | 없음 | 없음 | |
| 10 점검 묶기와 CI | 코드 | 2, 4~9 | 없음 | |
| E1 봇 생성과 업로드 | 실행 | 없음 | **쓴다**(청크 임베딩) | |
| E2 질문 쓰기 | 실행 | 없음(문서만 있으면 된다) | 없음 | |
| E3 검색 | 실행 | 4, E1, E2 | **쓴다**(질문 임베딩, 리랭커) | |
| E4 멀쩡한 답변 | 실행 | E3 | 없음 | |
| E5 배정 | 실행 | 5, E4 | 없음 | |
| E6 변형 답변 | 실행 | E5 | 없음 | |
| E7 첫 내보내기 | 실행 | 6, E6 | 없음 | |
| E8 검수 | 실행 | E7 | 없음 | **사용자**(Codex 를 열고 지시문을 붙여 넣는다) |
| E9 불일치 판단 | 실행 | E8 | 없음 | **사용자** |
| E10 관문 | 실행 | 7, E9 | 없음 | 통과하지 못하면 보충(E2~E10 반복) |
| E11 최종 내보내기와 동결 커밋 | 실행 | E10 통과, 3, 9, 10 | 없음 | |
| E12 M1 채점 | 실행 | E11, 3. **E1, E3 다음 날 이후** | **쓴다**(약 7,400) | |
| E13 코랩 채점 | 실행 | E11, 9 | 없음 | **사용자**(약 2.3시간) |
| E14 보고서, 결과 문서, PR | 실행 | 8, E12, E13 | 없음 | |

### 네 세션에 나누는 제안

| 세션 | 맡는 태스크(순서대로) | 비고 |
|---|---|---|
| 가 (출제) | E2, E4, E6, 보충 때 E2, E4, E6 다시 | **출제 세션은 이 세션 하나다.** 질문, 멀쩡한 답변, 변형 답변을 모두 쓴다. 말투와 기준이 한 세션 안에서 일관되게 하기 위해서다 |
| 나 | 1, 2, 3, 7, 8, 10 | 1 은 15분 안에 끝나는 작은 태스크다. 커밋되면 세션 다와 라가 4, 5 를 시작한다 |
| 다 | 4, 9, E3, E5 | E3 은 E1, E2 가 끝난 뒤 |
| 라 | E1, 5, 6, E7 | E1 은 첫날 바로 시작한다(뉴런을 쓰는 단계를 첫날에 몰아 M1 을 다음 날에 돌리기 위해서다) |
| 오케스트레이터 | E8 의 폴더 준비와 결과 옮기기, E9, E10, E11, E12, E14 | 나머지 세션을 나누고 사용자와 이야기하는 세션이다. E9 는 사용자 판단을 받아 적는다. E13 은 사용자가 코랩에서 돌린다 |
| 검수 세션 | E8 의 채점 | **Claude 세션이 아니라 Codex(OpenAI) 세션이다.** 사용자가 저장소 밖의 전용 폴더에서 새로 연다(E8). 출제가 Claude 이므로 계열이 다른 모델이 검수해야 두 모델이 함께 놓친 실수만 통과한다(스펙 4절) |

각 코드 태스크가 끝나면 다른 세션이 리뷰한다(예: 나의 태스크는 다가, 다의 태스크는 라가, 라의 태스크는 나가). 태스크마다 **리뷰 포인트** 를 적어 두었다.

### 날짜와 뉴런

- **첫날:** E1(업로드)과 E3(검색)을 끝낸다. 업로드(문서 131개)와 검색(질문 약 300개)의 뉴런은 재보지 않았다(스펙 8-2절). E1 과 E3 이 `run_log.md` 에 실제 값을 적는다. 한도(하루 10,000)를 넘을 것 같으면 E3 을 이틀에 나눈다.
- **M1 채점(E12)은 업로드와 검색을 한 날의 다음 날 이후, 그날 다른 뉴런 사용이 없을 때** 돌린다. 앞 실험에서 건당 약 31뉴런이었으므로 240문항은 약 7,400뉴런으로 추정한다. 보충 때문에 검색을 다시 하면 M1 은 그다음 날로 밀린다.
- 이 계획에서 **다음 날** 은 달력의 날짜가 아니라 **한도가 한 번 초기화된 뒤** 를 뜻한다. 검색의 마지막 호출과 M1 채점 사이에 초기화 시각이 한 번 이상 지나야 한다. 초기화 시각은 UTC 0시(한국 시각 오전 9시)로 본다. 이 시각은 이 저장소에서 재보지 않았다. 그래서 E3 과 E12 는 `run_log.md` 에 각 실행의 시작과 끝 시각을 한국 시각으로 적는다.
- 한도가 언제 초기화되는지는 대시보드 카운터로 추측하지 않는다. 그날 첫 호출(`--smoke`)이 성공하는지로 확인한다(AGENTS.md 평가 규칙).

---

## 코드 태스크

### Task 1: 공통 경로와 상수

**Files:**
- Create: `ai-service/tools/judge5v2_files.py`

**Interfaces:**
- Consumes: 없음
- Produces: `ROOT`, `V2`, `QUESTIONS`, `RETRIEVED`, `ASSIGNMENT`, `VARIANTS`, `REVIEW`, `CASES`, `CASES_SHA`, `ANSWER_KEY`, `MISMATCHES`, `GATE`, `RESULTS_DIR`, `REPORT`, `BOTS` (모두 `Path`), `DOMAINS: tuple[str, ...]`, `CORPUS_DIRS: dict[str, Path]`, `TYPE_NAMES: dict[int, str]`, `TABLE_SCORE: dict[int, int]`, `QUOTA: dict[int, int]`, `QUESTIONS_PER_DOMAIN = 75`, `SEED = 20261005`, `PROTECTED_BOTS: frozenset[int]`, `read_jsonl(path) -> list[dict]`, `write_jsonl(path, rows) -> None`, `append_jsonl(path, row) -> None`, `read_json(path) -> dict`, `write_json(path, data) -> None`, `SETTLED_DROPS: frozenset[str]`, `latest_by_qid(rows: list[dict]) -> list[dict]`, `value_in(value: str, text: str) -> bool`

- [ ] **Step 1: 파일을 만든다**

```python
"""채점 모델 비교 v2 실험(2026-10-05)의 경로와 상수.

설계: docs/superpowers/specs/2026-10-05-judge-selfhost-v2-design.md

도구 여섯(search, assign, export, gate, report, check)이 같은 경로와 같은 상수를 읽게 하려고 한 곳에 둔다.
할당량이나 대응표가 도구마다 따로 적혀 있으면 언젠가 한쪽만 바뀐다.
외부 API 도 DB 도 부르지 않는다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# __file__ 은 ai-service/tools/judge5v2_files.py 다. 두 번 올라가면 ai-service/ 다.
ROOT = Path(__file__).resolve().parent.parent
V2 = ROOT / "testdata" / "judge5v2"

BOTS = V2 / "bots.json"
QUESTIONS = V2 / "questions.jsonl"
RETRIEVED = V2 / "retrieved.jsonl"
ASSIGNMENT = V2 / "assignment.json"
VARIANTS = V2 / "variants.jsonl"
REVIEW = V2 / "review.jsonl"
CASES = V2 / "cases.jsonl"
CASES_SHA = V2 / "cases.sha256"
ANSWER_KEY = V2 / "answer_key.json"
MISMATCHES = V2 / "mismatches.md"
GATE = V2 / "gate.md"
RESULTS_DIR = V2 / "results"
REPORT = V2 / "report.md"

# 스펙 2-1절의 네 분야. 튜플이라 순서가 고정된다. 보고서의 분야 순서도 이것을 따른다.
DOMAINS: tuple[str, ...] = ("hr", "shop", "manual", "finance")
CORPUS_DIRS: dict[str, Path] = {
    "hr": ROOT / "testdata" / "corpus",
    "shop": V2 / "corpus" / "shop",
    "manual": V2 / "corpus" / "manual",
    "finance": V2 / "corpus" / "finance",
}

# 스펙 3-2절의 변형 유형. 키는 유형 번호다(①이 1).
TYPE_NAMES: dict[int, str] = {
    1: "① 원본 그대로",
    2: "② 표현만 바꿈",
    3: "③ 사소한 말 하나 추가",
    4: "④ 절반 바꾸기",
    5: "⑤ 대부분 지어냄",
    6: "⑥ 핵심을 근거와 반대로",
    7: "⑦ 통째로 지어냄",
    8: "⑧ 다른 대상의 규정 끌어오기",
}
# 스펙 3-2절의 대응표. 변형 유형에서 정답 점수가 정해진다.
TABLE_SCORE: dict[int, int] = {1: 5, 2: 5, 3: 4, 4: 3, 5: 2, 6: 1, 7: 1, 8: 1}
# 스펙 7-1절. 분야마다의 할당량. 합이 60 이다.
QUOTA: dict[int, int] = {1: 9, 2: 9, 3: 9, 4: 9, 5: 6, 6: 7, 7: 5, 8: 6}
QUESTIONS_PER_DOMAIN = 75
# 배정과 시험지 섞기에 쓰는 시드. 고정해야 같은 입력에서 같은 배정과 같은 시험지 해시가 나온다.
SEED = 20261005
# 데모 봇(1)과 리랭커 실험 봇(7, 8). 이 실험의 도구는 이 번호를 받으면 거절한다(스펙 2-2절).
PROTECTED_BOTS: frozenset[int] = frozenset({1, 7, 8})


def read_jsonl(path: Path) -> list[dict]:
    """한 줄에 JSON 하나인 파일을 읽는다. 파일이 없으면 빈 목록이다(이어 하기의 첫 실행)."""
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    # sort_keys=True: 키 순서를 고정해 같은 내용이면 같은 해시가 나오게 한다(시험지 해시가 재현돼야 한다).
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows), encoding="utf-8")


def append_jsonl(path: Path, row: dict) -> None:
    # "a" 는 이어 쓰기 모드다. 한 줄씩 바로 써 두면 중간에 멈춰도 그때까지의 결과가 남는다.
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# 다시 검색해도 결과가 같은 버림 원인(계획 형식 2). rerank_failed, keyword_failed 는 호출 실패라서 여기에 없다.
# 다시 부르면 풀릴 수 있으므로 검색 도구가 다음 실행에서 다시 검색한다.
SETTLED_DROPS: frozenset[str] = frozenset({"answerable", "max_distance"})


def latest_by_qid(rows: list[dict]) -> list[dict]:
    """retrieved.jsonl 은 시도마다 줄을 덧붙인다. 질문마다 마지막 줄만 남긴다(그 질문의 판정).

    dict 에 같은 키를 다시 넣으면 값은 바뀌고 자리는 처음 넣은 자리 그대로다. 그래서 순서는 첫 시도의 순서다.
    """
    last: dict[str, dict] = {}
    for r in rows:
        last[r["qid"]] = r
    return list(last.values())


def value_in(value: str, text: str) -> bool:
    """값이 text 안에 다른 값의 일부가 아닌 채로 있는가(계획 형식 1 의 값을 글자로 찾는 규칙).

    단순 포함(value in text)으로는 "10,000원" 이 "110,000원" 안에 있다고 나온다. 그래서 값의 끝이 숫자인
    쪽에만 경계를 건다. (?<!...) 는 "바로 앞이 ... 가 아니다", (?!...) 는 "바로 뒤가 ... 가 아니다" 는 뜻이다.
    앞쪽: 숫자나 "숫자 + 쉼표/점" 이 오면 안 된다. 뒤쪽: 숫자나 "쉼표/점 + 숫자" 가 오면 안 된다.
    값이 "원" 처럼 숫자가 아닌 글자로 끝나면 뒤쪽 경계를 걸지 않는다. 그래서 "10,000원." 의 마침표는 막지 않는다.
    """
    if not value:
        return False
    head = r"(?<!\d)(?<!\d[,.])" if value[0].isdigit() else ""
    tail = r"(?!\d|[,.]\d)" if value[-1].isdigit() else ""
    return re.search(head + re.escape(value) + tail, text) is not None
```

- [ ] **Step 2: 상수가 스펙과 맞는지 확인한다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-v2/ai-service
$PY -c "
from tools.judge5v2_files import QUOTA, TABLE_SCORE, CORPUS_DIRS, value_in
assert sum(QUOTA.values()) == 60
assert not value_in("10,000원", "110,000원") and not value_in("2,000원", "12,000원입니다.")
assert value_in("12,000원", "12,000원입니다.") and value_in("15", "15일입니다") and not value_in("15", "15.5일")
by_score = {s: sum(n for t, n in QUOTA.items() if TABLE_SCORE[t] == s) for s in range(1, 6)}
print(by_score, {d: len([p for p in v.glob('*.md') if p.name != 'README.md']) for d, v in CORPUS_DIRS.items()})
"
```

Expected: `{1: 18, 2: 6, 3: 9, 4: 9, 5: 18} {'hr': 56, 'shop': 25, 'manual': 25, 'finance': 25}` (스펙 7-1절의 비율 30%, 10%, 15%, 15%, 30%).

- [ ] **Step 3: 커밋한다**

```bash
git add ai-service/tools/judge5v2_files.py
git commit -m "feat: 채점 모델 비교 v2 의 공통 경로와 상수를 추가한다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/tools/judge5v2_files.py
```

**리뷰 포인트:** `QUOTA` 와 `TABLE_SCORE` 가 스펙 3-2절, 7-1절의 표와 글자 하나까지 같은가. `write_jsonl` 이 `sort_keys=True` 로 해시를 재현 가능하게 쓰는가.

---

### Task 2: judge5.py 의 읽는 규칙 판, 판정 문구, 기준 4

**Files:**
- Modify: `ai-service/tools/judge5.py` (`parse_result`, `Comparison.verdict`, `replacement_failures`, 상수 추가)
- Modify: `ai-service/tools/judge5_check.py` (점검 여섯 추가)

**Interfaces:**
- Consumes: 없음
- Produces:
  - `RULES_V1 = "v1"`, `RULES_V2 = "v2"`
  - `parse_result(text: str | None, finish: str | None = None, *, rules: str = RULES_V1) -> tuple[int | None, str]`
  - `Comparison.verdict(self, a: str, b: str, basis: str = "사람") -> str`
  - `replacement_failures(cand: Summary, m1: Summary, vs_m1: Comparison, *, basis: str = "사람", severe: tuple[int, int] | None = None) -> list[str]`. `severe` 는 `(후보의 심각한 놓침, M1 의 심각한 놓침)` 이다. `None` 이면 기준 4를 보지 않는다(앞 실험 판).

- [ ] **Step 1: 실패하는 점검을 쓴다** (`judge5_check.py`)

import 줄을 아래로 바꾼다.

```python
from .judge5 import (
    CRITERIA, MAX_NEW_TOKENS, MODELS, RUBRIC, RULES_V2, SCALE, Comparison,
    build_messages, compare, prompt_sha256, smoke_messages, linear_weighted_kappa, parse_result, pick_best,
    replacement_failures, sha256_file, sign_test_p, summarize, to_three,
)
```

`check_scores_of_counts_each_failure_kind` 앞에 아래 여섯을 더하고, `CHECKS` 목록 끝에 여섯 이름을 같은 순서로 더한다.

```python
def check_parse_v1_ignores_bracket_tail() -> None:
    """앞 실험 판은 그대로다. 대괄호로 끝나는 출력을 v1 이 읽기 시작하면 앞 실험의 M4 점수가 바뀐다."""
    assert parse_result("이유를 적었다. [4]") == (None, "missing")
    assert parse_result("이유를 적었다. [4]", "stop") == (None, "missing")


def check_parse_v2_reads_bracket_tail() -> None:
    """v2 스펙 6-4절: [RESULT] 가 없고 맨 끝이 대괄호 정수 하나이면 읽는다. 꾸밈은 [RESULT] 와 똑같이 받는다."""
    def v2(text: str, finish: str | None = "stop") -> tuple[int | None, str]:
        return parse_result(text, finish, rules=RULES_V2)

    assert v2("이유를 적었다. [4]") == (4, "ok")
    assert v2("이유를 적었다. [4]  \n") == (4, "ok")           # 뒤의 공백은 무시한다
    for tail in ("[４]", "[4/5]", "**[4]**", "[**4**]", "[ 4 ]"):
        assert v2("이유 " + tail) == (4, "ok"), tail
    assert v2("이유 [05]") == (5, "ok")                         # 앞의 0
    assert v2("근거 [1] 을 보면 맞다. [3]") == (3, "ok")         # 앞의 대괄호는 무시하고 맨 끝만 본다


def check_parse_v2_tail_is_strict() -> None:
    """1~5 정수가 아니거나 맨 끝이 아니면 규칙을 적용하지 않으므로 missing 이다(out_of_range 가 아니다)."""
    for text in ("이유 [7]", "이유 [4.5]", "이유 [4/10]", "이유 [0]", "이유 [-1]", "이유 [4].", "이유 [4] 끝", "점수 없음"):
        assert parse_result(text, "stop", rules=RULES_V2) == (None, "missing"), text


def check_parse_v2_refuses_truncated_tail() -> None:
    """512 토큰에서 잘린 출력의 끝은 모델이 점수를 적은 자리가 아니다(v2 스펙 6-4절 세부 규칙 2)."""
    assert parse_result("이유가 길어서 잘렸다 [2]", "length", rules=RULES_V2) == (None, "missing")
    assert parse_result("잘렸는지 모른다 [4]", None, rules=RULES_V2) == (None, "missing")   # None 은 "모른다"


def check_parse_v2_keeps_result_rules() -> None:
    """[RESULT] 가 있으면 대괄호 끝 규칙을 쓰지 않는다. 앞 판의 상태가 그대로 나와야 한다."""
    v2 = lambda t: parse_result(t, "stop", rules=RULES_V2)   # noqa: E731 - 점검 안에서만 쓰는 줄임
    assert v2("[RESULT] 4 그리고 [2]") == (4, "ok")
    assert v2("[RESULT] 점수 [3]") == (None, "out_of_range")
    assert v2("[RESULT] 2 [RESULT] 3") == (None, "conflict")
    try:
        parse_result("[RESULT] 4", rules="v3")
    except ValueError:
        return
    raise AssertionError("모르는 판은 거절해야 한다")


def check_verdict_basis_and_severe_criterion() -> None:
    """v2 는 사람이 아니라 대응표와 대조한다(스펙 1-3절). 기준 4는 severe 를 줄 때만 본다(앞 실험 보고서 보존)."""
    win = Comparison(0, 10, 0, 0, 0.002)
    assert win.verdict("M3", "M1") == "M3 가 사람에 더 가깝다"
    assert win.verdict("M3", "M1", basis="대응표") == "M3 가 대응표에 더 가깝다"
    s = summarize([(5, 5)] * 3)
    tie = Comparison(0, 0, 0, 3, 1.0)
    assert replacement_failures(s, s, tie) == []
    assert replacement_failures(s, s, tie, severe=(1, 1)) == []
    assert replacement_failures(s, s, tie, severe=(2, 1)) == ["심각한 놓침이 M1 보다 많다(2 > 1)"]
    lose = Comparison(0, 0, 10, 0, 0.002)
    assert replacement_failures(s, s, lose, basis="대응표") == ["부호 검정에서 M1 이 대응표에 더 가깝다(p = 0.0020)"]
```

- [ ] **Step 2: 점검이 실패하는지 본다**

Run: `cd /Users/cheonjamin/projects/AllDap-judge-v2/ai-service && $PY -m tools.judge5_check`
Expected: `ImportError: cannot import name 'RULES_V2'`

- [ ] **Step 3: judge5.py 를 고친다**

`_RESULT_RE` 정의 바로 아래에 더한다.

```python
# 점수 읽기 규칙의 판. v1 은 앞 실험(2026-10-02) 그대로이고 기본값이다. v2 는 v1 에 대괄호 끝 규칙 하나를 더한다
# (v2 스펙 6-4절). 기본값을 v1 로 두는 이유: judge5_report 와 judge5_check 가 인자 없이 앞 실험과 같은 결과를
# 내야 한다. 앞 실험의 M4 출력을 v2 로 다시 읽으면 못 읽음 41건이 점수로 바뀐다.
RULES_V1 = "v1"
RULES_V2 = "v2"

# v2 의 대괄호 끝 규칙. 출력의 맨 끝(뒤 공백 제외)이 [4] 꼴이면 그 값을 읽는다.
# 받는 꾸밈은 _RESULT_RE 와 같다: 굵게(**[4]**, [**4**]), 괄호 안 공백([ 4 ]), 앞의 0([05]), 전각 숫자([４]),
# 5점 만점 분수([4/5]). 값은 부호와 소수점까지 잡아 두고 아래에서 1~5 정수인지 따진다.
# \Z 는 "문자열의 진짜 끝" 이다. 그래서 맨 끝의 대괄호 하나만 맞고, 앞쪽의 근거 번호([1])는 맞지 않는다.
_TAIL_RE = re.compile(
    r"(?:\*\*)?\[\s*(?:\*\*)?\s*(-?\d+(?:\.\d+)?)(?:\s*/\s*(\d+))?\s*(?:\*\*)?\s*\](?:\*\*)?\s*\Z"
)


def _parse_tail(text: str, finish: str | None) -> tuple[int | None, str]:
    """[RESULT] 가 없는 출력에만 쓴다. 읽지 못하면 v1 과 같이 missing 이다(v2 스펙 6-4절)."""
    if finish != "stop":
        # 끝이 정상으로 끝났다고 기록된 출력에만 적용한다. "length" 이면 잘린 출력이라 끝은 모델이 점수를 적은
        # 자리가 아니라 토큰이 다 된 자리다. None 은 "잘리지 않았다" 가 아니라 "모른다" 다(app/cf.py 의
        # finish_reason). 모르는 채로 읽으면 잘린 출력에서도 모델이 쓰지 않은 점수를 만들 수 있다.
        return None, "missing"
    m = _TAIL_RE.search(text)
    if not m:
        return None, "missing"
    val, den = m.groups()
    if den and int(den) != 5:
        return None, "missing"
    # isdigit(): "4.5", "-1" 은 False 다. 전각 숫자 "４" 는 True 이고 int("４") 는 4 다.
    if not val.isdigit() or int(val) not in SCALE:
        return None, "missing"
    return int(val), "ok"
```

`parse_result` 의 머리와 첫 부분을 아래로 바꾼다. 그 뒤(분모 검사부터 끝까지)는 그대로 둔다.

```python
def parse_result(text: str | None, finish: str | None = None, *, rules: str = RULES_V1) -> tuple[int | None, str]:
    """모델 출력에서 점수를 읽는다. (점수, 상태) 를 돌려준다.

    상태는 넷이다. 앞의 하나만 점수가 있고 나머지 셋은 서로 다른 실패다.
      ok            점수 하나를 읽었다
      missing       [RESULT] 가 없다(출력이 잘렸거나 양식을 안 지켰다. v2: 대괄호 끝 규칙으로도 못 읽었다)
      out_of_range  [RESULT] 는 있는데 뒤의 값이 1~5 정수가 아니다(소수, 음수, 범위 밖, 숫자를 못 찾음)
      conflict      [RESULT] 를 여러 번 쓰고 값이 서로 다르다
    셋을 "못 읽음" 하나로 뭉개지 않는 이유: 원인이 다르면 고칠 곳도 다르다.
    규칙(꾸밈은 너그럽게, 값은 엄격하게)은 스펙 §4-7 에 측정 전에 고정돼 있다.
    rules 가 RULES_V2 이면 [RESULT] 가 없는 출력에 대괄호 끝 규칙(_parse_tail)을 더 적용한다.
    finish 는 생성이 끝난 이유(stop, length, 모르면 None)이고 v2 의 대괄호 끝 규칙만 쓴다. 그 규칙은 stop 일 때만 적용한다.
    """
    if rules not in (RULES_V1, RULES_V2):
        raise ValueError(f"알 수 없는 읽는 규칙 판입니다: {rules}. RULES_V1 또는 RULES_V2 를 주세요.")
    if not text:
        return None, "missing"
    pairs = _RESULT_RE.findall(text)   # (값, 분모) 목록. 예: [("4", "")], [("4.5", "")], [("4", "10")]
    if not pairs:
        # [RESULT] 는 썼는데 뒤에서 값을 못 찾은 것("[RESULT] Score: 4")은 missing 이 아니다.
        # 스펙 §4-7 표의 missing 은 "[RESULT] 가 없다" 이고, 이 경우는 "값을 읽을 수 없다" 쪽이다.
        if "[RESULT]" in text:
            return None, "out_of_range"
        return _parse_tail(text, finish) if rules == RULES_V2 else (None, "missing")
```

위 조각은 리뷰 반영(`adc2aea`) 뒤의 모습이다. 처음 계획은 `finish == "length"` 일 때만 막았다. 커밋된 파일은 기존 독스트링의 두 줄(스펙 §4-7 고정 문장, `[RESULT]` 를 못 쓴 것과 값 모양이 틀린 것은 고칠 곳이 다르다는 주석)도 그대로 남겼다.

`Comparison.verdict` 를 바꾼다.

```python
    def verdict(self, a: str, b: str, basis: str = "사람") -> str:
        """스펙 §4-3 의 판정 문장. p < 0.05 일 때만 더 가까운 쪽을 말한다.

        basis 는 무엇과 대조했는가다. 앞 실험은 사람 라벨이고, v2 는 대응표다(v2 스펙 1-3절).
        """
        if self.p_value < 0.05 and self.a_closer != self.b_closer:
            closer = a if self.a_closer > self.b_closer else b
            return f"{closer} 가 {basis}에 더 가깝다"
        return "구별되지 않음"
```

`replacement_failures` 를 바꾼다.

```python
def replacement_failures(cand: Summary, m1: Summary, vs_m1: Comparison, *,
                         basis: str = "사람", severe: tuple[int, int] | None = None) -> list[str]:
    """교체 후보 기준(스펙 §4-4, v2 스펙 6-3절)에서 어긋난 항목을 돌려준다. 빈 목록이면 교체 후보다.

    vs_m1 은 compare(정답, 후보, M1) 의 결과여야 한다(a 가 후보, b 가 M1).
    severe 는 (후보의 심각한 놓침, M1 의 심각한 놓침) 이다. v2 만 넘긴다. None 이면 기준 4를 보지 않는다.
    앞 실험의 보고서가 바뀌지 않게 하려고 기본값을 None 으로 둔다.
    """
    out = []
    if cand.within1 < m1.within1:
        out.append(f"거리 1 이하 사례가 M1 보다 적다({cand.within1} < {m1.within1})")
    if cand.unread > 0:
        out.append(f"못 읽음 사례가 {cand.unread}건 있다")
    if vs_m1.p_value < 0.05 and vs_m1.b_closer > vs_m1.a_closer:
        out.append(f"부호 검정에서 M1 이 {basis}에 더 가깝다(p = {vs_m1.p_value:.4f})")
    if severe is not None and severe[0] > severe[1]:
        out.append(f"심각한 놓침이 M1 보다 많다({severe[0]} > {severe[1]})")
    return out
```

- [ ] **Step 4: 점검이 통과하는지, 앞 실험의 보고서가 그대로인지 본다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-v2/ai-service
$PY -m tools.judge5_check | tail -1
$PY -m tools.judge5_report > /dev/null && git diff --exit-code testdata/judge5/report.md && echo 앞-보고서-그대로
```

Expected: `42가지 전부 통과.` 그리고 `앞-보고서-그대로`. 둘째 명령에서 diff 가 나오면 기본값이 v1 이 아닌 것이다.

- [ ] **Step 5: 커밋한다**

```bash
git add ai-service/tools/judge5.py ai-service/tools/judge5_check.py
git commit -m "feat: judge5 에 v2 읽는 규칙과 대응표 판정 문구, 심각한 놓침 기준을 더한다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/tools/judge5.py ai-service/tools/judge5_check.py
```

**리뷰 포인트:** v1 이 기본값이어서 앞 실험의 `report.md` 가 한 글자도 바뀌지 않는가(Step 4 의 diff). 대괄호 끝 규칙이 `[RESULT]` 가 있는 출력에는 절대 적용되지 않는가.

---

### Task 3: judge5_cloudflare.py 를 인자로 받게 한다

**Files:**
- Modify: `ai-service/tools/judge5_cloudflare.py`
- Modify: `ai-service/tools/judge5_check.py` (점검 둘 추가)

**Interfaces:**
- Consumes: 태스크 2 의 `judge5_check.py` (같은 파일이라 태스크 2 뒤에 한다)
- Produces: `sha_path(cases: Path) -> Path`, `result_line(..., cases_sha256: str, domain: str | None = None) -> dict`, `run_all(limit: int | None, cases: Path = CASES, results_dir: Path = RESULTS_DIR) -> int`, `_parser() -> argparse.ArgumentParser`. 명령줄 인자 `--cases`, `--results-dir`.

- [ ] **Step 1: 실패하는 점검을 쓴다** (`judge5_check.py`)

import 에 `from . import judge5_cloudflare` 와 `from .judge5_export import CASES, RESULTS_DIR` 을 더한다(`judge5_export` import 줄에 `CASES, RESULTS_DIR` 을 더하면 된다). 아래 둘을 더하고 `CHECKS` 끝에 이름을 더한다.

```python
def check_cloudflare_defaults_are_v1_paths() -> None:
    """인자 없이 부르면 앞 실험과 같은 시험지와 결과 폴더다(v2 스펙 8-3절)."""
    args = judge5_cloudflare._parser().parse_args([])
    assert args.cases == CASES and args.results_dir == RESULTS_DIR
    assert judge5_cloudflare.sha_path(CASES) == CASES.parent / "cases.sha256"


def check_cloudflare_run_all_takes_paths_and_copies_domain() -> None:
    """v2 시험지로 돌리면 결과 줄에 분야가 옮겨진다. 분야가 없는 줄(앞 실험)에는 domain 키를 만들지 않는다."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        cases = d / "cases.jsonl"
        cases.write_text(
            json.dumps({"case_id": "aa", "domain": "shop", "messages": []}) + "\n"
            + json.dumps({"case_id": "bb", "messages": []}) + "\n", encoding="utf-8")
        (d / "cases.sha256").write_text(f"{sha256_file(cases)}  cases.jsonl\n", encoding="utf-8")
        saved = judge5_cloudflare._call
        judge5_cloudflare._call = lambda messages: ("[RESULT] 5", "stop")   # 외부 API 대신 가짜 응답
        try:
            assert judge5_cloudflare.run_all(None, cases, d / "res") == 0
        finally:
            judge5_cloudflare._call = saved   # 모듈 전역을 바꿨으므로 반드시 되돌린다
        rows = [json.loads(l) for l in (d / "res" / "M1_run1.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[0]["domain"] == "shop" and "domain" not in rows[1]
```

- [ ] **Step 2: 점검이 실패하는지 본다**

Run: `$PY -m tools.judge5_check`
Expected: `AttributeError: module 'tools.judge5_cloudflare' has no attribute '_parser'`

- [ ] **Step 3: judge5_cloudflare.py 를 고친다**

모듈 설명 첫 부분의 실행 예에 한 줄을 더한다.

```python
    .venv/bin/python -m tools.judge5_cloudflare --cases testdata/judge5v2/cases.jsonl --results-dir testdata/judge5v2/results
```

`result_line` 과 그 앞에 아래를 둔다.

```python
def sha_path(cases: Path) -> Path:
    """시험지 해시 파일의 자리. 시험지와 같은 폴더의 cases.sha256 이다(앞 실험과 v2 모두).
    with_suffix 는 확장자만 바꾼다: cases.jsonl 이 cases.sha256 이 된다."""
    return cases.with_suffix(".sha256")


def result_line(case_id: str, model: str, repo: str, revision: str, run: int,
                output: str, finish: str | None, cases_sha256: str, domain: str | None = None) -> dict:
    """결과 파일 한 줄. 코랩 노트북도 같은 키로 쓴다(계획 파일 구조 절)."""
    line = {"case_id": case_id, "model": model, "repo": repo, "revision": revision, "run": run,
            "output": output, "finish": finish, "cases_sha256": cases_sha256}
    if domain is not None:
        # v2 시험지는 문항마다 분야를 적는다(v2 스펙 8-3절). 앞 실험의 줄 모양은 그대로 두려고 있을 때만 넣는다.
        line["domain"] = domain
    return line
```

`run_all` 의 머리와 경로를 쓰는 줄을 바꾼다.

```python
def run_all(limit: int | None, cases: Path = CASES, results_dir: Path = RESULTS_DIR) -> int:
    expected = sha_path(cases).read_text(encoding="utf-8").split()[0]
    actual = sha256_file(cases)
    if actual != expected:
        print(f"시험지 해시가 다릅니다: 파일 {actual} / 기록 {expected}. "
              f"시험지를 만든 도구(tools.judge5_export cases 또는 tools.judge5v2_export final)를 다시 실행하세요.")
        return 1
    results_dir.mkdir(parents=True, exist_ok=True)
    out = results_dir / f"{MODEL_KEY}_run{RUN}.jsonl"
    failures = results_dir / f"{MODEL_KEY}_failures.jsonl"
```

이제 `CASES_SHA` 를 쓰는 곳이 없으므로 import 줄을 `from .judge5_export import CASES, RESULTS_DIR` 로 바꾼다. 함수 안의 `CASES.read_text` 를 `cases.read_text` 로, `result_line(...)` 호출을 아래로 바꾼다.

```python
        line = result_line(r["case_id"], MODEL_KEY, MODELS[MODEL_KEY], "cloudflare", RUN, text, finish, actual,
                           r.get("domain"))
```

`main` 을 둘로 나눈다.

```python
def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="M1(Cloudflare)으로 시험지를 채점한다")
    p.add_argument("--smoke", action="store_true", help="가짜 사례 하나로 연결만 확인한다")
    p.add_argument("--limit", type=int, default=None, help="이번 실행에서 부를 최대 사례 수")
    # 기본값을 앞 실험 경로로 두는 이유: 앞 실험을 같은 명령으로 다시 돌릴 수 있어야 한다(v2 스펙 8-3절).
    p.add_argument("--cases", type=Path, default=CASES, help="시험지 파일. 해시 파일은 같은 폴더의 cases.sha256")
    p.add_argument("--results-dir", type=Path, default=RESULTS_DIR, help="결과를 쓸 폴더")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return smoke() if args.smoke else run_all(args.limit, args.cases, args.results_dir)
```

- [ ] **Step 4: 점검이 통과하는지 본다**

Run: `$PY -m tools.judge5_check | tail -1`
Expected: `44가지 전부 통과.`

- [ ] **Step 5: 커밋한다**

```bash
git add ai-service/tools/judge5_cloudflare.py ai-service/tools/judge5_check.py
git commit -m "feat: judge5_cloudflare 가 시험지와 결과 폴더를 인자로 받고 분야를 결과 줄에 옮긴다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/tools/judge5_cloudflare.py ai-service/tools/judge5_check.py
```

**리뷰 포인트:** 인자 없이 부를 때 앞 실험의 경로와 줄 모양(도메인 키 없음)이 그대로인가. 해시 불일치나 다른 시험지 줄이 섞였을 때 부르기 전에 멈추는 동작이 새 경로에서도 살아 있는가.

---

### Task 4: 검색 도구

**Files:**
- Create: `ai-service/tools/judge5v2_search.py`
- Create: `ai-service/tools/judge5v2_search_check.py`

**Interfaces:**
- Consumes: 태스크 1 의 `BOTS`, `DOMAINS`, `PROTECTED_BOTS`, `QUESTIONS`, `RETRIEVED`, `SETTLED_DROPS`, `append_jsonl`, `read_json`, `read_jsonl`, `latest_by_qid`. 서비스의 `app.config.Settings`(기본값), `retriever.search`, `retriever.embed_one`, `retriever.fetch_contents`, `app.db.cursor`, `app.cf.neurons_used`
- Produces: `search_one(bot_id: int, question: str, *, embed=None, search=None, fetch=None, top1=None) -> dict` (형식 2 의 `status`, `drop_reason`, `top1_distance`, `warnings`, `sources`), `drop_reason(n_sources: int, top1: float | None, answerable: float | None) -> str | None`, `warning_reason(messages: list[str]) -> str | None`, `parse_bots(items: list[str]) -> dict[str, int]`, `search_settings() -> dict`, `nondefault_settings(current: dict) -> dict[str, dict]`, `check_bots_file(bots: dict[str, int], recorded: dict) -> None`, `settled_qids(rows: list[dict]) -> set[str]`. 명령 `python -m tools.judge5v2_search --bot hr=N --bot shop=N --bot manual=N --bot finance=N [--limit K] [--allow-nondefault]`. 검색 설정이 기본값과 다르거나 `--bot` 이 `bots.json` 과 다르면 종료 코드 1 로 멈춘다(`e228b67`)

- [ ] **Step 1: 실패하는 점검을 쓴다** (`judge5v2_search_check.py`)

```python
"""tools.judge5v2_search 의 점검. DB 도 외부 API 도 쓰지 않는다(가짜 함수를 넣는다).

실행:  cd ai-service && python -m tools.judge5v2_search_check

이 도구가 틀리면 시험지에 서비스와 다른 근거가 들어간다. 앞 200자만 담기거나, 리랭커가 실패한 순서가
리랭커를 켠 설정으로 적히거나, 임베딩을 두 번 불러 뉴런을 두 배로 쓴다. 셋 다 결과 숫자로는 드러나지 않는다.
"""
from __future__ import annotations

import contextlib
import io
import json
import logging
import tempfile
from pathlib import Path
from unittest import mock

from app import retriever
from app.schemas import Source

from . import judge5v2_search
from .judge5v2_search import (
    SETTING_KEYS, check_bots_file, drop_reason, nondefault_settings, parse_bots, search_one, search_settings,
    settings_conflicts, settled_qids, warning_reason,
)


def _src(cid: int) -> Source:
    return Source(chunk_id=cid, document_id=1, filename=f"{cid}.md", score=0.9, preview="앞 200자")


def _fakes(sources: list[Source], warn: str | None = None, d1: float | None = 0.2,
           contents: dict | None = None) -> tuple[dict, dict]:
    calls = {"embed": 0}

    def embed(q: str) -> list[float]:
        calls["embed"] += 1
        return [0.5]

    def search(bot_id: int, q: str) -> list[Source]:
        # 실제 search 처럼 모듈의 embed_one 을 부른다. 바꿔 끼운 함수가 미리 만든 벡터를 돌려줘야 한다.
        assert retriever.embed_one(q) == [0.5]
        if warn:
            logging.getLogger("app.retriever").warning(warn)
        return sources

    def fetch(ids: list[int]) -> dict:
        return contents if contents is not None else {i: f"전문 {i}" for i in ids}

    return calls, {"embed": embed, "search": search, "fetch": fetch, "top1": lambda bot_id, vec: d1}


def check_search_one_returns_full_content() -> None:
    """시험지에는 앞 200자가 아니라 전문이 들어간다(스펙 2-3절)."""
    calls, f = _fakes([_src(1), _src(2)])
    row = search_one(9, "질문", **f)
    assert row["status"] == "ok" and row["drop_reason"] is None
    assert [s["content"] for s in row["sources"]] == ["전문 1", "전문 2"]
    assert [s["filename"] for s in row["sources"]] == ["1.md", "2.md"]
    assert calls["embed"] == 1          # 임베딩은 한 번만 부른다


def check_search_one_restores_embed_one() -> None:
    """embed_one 을 바꿔 끼운 것이 검색 뒤에 남으면 다음 질문이 앞 질문의 벡터로 검색된다."""
    original = retriever.embed_one
    _, f = _fakes([_src(1)])
    search_one(9, "질문", **f)
    assert retriever.embed_one is original


def check_rerank_failure_drops_question() -> None:
    _, f = _fakes([_src(1), _src(2)], warn="리랭킹 실패(원래 순서 유지) provider=cloudflare: HTTPError: 500")
    row = search_one(9, "질문", **f)
    assert row["status"] == "dropped" and row["drop_reason"] == "rerank_failed"
    assert row["warnings"] and row["sources"]   # 근거는 남겨 둔다. 왜 뺐는지 나중에 볼 수 있게


def check_keyword_failure_drops_question() -> None:
    _, f = _fakes([_src(1), _src(2)], warn="키워드 검색 실패(벡터 결과만 사용): OperationalError: x")
    assert search_one(9, "질문", **f)["drop_reason"] == "keyword_failed"


def check_empty_result_reasons() -> None:
    """빈 결과의 원인을 둘로 가른다(스펙 2-3절). 청크가 아예 없으면 원인이 아니라 준비 실수라서 멈춘다."""
    assert drop_reason(0, 0.99, 0.44) == "answerable"
    assert drop_reason(0, 0.30, 0.44) == "max_distance"
    assert drop_reason(2, 0.99, 0.44) is None
    try:
        drop_reason(0, None, 0.44)
    except RuntimeError:
        return
    raise AssertionError("청크가 없는 봇은 멈춰야 한다")


def check_missing_content_is_an_error() -> None:
    """검색이 돌려준 청크의 본문을 못 읽으면 앞 200자로 대신하지 않고 멈춘다."""
    _, f = _fakes([_src(1)], contents={})
    try:
        search_one(9, "질문", **f)
    except RuntimeError:
        return
    raise AssertionError("본문이 없으면 멈춰야 한다")


def check_parse_bots_refuses_protected() -> None:
    assert parse_bots(["hr=12", "shop=13"]) == {"hr": 12, "shop": 13}
    for bad in (["hr=1"], ["hr=7"], ["hr=8"], ["sales=12"], ["hr=x"]):
        try:
            parse_bots(bad)
        except SystemExit:
            continue
        raise AssertionError(bad)


def check_parse_bots_refuses_duplicates() -> None:
    """같은 분야를 두 번, 같은 번호를 두 분야에 주면 거절한다. answerable 판정은 다시 검색하지 않아 굳기 때문이다."""
    for bad in (["hr=12", "hr=13"], ["hr=12", "shop=12"]):
        try:
            parse_bots(bad)
        except SystemExit:
            continue
        raise AssertionError(bad)


def check_bots_file_must_match() -> None:
    recorded = {"hr": 12, "shop": 13, "manual": 14, "finance": 15}
    check_bots_file({"hr": 12, "shop": 13}, recorded)                    # 일부 분야만 줘도 된다
    for bad in ({"hr": 13}, {"shop": 12}, {"hr": 12, "manual": 99}):
        try:
            check_bots_file(bad, recorded)
        except SystemExit:
            continue
        raise AssertionError(bad)


def check_nondefault_settings_compares_with_config_defaults() -> None:
    """기준은 config.py 의 기본값이다. 셸에 남은 RERANKER_PROVIDER=local_int8 같은 값을 잡아야 한다."""
    from app.config import Settings
    defaults = {k: Settings.model_fields[k].get_default(call_default_factory=True) for k in SETTING_KEYS}
    # 스펙 2-3절이 글로 정한 값을 직접 못박는다. config.py 의 기본값이 바뀌면 위 비교는 따라 바뀌지만 이 줄은 실패한다.
    assert defaults["hybrid_enabled"] is True and defaults["reranker_enabled"] is True
    assert defaults["reranker_provider"] == "cloudflare"
    assert nondefault_settings(defaults) == {}
    changed = dict(defaults, reranker_provider="local_int8", top_k=8)
    assert nondefault_settings(changed) == {
        "reranker_provider": {"default": "cloudflare", "actual": "local_int8"},
        "top_k": {"default": defaults["top_k"], "actual": 8},
    }


def check_settings_conflicts_refuses_mixed_runs() -> None:
    """--allow-nondefault 로 뽑은 줄이 있으면 기본 설정으로 다시 돌릴 때 멈춘다. 같은 설정이면 통과한다."""
    now = search_settings()
    same = [{"qid": "a", "settings": dict(now)}, {"qid": "b", "settings": dict(now)}]
    assert settings_conflicts(same, now) == []
    mixed = same + [{"qid": "c", "settings": dict(now, reranker_provider="local_int8")}]
    got = settings_conflicts(mixed, now)
    assert len(got) == 1 and got[0].startswith("c: reranker_provider('local_int8' -> ")
    assert settings_conflicts([{"qid": "d", "settings": {}}], now)       # 설정이 비어 있는 줄도 다른 설정이다


def check_main_stops_on_mixed_settings_before_searching() -> None:
    """main 이 실제로 settings_conflicts 를 부르는가. 다른 설정의 줄이 섞인 파일이면 검색 전에 종료 코드 1 로 멈춘다.

    search_one 은 부르면 실패하는 가짜로 바꾼다. 멈추지 않고 검색으로 넘어가면 이 점검이 그 자리에서 실패한다.
    --allow-nondefault 를 줘도 멈춰야 한다(그 인자는 지금 설정을 허락할 뿐, 섞이는 것을 허락하지 않는다).
    """
    now = search_settings()

    def must_not_search(*_a, **_k):
        raise AssertionError("설정이 섞였는데 검색까지 갔다")

    for extra in ([], ["--allow-nondefault"]):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "bots.json").write_text(json.dumps({"hr": 12}), encoding="utf-8")
            (d / "q.jsonl").write_text(json.dumps({"qid": "hr-001", "domain": "hr", "question": "질문"}) + "\n",
                                       encoding="utf-8")
            rows = [{"qid": "hr-002", "settings": dict(now, reranker_provider="local_int8"),
                     "status": "ok", "drop_reason": None}]
            (d / "r.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
            out = io.StringIO()
            with mock.patch.multiple(judge5v2_search, BOTS=d / "bots.json", QUESTIONS=d / "q.jsonl",
                                     RETRIEVED=d / "r.jsonl", search_one=must_not_search), \
                    contextlib.redirect_stdout(out):
                code = judge5v2_search.main(["--bot", "hr=12", "--limit", "0", *extra])
        assert code == 1 and "다른 검색 설정" in out.getvalue(), (extra, code, out.getvalue())


def check_warning_reason_prefers_rerank() -> None:
    assert warning_reason([]) is None
    assert warning_reason(["키워드 검색 실패(...)", "리랭킹 실패(...)"]) == "rerank_failed"


def check_settled_qids_retries_call_failures() -> None:
    """호출 실패로 버린 질문은 끝난 것으로 보지 않는다(계획 형식 2). 다시 검색해 성공하면 마지막 줄이 판정이다."""
    def row(qid: str, reason: str | None) -> dict:
        return {"qid": qid, "status": "ok" if reason is None else "dropped", "drop_reason": reason}

    rows = [row("a", None), row("b", "answerable"), row("c", "max_distance"),
            row("d", "rerank_failed"), row("e", "keyword_failed"), row("f", "rerank_failed"), row("f", None)]
    assert settled_qids(rows) == {"a", "b", "c", "f"}


CHECKS = [
    check_search_one_returns_full_content,
    check_search_one_restores_embed_one,
    check_rerank_failure_drops_question,
    check_keyword_failure_drops_question,
    check_empty_result_reasons,
    check_missing_content_is_an_error,
    check_parse_bots_refuses_protected,
    check_parse_bots_refuses_duplicates,
    check_bots_file_must_match,
    check_nondefault_settings_compares_with_config_defaults,
    check_settings_conflicts_refuses_mixed_runs,
    check_main_stops_on_mixed_settings_before_searching,
    check_warning_reason_prefers_rerank,
    check_settled_qids_retries_call_failures,
]


def main() -> None:
    for fn in CHECKS:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(CHECKS)}가지 전부 통과.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 점검이 실패하는지 본다**

Run: `cd /Users/cheonjamin/projects/AllDap-judge-v2/ai-service && $PY -m tools.judge5v2_search_check`
Expected: `ModuleNotFoundError: No module named 'tools.judge5v2_search'`

- [ ] **Step 3: 검색 도구를 쓴다** (`judge5v2_search.py`)

```python
"""채점 모델 비교 v2 의 검색 도구. 질문마다 근거 청크를 실제 검색으로 뽑는다(스펙 2-3절).

실행:
    cd ai-service
    $PY -m tools.judge5v2_search --bot hr=12 --bot shop=13 --bot manual=14 --bot finance=15

입력은 testdata/judge5v2/questions.jsonl, 출력은 testdata/judge5v2/retrieved.jsonl 이다.
판정이 정해진 질문(ok, answerable, max_distance)은 건너뛴다. 뉴런을 다시 쓰지 않기 위해서다.
호출 실패(rerank_failed, keyword_failed)로 버린 질문은 다시 검색하고, 새 줄을 덧붙인다(계획 형식 2).

서비스 코드(app/)는 고치지 않는다. 대신 세 가지를 바깥에서 한다.
1. 질문 임베딩을 한 번만 만든다. search 안의 embed_one 을 그 벡터를 돌려주는 함수로 잠시 바꾼다.
   가장 가까운 청크의 거리를 따로 재는 데도 같은 벡터를 쓴다. 임베딩을 두 번 부르면 뉴런이 두 배다.
2. 리랭커와 키워드 검색의 실패 경고를 붙잡는다. 둘 다 실패해도 search 는 결과를 돌려주므로,
   경고를 보지 않으면 설정과 다른 순서의 근거가 시험지에 들어간다.
3. search 가 돌려준 앞 200자(preview)가 아니라 fetch_contents 로 전문을 읽는다.

검색 전에 두 가지를 확인하고 다르면 멈춘다.
- 검색 설정이 config.py 의 기본값과 같은가(스펙 2-3절의 "기본 설정 그대로"). 셸에 RERANKER_PROVIDER=local_int8
  같은 값이 남아 있으면 시험지에는 Cloudflare 리랭커로 뽑았다고 적히지만 실제는 다르다. 기본값과 다르게
  돌려야 하면 --allow-nondefault 를 주고, 그때는 결과 줄마다 다른 값을 nondefault 에 남긴다.
- --bot 의 분야와 번호가 testdata/judge5v2/bots.json(E1 이 만든 기록)과 같은가. answerable 로 버린 질문은
  다시 검색하지 않으므로, 분야와 봇을 잘못 짝지은 결과는 다시 돌려도 고쳐지지 않는다.
"""
from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter
from unittest import mock

from app import cf, retriever
from app.config import Settings, get_settings
from app.db import cursor

from .judge5v2_files import (
    BOTS, DOMAINS, PROTECTED_BOTS, QUESTIONS, RETRIEVED, SETTLED_DROPS, append_jsonl, latest_by_qid, read_json,
    read_jsonl,
)

# 시험지에 적을 검색 설정(스펙 2-3절). 검색 결과를 바꾸는 값만 고른다.
# rerank_fusion_k 는 rerank_fusion 이 꺼져 있으면 쓰이지 않는다. 그래도 적는다. 켜면 순서를 바꾸는 값이기 때문이다.
SETTING_KEYS = (
    "top_k", "max_distance", "answerable_max_distance", "reranker_enabled", "reranker_provider",
    "reranker_model", "rerank_candidates", "rerank_fusion", "rerank_fusion_k", "hybrid_enabled",
    "hybrid_candidates", "hybrid_rrf_k", "embedding_model",
)
# app/retriever.py 의 경고 문장 첫머리. 서비스 코드의 문장이 바뀌면 search_check 가 아니라 실제 실행에서만
# 드러나므로, 실행 태스크 E3 이 리랭커 실패 수를 run_log.md 에 적어 둔다.
RERANK_FAIL = "리랭킹 실패"
KEYWORD_FAIL = "키워드 검색 실패"


def search_settings() -> dict:
    s = get_settings()
    return {k: getattr(s, k) for k in SETTING_KEYS}


def nondefault_settings(current: dict) -> dict[str, dict]:
    """current(search_settings 의 결과) 중 config.py 의 기본값과 다른 값. {키: {"default": 기본값, "actual": 실제 값}}.

    기준을 config.py 의 기본값으로 둔 이유: 스펙 2-3절의 "기본 설정" 은 서비스의 기본값이다. .env 가 같은 값을
    다시 적는 것(TOP_K=5 등)은 통과하고, 셸 환경변수든 .env 든 기본값과 다르면 출처와 관계없이 걸린다.
    get_default(call_default_factory=True) 는 Settings 클래스에 적힌 기본값이다(환경변수를 읽기 전의 값).
    .default 대신 쓰는 이유: 기본값을 default_factory(함수)로 적은 필드는 .default 가 빈 표시값이라 늘 다르다고 나온다.
    """
    out = {}
    for k, v in current.items():
        default = Settings.model_fields[k].get_default(call_default_factory=True)
        if v != default:
            out[k] = {"default": default, "actual": v}
    return out


def settings_conflicts(rows: list[dict], current: dict) -> list[str]:
    """이미 있는 검색 줄 중 지금 설정과 다른 설정으로 뽑은 줄. "qid: 키(줄의 값 -> 지금 값)" 목록이다.

    판정이 정해진 질문(settled_qids)은 다시 검색하지 않는다. 그래서 --allow-nondefault 로 끝낸 질문이 있으면
    기본 설정으로 다시 돌려도 그 질문은 건너뛰어져, 한 파일에 서로 다른 설정의 근거가 섞인다. 섞이기 전에 멈춘다.
    """
    out = []
    for r in rows:
        got = r.get("settings") or {}
        keys = [k for k in current if got.get(k) != current[k]]
        if keys:
            out.append(f"{r['qid']}: " + ", ".join(f"{k}({got.get(k)!r} -> {current[k]!r})" for k in keys))
    return out


def check_bots_file(bots: dict[str, int], recorded: dict) -> None:
    """--bot 으로 받은 짝이 bots.json 의 기록과 같은지 본다. 다르면 멈춘다."""
    wrong = [f"{d}={n}(기록은 {recorded.get(d)})" for d, n in bots.items() if recorded.get(d) != n]
    if wrong:
        raise SystemExit(f"--bot 이 testdata/judge5v2/bots.json 과 다릅니다: {', '.join(wrong)}. "
                         f"bots.json 의 번호를 그대로 주세요(계획 E3 Step 1 의 BOTS 변수).")


def drop_reason(n_sources: int, top1: float | None, answerable: float | None) -> str | None:
    """빈 결과의 원인. 결과가 있으면 None 이다(스펙 2-3절).

    search 는 가장 가까운 청크가 answerable 보다 멀면 빈 목록을 돌려준다(근거 유무 판정). 그게 아니면서
    비었다면 모든 청크가 max_distance 컷에 걸린 것이다(검색용 컷).
    """
    if n_sources > 0:
        return None
    if top1 is None:
        raise RuntimeError("봇에 임베딩된 청크가 없습니다. 업로드가 끝났는지(documents.status 가 ready 인지) 확인하세요.")
    if answerable is not None and top1 > answerable:
        return "answerable"
    return "max_distance"


def warning_reason(messages: list[str]) -> str | None:
    if any(m.startswith(RERANK_FAIL) for m in messages):
        return "rerank_failed"
    if any(m.startswith(KEYWORD_FAIL) for m in messages):
        return "keyword_failed"
    return None


class _Catch(logging.Handler):
    """app.retriever 로거의 경고를 모은다. logging.Handler 를 상속하면 로거에 붙여 기록을 받을 수 있다."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())   # getMessage 는 %s 자리에 인자를 채운 문장이다


def top1_distance(bot_id: int, qvec: list[float]) -> float | None:
    """그 봇에서 가장 가까운 청크의 벡터 거리. 빈 결과의 원인을 가르는 데만 쓴다."""
    with cursor() as cur:
        cur.execute(
            "SELECT min(c.embedding <=> %s::vector) FROM chunks c "
            "WHERE c.bot_id = %s AND c.embedding IS NOT NULL",
            (qvec, bot_id),
        )
        v = cur.fetchone()[0]
    return None if v is None else float(v)


def search_one(bot_id: int, question: str, *, embed=None, search=None, fetch=None, top1=None) -> dict:
    """질문 하나를 검색해 형식 2 의 뒷부분(status 부터 sources 까지)을 돌려준다.

    embed, search, fetch, top1 은 점검에서 가짜를 넣으려고 받는다. None 이면 서비스의 함수를 쓴다.
    기본값을 인자 기본값(embed=retriever.embed_one)으로 두지 않는 이유: 그러면 모듈을 불러온 시점의 함수가
    고정돼, 아래에서 embed_one 을 바꿔 끼운 것과 섞일 수 있다.
    """
    embed = embed or retriever.embed_one
    search = search or retriever.search
    fetch = fetch or retriever.fetch_contents
    top1 = top1 or top1_distance
    s = get_settings()

    vec = embed(question)
    catch = _Catch()
    log = logging.getLogger("app.retriever")   # retriever.py 의 _log 와 같은 이름(__name__)이다
    log.addHandler(catch)
    try:
        # mock.patch.object(모듈, 이름, 값): with 블록 안에서만 모듈의 이름을 바꿔 끼우고 끝나면 되돌린다.
        # search 는 안에서 embed_one(query) 를 부르므로, 이렇게 하면 임베딩을 다시 부르지 않는다.
        with mock.patch.object(retriever, "embed_one", lambda _q: vec):
            sources = search(bot_id, question)
    finally:
        log.removeHandler(catch)

    d1 = top1(bot_id, vec)
    reason = warning_reason(catch.messages) or drop_reason(len(sources), d1, s.answerable_max_distance)
    contents = fetch([x.chunk_id for x in sources])
    lost = [x.chunk_id for x in sources if x.chunk_id not in contents]
    if lost:
        raise RuntimeError(f"검색이 돌려준 청크 {lost} 의 본문을 읽지 못했습니다. 검색 도중 문서가 지워졌는지 확인하세요.")
    return {
        "status": "ok" if reason is None else "dropped",
        "drop_reason": reason,
        "top1_distance": d1,
        "warnings": catch.messages,
        "sources": [{"chunk_id": x.chunk_id, "filename": x.filename, "content": contents[x.chunk_id]} for x in sources],
    }


def settled_qids(rows: list[dict]) -> set[str]:
    """판정이 정해진 질문. 질문마다 마지막 줄을 보고, ok 이거나 다시 해도 같은 원인으로 버린 질문만 넣는다."""
    return {r["qid"] for r in latest_by_qid(rows) if r["status"] == "ok" or r["drop_reason"] in SETTLED_DROPS}


def parse_bots(items: list[str]) -> dict[str, int]:
    """--bot hr=12 꼴을 {"hr": 12} 로 바꾼다. 보호한 봇 번호, 같은 분야를 두 번, 같은 번호를 두 분야에 준 것을 거절한다."""
    out: dict[str, int] = {}
    for item in items:
        domain, _, num = item.partition("=")   # partition 은 첫 "=" 에서 셋으로 자른다
        if domain not in DOMAINS or not num.isdigit():
            raise SystemExit(f"--bot 은 분야=번호 꼴입니다(예: hr=12). 분야는 {', '.join(DOMAINS)}. 받은 값: {item}")
        bot_id = int(num)
        if bot_id in PROTECTED_BOTS:
            raise SystemExit(f"봇 {bot_id}번은 이 실험에서 쓰지 않습니다(데모 봇과 리랭커 실험 봇). "
                             f"testdata/judge5v2/bots.json 의 번호를 주세요.")
        if domain in out:
            raise SystemExit(f"--bot 에 분야 {domain} 이 두 번 있습니다. 분야마다 한 번씩 주세요.")
        if bot_id in out.values():
            raise SystemExit(f"봇 {bot_id}번이 두 분야에 있습니다. 분야마다 다른 봇입니다(스펙 2-2절).")
        out[domain] = bot_id
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="질문마다 실제 검색으로 근거 청크 전문을 뽑는다")
    p.add_argument("--bot", action="append", required=True, help="분야=봇 번호. 분야마다 한 번씩")
    p.add_argument("--limit", type=int, default=None, help="이번 실행에서 검색할 최대 질문 수")
    p.add_argument("--allow-nondefault", action="store_true",
                   help="검색 설정이 기본값과 달라도 돌린다. 다른 값은 결과 줄의 nondefault 에 남는다. "
                        "이미 다른 설정의 줄이 retrieved.jsonl 에 있으면 이 인자를 줘도 멈춘다")
    args = p.parse_args(argv)
    bots = parse_bots(args.bot)
    if not BOTS.exists():
        print("testdata/judge5v2/bots.json 이 없습니다. 계획 E1 이 봇을 만들고 남기는 파일입니다. E1 을 먼저 하세요.")
        return 1
    check_bots_file(bots, read_json(BOTS))
    settings = search_settings()
    diff = nondefault_settings(settings)
    if diff and not args.allow_nondefault:
        print("검색 설정이 config.py 의 기본값과 다릅니다(스펙 2-3절은 기본 설정 그대로 검색한다):")
        for k, d in diff.items():
            print(f"  - {k}: 기본값 {d['default']!r}, 지금 {d['actual']!r}")
        print("셸에 남은 환경변수(예: RERANKER_PROVIDER)나 .env 를 확인하세요. "
              "일부러 다르게 돌리려면 --allow-nondefault 를 주고 run_log.md 에 이유를 적으세요.")
        return 1
    if diff:
        print("기본값과 다른 설정으로 돌립니다(--allow-nondefault). 결과 줄마다 nondefault 에 남깁니다: "
              + ", ".join(f"{k}={d['actual']!r}" for k, d in diff.items()))

    questions = read_jsonl(QUESTIONS)
    ids = [q["qid"] for q in questions]
    dup = [k for k, n in Counter(ids).items() if n > 1]
    if dup:
        print(f"questions.jsonl 에 같은 qid 가 두 번 있습니다: {dup[:5]}. 고친 뒤 다시 실행하세요.")
        return 1
    existing = read_jsonl(RETRIEVED)
    if conflicts := settings_conflicts(existing, settings):
        print(f"retrieved.jsonl 에 지금과 다른 검색 설정으로 뽑은 줄이 {len(conflicts)}개 있습니다. 섞이지 않게 멈춥니다:")
        for c in conflicts[:10]:
            print(f"  - {c}")
        print("설정을 그 줄들과 같게 맞추세요. 줄을 옮기거나 지우려면 그 전에 오케스트레이터에 알리세요. "
              "옮기면 그 질문들을 다시 검색해 뉴런을 쓰고, 배정(E5) 뒤라면 배정 점검이 깨집니다.")
        return 1
    done = settled_qids(existing)
    todo = [q for q in questions if q["domain"] in bots and q["qid"] not in done][: args.limit]
    # 기본값과 다르게 돌린 실행은 줄마다 표시한다. 나중에 이 줄로 만든 문항이 기본 설정이 아니었음을 알 수 있게.
    extra = {"nondefault": diff} if diff else {}
    counts: Counter = Counter()
    for q in todo:
        row = search_one(bots[q["domain"]], q["question"])
        append_jsonl(RETRIEVED, {"qid": q["qid"], "domain": q["domain"], "bot_id": bots[q["domain"]],
                                 "settings": settings, **extra, **row})
        counts[(q["domain"], row["drop_reason"] or "ok")] += 1
    for (domain, reason), n in sorted(counts.items()):
        print(f"{domain}: {reason} {n}")
    print(f"이번 실행의 뉴런: {cf.neurons_used()}")
    rows = read_jsonl(RETRIEVED)
    tried, done = {r["qid"] for r in rows}, settled_qids(rows)
    mine = [q["qid"] for q in questions if q["domain"] in bots]
    never = sum(1 for qid in mine if qid not in tried)
    failed = sum(1 for qid in mine if qid in tried and qid not in done)
    if failed:
        # 종료 코드를 1 로 하지 않는다. 다시 해도 실패하면 그 줄이 판정이 되기 때문이다(계획 E3 Step 3).
        print(f"호출 실패로 버린 질문 {failed}개. 같은 명령을 다시 실행하면 그 질문만 다시 검색합니다.")
    if never:
        print(f"아직 검색하지 않은 질문 {never}개. 같은 명령을 다시 실행하면 이어서 합니다.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 점검이 통과하는지 본다**

Run: `$PY -m tools.judge5v2_search_check | tail -1`
Expected: `14가지 전부 통과.` (처음 계획은 9가지. `e228b67` 이 셋, `4980edf` 와 `217048d` 가 하나씩 더했다)

- [ ] **Step 5: 커밋한다**

```bash
git add ai-service/tools/judge5v2_search.py ai-service/tools/judge5v2_search_check.py
git commit -m "feat: 채점 모델 비교 v2 의 근거 청크를 실제 검색으로 뽑는 도구를 추가한다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/tools/judge5v2_search.py ai-service/tools/judge5v2_search_check.py
```

**리뷰 포인트:** `RERANK_FAIL`, `KEYWORD_FAIL` 이 `app/retriever.py` 의 실제 경고 문장 첫머리와 같은가(`grep -n '리랭킹 실패\|키워드 검색 실패' ai-service/app/retriever.py`). 질문 하나에 임베딩을 정확히 한 번 부르는가. 호출 실패로 버린 줄을 끝난 것으로 세지 않는가.

---

### Task 5: 배정 도구

**Files:**
- Create: `ai-service/tools/judge5v2_assign.py`
- Create: `ai-service/tools/judge5v2_assign_check.py`

**Interfaces:**
- Consumes: 태스크 1 의 상수와 읽고 쓰기 함수(`latest_by_qid`, `value_in` 포함), `judge5.sha256_file`
- Produces:
  - `eligible3(q)`, `eligible4(q)`, `eligible6(q)`, `eligible8(q)` (자격 조건, 모두 `-> bool`)
  - `assign_domain(pool: list[dict], needs: dict[int, int], rng: random.Random) -> tuple[dict, dict[int, int]]`. 앞 값은 `{"types": {qid: 유형}, "unused": [qid...], "eighth_to_sixth": int}`, 뒤 값은 모자란 유형과 수(③, ④, ⑥, 그리고 남은 질문이 모자란 유형).
  - `run_round(pools: dict[str, list[dict]], needs: dict[str, dict[int, int]], seed: int, no: int) -> dict[str, dict]` (모자라면 `Shortfall`)
  - `replay_round(rnd: dict, questions_by_id: dict[str, dict], seed: int, no: int) -> dict[str, dict]`
  - `assigned_types(assignment: dict) -> dict[str, int]` (모든 회차를 합친 qid 별 유형)
  - `pool_for(questions: list[dict], retrieved: list[dict], excluded: dict | None = None) -> dict[str, list[dict]]` (`excluded` 는 `excluded.json` 의 내용. `a0557d2`)
  - `valid_contrast(contrast: dict, sources: list[dict]) -> str | None`
  - `supplement_needs(assignment: dict, dropped_qids: set[str], domain_of: dict[str, str]) -> dict[str, dict[int, int]]`
  - `supplement_pools(pools: dict[str, list[dict]], assignment: dict) -> dict[str, list[dict]]` (보충 후보. 앞 회차에서 유형을 받은 질문을 빼고, 받지 않은 질문과 새 질문은 남긴다. `f17877a`)
  - `class Shortfall(Exception)` with `.short: dict[str, dict[int, int]]`
  - 명령 `python -m tools.judge5v2_assign first`, `python -m tools.judge5v2_assign supplement`. 종료 코드: 0 배정함, 1 배정하지 못함(`first` 는 파일을 만들지 않고, `supplement` 는 파일을 고치지 않는다), 2 배정했지만 그 회차에서 ⑧ 을 ⑥ 으로 돌린 분야가 있다(파일은 남는다. `first` 는 E5 의 멈춤, `f17877a`. `supplement` 는 E10 의 멈춤, `d368ba5`)

- [ ] **Step 1: 실패하는 점검을 쓴다** (`judge5v2_assign_check.py`)

```python
"""tools.judge5v2_assign 의 점검. DB 도 외부 API 도 쓰지 않는다.

실행:  cd ai-service && python -m tools.judge5v2_assign_check

배정이 틀리면 정답 점수 분포가 스펙 7-1절과 달라지거나, 자격이 없는 질문에 ③, ④가 붙어
정답 점수가 하나로 정해지지 않는 문항이 생긴다(스펙 3-2절). 어느 쪽도 결과 숫자로는 드러나지 않는다.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import random
import tempfile
from collections import Counter
from pathlib import Path
from unittest import mock

from . import judge5v2_assign
from .judge5v2_assign import (
    Shortfall, assign_domain, assigned_types, pool_for, replay_round, run_round, supplement_needs, supplement_pools,
    valid_contrast,
)
from .judge5v2_files import DOMAINS, QUOTA, read_json, write_json, write_jsonl

_CONTRAST = {"asked": {"target": "골드", "value": "10,000원"}, "other": {"target": "실버", "value": "20,000원"},
             "chunk_ids": [1]}


def _pool(domain: str = "shop", n: int = 75, even: int = 20, odd3: int = 15, contrast_every: int = 7) -> list[dict]:
    """주장 2개 even 개, 주장 3개 odd3 개, 나머지는 주장 1개. 주장 2개짜리만 답이 두 가지인 질문(two_part)이다.
    답이 하나인 질문 중 contrast_every 번째마다 ⑧ 조건을 만족한다(⑧ 은 답이 하나인 질문에만 붙는다)."""
    out = []
    for i in range(n):
        claims = 2 if i < even else 3 if i < even + odd3 else 1
        two_part = i < even
        out.append({"qid": f"{domain}-{i:03d}", "domain": domain, "question": f"질문 {i}", "answer": f"답 {i}",
                    "claims": claims, "two_part": two_part,
                    "contrast": _CONTRAST if not two_part and i % contrast_every == 0 else None})
    return out


def check_assign_meets_quota_and_eligibility() -> None:
    res, short = assign_domain(_pool(), dict(QUOTA), random.Random("s"))
    assert short == {}
    assert Counter(res["types"].values()) == Counter(QUOTA)
    claims = {q["qid"]: q for q in _pool()}
    for qid, t in res["types"].items():
        c = claims[qid]["claims"]
        if t == 4:
            assert c >= 2 and c % 2 == 0, qid
        if t == 3:
            assert c >= 2, qid
        if t == 8:
            assert claims[qid]["contrast"] is not None, qid
        if t in (6, 8):
            assert not claims[qid]["two_part"], qid
    assert len(res["unused"]) == 75 - 60 and res["eighth_to_sixth"] == 0


def check_assign_is_reproducible_and_order_free() -> None:
    """같은 입력과 같은 시드면 같은 배정이다(스펙 3-3절). 입력 순서는 결과를 바꾸지 않는다."""
    a, _ = assign_domain(_pool(), dict(QUOTA), random.Random("s"))
    b, _ = assign_domain(_pool()[::-1], dict(QUOTA), random.Random("s"))
    c, _ = assign_domain(_pool(), dict(QUOTA), random.Random("다른 시드"))
    assert a == b and a != c


def check_assign_moves_missing_eighth_to_sixth() -> None:
    """⑧ 조건을 만족하는 질문이 모자라면 ⑥ 으로 채운다(스펙 3-3절 5). 둘 다 정답 점수가 1이다."""
    pool = _pool(contrast_every=10**6)           # ⑧ 조건을 만족하는 질문이 없다(0번은 답이 두 가지라 붙지 않는다)
    pool[60]["contrast"] = _CONTRAST             # 주장 1개라 ④, ③ 에 뽑히지 않는 답이 하나인 질문에 하나만 붙인다
    res, short = assign_domain(pool, dict(QUOTA), random.Random("s"))
    counts = Counter(res["types"].values())
    assert short == {} and counts[8] == 1 and counts[6] == QUOTA[6] + QUOTA[8] - 1
    assert res["eighth_to_sixth"] == QUOTA[8] - 1


def check_assign_sixth_and_eighth_need_single_answer() -> None:
    """⑥, ⑧ 은 답이 하나인 질문에만 붙는다(스펙 3-2절). 그런 질문이 모자라면 ⑥ 이 모자란다고 알린다(스펙 3-3절 5)."""
    pool = _pool()
    for i, q in enumerate(pool):
        q["two_part"], q["contrast"] = i < 65, None  # 답이 하나인 질문은 마지막 10개(65~74번, 주장 1개)뿐이다
    # 답이 두 가지인 질문의 contrast 는 ⑧ 자격이 아니다. 주장 1개인 질문(50번)에 붙인다. 주장 2개인 질문에 붙이면
    # ④ 가 먼저 가져갈 수 있어서, ⑧ 이 two_part 를 거절하지 않아도 이 점검이 통과해 버린다.
    pool[50]["contrast"] = _CONTRAST
    res, short = assign_domain(pool, dict(QUOTA), random.Random("s"))
    counts = Counter(res["types"].values())
    assert counts[8] == 0 and res["eighth_to_sixth"] == QUOTA[8]
    assert counts[6] == 10 and short == {6: QUOTA[6] + QUOTA[8] - 10}
    assert all(int(qid[-3:]) >= 65 for qid, t in res["types"].items() if t == 6)


def check_assign_reports_fourth_and_third_shortfall() -> None:
    """④, ③ 자격 질문이 모자라면 다른 유형으로 채우지 않고 모자란 수를 알린다(스펙 3-3절 4)."""
    _, short = assign_domain(_pool(even=5, odd3=0), dict(QUOTA), random.Random("s"))
    assert short[4] == QUOTA[4] - 5 and short[3] == QUOTA[3]
    try:
        run_round({d: _pool(d, even=5, odd3=0) for d in DOMAINS},
                  {d: dict(QUOTA) for d in DOMAINS}, 1, 0)
    except Shortfall as e:
        assert set(e.short) == set(DOMAINS)
        return
    raise AssertionError("모자라면 Shortfall 이어야 한다")


def check_replay_reproduces_round() -> None:
    pools = {d: _pool(d) for d in DOMAINS}
    needs = {d: dict(QUOTA) for d in DOMAINS}
    domains = run_round(pools, needs, 20261005, 0)
    rnd = {"pool": {d: [q["qid"] for q in pools[d]] for d in DOMAINS},
           "needs": {d: {str(t): n for t, n in QUOTA.items()} for d in DOMAINS}, "domains": domains}
    by_id = {q["qid"]: q for d in DOMAINS for q in pools[d]}
    assert replay_round(rnd, by_id, 20261005, 0) == domains


def check_supplement_needs_counts_only_drops() -> None:
    res, _ = assign_domain(_pool(), dict(QUOTA), random.Random("s"))
    empty = {"types": {}, "unused": [], "eighth_to_sixth": 0}
    assignment = {"seed": 1, "rounds": [{"domains": {"shop": res, "hr": empty, "manual": empty, "finance": empty}}]}
    fourth = sorted(q for q, t in res["types"].items() if t == 4)[:2]
    domain_of = {q: "shop" for q in res["types"]}
    needs = supplement_needs(assignment, set(fourth), domain_of)
    assert needs["shop"] == {t: (2 if t == 4 else 0) for t in QUOTA}
    assert needs["hr"] == QUOTA
    assert assigned_types(assignment) == res["types"]


def check_valid_contrast() -> None:
    """⑧ 조건은 두 값이 근거 청크에 글자 그대로 있고 서로 다를 때만이다(스펙 3-2절)."""
    src = [{"chunk_id": 1, "content": "골드 10,000원 / 실버 20,000원"}, {"chunk_id": 2, "content": "다른 내용"}]
    assert valid_contrast(_CONTRAST, src) is None
    same = {**_CONTRAST, "other": {"target": "실버", "value": "10,000원"}}
    assert valid_contrast(same, src) is not None                       # 값이 같다
    assert valid_contrast({**_CONTRAST, "chunk_ids": [2]}, src) is not None   # 그 청크에 값이 없다
    assert valid_contrast({**_CONTRAST, "chunk_ids": [9]}, src) is not None   # 근거 청크가 아니다
    near = [{"chunk_id": 1, "content": "골드 110,000원 / 실버 20,000원"}]
    assert valid_contrast(_CONTRAST, near) is not None   # 10,000원 은 110,000원 의 일부일 뿐이다(값 경계)
    number = {**_CONTRAST, "asked": {"target": "골드", "value": 10000}}
    assert "따옴표" in valid_contrast(number, src)       # 숫자로 적은 값은 TypeError 가 아니라 안내로 거절한다


def check_pool_for_uses_last_search_and_refuses_two_part_contrast() -> None:
    """검색 줄은 질문마다 마지막 줄이 판정이다(계획 형식 2). 답이 두 가지인 질문의 contrast 는 잘못 적은 것이다."""
    src = [{"chunk_id": 1, "content": "골드 10,000원 / 실버 20,000원"}]
    q = {"qid": "shop-001", "domain": "shop", "answer": "답", "claims": 1, "two_part": False, "contrast": _CONTRAST}
    tried = [{"qid": "shop-001", "status": "dropped", "drop_reason": "rerank_failed", "sources": src},
             {"qid": "shop-001", "status": "ok", "drop_reason": None, "sources": src}]
    assert [x["qid"] for x in pool_for([q], tried)["shop"]] == ["shop-001"]   # 다시 검색해 성공했다
    assert pool_for([q], tried[::-1])["shop"] == []                          # 마지막 시도가 호출 실패다
    for bad in (dict(q, two_part=True),                                      # 답이 두 가지인 질문의 contrast
                dict(q, contrast=None, claims=True)):                        # true 는 int 이기도 하지만 주장 수가 아니다
        try:
            pool_for([bad], tried)
        except ValueError:
            continue
        raise AssertionError(bad)


def check_assign_order_fourth_eighth_third_sixth() -> None:
    """뽑는 순서 ④ → ⑧ → ③ → ⑥ 을 고정한다(스펙 3-3절 3).

    ⑧ 자격 질문 6개가 모두 주장 3개다. ③ 이 ⑧ 보다 먼저 뽑으면 그중 일부를 ③ 으로 가져가 ⑧ 이 모자라고,
    ⑥ 이 ⑧ 보다 먼저 뽑으면 답이 하나인 질문 중에서 ⑧ 자격 질문을 가져간다. 어느 쪽이든 eighth_to_sixth 가 0 이 아니게 된다.
    """
    out = []
    for i in range(75):
        # 0~8: 주장 2, 답 두 가지(④ 몫) / 9~23: 주장 3, 답 하나(9~14 가 ⑧ 자격) / 24~30: 주장 1, 답 하나(⑥ 몫) / 나머지: 주장 1, 답 두 가지
        claims, two_part = (2, True) if i < 9 else (3, False) if i < 24 else (1, False) if i < 31 else (1, True)
        out.append({"qid": f"shop-{i:03d}", "domain": "shop", "answer": "답", "claims": claims, "two_part": two_part,
                    "contrast": _CONTRAST if 9 <= i < 15 else None})
    res, short = assign_domain(out, dict(QUOTA), random.Random("s"))
    assert short == {} and res["eighth_to_sixth"] == 0
    assert {q for q, t in res["types"].items() if t == 8} == {f"shop-{i:03d}" for i in range(9, 15)}
    assert {q for q, t in res["types"].items() if t == 6} == {f"shop-{i:03d}" for i in range(24, 31)}


def check_supplement_needs_with_eighth_moved_to_sixth() -> None:
    """⑧ 을 ⑥ 으로 돌린 회차 뒤의 보충은 돌린 ⑧ 을 다시 요구하지 않는다(스펙 3-3절 5, 7-2절 끝의 경우 2)."""
    pool = _pool(contrast_every=10**6)
    pool[60]["contrast"] = _CONTRAST                     # ⑧ 자격이 하나뿐이라 5개가 ⑥ 으로 간다
    res, _ = assign_domain(pool, dict(QUOTA), random.Random("s"))
    assert res["eighth_to_sixth"] == QUOTA[8] - 1
    empty = {"types": {}, "unused": [], "eighth_to_sixth": 0}
    assignment = {"seed": 1, "rounds": [{"domains": {"shop": res, "hr": empty, "manual": empty, "finance": empty}}]}
    domain_of = {q: "shop" for q in res["types"]}
    zero = {t: 0 for t in QUOTA}
    assert supplement_needs(assignment, set(), domain_of)["shop"] == zero
    sixth = sorted(q for q, t in res["types"].items() if t == 6)[0]
    eighth = next(q for q, t in res["types"].items() if t == 8)
    assert supplement_needs(assignment, {sixth}, domain_of)["shop"] == {**zero, 6: 1}
    assert supplement_needs(assignment, {eighth}, domain_of)["shop"] == {**zero, 8: 1}


def check_supplement_pools_skip_used_keep_unused() -> None:
    """보충 후보는 앞 회차에서 유형을 받은 질문을 빼고, 받지 않은 질문과 새 질문은 남긴다(스펙 7-2절)."""
    pool = _pool()
    res, _ = assign_domain(pool, dict(QUOTA), random.Random("s"))
    empty = {"types": {}, "unused": [], "eighth_to_sixth": 0}
    assignment = {"seed": 1, "rounds": [{"domains": {"shop": res, "hr": empty, "manual": empty, "finance": empty}}]}
    new = dict(pool[0], qid="shop-075")
    got = supplement_pools({"shop": pool + [new], "hr": []}, assignment)
    assert sorted(q["qid"] for q in got["shop"]) == sorted(res["unused"] + ["shop-075"])
    assert got["hr"] == []


def check_first_stops_with_code_2_when_eighth_moved() -> None:
    """⑧ 을 ⑥ 으로 돌린 분야가 있으면 first 는 파일을 남기고 종료 코드 2 로 멈춘다(계획 E5).
    질문 파일에 잘못된 줄이 있으면 traceback 이 아니라 한국어 안내와 종료 코드 1 이다."""
    src = [{"chunk_id": 1, "content": "골드 10,000원 / 실버 20,000원"}]

    def run(questions: list[dict]) -> tuple[int, bool]:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            # EXCLUDED 도 돌린다. 돌리지 않으면 실제 excluded.json 을 읽고, 가짜 질문 번호가 실제 제외 qid 와 겹친다.
            paths = {"ASSIGNMENT": d / "a.json", "QUESTIONS": d / "q.jsonl", "RETRIEVED": d / "r.jsonl",
                     "EXCLUDED": d / "x.json"}
            write_jsonl(paths["QUESTIONS"], questions)
            write_jsonl(paths["RETRIEVED"], [{"qid": q["qid"], "status": "ok", "sources": src} for q in questions])
            # mock.patch.multiple: 모듈 전역(경로 상수)을 with 블록 안에서만 바꾸고 끝나면 되돌린다.
            out = io.StringIO()
            with mock.patch.multiple(judge5v2_assign, **paths), contextlib.redirect_stdout(out):
                code = judge5v2_assign.cmd_first()
            if code == 2:
                assert "멈춘다: 계획 E5." in out.getvalue() and "git checkout" not in out.getvalue()
            return code, paths["ASSIGNMENT"].exists()

    assert run([q for d in DOMAINS for q in _pool(d)]) == (0, True)
    moved = [q for d in DOMAINS for q in _pool(d, contrast_every=10**6)]
    moved[60]["contrast"] = _CONTRAST
    assert run(moved) == (2, True)
    assert run([dict(q, claims=True) for d in DOMAINS for q in _pool(d)]) == (1, False)



def check_supplement_stops_with_code_2_when_eighth_moved() -> None:
    """보충 회차에서 ⑧ 을 ⑥ 으로 돌리면 supplement 도 회차를 덧붙인 뒤 종료 코드 2 로 멈춘다(스펙 7-2절 끝의 경우 2).

    재현: 검수에서 shop 의 ⑧ 두 문항을 버리고, shop 에 남은 질문의 contrast 를 지운 뒤 보충한다. 보충할 ⑧ 2개를
    채울 질문이 없어 ⑥ 으로 돌아간다. 같은 입력에서 contrast 를 남기면 ⑧ 으로 채워져 종료 코드 0 이다.
    """
    src = [{"chunk_id": 1, "content": "골드 10,000원 / 실버 20,000원"}]
    # contrast_every=3: 답이 하나인 질문의 셋에 하나가 ⑧ 자격이다. 회차 0 에서 쓰지 않은 질문에도 ⑧ 자격이 남아야
    # 대조(contrast 를 남긴 실행)에서 보충 ⑧ 을 채울 수 있다.
    questions = [q for d in DOMAINS for q in _pool(d, contrast_every=3)]
    pools = {d: [q for q in questions if q["domain"] == d] for d in DOMAINS}
    needs = {d: dict(QUOTA) for d in DOMAINS}
    rnd0 = {"round": 0, "pool": {d: [q["qid"] for q in pools[d]] for d in DOMAINS},
            "needs": {d: {str(t): n for t, n in QUOTA.items()} for d in DOMAINS},
            "domains": run_round(pools, needs, 20261005, 0)}
    eighth = sorted(q for q, t in rnd0["domains"]["shop"]["types"].items() if t == 8)[:2]
    key = {"stage": "draft", "cases": {f"c{i}": {"qid": q} for i, q in enumerate(eighth)}, "dropped": {}}
    review = [{"case_id": c, "review_score": 3, "user_decision": "drop", "reason": "애매하다"} for c in key["cases"]]

    def run(strip_contrast: bool) -> tuple[int, int, int]:
        qs = [dict(q, contrast=None) if strip_contrast and q["domain"] == "shop" and q["qid"] not in eighth else q
              for q in questions]
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            paths = {"ASSIGNMENT": d / "a.json", "QUESTIONS": d / "q.jsonl", "RETRIEVED": d / "r.jsonl",
                     "ANSWER_KEY": d / "k.json", "REVIEW": d / "v.jsonl", "EXCLUDED": d / "x.json"}
            write_json(paths["ASSIGNMENT"], {"seed": 20261005, "rounds": [rnd0]})
            write_json(paths["ANSWER_KEY"], key)
            write_jsonl(paths["REVIEW"], review)
            write_jsonl(paths["QUESTIONS"], qs)
            write_jsonl(paths["RETRIEVED"], [{"qid": q["qid"], "status": "ok", "sources": src} for q in qs])
            out = io.StringIO()
            with mock.patch.multiple(judge5v2_assign, **paths), contextlib.redirect_stdout(out):
                code = judge5v2_assign.cmd_supplement()
            rounds = read_json(paths["ASSIGNMENT"])["rounds"]
        if code == 2:   # 보충의 멈춤은 E10 의 것이고, 덧붙인 회차를 되돌리는 명령을 함께 보인다
            text = out.getvalue()
            assert "멈춘다: 계획 E10, 스펙 7-2절 경우 2." in text and "git checkout -- ai-service/testdata/judge5v2/assignment.json" in text
            assert "관문 4" in text
        return code, len(rounds), rounds[-1]["domains"]["shop"]["eighth_to_sixth"]

    assert run(strip_contrast=False) == (0, 2, 0)
    assert run(strip_contrast=True) == (2, 2, 2)   # 회차는 덧붙였고(파일은 남는다) ⑧ 두 개가 ⑥ 으로 갔다

    # 이미 유형을 받은 질문(회차 0 의 shop ①)을 제외에 적으면 회차를 덧붙이지 않고 종료 1 로 멈춘다.
    taken = sorted(q for q, t in rnd0["domains"]["shop"]["types"].items() if t == 1)[0]
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        paths = {"ASSIGNMENT": d / "a.json", "QUESTIONS": d / "q.jsonl", "RETRIEVED": d / "r.jsonl",
                 "ANSWER_KEY": d / "k.json", "REVIEW": d / "v.jsonl", "EXCLUDED": d / "x.json"}
        write_json(paths["ASSIGNMENT"], {"seed": 20261005, "rounds": [rnd0]})
        write_json(paths["ANSWER_KEY"], key)
        write_jsonl(paths["REVIEW"], review)
        write_jsonl(paths["QUESTIONS"], questions)
        write_jsonl(paths["RETRIEVED"], [{"qid": q["qid"], "status": "ok", "sources": src} for q in questions])
        write_json(paths["EXCLUDED"], {taken: {"reason": "answer_not_in_top5", "note": "top5 밖"}})
        out = io.StringIO()
        with mock.patch.multiple(judge5v2_assign, **paths), contextlib.redirect_stdout(out):
            code = judge5v2_assign.cmd_supplement()
        assert code == 1 and len(read_json(paths["ASSIGNMENT"])["rounds"]) == 1
        assert taken in out.getvalue() and "검수에서 drop 한다(계획 E6, E9)" in out.getvalue()



def _excluded_inputs() -> tuple[list[dict], list[dict]]:
    """질문 넷(shop-001~004)과 검색 줄. shop-003 은 검색에서 버렸다. shop-004 는 답변이 비었다(제외할 질문)."""
    src = [{"chunk_id": 1, "content": "근거"}]
    qs = [{"qid": f"shop-00{i}", "domain": "shop", "answer": None if i == 4 else "답", "claims": 1,
           "two_part": False, "contrast": None} for i in range(1, 5)]
    rs = [{"qid": q["qid"], "domain": "shop", "status": "dropped" if q["qid"] == "shop-003" else "ok",
           "drop_reason": "answerable" if q["qid"] == "shop-003" else None, "sources": src} for q in qs]
    return qs, rs


def check_pool_for_skips_excluded_questions() -> None:
    """제외한 질문은 후보에서 빠진다. 답변이 비어 있어도 멈추지 않는다(근거로 답을 쓸 수 없는 질문이다)."""
    qs, rs = _excluded_inputs()
    ex = {"shop-004": {"reason": "answer_not_in_top5", "note": "정답 청크가 top5 밖"},
          "shop-002": {"reason": "partial_answer_not_in_top5", "note": "한쪽이 top5 밖"}}
    assert [q["qid"] for q in pool_for(qs, rs, ex)["shop"]] == ["shop-001"]
    try:
        pool_for(qs, rs)                       # 제외가 없으면 shop-004 의 빈 답변 때문에 멈춘다
    except ValueError:
        return
    raise AssertionError("제외하지 않은 질문의 빈 답변은 거절해야 한다")


def check_pool_for_refuses_bad_excluded() -> None:
    """원인이 정해진 둘이 아니거나, 없는 질문이거나, 검색에서 이미 버린 질문이면 멈춘다."""
    qs, rs = _excluded_inputs()
    ok = {"shop-004": {"reason": "answer_not_in_top5", "note": ""}}
    # 검색 줄에는 있지만 questions.jsonl 에는 없는 질문(shop-099). 검색 줄까지 없으면 다음 검사가 대신 잡아 버려서
    # "없는 질문" 검사가 빠져도 이 점검이 통과한다.
    stray = rs + [dict(rs[0], qid="shop-099")]
    bad = [   # (제외 내용, 검색 줄, 오류에 나와야 하는 말)
        ({"shop-004": {"reason": "too_hard", "note": ""}}, rs, "too_hard"),              # 정해지지 않은 원인
        ({"shop-004": "answer_not_in_top5"}, rs, "None"),                                 # 원인을 객체에 담지 않았다
        ({**ok, "shop-099": {"reason": "answer_not_in_top5", "note": ""}}, stray, "questions.jsonl 에 없는"),
        ({**ok, "shop-003": {"reason": "answer_not_in_top5", "note": ""}}, rs, "이미 버린"),
        (ok, rs[:3], "검색하지 않은"),                                                    # shop-004 의 검색 줄이 없다
    ]
    for ex, rows, says in bad:
        try:
            pool_for(qs, rows, ex)
        except ValueError as e:
            assert "excluded.json" in str(e) and says in str(e), (says, str(e))
            continue
        raise AssertionError(says)


def check_first_records_excluded_and_replay_refuses_mixed() -> None:
    """first 는 회차 0 에 excluded.json 의 해시, 질문별 원인, 분야별 원인 수를 적는다. 파일이 없으면 해시는 null 이다.
    회차의 후보에 그 회차가 제외한 질문이 들어 있으면 replay 가 멈춘다."""
    src = [{"chunk_id": 1, "content": "골드 10,000원 / 실버 20,000원"}]
    questions = [q for d in DOMAINS for q in _pool(d, n=80)]          # 75 + 5: 제외 다섯을 빼도 할당량을 채운다
    ex = {f"hr-07{i}": {"reason": "answer_not_in_top5", "note": "top5 밖"} for i in range(5, 8)}
    ex["shop-079"] = {"reason": "partial_answer_not_in_top5", "note": "한쪽이 top5 밖"}

    def run(write_ex: bool) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            paths = {"ASSIGNMENT": d / "a.json", "QUESTIONS": d / "q.jsonl", "RETRIEVED": d / "r.jsonl",
                     "EXCLUDED": d / "x.json"}
            write_jsonl(paths["QUESTIONS"], questions)
            write_jsonl(paths["RETRIEVED"], [{"qid": q["qid"], "status": "ok", "sources": src} for q in questions])
            if write_ex:
                write_json(paths["EXCLUDED"], ex)
            with mock.patch.multiple(judge5v2_assign, **paths), contextlib.redirect_stdout(io.StringIO()):
                assert judge5v2_assign.cmd_first() == 0
            rnd = read_json(paths["ASSIGNMENT"])["rounds"][0]
            sha = hashlib.sha256(paths["EXCLUDED"].read_bytes()).hexdigest() if write_ex else None
        assert rnd["excluded_sha256"] == sha
        return rnd

    rnd = run(write_ex=True)
    assert rnd["excluded"] == {q: e["reason"] for q, e in ex.items()}
    assert rnd["excluded_counts"] == {"hr": {"answer_not_in_top5": 3}, "shop": {"partial_answer_not_in_top5": 1},
                                      "manual": {}, "finance": {}}
    assert not set(rnd["pool"]["hr"] + rnd["pool"]["shop"]) & set(ex)
    by_id = {q["qid"]: q for q in questions}
    assert replay_round(rnd, by_id, 20261005, 0) == rnd["domains"]
    mixed = dict(rnd, pool=dict(rnd["pool"], hr=rnd["pool"]["hr"] + ["hr-075"]))
    try:
        replay_round(mixed, by_id, 20261005, 0)
    except ValueError:
        pass
    else:
        raise AssertionError("후보에 제외한 질문이 있으면 replay 가 멈춰야 한다")
    empty = run(write_ex=False)
    assert empty["excluded"] == {} and empty["excluded_counts"] == {d: {} for d in DOMAINS}


CHECKS = [
    check_assign_meets_quota_and_eligibility,
    check_assign_is_reproducible_and_order_free,
    check_assign_moves_missing_eighth_to_sixth,
    check_assign_sixth_and_eighth_need_single_answer,
    check_assign_reports_fourth_and_third_shortfall,
    check_replay_reproduces_round,
    check_supplement_needs_counts_only_drops,
    check_valid_contrast,
    check_pool_for_uses_last_search_and_refuses_two_part_contrast,
    check_assign_order_fourth_eighth_third_sixth,
    check_supplement_needs_with_eighth_moved_to_sixth,
    check_supplement_pools_skip_used_keep_unused,
    check_first_stops_with_code_2_when_eighth_moved,
    check_supplement_stops_with_code_2_when_eighth_moved,
    check_pool_for_skips_excluded_questions,
    check_pool_for_refuses_bad_excluded,
    check_first_records_excluded_and_replay_refuses_mixed,
]


def main() -> None:
    for fn in CHECKS:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(CHECKS)}가지 전부 통과.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 점검이 실패하는지 본다**

Run: `$PY -m tools.judge5v2_assign_check`
Expected: `ModuleNotFoundError: No module named 'tools.judge5v2_assign'`

- [ ] **Step 3: 배정 도구를 쓴다** (`judge5v2_assign.py`)

```python
"""채점 모델 비교 v2 의 변형 유형 배정(스펙 3-3절, 7-2절).

실행:
    cd ai-service
    $PY -m tools.judge5v2_assign first        # 첫 배정. assignment.json 이 없어야 한다
    $PY -m tools.judge5v2_assign supplement   # 관문을 통과하지 못했을 때 보충 배정. 새 회차를 덧붙인다

배정을 출제 세션의 판단이 아니라 시드로 정하는 이유: 출제 세션이 유형을 고르면 망가뜨리기 쉬운 질문에
어려운 유형이 몰릴 수 있다(스펙 3-3절).
"""
from __future__ import annotations

import argparse
import random
import sys
from collections import Counter

from .judge5 import sha256_file
from .judge5v2_files import (
    ANSWER_KEY, ASSIGNMENT, DOMAINS, QUESTIONS, QUOTA, RETRIEVED, REVIEW, SEED, V2,
    latest_by_qid, read_json, read_jsonl, value_in, write_json,
)

# 자격 조건이 없는 유형을 채우는 순서(스펙 3-3절 3의 5).
REST_ORDER = (1, 2, 5, 7)

# 검색은 통과했지만 정답 청크가 근거 5청크 밖이라 멀쩡한 답변을 근거만으로 쓸 수 없는 질문. 출제 세션이 적는다.
# 모양: {"<qid>": {"reason": 아래 둘 중 하나, "note": "한국어 한 줄"}}. 파일이 없으면 제외가 없는 것이다.
# questions.jsonl 에 표시하지 않고 따로 두는 이유: 배정 회차의 pool 에 든 질문의 줄은 고치지 않는다(계획 E6).
EXCLUDED = V2 / "excluded.json"
EXCLUDE_REASONS = frozenset({"answer_not_in_top5", "partial_answer_not_in_top5"})


class Shortfall(Exception):
    """할당량을 채우지 못했다. short 는 {분야: {유형: 모자란 수}} 다."""

    def __init__(self, short: dict[str, dict[int, int]]) -> None:
        super().__init__(short)
        self.short = short


def eligible4(q: dict) -> bool:
    return q["claims"] >= 2 and q["claims"] % 2 == 0     # 주장 2 이상의 짝수(스펙 3-2절)


def eligible3(q: dict) -> bool:
    return q["claims"] >= 2                               # 주장 2 이상(스펙 3-2절)


def eligible6(q: dict) -> bool:
    # 답이 하나인 질문만(스펙 3-2절). 답이 두 가지인 질문에서 한쪽만 근거와 반대로 바꾸면 채점표의 1점("반대되는
    # 내용")과 3점("비슷한 정도로 섞여")에 모두 해당해 정답 점수가 하나로 정해지지 않는다.
    return not q["two_part"]


def eligible8(q: dict) -> bool:
    return not q["two_part"] and q["contrast"] is not None   # ⑥ 과 같은 이유로 답이 하나인 질문만


def assign_domain(pool: list[dict], needs: dict[int, int], rng: random.Random) -> tuple[dict, dict[int, int]]:
    """한 분야를 배정한다. 순서는 ④, ⑧, ③, ⑥, 나머지(스펙 3-3절 3).

    pool 을 qid 로 먼저 줄 세운다. 입력 순서와 무관하게 같은 시드에서 같은 배정이 나오게 하려는 것이다.
    rng.sample(목록, k) 는 목록에서 k 개를 중복 없이 뽑는다. 같은 시드의 Random 이면 늘 같은 k 개다.
    """
    pool = sorted(pool, key=lambda q: q["qid"])
    needs = dict(needs)
    types: dict[str, int] = {}
    short: dict[int, int] = {}

    def take(t: int, ok) -> int:
        cands = [q for q in pool if q["qid"] not in types and ok(q)]
        k = min(needs.get(t, 0), len(cands))
        for q in rng.sample(cands, k):
            types[q["qid"]] = t
        return needs.get(t, 0) - k

    if (n := take(4, eligible4)):         # := 는 값을 이름에 담으면서 그 값을 조건으로 쓴다
        short[4] = n
    moved = take(8, eligible8)            # ⑧ 이 모자란 수는 ⑥ 으로 돌린다(스펙 3-3절 5)
    needs[6] = needs.get(6, 0) + moved
    if (n := take(3, eligible3)):
        short[3] = n
    if (n := take(6, eligible6)):         # ⑥ 은 ⑧ 에서 돌린 수까지 합쳐 뽑는다. 그래서 ⑧ 다음이다
        short[6] = n

    rest = [q for q in pool if q["qid"] not in types]
    rng.shuffle(rest)
    i = 0
    for t in REST_ORDER:
        want = needs.get(t, 0)
        chunk = rest[i:i + want]
        if len(chunk) < want:
            short[t] = want - len(chunk)
        for q in chunk:
            types[q["qid"]] = t
        i += len(chunk)
    unused = sorted(q["qid"] for q in rest[i:])
    return {"types": types, "unused": unused, "eighth_to_sixth": moved}, short


def run_round(pools: dict[str, list[dict]], needs: dict[str, dict[int, int]], seed: int, no: int) -> dict[str, dict]:
    """네 분야를 한 회차로 배정한다. 분야마다 Random 을 따로 둔다(f"{seed}:{분야}:{회차}").
    따로 두는 이유: 한 분야의 질문 수가 바뀌어도 다른 분야의 배정이 흔들리지 않게 한다."""
    domains: dict[str, dict] = {}
    short: dict[str, dict[int, int]] = {}
    for d in DOMAINS:
        res, s = assign_domain(pools.get(d, []), needs.get(d, {}), random.Random(f"{seed}:{d}:{no}"))
        domains[d] = res
        if s:
            short[d] = s
    if short:
        raise Shortfall(short)
    return domains


def replay_round(rnd: dict, questions_by_id: dict[str, dict], seed: int, no: int) -> dict[str, dict]:
    """저장된 회차를 같은 입력으로 다시 돌린다. CI 가 배정이 시드로 재현되는지 볼 때 쓴다.

    회차에 적힌 제외 질문(excluded)이 그 회차의 후보에 들어 있으면 다시 돌리지 않고 멈춘다. 후보는 제외를 뺀 뒤의
    목록이어야 하므로, 들어 있으면 기록이 서로 어긋난 것이다.
    """
    pooled = {q for d in DOMAINS for q in rnd["pool"][d]}
    if again := sorted(pooled & set(rnd.get("excluded", {}))):
        raise ValueError(f"회차 {no} 의 후보에 제외한 질문이 들어 있다: {again[:5]}")
    pools = {d: [questions_by_id[q] for q in rnd["pool"][d]] for d in DOMAINS}
    needs = {d: {int(t): n for t, n in rnd["needs"][d].items()} for d in DOMAINS}
    return run_round(pools, needs, seed, no)


def assigned_types(assignment: dict) -> dict[str, int]:
    out: dict[str, int] = {}
    for rnd in assignment["rounds"]:
        for res in rnd["domains"].values():
            out.update(res["types"])
    return out


def valid_contrast(contrast: dict, sources: list[dict]) -> str | None:
    """⑧ 조건이 맞으면 None, 아니면 이유. 두 값이 그 질문의 근거 청크에 글자 그대로 있고 서로 달라야 한다."""
    # 값을 숫자(10000)로 적으면 아래 글자 비교(value_in)가 TypeError 로 멈춘다. 먼저 모양을 본다.
    values = [(contrast.get(side) or {}).get("value") for side in ("asked", "other")]
    if not all(isinstance(v, str) and v for v in values):
        return "asked.value 와 other.value 는 따옴표로 감싼 글자로 적는다"
    ids = set(contrast.get("chunk_ids") or [])
    texts = [s["content"] for s in sources if s["chunk_id"] in ids]
    if not ids or len(texts) != len(ids):
        return "chunk_ids 가 이 질문의 근거 청크가 아니다"
    asked, other = contrast["asked"]["value"], contrast["other"]["value"]
    if asked == other:
        return "두 대상의 값이 같다"
    joined = "\n".join(texts)
    if not value_in(asked, joined) or not value_in(other, joined):   # 단순 포함이 아니다(계획 형식 1)
        return "두 값이 chunk_ids 의 청크에 글자 그대로 있지 않다"
    return None


def excluded_problems(excluded: dict, questions: list[dict], retrieved: list[dict]) -> list[str]:
    """excluded.json 의 내용이 규칙대로인가. 문제 목록을 돌려준다(빈 목록이면 통과).

    검색을 통과한(status ok) 질문만 제외할 수 있다. 검색에서 버린 질문은 이미 후보가 아니므로, 거기에 제외를
    겹쳐 적으면 보고서의 버린 원인이 두 번 세어진다. 없는 qid 는 오타일 가능성이 크다.
    """
    if not isinstance(excluded, dict):
        return ["excluded.json 은 {\"qid\": {\"reason\": ..., \"note\": ...}} 꼴의 객체여야 한다"]
    known = {q["qid"] for q in questions}
    latest = {r["qid"]: r for r in latest_by_qid(retrieved)}
    out = []
    for qid, e in sorted(excluded.items()):
        reason = e.get("reason") if isinstance(e, dict) else None
        if reason not in EXCLUDE_REASONS:
            out.append(f"{qid}: 제외 원인 {reason!r} 는 쓸 수 없다. {', '.join(sorted(EXCLUDE_REASONS))} 중 하나를 적는다")
        elif qid not in known:
            out.append(f"{qid}: questions.jsonl 에 없는 질문이다")
        elif qid not in latest:
            out.append(f"{qid}: 검색하지 않은 질문이다(retrieved.jsonl 에 없다)")
        elif latest[qid]["status"] != "ok":
            out.append(f"{qid}: 검색에서 이미 버린 질문이다({latest[qid]['drop_reason']}). 제외에 적지 않는다")
    return out


def load_excluded() -> tuple[dict, str | None]:
    """(excluded.json 내용, 그 파일의 SHA-256). 파일이 없으면 ({}, None) 이다."""
    if not EXCLUDED.exists():
        return {}, None
    return read_json(EXCLUDED), sha256_file(EXCLUDED)


def pool_for(questions: list[dict], retrieved: list[dict], excluded: dict | None = None) -> dict[str, list[dict]]:
    """검색을 통과한 질문 중 제외하지 않았고 멀쩡한 답변, 주장 수, ⑧ 조건이 제대로 적힌 것. 하나라도 잘못되면 멈춘다.
    검색 줄은 질문마다 마지막 줄만 본다(계획 형식 2). excluded 는 excluded.json 의 내용이다(없으면 제외 없음)."""
    excluded = excluded or {}
    if bad := excluded_problems(excluded, questions, retrieved):
        raise ValueError("배정하지 않았습니다. excluded.json 을 고친 뒤 다시 실행하세요.\n  - " + "\n  - ".join(bad))
    ok = {r["qid"]: r for r in latest_by_qid(retrieved) if r["status"] == "ok"}
    pools: dict[str, list[dict]] = {d: [] for d in DOMAINS}
    problems = []
    for q in questions:
        r = ok.get(q["qid"])
        # 제외한 질문은 답변 칸을 보기 전에 건너뛴다. 근거로 답을 쓸 수 없는 질문이라 답변이 비어 있을 수 있다.
        if r is None or q["qid"] in excluded:
            continue
        # type(x) is int: isinstance(True, int) 는 True 라서 claims 에 true 를 적어도 1 로 통과한다. bool 을 막으려고 정확히 int 만 받는다.
        if not q.get("answer") or type(q.get("claims")) is not int or q["claims"] < 1:
            problems.append(f"{q['qid']}: answer 또는 claims 가 비었다")
            continue
        if not isinstance(q.get("two_part"), bool):
            problems.append(f"{q['qid']}: two_part 가 true 나 false 가 아니다")
            continue
        if q["two_part"] and q.get("contrast") is not None:
            problems.append(f"{q['qid']}: 답이 두 가지인 질문에는 contrast 를 적지 않는다(⑧ 은 답이 하나인 질문에만 만든다)")
            continue
        if q.get("contrast") is not None and (why := valid_contrast(q["contrast"], r["sources"])):
            problems.append(f"{q['qid']}: ⑧ 조건이 잘못됐다({why})")
            continue
        pools[q["domain"]].append(q)
    if problems:
        raise ValueError("배정하지 않았습니다. questions.jsonl 을 고친 뒤 다시 실행하세요.\n  - " + "\n  - ".join(problems))
    return pools


def supplement_needs(assignment: dict, dropped_qids: set[str], domain_of: dict[str, str]) -> dict[str, dict[int, int]]:
    """보충할 할당량. 분야마다 (목표 - 남은 문항) 이다. 목표는 QUOTA 에서 ⑧ 을 ⑥ 으로 돌린 수를 반영한 값이다."""
    target = {d: dict(QUOTA) for d in DOMAINS}
    for rnd in assignment["rounds"]:
        for d, res in rnd["domains"].items():
            target[d][8] -= res["eighth_to_sixth"]
            target[d][6] += res["eighth_to_sixth"]
    kept = {d: Counter() for d in DOMAINS}
    for qid, t in assigned_types(assignment).items():
        if qid not in dropped_qids:
            kept[domain_of[qid]][t] += 1
    return {d: {t: max(0, target[d][t] - kept[d][t]) for t in QUOTA} for d in DOMAINS}


def supplement_pools(pools: dict[str, list[dict]], assignment: dict) -> dict[str, list[dict]]:
    """보충 회차의 후보. 앞 회차들에서 유형을 받은 질문은 빼고, 받지 않은 질문(unused)은 남긴다(스펙 7-2절).
    버린 문항의 질문도 뺀다. 같은 질문에 다른 유형을 붙여 다시 쓰면 그 질문의 검수 판단이 두 번 쓰이기 때문이다."""
    used = set(assigned_types(assignment))
    return {d: [q for q in ps if q["qid"] not in used] for d, ps in pools.items()}


def _round_doc(no: int, pools: dict[str, list[dict]], needs: dict[str, dict[int, int]], domains: dict,
               excluded: dict, excluded_sha: str | None, domain_of: dict[str, str]) -> dict:
    counts: dict[str, dict[str, int]] = {d: {} for d in DOMAINS}
    for qid, e in sorted(excluded.items()):
        counts[domain_of[qid]][e["reason"]] = counts[domain_of[qid]].get(e["reason"], 0) + 1
    return {
        "round": no,
        "questions_sha256": sha256_file(QUESTIONS),
        "retrieved_sha256": sha256_file(RETRIEVED),
        # 이 회차가 쓴 제외. 파일이 나중에 바뀌어도 이 회차의 후보가 무엇을 뺀 것인지 기록에서 알 수 있게
        # 해시(파일이 없었으면 null)와 질문별 원인, 분야별 원인 수를 함께 적는다. 보고서는 excluded_counts 를 읽는다.
        "excluded_sha256": excluded_sha,
        "excluded": {qid: e["reason"] for qid, e in sorted(excluded.items())},
        "excluded_counts": counts,
        "pool": {d: sorted(q["qid"] for q in pools[d]) for d in DOMAINS},
        # JSON 의 키는 글자뿐이라 유형 번호를 글자로 바꿔 적는다. replay_round 가 다시 정수로 읽는다.
        "needs": {d: {str(t): n for t, n in needs[d].items()} for d in DOMAINS},
        "domains": domains,
    }


def _print_short(e: Shortfall) -> None:
    print("할당량을 채우지 못했습니다. 아래 분야의 질문을 더 써서 questions.jsonl 에 더한 뒤(계획 E2 의 보충),")
    print("검색(E3)과 멀쩡한 답변(E4)을 거쳐 다시 실행하세요.")
    for d, s in e.short.items():
        print(f"  - {d}: " + ", ".join(f"유형 {t} 이 {n}개 모자람" for t, n in sorted(s.items())))
    print("유형 4는 주장 수 2 이상의 짝수, 유형 3은 주장 수 2 이상, 유형 6은 답이 하나인(two_part false) 질문이 필요하다.")


def _stop_if_eighth_moved(domains: dict[str, dict], stage: str, undo: bool = False) -> int:
    """이번 회차에서 ⑧ 을 ⑥ 으로 돌린 분야가 있으면 알리고 2, 없으면 0 을 돌려준다. first 와 supplement 가 같이 쓴다.

    stage 는 이 멈춤을 다루는 계획의 단계 이름이다(first 는 "E5", supplement 는 "E10, 스펙 7-2절 경우 2").
    undo 가 참이면(supplement) 덧붙인 회차를 되돌리는 명령과 그대로 갈 때 할 일을 함께 찍는다. supplement 는
    이미 커밋된 assignment.json 에 회차를 덧붙이므로, first 와 달리 파일을 지우는 것으로는 되돌릴 수 없다.
    """
    moved = {d: domains[d]["eighth_to_sixth"] for d in DOMAINS if domains[d]["eighth_to_sixth"]}
    if not moved:
        return 0
    # 이 경우 커밋하지 않고 사용자 판단을 받는다. 출력 한 줄로는 지나치기 쉬워서 종료 코드를 따로 둔다.
    # 1(배정 못 함)과 나누는 이유: 파일은 만들어졌다. 사용자가 그대로 가기로 하면 이 파일을 그대로 쓴다.
    print(f"멈춘다: 계획 {stage}. ⑧ 을 ⑥ 으로 돌린 분야가 있다("
          + ", ".join(f"{d} {n}개" for d, n in moved.items())
          + f"). {ASSIGNMENT.name} 는 남겼지만 커밋하지 않는다. 사용자에게 보충할지 그대로 갈지 묻는다.")
    if undo:
        print("  되돌리려면: git checkout -- ai-service/testdata/judge5v2/assignment.json")
        print("  그대로 가면: 변형 답변(E6)과 검수를 거친 뒤 관문 4(⑧ 15개 이상)를 다시 본다.")
    return 2


def cmd_first() -> int:
    if ASSIGNMENT.exists():
        print(f"{ASSIGNMENT.name} 가 이미 있습니다. 보충은 supplement 를 쓰세요. 덮어쓰지 않습니다.")
        return 1
    questions = read_jsonl(QUESTIONS)
    excluded, excluded_sha = load_excluded()
    try:
        pools = pool_for(questions, read_jsonl(RETRIEVED), excluded)
    except ValueError as e:
        print(e)   # pool_for 의 메시지가 이미 한국어로 고칠 곳을 줄마다 적는다
        return 1
    needs = {d: dict(QUOTA) for d in DOMAINS}
    try:
        domains = run_round(pools, needs, SEED, 0)
    except Shortfall as e:
        _print_short(e)
        return 1
    domain_of = {q["qid"]: q["domain"] for q in questions}
    doc = _round_doc(0, pools, needs, domains, excluded, excluded_sha, domain_of)
    write_json(ASSIGNMENT, {"seed": SEED, "rounds": [doc]})
    for d in DOMAINS:
        res = domains[d]
        print(f"{d}: 배정 {len(res['types'])}, 쓰지 않음 {len(res['unused'])}, ⑧ 을 ⑥ 으로 {res['eighth_to_sixth']}")
    if excluded:
        print("제외한 질문: " + ", ".join(f"{d} {sum(c.values())}개" for d, c in doc["excluded_counts"].items() if c))
    return _stop_if_eighth_moved(domains, "E5")


def cmd_supplement() -> int:
    assignment = read_json(ASSIGNMENT)
    key = read_json(ANSWER_KEY)
    every = {**key["cases"], **key.get("dropped", {})}
    drops = {r["case_id"] for r in read_jsonl(REVIEW) if r.get("user_decision") == "drop"}
    dropped_qids = {every[c]["qid"] for c in drops if c in every}
    questions = read_jsonl(QUESTIONS)
    domain_of = {q["qid"]: q["domain"] for q in questions}
    needs = supplement_needs(assignment, dropped_qids, domain_of)
    if not any(n for s in needs.values() for n in s.values()):
        print("보충할 할당량이 없습니다. 관문이 할당량 밖의 이유로 실패했다면 사용자에게 알리고 멈춥니다.")
        return 1
    excluded, excluded_sha = load_excluded()
    # 이미 유형을 받은 질문을 제외에 적으면, 그 질문은 앞 회차의 배정으로 시험지에 남으면서 이번 회차의 기록에는
    # 제외로 적힌다. 같은 질문이 서로 다른 두 사실로 기록되므로 멈춘다. 그런 질문은 검수에서 drop 한다.
    if both := sorted(set(excluded) & set(assigned_types(assignment))):
        print(f"excluded.json 에 이미 배정된 질문이 있습니다: {', '.join(both[:10])}. "
              "이미 배정된 질문은 제외에 적지 않고 검수에서 drop 한다(계획 E6, E9). excluded.json 에서 지운 뒤 다시 실행하세요.")
        return 1
    try:
        pools = supplement_pools(pool_for(questions, read_jsonl(RETRIEVED), excluded), assignment)
    except ValueError as e:
        print(e)
        return 1
    no = len(assignment["rounds"])
    try:
        domains = run_round(pools, needs, assignment["seed"], no)
    except Shortfall as e:
        _print_short(e)
        return 1
    assignment["rounds"].append(_round_doc(no, pools, needs, domains, excluded, excluded_sha, domain_of))
    write_json(ASSIGNMENT, assignment)
    print(f"회차 {no}: " + ", ".join(f"{d} {len(domains[d]['types'])}문항" for d in DOMAINS))
    # 보충 회차에서 ⑧ 을 ⑥ 으로 돌리면 스펙 7-2절 끝의 경우 2 다. 보충 배정은 돌린 ⑧ 을 다시 요구하지 않으므로
    # 다음 보충으로도 ⑧ 이 늘지 않는다. 그래서 first 와 같이 멈추고 사용자에게 보인다.
    return _stop_if_eighth_moved(domains, "E10, 스펙 7-2절 경우 2", undo=True)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="채점 모델 비교 v2 의 변형 유형을 배정한다")
    p.add_argument("cmd", choices=("first", "supplement"))
    args = p.parse_args(argv)
    return cmd_first() if args.cmd == "first" else cmd_supplement()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 점검이 통과하는지 본다**

Run: `$PY -m tools.judge5v2_assign_check | tail -1`
Expected: `17가지 전부 통과.` (처음 계획은 9가지. `f17877a` 가 넷, `d368ba5` 가 하나, `a0557d2` 가 셋을 더했다)

- [ ] **Step 5: 커밋한다**

```bash
git add ai-service/tools/judge5v2_assign.py ai-service/tools/judge5v2_assign_check.py
git commit -m "feat: 채점 모델 비교 v2 의 변형 유형을 시드로 배정하는 도구를 추가한다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/tools/judge5v2_assign.py ai-service/tools/judge5v2_assign_check.py
```

**리뷰 포인트:** 뽑는 순서가 스펙 3-3절(④, ⑧, ③, ⑥, 나머지 ①②⑤⑦)과 같은가. ③, ④, ⑥ 이 모자랄 때 다른 유형으로 채우지 않고 멈추는가. ⑥, ⑧ 이 답이 두 가지인 질문에 붙지 않는가.

---

### Task 6: 내보내기 도구

**Files:**
- Create: `ai-service/tools/judge5v2_export.py`
- Create: `ai-service/tools/judge5v2_export_check.py`

**Interfaces:**
- Consumes: 태스크 1 의 상수와 `latest_by_qid`, `value_in`, 태스크 5 의 `assigned_types`, `judge5.build_messages`, `judge5.prompt_sha256`, `judge5.sha256_file`, `judge5.SCALE`
- Produces:
  - `CASE_KEYS = frozenset({"case_id", "domain", "messages", "search_settings"})`
  - `fence_for(text: str) -> str` (`mismatches.md` 의 코드 울타리. 본문 안의 가장 긴 백틱 연속보다 하나 길다. `f17877a`)
  - `case_id_of(domain: str, question: str, answer: str) -> str` (12자)
  - `build_cases(questions, retrieved, types: dict[str, int], variants) -> tuple[list[dict], dict[str, dict]]` (시험지 줄 목록, `case_id` 별 정답 정보)
  - `load_and_build() -> tuple[list[dict], dict[str, dict]]`
  - `apply_review(key: dict[str, dict], reviews: list[dict]) -> tuple[dict, dict, list[str]]` (남긴 문항, 버린 문항, 문제 목록)
  - `class ExportProblem(RuntimeError)` with `.problems: list[str]`
  - 명령 `python -m tools.judge5v2_export draft | mismatches | final`. `draft` 는 `answer_key.json` 이 이미 `final` 이면 거절한다(`f17877a`)

- [ ] **Step 1: 실패하는 점검을 쓴다** (`judge5v2_export_check.py`)

```python
"""tools.judge5v2_export 의 점검. DB 도 외부 API 도 쓰지 않는다.

실행:  cd ai-service && python -m tools.judge5v2_export_check

시험지에 변형 유형이나 정답 점수가 새어 들어가면 채점 모델과 검수 세션이 답을 보고 매기게 된다.
검수 결과를 잘못 반영하면 정답 점수가 바뀐다. 둘 다 결과 숫자로는 드러나지 않는다.
"""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
from pathlib import Path
from unittest import mock

from . import judge5v2_export
from .judge5 import build_messages
from .judge5v2_export import CASE_KEYS, ExportProblem, apply_review, build_cases, case_id_of, fence_for

_SRC = [{"chunk_id": 1, "filename": "a.md",
         "content": "골드 10,000원 / 실버 20,000원 / 브론즈 30,000원. 이 문장은 200자보다 길 수 있다."}]
_SETTINGS = {"top_k": 5}


def _inputs():
    questions = [
        {"qid": "shop-001", "domain": "shop", "question": "골드 무료 기준은?", "answer": "골드는 10,000원 이상이면 무료입니다.",
         "claims": 1, "two_part": False, "contrast": {"asked": {"target": "골드", "value": "10,000원"},
                                                      "other": {"target": "실버", "value": "20,000원"}, "chunk_ids": [1]}},
        {"qid": "shop-002", "domain": "shop", "question": "실버 무료 기준은?", "answer": "실버는 20,000원 이상이면 무료입니다.",
         "claims": 1, "two_part": False, "contrast": None},
        {"qid": "shop-003", "domain": "shop", "question": "브론즈 무료 기준은?", "answer": "브론즈는 30,000원 이상이면 무료입니다.",
         "claims": 1, "two_part": False, "contrast": None},
    ]
    retrieved = [{"qid": q["qid"], "status": "ok", "settings": _SETTINGS, "sources": _SRC} for q in questions]
    types = {"shop-001": 8, "shop-002": 1, "shop-003": 6}
    variants = [{"qid": "shop-001", "type": 8, "answer": "골드는 20,000원 이상이면 무료입니다.", "note": ""},
                {"qid": "shop-002", "type": 1, "answer": "실버는 20,000원 이상이면 무료입니다.", "note": ""},
                {"qid": "shop-003", "type": 6, "answer": "브론즈는 35,000원 이상이면 무료입니다.", "note": "",
                 "new_value": "35,000원", "old_value": "30,000원"}]
    return questions, retrieved, types, variants


def check_cases_hide_type_and_score() -> None:
    rows, key = build_cases(*_inputs())
    assert all(set(r) == CASE_KEYS for r in rows)
    text = json.dumps(rows, ensure_ascii=False)
    assert "table_score" not in text and "shop-001" not in text   # qid 도 단서가 되지 않게 넣지 않는다
    assert {k["table_score"] for k in key.values()} == {1, 5}


def check_messages_carry_full_sources_and_variant() -> None:
    rows, key = build_cases(*_inputs())
    by_qid = {k["qid"]: cid for cid, k in key.items()}
    row = next(r for r in rows if r["case_id"] == by_qid["shop-001"])
    assert row["messages"] == build_messages("골드 무료 기준은?", [{"filename": "a.md", "content": _SRC[0]["content"]}],
                                             "골드는 20,000원 이상이면 무료입니다.")
    assert row["search_settings"] == _SETTINGS


def check_case_id_uses_no_type() -> None:
    assert case_id_of("shop", "q", "a") == case_id_of("shop", "q", "a")
    assert len(case_id_of("shop", "q", "a")) == 12 and case_id_of("shop", "q", "a") != case_id_of("shop", "q", "b")


def check_rows_are_shuffled_but_fixed() -> None:
    q, r, t, v = _inputs()
    a, _ = build_cases(q, r, t, v)
    b, _ = build_cases(q[::-1], r[::-1], t, v[::-1])
    assert a == b


def check_build_refuses_bad_variants() -> None:
    q, r, t, v = _inputs()
    sixth_in_source = dict(v[2], answer="브론즈는 20,000원 이상이면 무료입니다.", new_value="20,000원")
    bad_cases = [
        [dict(v[0], type=6), v[1], v[2]],                                       # 배정과 유형이 다르다
        [v[0], dict(v[1], answer="실버는 2만 원 이상이면 무료입니다."), v[2]],     # ①이 원본과 다르다
        [dict(v[0], answer=q[0]["answer"]), v[1], v[2]],                          # ⑧ 이 원본과 같다
        [dict(v[0], answer="골드는 무료입니다."), v[1], v[2]],                     # ⑧ 이 다른 대상의 값을 쓰지 않았다
        [v[1], v[2]],                                                              # 변형 답변이 빠졌다
        [v[0], v[1], sixth_in_source],                                             # ⑥ 의 값이 근거에 있다
        [v[0], v[1], {k: x for k, x in v[2].items() if k != "new_value"}],         # ⑥ 에 new_value 가 없다
        [v[0], v[1], dict(v[2], new_value="40,000원")],                           # ⑥ 의 new_value 가 답변에 없다
        [v[0], v[1], dict(v[2], answer="브론즈는 35,000원 이상이면 무료입니다. 기존 기준은 30,000원입니다.")],  # ⑥ 에 옛 값이 남았다
        [v[0], v[1], {k: x for k, x in v[2].items() if k != "old_value"}],         # ⑥ 에 old_value 가 없다
        [v[0], v[1], dict(v[2], old_value="25,000원")],                           # ⑥ 의 old_value 가 멀쩡한 답변에 없다
        [v[0], v[1], dict(v[2], new_value=35000)],                               # ⑥ 의 값을 글자가 아닌 숫자로 적었다
        [dict(v[0], answer="골드는 10,000원, 실버는 20,000원입니다."), v[1], v[2]],  # ⑧ 이 두 대상의 값을 다 썼다
    ]
    for variants in bad_cases:
        try:
            build_cases(q, r, t, variants)
        except ExportProblem:
            continue
        raise AssertionError(variants)
    two_part = [dict(x, two_part=True) if x["qid"] == "shop-003" else x for x in q]
    try:
        build_cases(two_part, r, t, v)                                     # ⑥ 이 답이 두 가지인 질문에 붙었다
    except ExportProblem:
        return
    raise AssertionError("답이 두 가지인 질문의 ⑥ 은 거절해야 한다")


def check_values_are_matched_with_boundaries() -> None:
    """값은 다른 값의 일부로 찾지 않는다(계획 형식 1). 묻는 값 2,000원 이 답변의 12,000원 안에 있다고 보면
    멀쩡한 ⑧ 을 거절한다. ⑥ 의 새 값 35,000원 이 근거의 135,000원 안에 있다고 보면 멀쩡한 ⑥ 을 거절한다."""
    src = [{"chunk_id": 1, "filename": "a.md", "content": "일반 2,000원, 프리미엄 12,000원, 법인 135,000원"}]
    q = [{"qid": "fin-001", "domain": "finance", "question": "일반 수수료는?", "answer": "2,000원입니다.", "claims": 1,
          "two_part": False, "contrast": {"asked": {"target": "일반", "value": "2,000원"},
                                          "other": {"target": "프리미엄", "value": "12,000원"}, "chunk_ids": [1]}},
         {"qid": "fin-002", "domain": "finance", "question": "법인 수수료는?", "answer": "135,000원입니다.", "claims": 1,
          "two_part": False, "contrast": None}]
    r = [{"qid": x["qid"], "status": "ok", "settings": _SETTINGS, "sources": src} for x in q]
    v = [{"qid": "fin-001", "type": 8, "answer": "12,000원입니다.", "note": ""},
         {"qid": "fin-002", "type": 6, "answer": "35,000원입니다.", "note": "", "new_value": "35,000원",
          "old_value": "135,000원"}]    # 옛 값 135,000원 은 변형 답변의 35,000원 안에 있지 않다(값 경계)
    rows, _ = build_cases(q, r, {"fin-001": 8, "fin-002": 6}, v)
    assert len(rows) == 2


def check_apply_review_paths() -> None:
    """스펙 4절: 같으면 통과, 다르면 사용자 판단(keep, override, drop). 판단이 없으면 멈춘다."""
    key = {c: {"qid": c, "domain": "shop", "type": 3, "table_score": 4} for c in ("a", "b", "c", "d", "e")}
    reviews = [
        {"case_id": "a", "review_score": 4},
        {"case_id": "b", "review_score": 3, "user_decision": "keep", "reason": "대응표가 맞다"},
        {"case_id": "c", "review_score": 3, "user_decision": "override", "override_score": 3, "reason": "주장이 둘이 아니다"},
        {"case_id": "d", "review_score": 2, "user_decision": "drop", "reason": "애매하다"},
        {"case_id": "e", "review_score": 2},
    ]
    kept, dropped, problems = apply_review(key, reviews)
    assert kept["a"]["score"] == 4 and kept["a"]["decision"] == "match"
    assert kept["b"]["score"] == 4 and kept["b"]["decision"] == "keep"
    assert kept["c"]["score"] == 3 and kept["c"]["decision"] == "override"
    assert set(dropped) == {"d"} and "e" not in kept
    assert len(problems) == 1 and problems[0].startswith("e:")
    _, _, p2 = apply_review(key, reviews[:4])
    assert any(x.startswith("e:") for x in p2)                     # 검수 점수가 없는 문항
    _, _, p3 = apply_review(key, [dict(reviews[2], reason="")] + reviews[:2] + reviews[3:4] + [reviews[0] | {"case_id": "e"}])
    assert any(x.startswith("c:") for x in p3)                     # 고친 점수에 이유가 없다
    ok = reviews[:4] + [reviews[0] | {"case_id": "e"}]               # 문제가 없는 검수 줄 다섯
    _, _, p4 = apply_review(key, [dict(ok[1], reason="  ")] + ok[:1] + ok[2:])
    assert [x[:2] for x in p4] == ["b:"]                           # 대응표대로 둔다는 판단에도 이유가 있어야 한다
    _, _, p5 = apply_review(key, ok + [{"case_id": "z", "review_score": 3}])
    assert [x[:2] for x in p5] == ["z:"]                           # 시험지에 없는 문항의 검수 줄


def check_build_uses_last_search_line() -> None:
    """검색 줄은 질문마다 마지막 줄이 판정이다(계획 형식 2). 첫 줄을 쓰면 버린 시도의 근거로 시험지를 만든다."""
    q, r, t, v = _inputs()
    old = dict(r[1], settings={"top_k": 3}, sources=[{"chunk_id": 9, "filename": "old.md", "content": "옛 시도"}])
    rows, key = build_cases(q, [old] + r, t, v)
    cid = next(c for c, k in key.items() if k["qid"] == "shop-002")
    row = next(x for x in rows if x["case_id"] == cid)
    assert row["search_settings"] == _SETTINGS and "옛 시도" not in json.dumps(row, ensure_ascii=False)
    failed_last = dict(r[1], status="dropped", drop_reason="rerank_failed")
    try:
        build_cases(q, r + [failed_last], t, v)                    # 첫 줄은 ok 지만 마지막 시도가 실패했다
    except ExportProblem:
        return
    raise AssertionError("마지막 검색 줄이 실패면 그 질문으로 시험지를 만들지 않아야 한다")


def check_mismatch_fence_outlasts_inner_backticks() -> None:
    """근거 청크 안의 백틱 셋이 mismatches.md 의 코드 블록을 일찍 닫지 않게 울타리를 더 길게 만든다."""
    tick = "`"
    assert fence_for("평범한 글") == tick * 3
    body = "앞\n" + tick * 3 + "python\nx = 1\n" + tick * 3 + "\n뒤 " + tick * 5
    assert fence_for(body) == tick * 6


def check_draft_refuses_to_overwrite_final() -> None:
    """동결된 최종 정답 파일을 draft 로 덮지 않는다. 덮으면 M1 채점이 검수 전 시험지로 돈다."""
    with tempfile.TemporaryDirectory() as tmp:
        ak = Path(tmp) / "answer_key.json"
        ak.write_text(json.dumps({"stage": "final", "cases": {}}), encoding="utf-8")
        before = ak.read_text(encoding="utf-8")

        def must_not_build():
            raise AssertionError("final 이 있으면 시험지를 다시 만들기 전에 멈춰야 한다")

        with mock.patch.multiple(judge5v2_export, ANSWER_KEY=ak, load_and_build=must_not_build), \
                contextlib.redirect_stdout(io.StringIO()):
            assert judge5v2_export.cmd_draft() == 1
        assert ak.read_text(encoding="utf-8") == before


CHECKS = [
    check_cases_hide_type_and_score,
    check_messages_carry_full_sources_and_variant,
    check_case_id_uses_no_type,
    check_rows_are_shuffled_but_fixed,
    check_build_refuses_bad_variants,
    check_values_are_matched_with_boundaries,
    check_apply_review_paths,
    check_build_uses_last_search_line,
    check_mismatch_fence_outlasts_inner_backticks,
    check_draft_refuses_to_overwrite_final,
]


def main() -> None:
    for fn in CHECKS:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(CHECKS)}가지 전부 통과.")


if __name__ == "__main__":
    main()
```

`check_apply_review_paths` 마지막 줄의 `reviews[0] | {"case_id": "e"}` 는 dict 를 합치는 연산자다. 오른쪽 값이 이긴다. 즉 "e 의 검수 점수가 4" 인 줄을 만든다.

- [ ] **Step 2: 점검이 실패하는지 본다**

Run: `$PY -m tools.judge5v2_export_check`
Expected: `ModuleNotFoundError: No module named 'tools.judge5v2_export'`

- [ ] **Step 3: 내보내기 도구를 쓴다** (`judge5v2_export.py`)

```python
"""채점 모델 비교 v2 의 시험지 파일과 정답 파일을 만든다(스펙 8-1절 5단계와 8단계).

실행:
    cd ai-service
    $PY -m tools.judge5v2_export draft        # 검수 전. 배정된 모든 문항으로 시험지를 만든다
    $PY -m tools.judge5v2_export mismatches   # 검수 뒤. 검수 점수와 정답 점수가 다른 문항을 사용자용으로 정리한다
    $PY -m tools.judge5v2_export final        # 관문 통과 뒤. 버린 문항을 빼고 고친 정답 점수를 넣는다

시험지 파일(cases.jsonl)에는 변형 유형, 정답 점수, qid 를 넣지 않는다. 채점 모델과 검수 세션은 이 파일만 읽는다.
"""
from __future__ import annotations

import argparse
import hashlib
import random
import re
import sys

from .judge5 import SCALE, build_messages, prompt_sha256, sha256_file
from .judge5v2_assign import assigned_types
from .judge5v2_files import (
    ANSWER_KEY, ASSIGNMENT, CASES, CASES_SHA, MISMATCHES, QUESTIONS, RETRIEVED, REVIEW, SEED, TABLE_SCORE,
    TYPE_NAMES, VARIANTS, latest_by_qid, read_json, read_jsonl, value_in, write_json, write_jsonl,
)

CASE_KEYS = frozenset({"case_id", "domain", "messages", "search_settings"})


def fence_for(text: str) -> str:
    """text 를 감쌀 마크다운 코드 울타리. text 안에서 가장 긴 백틱 연속보다 하나 길게(최소 셋) 만든다.

    고정 길이 셋이면 근거 청크(마크다운 문서)에 들어 있는 백틱 셋이 울타리를 일찍 닫아, mismatches.md 에서
    그 뒤의 내용이 코드 블록 밖으로 나와 제목이나 목록으로 그려진다. 마크다운은 여는 울타리보다 짧은 백틱 줄로는
    닫지 않는다. 백틱을 곱셈으로 만드는 이유: 글자 그대로 적으면 이 코드를 담은 문서의 코드 블록이 거기서 끝난다.
    """
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


class ExportProblem(RuntimeError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems[:5]))
        self.problems = problems


def case_id_of(domain: str, question: str, answer: str) -> str:
    """문항 id. 해시의 입력에 변형 유형과 정답 점수를 넣지 않는다(스펙 8-3절). 그래서 id 로 유형을 알 수 없다.
    "\\x00" 으로 잇는 이유: 경계가 옮겨 간 다른 입력("ab"+"c" 와 "a"+"bc")이 같은 해시가 되지 않게 한다."""
    raw = "\x00".join([domain, question, answer])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def build_cases(questions: list[dict], retrieved: list[dict], types: dict[str, int],
                variants: list[dict]) -> tuple[list[dict], dict[str, dict]]:
    """배정된 질문마다 문항 하나를 만든다. 형식이 하나라도 틀리면 ExportProblem 으로 전부 알린다."""
    q_by = {q["qid"]: q for q in questions}
    r_by = {r["qid"]: r for r in latest_by_qid(retrieved)}   # 질문마다 마지막 검색 줄이 판정이다(계획 형식 2)
    v_by: dict[str, dict] = {}
    problems: list[str] = []
    for v in variants:
        if v["qid"] in v_by:
            problems.append(f"{v['qid']}: 변형 답변이 두 줄 있다")
        v_by[v["qid"]] = v
    rows: list[dict] = []
    key: dict[str, dict] = {}
    for qid, t in sorted(types.items()):
        q, r, v = q_by.get(qid), r_by.get(qid), v_by.get(qid)
        if v is None:
            problems.append(f"{qid}: 변형 답변이 없다")
            continue
        if q is None or r is None or r["status"] != "ok":
            problems.append(f"{qid}: 질문이 없거나 검색을 통과하지 못했다")
            continue
        if v["type"] != t:
            problems.append(f"{qid}: 배정은 {t} 인데 변형 답변은 {v['type']} 이다")
            continue
        if t == 1 and v["answer"] != q["answer"]:
            problems.append(f"{qid}: ①은 멀쩡한 답변과 글자까지 같아야 한다")
        if t != 1 and v["answer"] == q["answer"]:
            problems.append(f"{qid}: 변형 답변이 멀쩡한 답변과 같다")
        if t in (6, 8) and q.get("two_part") is not False:
            problems.append(f"{qid}: ⑥, ⑧ 은 답이 하나인 질문(two_part false)에만 만든다")
        if t == 8:
            c = q.get("contrast") or {}
            other, asked = c.get("other", {}).get("value"), c.get("asked", {}).get("value")
            if not other or not value_in(other, v["answer"]) or (asked and value_in(asked, v["answer"])):
                problems.append(f"{qid}: ⑧ 은 다른 대상의 값({other})으로 답하고 묻는 대상의 값({asked})은 쓰지 않아야 한다")
        if t == 6:
            # 스펙 3-2절: 바꿔 넣은 값이 근거 청크 전문 어디에도 없어야 한다. 옛 값이나 다른 대상의 값이 근거에
            # 글자로 있으면 ⑥ 이 아니라 근거에 적힌 값으로 답한 것이 된다.
            new, old = v.get("new_value") or "", v.get("old_value") or ""
            if not isinstance(new, str) or not isinstance(old, str):
                # 35000 처럼 숫자로 적으면 value_in 의 글자 비교가 TypeError 로 멈춘다. 원인을 바로 알려 준다.
                problems.append(f"{qid}: ⑥ 의 old_value/new_value 는 따옴표로 감싼 글자로 적는다")
                continue
            if not new or not value_in(new, v["answer"]):
                problems.append(f"{qid}: ⑥ 은 바꿔 넣은 값을 new_value 에 답변의 글자 그대로 적어야 한다")
            elif any(value_in(new, s["content"]) for s in r["sources"]):
                problems.append(f"{qid}: ⑥ 의 새 값({new})이 근거 청크에 글자로 있다. 근거 어디에도 없는 값으로 바꾼다")
            # 바꾸기 전 값(old_value)이 변형 답변에 남으면 근거와 맞는 주장과 반대인 주장이 함께 있는 답변이 된다
            # ("35,000원 이상이면 무료입니다. 기존 기준은 30,000원입니다."). 1점(반대)과 3점(섞임) 사이에서 정답 점수가
            # 하나로 정해지지 않는다(스펙 3-2절의 원칙). 그래서 옛 값이 멀쩡한 답변에는 있고 변형 답변에는 없는지 본다.
            if not old or not value_in(old, q["answer"]):
                problems.append(f"{qid}: ⑥ 은 바꾸기 전 값을 old_value 에 멀쩡한 답변의 글자 그대로 적어야 한다")
            elif value_in(old, v["answer"]):
                problems.append(f"{qid}: ⑥ 의 변형 답변에 바꾸기 전 값({old})이 남아 있다. 옛 값을 답변에서 지운다")
        cid = case_id_of(q["domain"], q["question"], v["answer"])
        if cid in key:
            problems.append(f"{qid}: 다른 문항과 문항 id 가 같다({cid})")
            continue
        sources = [{"filename": s["filename"], "content": s["content"]} for s in r["sources"]]
        rows.append({"case_id": cid, "domain": q["domain"],
                     "messages": build_messages(q["question"], sources, v["answer"]),
                     "search_settings": r["settings"]})
        key[cid] = {"qid": qid, "domain": q["domain"], "type": t, "table_score": TABLE_SCORE[t]}
    if problems:
        raise ExportProblem(problems)
    # case_id 로 먼저 줄 세운 뒤 고정 시드로 섞는다. 분야나 유형 순서가 시험지 순서에 남지 않게 한다.
    rows.sort(key=lambda row: row["case_id"])
    random.Random(SEED).shuffle(rows)
    return rows, key


def load_and_build() -> tuple[list[dict], dict[str, dict]]:
    return build_cases(read_jsonl(QUESTIONS), read_jsonl(RETRIEVED),
                       assigned_types(read_json(ASSIGNMENT)), read_jsonl(VARIANTS))


def apply_review(key: dict[str, dict], reviews: list[dict]) -> tuple[dict, dict, list[str]]:
    """검수 결과를 반영한다(스펙 4절). (남긴 문항, 버린 문항, 문제 목록) 을 돌려준다.

    사용자가 판단하지 않은 불일치 문항을 조용히 버리지 않고 문제로 알린다. 버리는 것도 사용자의 판단으로
    review.jsonl 에 남아야 보고서에 버린 이유를 적을 수 있다.
    """
    by: dict[str, dict] = {}
    problems: list[str] = []
    for r in reviews:
        if r["case_id"] in by:
            problems.append(f"{r['case_id']}: 검수 줄이 두 개다")
        by[r["case_id"]] = r
    kept: dict[str, dict] = {}
    dropped: dict[str, dict] = {}
    for cid, k in sorted(key.items()):
        r = by.get(cid)
        if r is None or r.get("review_score") not in SCALE:
            problems.append(f"{cid}: 검수 점수가 없다")
            continue
        base = {**k, "review_score": r["review_score"]}   # {**a, ...} 는 a 를 복사하고 키를 더한 새 dict 다
        if r["review_score"] == k["table_score"]:
            kept[cid] = {**base, "score": k["table_score"], "decision": "match"}
            continue
        decision, reason = r.get("user_decision"), (r.get("reason") or "").strip()
        if decision == "keep" and reason:
            kept[cid] = {**base, "score": k["table_score"], "decision": "keep", "reason": reason}
        elif decision == "override" and r.get("override_score") in SCALE and reason:
            kept[cid] = {**base, "score": r["override_score"], "decision": "override", "reason": reason}
        elif decision == "drop" and reason:
            dropped[cid] = {**base, "reason": reason}
        else:
            problems.append(f"{cid}: 검수 점수({r['review_score']})와 정답 점수({k['table_score']})가 달라 "
                            f"사용자 판단(keep, override, drop)과 이유가 필요하다")
    for cid in sorted(set(by) - set(key)):
        problems.append(f"{cid}: 검수 파일에 있지만 시험지에 없는 문항이다")
    return kept, dropped, problems


def _write(rows: list[dict], doc: dict) -> str:
    write_jsonl(CASES, rows)
    sha = sha256_file(CASES)
    # 첫 줄은 시험지 해시(다른 도구는 split()[0] 으로 이 값만 읽는다), 둘째 줄은 공통 지시문 해시(앞 실험과 같다).
    CASES_SHA.write_text(f"{sha}  cases.jsonl\n{prompt_sha256()}  prompt\n", encoding="utf-8")
    write_json(ANSWER_KEY, {**doc, "cases_sha256": sha, "prompt_sha256": prompt_sha256()})
    return sha


def cmd_draft() -> int:
    # 동결(E11) 뒤에 draft 를 다시 만들면 최종 시험지와 정답 파일을 검수 전 판으로 덮는다. M1 채점 도구는 단계를
    # 보지 않고 같은 폴더의 해시만 대조하므로, 그대로 E12 를 돌리면 검수 전 시험지에 뉴런을 쓴다. 그래서 거절한다.
    if ANSWER_KEY.exists() and read_json(ANSWER_KEY).get("stage") == "final":
        print(f"{ANSWER_KEY.name} 가 이미 최종본(final)입니다. draft 로 덮지 않습니다. "
              "보충으로 다시 만들어야 하면 사용자에게 알린 뒤 final 커밋을 되돌리고 다시 실행하세요.")
        return 1
    rows, key = load_and_build()
    sha = _write(rows, {"stage": "draft", "seed": SEED, "cases": key, "dropped": {}})
    reviewed = {r["case_id"] for r in read_jsonl(REVIEW)}
    todo = sum(1 for cid in key if cid not in reviewed)
    print(f"시험지 {len(rows)}문항, SHA-256 {sha}. 검수 점수가 아직 없는 문항 {todo}개.")
    return 0


def cmd_mismatches() -> int:
    rows, key = load_and_build()
    by_id = {r["case_id"]: r for r in rows}
    notes = {v["qid"]: v.get("note", "") for v in read_jsonl(VARIANTS)}
    reviews = {r["case_id"]: r for r in read_jsonl(REVIEW)}
    out = ["# 검수 점수와 정답 점수가 다른 문항", "",
           "이 파일에는 변형 유형이 적혀 있다. 검수 세션에 주지 않는다.", ""]
    n = 0
    for cid, k in sorted(key.items()):
        r = reviews.get(cid)
        if r is None or r.get("review_score") == k["table_score"] or r.get("user_decision"):
            continue
        n += 1
        body = by_id[cid]["messages"][1]["content"]
        fence = fence_for(body)
        out += [f"## {cid}", "",
                f"- 분야 {k['domain']}, {TYPE_NAMES[k['type']]}, 대응표 점수 {k['table_score']}, 검수 점수 {r['review_score']}",
                f"- 검수 메모: {r.get('review_note', '')}",
                f"- 출제 메모: {notes.get(k['qid'], '')}", "",
                fence, body, fence, ""]
    MISMATCHES.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"사용자 판단이 필요한 문항 {n}개. 목록: {MISMATCHES}")
    return 0


def cmd_final() -> int:
    rows, key = load_and_build()
    kept, dropped, problems = apply_review(key, read_jsonl(REVIEW))
    if problems:
        print("최종 시험지를 만들지 않았습니다.")
        for p in problems[:20]:
            print(f"  - {p}")
        return 1
    rows = [r for r in rows if r["case_id"] in kept]   # 섞인 순서를 그대로 두고 버린 문항만 뺀다
    sha = _write(rows, {"stage": "final", "seed": SEED, "cases": kept, "dropped": dropped})
    print(f"최종 시험지 {len(rows)}문항(버린 문항 {len(dropped)}개). SHA-256: {sha}")
    print("코랩 노트북(notebooks/judge5v2_colab.ipynb)의 EXPECTED_SHA256 에 이 값을 넣으세요(계획 E11).")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="채점 모델 비교 v2 의 시험지 파일과 정답 파일을 만든다")
    p.add_argument("cmd", choices=("draft", "mismatches", "final"))
    args = p.parse_args(argv)
    try:
        return {"draft": cmd_draft, "mismatches": cmd_mismatches, "final": cmd_final}[args.cmd]()
    except ExportProblem as e:
        print("시험지를 만들지 않았습니다. 아래를 고친 뒤 다시 실행하세요.")
        for p_ in e.problems[:30]:
            print(f"  - {p_}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 점검이 통과하는지 본다**

Run: `$PY -m tools.judge5v2_export_check | tail -1`
Expected: `10가지 전부 통과.` (처음 계획은 7가지. `f17877a` 가 셋을 더했다)

- [ ] **Step 5: 커밋한다**

```bash
git add ai-service/tools/judge5v2_export.py ai-service/tools/judge5v2_export_check.py
git commit -m "feat: 채점 모델 비교 v2 의 시험지와 정답 파일을 만들고 검수 결과를 반영하는 도구를 추가한다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/tools/judge5v2_export.py ai-service/tools/judge5v2_export_check.py
```

**리뷰 포인트:** 시험지 줄에 `qid`, 유형, 정답 점수 중 어느 것도 들어가지 않는가. 사용자 판단이 없는 불일치 문항이 조용히 남거나 버려지지 않고 멈추는가. ⑥ 의 `new_value` 를 근거 청크 전부에서 찾는가(질문과 관계없는 청크 포함). ⑥ 의 `old_value` 가 변형 답변에 남지 않았는지 보는가.

---

### Task 7: 관문 도구

**Files:**
- Create: `ai-service/tools/judge5v2_gate.py`
- Create: `ai-service/tools/judge5v2_gate_check.py`

**Interfaces:**
- Consumes: 태스크 1 의 상수. 명령으로 실행할 때만 태스크 6 의 `apply_review`, `load_and_build` (함수 안에서 늦게 불러온다. 그래서 태스크 6 이 끝나기 전에도 이 태스크를 만들고 점검할 수 있다)
- Produces: `Condition(no: int, ok: bool, text: str)`, `fake_within1(scores: list[int]) -> dict[int, float]`, `check_gate(cases: list[dict]) -> list[Condition]` (`cases` 의 원소는 `domain`, `type`, `score` 를 가진다), `render(conds) -> str`. 명령 `python -m tools.judge5v2_gate`

- [ ] **Step 1: 실패하는 점검을 쓴다** (`judge5v2_gate_check.py`)

```python
"""tools.judge5v2_gate 의 점검. DB 도 외부 API 도 쓰지 않는다.

실행:  cd ai-service && python -m tools.judge5v2_gate_check

관문 계산이 틀리면 변별력이 없는 시험 문제로 모델을 돌리게 된다. 앞 실험이 그렇게 끝났다(스펙 1-1절).
"""
from __future__ import annotations

from .judge5v2_files import DOMAINS, QUOTA, TABLE_SCORE
from .judge5v2_gate import check_gate, fake_within1


def _full() -> list[dict]:
    return [{"domain": d, "type": t, "score": TABLE_SCORE[t]} for d in DOMAINS for t, n in QUOTA.items() for _ in range(n)]


def check_fake_ratios_match_spec() -> None:
    """스펙 7-1절의 가짜 모델 수치: 늘 5점 45%, 늘 4점 60%, 늘 3점 40%, 늘 2점 55%, 늘 1점 40%."""
    got = {k: round(v, 4) for k, v in fake_within1([c["score"] for c in _full()]).items()}
    assert got == {1: 0.40, 2: 0.55, 3: 0.40, 4: 0.60, 5: 0.45}, got


def check_gate_passes_on_full_quota() -> None:
    assert all(c.ok for c in check_gate(_full()))


def check_gate_fails_each_condition() -> None:
    def failed(cases: list[dict]) -> set[int]:
        return {c.no for c in check_gate(cases) if not c.ok}

    full = _full()
    assert 1 in failed(full[:199])
    assert {2, 3, 5} <= failed([dict(c, score=5) for c in full])          # 모두 5점
    no_hr = [c for c in full if c["domain"] != "hr"] + [c for c in full if c["domain"] == "hr"][:39]
    assert 4 in failed(no_hr)                                              # hr 이 39문항
    eighth = [c for c in full if c["type"] == 8]
    assert 4 in failed([c for c in full if c["type"] != 8] + eighth[:14])  # ⑧ 이 14문항
    assert failed([]) >= {1, 2, 3, 4, 5}                                   # 빈 시험은 모두 실패


CHECKS = [check_fake_ratios_match_spec, check_gate_passes_on_full_quota, check_gate_fails_each_condition]


def main() -> None:
    for fn in CHECKS:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(CHECKS)}가지 전부 통과.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 점검이 실패하는지 본다**

Run: `$PY -m tools.judge5v2_gate_check`
Expected: `ModuleNotFoundError: No module named 'tools.judge5v2_gate'`

- [ ] **Step 3: 관문 도구를 쓴다** (`judge5v2_gate.py`)

```python
"""채점 모델 비교 v2 의 변별력 관문(스펙 7-2절). 모델을 돌리기 전에 다섯 조건을 모두 넘는지 본다.

실행:  cd ai-service && $PY -m tools.judge5v2_gate
산출:  testdata/judge5v2/gate.md. 하나라도 통과하지 못하면 종료 코드가 1 이다.

관문은 검수(스펙 4절)를 반영한 정답 점수로 계산한다. 그래서 review.jsonl 에 사용자 판단이 빠진
불일치 문항이 있으면 계산하지 않고 멈춘다.
"""
from __future__ import annotations

import sys
from collections import Counter
from dataclasses import dataclass

from .judge5 import SCALE
from .judge5v2_files import DOMAINS, GATE, REVIEW, read_jsonl

MIN_TOTAL = 200
FIVE_LOW, FIVE_HIGH = 0.25, 0.35
LOW_SCORES = (4, 3, 2, 1)
MIN_PER_LOW_SCORE = 20
MIN_PER_DOMAIN = 40
MIN_TYPE8 = 15
MAX_FAKE = 0.65


@dataclass(frozen=True)
class Condition:
    no: int
    ok: bool
    text: str


def fake_within1(scores: list[int]) -> dict[int, float]:
    """가짜 모델(늘 k점)의 거리 1 이하 비율. 문항이 없으면 0.0 이다."""
    n = len(scores)
    return {k: (sum(1 for s in scores if abs(s - k) <= 1) / n if n else 0.0) for k in SCALE}


def check_gate(cases: list[dict]) -> list[Condition]:
    n = len(cases)
    scores = [c["score"] for c in cases]
    by_score = Counter(scores)
    by_domain = Counter(c["domain"] for c in cases)
    n8 = sum(1 for c in cases if c["type"] == 8)
    five = by_score[5] / n if n else 0.0
    fakes = fake_within1(scores)
    best = max(fakes.values()) if n else 1.0     # 문항이 없으면 통과시키지 않으려고 1.0 으로 둔다
    return [
        Condition(1, n >= MIN_TOTAL, f"남은 문항 {n}개(기준 {MIN_TOTAL}개 이상)"),
        Condition(2, n > 0 and FIVE_LOW <= five <= FIVE_HIGH, f"정답 점수 5 의 비율 {five:.1%}(기준 25~35%)"),
        Condition(3, all(by_score[s] >= MIN_PER_LOW_SCORE for s in LOW_SCORES),
                  "정답 점수별 " + ", ".join(f"{s}점 {by_score[s]}개" for s in LOW_SCORES) + "(기준 각 20개 이상)"),
        Condition(4, all(by_domain[d] >= MIN_PER_DOMAIN for d in DOMAINS) and n8 >= MIN_TYPE8,
                  "분야별 " + ", ".join(f"{d} {by_domain[d]}개" for d in DOMAINS)
                  + f", ⑧ {n8}개(기준 분야마다 40개 이상, ⑧ 15개 이상)"),
        Condition(5, best <= MAX_FAKE,
                  "가짜 모델의 거리 1 이하 비율 " + ", ".join(f"늘 {k}점 {v:.1%}" for k, v in sorted(fakes.items(), reverse=True))
                  + "(기준 가장 높은 값 65% 이하)"),
    ]


def render(conds: list[Condition]) -> str:
    lines = ["# 변별력 관문 (스펙 7-2절)", "", "| 번호 | 통과 | 내용 |", "|---|---|---|"]
    lines += [f"| {c.no} | {'통과' if c.ok else '실패'} | {c.text} |" for c in conds]
    lines += ["", "모두 통과" if all(c.ok for c in conds) else "통과하지 못한 조건이 있다. 모델을 돌리지 않는다."]
    return "\n".join(lines) + "\n"


def main() -> int:
    # 여기서 늦게 불러오는 이유: 관문 계산(check_gate)만 점검할 때는 내보내기 도구가 없어도 되게 한다.
    # 두 파일을 서로 다른 세션이 동시에 만든다.
    from .judge5v2_export import apply_review, load_and_build

    _, key = load_and_build()
    kept, _, problems = apply_review(key, read_jsonl(REVIEW))
    if problems:
        print("관문을 계산하지 않았습니다. 검수가 끝나지 않았습니다.")
        for p in problems[:20]:
            print(f"  - {p}")
        return 1
    conds = check_gate(list(kept.values()))
    text = render(conds)
    GATE.write_text(text, encoding="utf-8")
    print(text)
    return 0 if all(c.ok for c in conds) else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 점검이 통과하는지 본다**

Run: `$PY -m tools.judge5v2_gate_check | tail -1`
Expected: `3가지 전부 통과.`

- [ ] **Step 5: 커밋한다**

```bash
git add ai-service/tools/judge5v2_gate.py ai-service/tools/judge5v2_gate_check.py
git commit -m "feat: 채점 모델 비교 v2 의 변별력 관문 도구를 추가한다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/tools/judge5v2_gate.py ai-service/tools/judge5v2_gate_check.py
```

**리뷰 포인트:** 다섯 조건의 숫자가 스펙 7-2절 표와 같은가. 조건 2, 3, 5 가 변형 유형이 아니라 최종 정답 점수로 계산되는가(스펙 6-1절 끝 문단).

---

### Task 8: 보고서 도구

**Files:**
- Create: `ai-service/tools/judge5v2_report.py`
- Create: `ai-service/tools/judge5v2_report_check.py`

**Interfaces:**
- Consumes: 태스크 2 의 `RULES_V2`, `parse_result(..., rules=)`, `Comparison.verdict(..., basis=)`, `replacement_failures(..., basis=, severe=)`. 기존 `judge5.summarize`, `judge5.compare`, `judge5_report.load_run`, `judge5_report.load_finishes`, `judge5_report.ReportProblem`. 태스크 7 의 `check_gate`, `fake_within1`. 태스크 1 의 상수와 `latest_by_qid`
- Produces: `Errors(miss, false_alarm, severe_miss)`, `error_counts(pairs: list[tuple[int, int | None]]) -> Errors`, `read_scores(outputs: dict[str, str], finishes: dict[str, str | None]) -> tuple[dict[str, int | None], dict[str, int]]`, `build(answer_key=ANSWER_KEY, cases_sha=CASES_SHA, results_dir=RESULTS_DIR, retrieved=RETRIEVED, assignment=ASSIGNMENT) -> str`. 명령 `python -m tools.judge5v2_report`

- [ ] **Step 1: 실패하는 점검을 쓴다** (`judge5v2_report_check.py`)

```python
"""tools.judge5v2_report 의 점검. DB 도 외부 API 도 쓰지 않는다.

실행:  cd ai-service && python -m tools.judge5v2_report_check

비교 쌍의 순서, 놓침과 헛경보의 방향, 대괄호 끝 규칙의 적용 중 하나만 틀려도 결론이 바뀐다.
숫자는 그럴듯하게 나오므로 눈으로는 잡히지 않는다.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from .judge5v2_report import build, error_counts

_KEY = [5, 5, 5, 4, 3, 2, 1, 1, 1, 1]
_TYPE_OF = {5: 1, 4: 3, 3: 4, 2: 5, 1: 6}


def check_error_counts_follow_spec() -> None:
    """놓침, 헛경보, 심각한 놓침은 정답 점수로 정의한다(스펙 6-1절). 못 읽음은 세지 않는다."""
    e = error_counts([(4, 5), (1, 5), (1, 4), (5, 4), (5, 5), (1, None), (3, 3)])
    assert (e.miss, e.false_alarm, e.severe_miss) == (2, 1, 2)


def _write_inputs(d: Path) -> dict:
    ids = [f"c{i:02d}" for i in range(len(_KEY))]
    cases = {cid: {"qid": f"q{i}", "domain": "shop", "type": _TYPE_OF[k], "table_score": k, "score": k,
                   "review_score": k, "decision": "match"} for i, (cid, k) in enumerate(zip(ids, _KEY))}
    (d / "key.json").write_text(json.dumps({"stage": "final", "cases_sha256": "s", "cases": cases, "dropped": {}}))
    (d / "sha").write_text("s  cases.jsonl\n")
    (d / "retrieved.jsonl").write_text("".join(
        json.dumps({"qid": f"q{i}", "domain": "shop", "status": "ok", "drop_reason": None}) + "\n" for i in range(10))
        + json.dumps({"qid": "qx", "domain": "hr", "status": "dropped", "drop_reason": "answerable"}) + "\n")
    (d / "assignment.json").write_text(json.dumps({"seed": 1, "rounds": [{"domains": {
        "shop": {"types": {f"q{i}": _TYPE_OF[k] for i, k in enumerate(_KEY)}, "unused": [], "eighth_to_sixth": 0}}}]}))
    res = d / "results"
    res.mkdir()

    def write(name: str, outs: list[str]) -> None:
        (res / name).write_text("".join(
            json.dumps({"case_id": c, "output": o, "finish": "stop", "cases_sha256": "s"}) + "\n" for c, o in zip(ids, outs)))

    write("M1_run1.jsonl", ["[RESULT] 4"] * 10)
    write("M3_run1.jsonl", ["[RESULT] 5"] * 10)
    write("M4_run1.jsonl", [f"이유를 적었다. [{k}]" for k in _KEY])   # 대괄호 끝 규칙으로만 읽힌다
    return {"answer_key": d / "key.json", "cases_sha": d / "sha", "results_dir": res,
            "retrieved": d / "retrieved.jsonl", "assignment": d / "assignment.json"}


def check_build_compares_in_the_right_direction() -> None:
    """M1 은 전부 4, M3 는 전부 5, M4 는 대응표와 같다(대괄호 끝으로 적었다).
    M3 와 M1: M3 가 더 가까움 3, M1 이 더 가까움 7. M3 와 M4: 0 대 7 로 M4. M4 만 교체 후보다."""
    with tempfile.TemporaryDirectory() as tmp:
        text = build(**_write_inputs(Path(tmp)))
    assert "| M4 | 10/10 | 0 | 0 | 0 | 10 |" in text                     # v2 규칙으로 모두 읽혔다
    assert "| M3 | 4/10 | 7 | 0 | 4 |" in text                            # 놓침 7, 헛경보 0, 심각한 놓침 4
    assert "- M3 와 M1 (서비스의 채점 모델을 M3 로 바꿔도 되는가): M3 가 더 가까움 3, M1 가 더 가까움 7" in text
    assert "M3 가 더 가까움 0, M4 가 더 가까움 7" in text and "판정: **M4 가 대응표에 더 가깝다**" in text
    assert "- M4: **교체 후보**" in text
    assert "- M3: 아님. 거리 1 이하 사례가 M1 보다 적다(4 < 5)" in text
    assert "hr: 검색한 질문 1개 중 버림 answerable 1" in text
    assert "| 늘 4점 |" in text                                          # 가짜 모델 행


def check_build_counts_no_finish_and_nondefault() -> None:
    """못 읽음 중 512 잘림, finish 기록 없음, 그 밖의 finish 값을 따로 센다. 검색 줄의 nondefault 수와 시험지의
    검색 설정 종류를 적는다."""
    with tempfile.TemporaryDirectory() as tmp:
        paths = _write_inputs(Path(tmp))
        m4 = paths["results_dir"] / "M4_run1.jsonl"
        rows = [json.loads(l) for l in m4.read_text().splitlines()]
        for i, r in enumerate(rows):
            # 대괄호 끝은 stop 일 때만 읽는다. content_filter 는 stop, length, 기록 없음이 아닌 그 밖의 값의 예다.
            r["finish"] = None if i < 3 else "length" if i < 5 else "content_filter" if i == 5 else "stop"
        m4.write_text("".join(json.dumps(r) + "\n" for r in rows))
        with paths["retrieved"].open("a") as f:   # q0 를 다른 설정으로 다시 검색한 줄
            f.write(json.dumps({"qid": "q0", "domain": "shop", "status": "ok", "drop_reason": None,
                                "settings": {"top_k": 8}, "nondefault": {"top_k": {"default": 5, "actual": 8}}}) + "\n")
            # 시험지에 없는 질문(qy)의 줄은 시험지의 설정 종류에 세지 않는다.
            f.write(json.dumps({"qid": "qy", "domain": "hr", "status": "dropped", "drop_reason": "max_distance",
                                "settings": {"top_k": 3}}) + "\n")
        text = build(**paths)
    assert "(missing 6, 그중 2개는 512 토큰에서 잘림, 3개는 finish 기록 없음, 1개는 finish 가 그 밖의 값)" in text, text
    assert "검색 줄(nondefault) 1개, 최종 시험지의 검색 설정 2가지" in text


def check_settings_kinds_use_last_search_line() -> None:
    """시험지 문항의 앞 검색 줄이 다른 설정이어도 마지막 줄이 기본이면 설정은 1가지다. 시험지는 마지막 줄의
    settings 를 옮기므로(judge5v2_export), 앞 줄까지 세면 시험지에 없는 설정을 섞였다고 잘못 적는다."""
    with tempfile.TemporaryDirectory() as tmp:
        paths = _write_inputs(Path(tmp))
        base = paths["retrieved"].read_text()
        earlier = json.dumps({"qid": "q1", "domain": "shop", "status": "dropped", "drop_reason": "rerank_failed",
                              "settings": {"top_k": 8}}) + "\n"
        paths["retrieved"].write_text(earlier + base)   # q1 의 앞 줄은 다른 설정, 마지막 줄은 다른 문항과 같은 설정
        text = build(**paths)
    assert "최종 시험지의 검색 설정 1가지" in text, text


def check_build_counts_excluded_once() -> None:
    """정답이 근거 청크 밖이라 뺀 질문을 분야, 원인별로 한 번씩 센다. 회차마다 같은 제외가 기록돼도 두 번 세지 않고,
    "쓰지 않은 질문" 에도 다시 넣지 않는다."""
    with tempfile.TemporaryDirectory() as tmp:
        paths = _write_inputs(Path(tmp))
        with paths["retrieved"].open("a") as f:   # 검색은 통과했지만 제외한 shop 질문 둘
            for q in ("qe1", "qe2"):
                f.write(json.dumps({"qid": q, "domain": "shop", "status": "ok", "drop_reason": None}) + "\n")
        doc = json.loads(paths["assignment"].read_text())
        ex = {"qe1": "answer_not_in_top5", "qe2": "partial_answer_not_in_top5"}
        rnd = doc["rounds"][0]
        empty = {"types": {}, "unused": [], "eighth_to_sixth": 0}
        doc["rounds"] = [dict(rnd, excluded=ex), {"domains": {"shop": empty}, "excluded": ex}]   # 두 회차가 같은 제외를 기록
        paths["assignment"].write_text(json.dumps(doc))
        text = build(**paths)
    assert "- shop: answer_not_in_top5 1, partial_answer_not_in_top5 1" in text, text
    assert "- hr: 없음" in text
    assert "- shop: 검색을 통과하고 제외되지 않은 질문 10개 중 모든 회차 뒤에도 쓰지 않은 질문 0개" in text, text


def check_build_lifted_exclusion_not_counted_twice() -> None:
    """회차 0 이 제외한 질문이 뒤 회차에서 제외가 풀려 배정되면, 제외로 세지 않고 배정으로만 센다.
    변이: 합집합에서 배정된 질문을 빼지 않으면 shop 의 제외가 2개가 되어 이 점검이 실패한다."""
    with tempfile.TemporaryDirectory() as tmp:
        paths = _write_inputs(Path(tmp))
        with paths["retrieved"].open("a") as f:
            for q in ("qe1", "qe2"):
                f.write(json.dumps({"qid": q, "domain": "shop", "status": "ok", "drop_reason": None}) + "\n")
        doc = json.loads(paths["assignment"].read_text())
        rnd = doc["rounds"][0]
        lifted = {"types": {"qe2": 1}, "unused": [], "eighth_to_sixth": 0}   # 회차 1 에서 qe2 의 제외가 풀려 ① 을 받았다
        doc["rounds"] = [dict(rnd, excluded={"qe1": "answer_not_in_top5", "qe2": "partial_answer_not_in_top5"}),
                         {"domains": {"shop": lifted}, "excluded": {"qe1": "answer_not_in_top5"}}]
        paths["assignment"].write_text(json.dumps(doc))
        text = build(**paths)
    assert "- shop: answer_not_in_top5 1\n" in text, text
    assert "- shop: 검색을 통과하고 제외되지 않은 질문 11개 중 모든 회차 뒤에도 쓰지 않은 질문 0개" in text, text


def check_build_refuses_draft_key() -> None:
    from .judge5_report import ReportProblem
    with tempfile.TemporaryDirectory() as tmp:
        paths = _write_inputs(Path(tmp))
        doc = json.loads(paths["answer_key"].read_text())
        paths["answer_key"].write_text(json.dumps({**doc, "stage": "draft"}))
        try:
            build(**paths)
        except ReportProblem:
            return
    raise AssertionError("검수 전 정답 파일로는 보고서를 만들지 않는다")


CHECKS = [check_error_counts_follow_spec, check_build_compares_in_the_right_direction, check_build_counts_no_finish_and_nondefault,
          check_settings_kinds_use_last_search_line, check_build_counts_excluded_once, check_build_lifted_exclusion_not_counted_twice,
          check_build_refuses_draft_key]


def main() -> None:
    for fn in CHECKS:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(CHECKS)}가지 전부 통과.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 점검이 실패하는지 본다**

Run: `$PY -m tools.judge5v2_report_check`
Expected: `ModuleNotFoundError: No module named 'tools.judge5v2_report'`

- [ ] **Step 3: 보고서 도구를 쓴다** (`judge5v2_report.py`)

```python
"""채점 모델 비교 v2 의 보고서. v2 스펙 6절을 계산한다.

실행:  cd ai-service && $PY -m tools.judge5v2_report
산출:  testdata/judge5v2/report.md (화면에도 같은 내용을 찍는다)

판정 규칙은 스펙 6절에 측정 전에 고정돼 있다. 이 도구는 그 규칙을 계산할 뿐이고, 결과를 보고 규칙을
바꾸는 자리가 아니다. 앞 실험과 다른 점: 정답이 사람 라벨이 아니라 대응표이고(판정 문구의 basis),
점수는 v2 규칙으로 읽고, 교체 후보 기준에 심각한 놓침이 더해졌다.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .judge5 import MODELS, RULES_V2, SCALE, Summary, compare, parse_result, replacement_failures, summarize
from .judge5_report import ReportProblem, load_finishes, load_run
from .judge5v2_assign import assigned_types
from .judge5v2_files import (
    ANSWER_KEY, ASSIGNMENT, CASES_SHA, DOMAINS, REPORT, RESULTS_DIR, RETRIEVED, TYPE_NAMES, latest_by_qid, read_json,
    read_jsonl,
)
from .judge5v2_gate import check_gate, fake_within1

MODEL_KEYS = ("M1", "M3", "M4")
BASIS = "대응표"
PAIRS = (("M3", "M1", "서비스의 채점 모델을 M3 로 바꿔도 되는가"),
         ("M3", "M4", "같은 바탕 모델에 채점 학습을 더한 효과가 있는가"))


@dataclass(frozen=True)
class Errors:
    miss: int          # 정답 점수 4 이하에 5점
    false_alarm: int   # 정답 점수 5 에 4점 이하
    severe_miss: int   # 정답 점수 1 에 4점 이상


def error_counts(pairs: list[tuple[int, int | None]]) -> Errors:
    """(정답 점수, 모델 점수 또는 None) 목록에서 스펙 6-1절의 세 수를 센다. 못 읽음은 세지 않는다."""
    read = [(k, m) for k, m in pairs if m is not None]
    return Errors(
        miss=sum(1 for k, m in read if k <= 4 and m == 5),
        false_alarm=sum(1 for k, m in read if k == 5 and m <= 4),
        severe_miss=sum(1 for k, m in read if k == 1 and m >= 4),
    )


def read_scores(outputs: dict[str, str], finishes: dict[str, str | None]) -> tuple[dict[str, int | None], dict[str, int]]:
    scores: dict[str, int | None] = {}
    kinds: Counter = Counter()
    for cid, text in outputs.items():
        v, status = parse_result(text, finishes.get(cid), rules=RULES_V2)
        scores[cid] = v
        kinds[status] += 1
    return scores, dict(kinds)


def _fmt(x: float | None) -> str:
    return "계산 불가" if x is None else f"{round(x, 3):.3f}"


def _row(name: str, s: Summary, e: Errors, note: str = "") -> str:
    return (f"| {name} | {s.within1}/{s.total} | {e.miss} | {e.false_alarm} | {e.severe_miss} | {s.exact} "
            f"| {_fmt(s.mean_distance)} | {s.unread}{note} |")


def _pipeline(ak: dict, retrieved: list[dict], assignment: dict) -> list[str]:
    # 검색 도구의 --allow-nondefault 로 돌린 줄은 nondefault 키를 가진다. 시도 기록까지 모두 센다(마지막 줄만이 아니다).
    nondefault = sum(1 for r in retrieved if "nondefault" in r)
    # 호출 실패로 다시 검색한 질문은 줄이 여럿이다. 질문마다 마지막 줄이 판정이다(계획 형식 2).
    retrieved = latest_by_qid(retrieved)
    # 시험지의 search_settings 는 그 질문의 마지막 검색 줄의 settings 를 그대로 옮긴 것이다(judge5v2_export).
    # 그래서 시험지 파일을 따로 읽지 않고 여기서 센다. dict 는 집합에 못 넣어서 키를 고정한 JSON 글자로 바꾼다.
    in_cases = {c["qid"] for c in ak["cases"].values()}
    kinds = {json.dumps(r.get("settings"), ensure_ascii=False, sort_keys=True) for r in retrieved if r["qid"] in in_cases}
    out = ["## 문항이 줄어든 경위", "",
           f"검색 설정: 기본값과 다른 설정으로 돌린 검색 줄(nondefault) {nondefault}개, "
           f"최종 시험지의 검색 설정 {len(kinds)}가지(스펙 2-3절은 모두 기본 설정 한 가지다)", "",
           "검색에서 버린 질문(스펙 2-3절, 다시 검색한 뒤의 판정):", ""]
    for d in DOMAINS:
        rows = [r for r in retrieved if r["domain"] == d]
        drops = Counter(r["drop_reason"] for r in rows if r["status"] != "ok")
        parts = ", ".join(f"{reason} {n}" for reason, n in sorted(drops.items())) or "없음"
        out.append(f"- {d}: 검색한 질문 {len(rows)}개 중 버림 {parts}")
    # 검색은 통과했지만 정답이 근거 청크 밖이라 배정 후보에서 뺀 질문(스펙 2-3절). 회차마다 그때의 excluded.json
    # 전체를 기록하므로(judge5v2_assign 의 _round_doc) 회차의 excluded_counts 를 더하면 같은 질문을 회차 수만큼
    # 센다. 그래서 회차들의 excluded({qid: 원인})를 합친 뒤 한 번씩 센다. 분야는 검색 줄에서 읽는다.
    excluded: dict[str, str] = {}
    for rnd in assignment["rounds"]:
        excluded.update(rnd.get("excluded") or {})
    # 앞 회차가 제외했다가 뒤 회차에서 제외가 풀려 배정된 질문은 합집합에 남아 있다. 그대로 두면 아래 "배정" 에서
    # 쓴 질문으로도 세고 여기서 제외로도 세어 두 번 들어간다. 마지막 상태는 배정이므로 제외에서 뺀다.
    for qid in assigned_types(assignment):
        excluded.pop(qid, None)
    domain_of = {r["qid"]: r["domain"] for r in retrieved}
    out += ["", "검색은 통과했지만 정답이 근거 청크 밖이라 배정 후보에서 뺀 질문(스펙 2-3절, excluded.json):", ""]
    for d in DOMAINS:
        reasons = Counter(why for q, why in excluded.items() if domain_of.get(q) == d)
        parts = ", ".join(f"{reason} {n}" for reason, n in sorted(reasons.items())) or "없음"
        out.append(f"- {d}: {parts}")
    assigned: dict[str, int] = {}
    moved: Counter = Counter()
    for rnd in assignment["rounds"]:
        for d, res in rnd["domains"].items():
            assigned.update(res["types"])
            moved[d] += res["eighth_to_sixth"]
    out += ["", "배정(스펙 3-3절):", ""]
    for d in DOMAINS:
        # 제외한 질문은 위에서 따로 셌으므로 여기서는 빼고 센다. 빼지 않으면 "쓰지 않은 질문" 에 한 번 더 들어간다.
        ok = [r["qid"] for r in retrieved if r["domain"] == d and r["status"] == "ok" and r["qid"] not in excluded]
        unused = sum(1 for q in ok if q not in assigned)
        # 보충 회차는 앞 회차에서 쓰지 않은 질문도 다시 뽑는다(스펙 3-3절 6). 그래서 모든 회차를 거친 뒤의 수를 적는다.
        out.append(f"- {d}: 검색을 통과하고 제외되지 않은 질문 {len(ok)}개 중 모든 회차 뒤에도 쓰지 않은 질문 {unused}개, "
                   f"⑧ 이 모자라 ⑥ 으로 돌린 문항 {moved[d]}개")
    dec = Counter(c["decision"] for c in ak["cases"].values())
    out += ["", "검수(스펙 4절):", "",
            f"- 검수 점수가 정답 점수와 같았던 문항 {dec['match']}개, 달랐지만 대응표대로 둔 문항 {dec['keep']}개, "
            f"사용자가 정답 점수를 고친 문항 {dec['override']}개, 버린 문항 {len(ak['dropped'])}개"]
    for cid, c in sorted(ak["cases"].items()):
        if c["decision"] == "override":
            out.append(f"  - 고침 {cid} ({TYPE_NAMES[c['type']]}): 대응표 {c['table_score']}점에서 {c['score']}점으로. 이유: {c['reason']}")
    for cid, c in sorted(ak["dropped"].items()):
        out.append(f"  - 버림 {cid} ({TYPE_NAMES[c['type']]}): {c['reason']}")
    by_type = Counter(TYPE_NAMES[c["type"]] for c in ak["dropped"].values())
    if by_type:
        out.append("- 버린 문항의 유형별 수: " + ", ".join(f"{t} {n}" for t, n in sorted(by_type.items())))
    return out


def _breakdown(title: str, groups: dict[str, list[str]], key: dict[str, int],
               scores: dict[str, dict[str, int | None]]) -> list[str]:
    out = [f"### {title}", "", "| 묶음 | 모델 | 문항 | 거리 1 이하 | 놓침 | 헛경보 | 심각한 놓침 | 못 읽음 |",
           "|---|---|---|---|---|---|---|---|"]
    for g, ids in groups.items():
        for m, sc in scores.items():
            pairs = [(key[c], sc[c]) for c in ids]
            s, e = summarize(pairs), error_counts(pairs)
            out.append(f"| {g} | {m} | {len(ids)} | {s.within1} | {e.miss} | {e.false_alarm} | {e.severe_miss} | {s.unread} |")
    return out + [""]


def build(answer_key: Path = ANSWER_KEY, cases_sha: Path = CASES_SHA, results_dir: Path = RESULTS_DIR,
          retrieved: Path = RETRIEVED, assignment: Path = ASSIGNMENT) -> str:
    ak = read_json(answer_key)
    if ak.get("stage") != "final":
        raise ReportProblem("정답 파일이 최종본이 아닙니다. tools.judge5v2_export final 을 먼저 실행하세요.")
    sha = cases_sha.read_text(encoding="utf-8").split()[0]
    if sha != ak["cases_sha256"]:
        raise ReportProblem("정답 파일과 시험지 해시 파일의 해시가 다릅니다. 같은 final 실행의 산출물인지 확인하세요.")
    key = {cid: c["score"] for cid, c in ak["cases"].items()}
    ids = sorted(key)

    scores: dict[str, dict[str, int | None]] = {}
    kinds: dict[str, dict[str, int]] = {}
    cuts: dict[str, int] = {}
    no_finish: dict[str, int] = {}
    other_finish: dict[str, int] = {}
    skipped: dict[str, str] = {}
    for m in MODEL_KEYS:
        run1, skip = results_dir / f"{m}_run1.jsonl", results_dir / f"{m}_skipped.json"
        if skip.exists():
            skipped[m] = json.loads(skip.read_text(encoding="utf-8"))["reason"]
            continue
        if not run1.exists():
            skipped[m] = "결과 파일 없음"
            continue
        outputs = load_run(run1, set(ids), sha)   # 빠진 문항이나 다른 시험지 줄이 있으면 멈춘다(스펙 6-5절)
        finishes = load_finishes(run1)
        scores[m], kinds[m] = read_scores(outputs, finishes)
        cuts[m] = sum(1 for c in ids if scores[m][c] is None and finishes.get(c) == "length")
        # finish 기록이 없는 못 읽음. v2 규칙은 finish 가 stop 이 아니면 대괄호 끝을 읽지 않으므로(스펙 6-4절 세부 규칙 2)
        # 잘림과 따로 센다. 이 수가 크면 모델이 못한 것이 아니라 결과 파일에 finish 를 적지 않은 것일 수 있다.
        no_finish[m] = sum(1 for c in ids if scores[m][c] is None and finishes.get(c) is None)
        # stop, length, 기록 없음이 아닌 값(예: 제공자의 내용 거름). 스펙 6-4절 세부 규칙 2 에 따라 이것도 대괄호 끝을
        # 읽지 않는다. 셋 중 어디에도 안 세면 못 읽음의 원인 일부가 표에서 사라진다.
        other_finish[m] = sum(1 for c in ids if scores[m][c] is None and finishes.get(c) not in (None, "stop", "length"))

    sums = {m: summarize([(key[c], scores[m][c]) for c in ids]) for m in scores}
    errs = {m: error_counts([(key[c], scores[m][c]) for c in ids]) for m in scores}

    out = ["# 채점 모델 비교 v2 결과", "",
           f"문항 {len(ids)}개. 정답 점수 분포: " + ", ".join(f"{v}점 {sum(1 for k in key.values() if k == v)}개" for v in SCALE),
           "분야 분포: " + ", ".join(f"{d} {sum(1 for c in ak['cases'].values() if c['domain'] == d)}개" for d in DOMAINS), ""]
    out += _pipeline(ak, read_jsonl(retrieved), read_json(assignment))
    out += ["", "## 변별력 관문 (스펙 7-2절)", ""]
    out += [f"- {c.no}. {'통과' if c.ok else '실패'}: {c.text}" for c in check_gate(list(ak["cases"].values()))]

    out += ["", "## 모델마다의 수치 (스펙 6-1절)", "",
            "| 모델 | 거리 1 이하 | 놓침 | 헛경보 | 심각한 놓침 | 정확히 같음 | 평균 거리 | 못 읽음 |",
            "|---|---|---|---|---|---|---|---|"]
    for m in scores:
        detail = ", ".join(f"{k} {v}" for k, v in sorted(kinds[m].items()) if k != "ok")
        why = [f"{n}개는 {label}" for n, label in ((cuts[m], "512 토큰에서 잘림"), (no_finish[m], "finish 기록 없음"),
                                                   (other_finish[m], "finish 가 그 밖의 값")) if n]
        note = (f" ({detail}" + (", 그중 " + ", ".join(why) if why else "") + ")") if detail else ""
        out.append(_row(m, sums[m], errs[m], note))
    for m, why in skipped.items():
        out.append(f"| {m} | 제외: {why} | | | | | | |")
    fakes = fake_within1([key[c] for c in ids])
    for k in sorted(SCALE, reverse=True):
        pairs = [(key[c], k) for c in ids]
        out.append(_row(f"늘 {k}점", summarize(pairs), error_counts(pairs)))
    out += ["", "가짜 모델의 거리 1 이하 비율: " + ", ".join(f"늘 {k}점 {v:.1%}" for k, v in sorted(fakes.items(), reverse=True))]

    out += ["", "## 혼동행렬 (행은 정답 점수, 열은 모델 점수)", ""]
    for m in sums:
        out += [f"### {m} ({MODELS[m]})", "", f"| 정답 점수 \\ {m} | " + " | ".join(str(v) for v in SCALE) + " |",
                "|---" * (len(SCALE) + 1) + "|"]
        out += [f"| {h} | " + " | ".join(str(sums[m].confusion[(h, v)]) for v in SCALE) + " |" for h in SCALE]
        out.append("")

    out += ["## 두 모델 비교 (스펙 6-2절)", ""]
    for a, b, what in PAIRS:
        if a not in scores or b not in scores:
            out.append(f"- {a} 와 {b} ({what}): 하지 않음. 결과가 없는 모델이 있다")
            continue
        c = compare(key, scores[a], scores[b])
        out.append(f"- {a} 와 {b} ({what}): {a} 가 더 가까움 {c.a_closer}, {b} 가 더 가까움 {c.b_closer}, "
                   f"같음 {c.ties}, 제외 {c.excluded}, p = {c.p_value:.4f}, 판정: **{c.verdict(a, b, basis=BASIS)}**")

    out += ["", "## 교체 후보 (스펙 6-3절)", ""]
    for k in ("M3", "M4"):
        if k not in sums or "M1" not in sums:
            out.append(f"- {k}: 판단하지 않음. 결과가 없는 모델이 있다")
            continue
        fails = replacement_failures(sums[k], sums["M1"], compare(key, scores[k], scores["M1"]),
                                     basis=BASIS, severe=(errs[k].severe_miss, errs["M1"].severe_miss))
        out.append(f"- {k}: " + ("**교체 후보**" if not fails else "아님. " + "; ".join(fails)))
    if "M1" in sums:
        out.append(f"- 참고: M1 의 못 읽음 {sums['M1'].unread}개. M1 에 못 읽음이 있으면 기준 1은 후보에게 유리해지고 "
                   f"기준 4는 후보에게 불리해진다(스펙 9절)")

    out += ["", "## 나눠 본 표 (판정에 쓰지 않는다)", ""]
    meta = ak["cases"]
    by_type = {TYPE_NAMES[t]: [c for c in ids if meta[c]["type"] == t] for t in sorted({m["type"] for m in meta.values()})}
    by_domain = {d: [c for c in ids if meta[c]["domain"] == d] for d in DOMAINS}
    out += _breakdown("유형별", by_type, key, scores)
    out += _breakdown("분야별", by_domain, key, scores)
    return "\n".join(out) + "\n"


def main() -> int:
    try:
        text = build()
    except ReportProblem as e:
        print(f"보고서를 만들지 않았습니다: {e}")
        return 1
    REPORT.write_text(text, encoding="utf-8")
    print(text)
    print(f"보고서: {REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 점검이 통과하는지 본다**

Run: `$PY -m tools.judge5v2_report_check | tail -1`
Expected: `3가지 전부 통과.`

- [ ] **Step 5: 커밋한다**

```bash
git add ai-service/tools/judge5v2_report.py ai-service/tools/judge5v2_report_check.py
git commit -m "feat: 채점 모델 비교 v2 의 보고서 도구를 추가한다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/tools/judge5v2_report.py ai-service/tools/judge5v2_report_check.py
```

**리뷰 포인트:** 비교 쌍이 스펙 6-2절의 둘(M3 와 M1, M3 와 M4)이고 `compare` 의 인자 순서가 (정답, 후보, M1) 인가. 점수를 `rules=RULES_V2` 와 `finish` 를 함께 넘겨 읽는가.

---

### Task 9: 코랩 노트북

**Files:**
- Create: `ai-service/notebooks/judge5v2_colab.ipynb` (앞 노트북 `judge5_colab.ipynb` 는 고치지 않는다)

**Interfaces:**
- Consumes: 없음
- Produces: 노트북 안의 `DIR = '/content/drive/MyDrive/alldap_judge5v2'`, `EXPECTED_SHA256 = ""`(E11 에서 채운다), `REPOS` 에 M3, M4 만, 결과 줄의 `'domain': row['domain']`. 태스크 10 의 점검이 이 글자들을 본다.

- [ ] **Step 1: 복사하고 바꾸는 스크립트를 돌린다**

바꿀 곳은 스펙 8-3절의 일곱(Drive 폴더, 시험지 해시, 모델 목록, 4번 칸의 반복문, 실행 번호, 결과 zip 이름, 머리말의 44건)과 결과 줄의 분야, 두 번 채점과 M2 를 말하는 주석 둘, 그리고 노트북을 대조하는 점검의 이름을 말하는 주석 하나다(`e228b67`). 각 바꿀 글자가 원본에 몇 번 있는지 확인하면서 바꾼다. 개수가 다르면 원본이 바뀐 것이므로 멈춘다.

```bash
cd /Users/cheonjamin/projects/AllDap-judge-v2/ai-service
$PY - <<'EOF'
import json, re
from pathlib import Path

src = Path("notebooks/judge5_colab.ipynb")
dst = Path("notebooks/judge5v2_colab.ipynb")
nb = json.loads(src.read_text(encoding="utf-8"))

HEADER = """# AllDap 채점 모델 비교 v2 (M3, M4)

설계: `docs/superpowers/specs/2026-10-05-judge-selfhost-v2-design.md`

**실행 방법**
1. 런타임 > 런타임 유형 변경 > **T4 GPU**
2. 왼쪽 열쇠 아이콘(비밀값)에 `HF_TOKEN` 을 넣는다(Hugging Face 토큰, 읽기 권한). 노트북 접근을 허용한다.
3. Google Drive 의 `MyDrive/alldap_judge5v2/` 폴더에 `cases.jsonl` 을 올린다.
4. 런타임 > **모두 실행**. Drive 연결 허용 창이 뜨면 허용한다.
5. 끊기면 같은 순서로 다시 **모두 실행** 한다. 이미 채점한 문항은 건너뛴다.
   **오류로 멈춘 뒤 다시 실행할 때는 런타임 > 세션 다시 시작 후 모두 실행** 한다. 같은 커널에서 이어 돌리면 앞 모델이 GPU 에 남아 다음 모델이 메모리 부족으로 잘못 건너뛰어진다(2026-10-02 에 겪었다).
6. 끝나면 마지막 칸이 `alldap_judge5v2_results.zip` 을 내려받는다. 중간에 오류로 멈췄으면 마지막 칸만 따로 실행해 그때까지의 결과를 받는다.

이번 실험은 시험지를 **한 번만** 채점한다(v2 스펙 5절). 앞 실험에서 두 번 채점한 결과가 M3, M4 모두 같았기 때문이다. M2 는 앞 실험에서 T4 메모리에 올라가지 않아 뺐다.

모델 하나가 메모리에 안 올라가면 그 모델은 건너뛰고 이유를 `{모델}_skipped.json` 에 남긴다. 다른 모델로 바꿔 끼우지 않는다. 건너뜀 기록이 있는 모델은 다시 실행해도 건너뛴다(탐욕적 디코딩이라 다시 해도 같은 곳에서 모자란다). 다시 시도하려면 그 파일을 지운다.

모델마다 시험 문항 전에 가짜 문항 하나로 먼저 확인하고 출력을 `{모델}_smoke.json` 에 남긴다. 출력이 비어 있으면 멈춘다. `[RESULT]` 가 없는 것만으로는 멈추지 않는다. 양식을 안 따르는 것도 그 모델의 성적이고, 보고서가 못 읽음으로 센다.

디스크: 원본 가중치가 M3, M4 각 약 30GB 라 모델 하나를 끝낼 때마다 그 모델의 내려받은 파일을 지운다."""

# (바꿀 글자, 새 글자, 원본의 코드 칸 전체에서 나와야 하는 횟수)
REPL = [
    ("/content/drive/MyDrive/alldap_judge5'", "/content/drive/MyDrive/alldap_judge5v2'", 1),
    ('    "M2": "mistralai/Mistral-Small-3.1-24B-Instruct-2503",\n', "", 1),
    ("for key in ('M3', 'M4', 'M2'):", "for key in ('M3', 'M4'):", 1),
    ("for r in (1, 2)]", "for r in (1,)]", 1),
    ("for run, path in zip((1, 2), paths):", "for run, path in zip((1,), paths):", 1),
    ("'run': run, 'output': text, 'finish': finish, 'cases_sha256': sha}",
     "'run': run, 'output': text, 'finish': finish, 'cases_sha256': sha,\n                        'domain': row['domain']}", 1),
    ("alldap_judge5_results", "alldap_judge5v2_results", 2),
    ("(44건과 무관)", "(시험 문항과 무관)", 1),
    ("세 모델을 합치면 약 107GB 라", "두 모델을 합치면 약 60GB 라", 1),
    # 주석도 바꾼다. 남겨 두면 한 번만 채점하고 M2 를 돌리지 않는 노트북에 두 번 채점, M2 이야기가 남는다.
    ("smoke, run1, run2 중 하나다.", "smoke, run1 중 하나다(v2 는 한 번만 채점한다).", 1),
    ("한국어 입력이 잘못 쪼개지면 M2 의 결과가 오염되므로 켠다.",
     "한국어 입력이 잘못 쪼개지면 Mistral 계열의 결과가 오염되므로 켠다(v2 는 M2 를 돌리지 않지만 앞 노트북과 같게 둔다).", 1),
    ("# tools.judge5_check 가 같은지 확인한다.", "# tools.judge5v2_check 가 같은지 확인한다.", 1),
]

code_cells = [c for c in nb["cells"] if c["cell_type"] == "code"]
def text_of(c):
    return c["source"] if isinstance(c["source"], str) else "".join(c["source"])
for c in code_cells:
    c["source"] = text_of(c)
whole = "\n".join(c["source"] for c in code_cells)
for old, new, n in REPL:
    got = whole.count(old)
    assert got == n, f"{old!r} 이 {got}번 있다(기대 {n}). 원본 노트북이 바뀌었는지 확인한다"
    for c in code_cells:
        c["source"] = c["source"].replace(old, new)
# 시험지 해시는 E11 에서 최종 해시로 채운다. 빈 글자로 두면 노트북의 assert 가 실행을 막는다.
for c in code_cells:
    c["source"] = re.sub(r'EXPECTED_SHA256 = "[0-9a-f]{64}"', 'EXPECTED_SHA256 = ""', c["source"])
assert nb["cells"][0]["cell_type"] == "markdown"
nb["cells"][0]["source"] = HEADER
for c in code_cells:
    c["outputs"], c["execution_count"] = [], None
dst.write_text(json.dumps(nb, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print("만들었다:", dst)
EOF
```

Expected: `만들었다: notebooks/judge5v2_colab.ipynb`. 어느 `assert` 가 실패하면 그 글자를 원본에서 찾아 계획과 다른 점을 리뷰 세션에 알린다.

- [ ] **Step 2: 바뀐 곳을 눈으로 확인한다**

```bash
$PY - <<'EOF'
import json
nb = json.load(open("notebooks/judge5v2_colab.ipynb", encoding="utf-8"))
code = "\n".join(c["source"] for c in nb["cells"] if c["cell_type"] == "code")
for s in ("alldap_judge5v2'", 'EXPECTED_SHA256 = ""', "for key in ('M3', 'M4'):", "zip((1,), paths)",
          "'domain': row['domain']", "alldap_judge5v2_results.zip"):
    print(s in code, s)
print('"M2":' in code, '"M2": 가 남았는가')
EOF
```

Expected: 앞 여섯 줄은 `True`, 마지막 줄은 `False`.

- [ ] **Step 3: 커밋한다**

```bash
git add ai-service/notebooks/judge5v2_colab.ipynb
git commit -m "feat: 채점 모델 비교 v2 의 코랩 노트북을 앞 노트북에서 복사해 바꾼다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/notebooks/judge5v2_colab.ipynb
```

**리뷰 포인트:** 앞 노트북(`judge5_colab.ipynb`)이 바뀌지 않았는가(`git diff --stat` 에 없어야 한다). 생성 설정 줄(`GenerationConfig`, `use_model_defaults=False`)이 원본 그대로 남았는가.

---

### Task 10: 점검 묶기와 CI

**Files:**
- Create: `ai-service/tools/judge5v2_check.py`
- Modify: `.github/workflows/ci.yml` (주석 한 줄, 실행 한 줄)

**Interfaces:**
- Consumes: 태스크 4~8 의 점검 파일의 `CHECKS`, 태스크 2 의 v2 읽는 규칙 점검 함수, 태스크 5 의 `replay_round`, `assigned_types`, `eligible3`, `eligible4`, `eligible6`, `eligible8`, 태스크 6 의 `CASE_KEYS`, 태스크 9 의 노트북
- Produces: 명령 `python -m tools.judge5v2_check`

- [ ] **Step 1: 점검 입구를 쓴다** (`judge5v2_check.py`)

```python
"""채점 모델 비교 v2 의 자체 점검 입구. DB 도 외부 API 도 쓰지 않는다. CI 에서 돈다.

실행:  cd ai-service && python -m tools.judge5v2_check

도구마다 점검 파일이 따로 있다(도구를 서로 다른 세션이 동시에 만들었기 때문이다). 이 파일은 그것들을 모두
부르고, 도구 하나로는 볼 수 없는 것을 더 본다: 노트북이 judge5 와 같은 값을 쓰는가, 커밋된 시험지에
정답이 새지 않았는가(draft 와 final 모두), 커밋된 최종 시험지가 커밋된 입력에서 그대로 다시 만들어지는가,
커밋된 배정이 시드로 재현되고 후보 목록이 규칙대로인가(스펙 8-3절의 judge5v2_check 항목).

커밋된 파일을 보는 점검은 파일이 아직 없으면 아무것도 보지 않고 통과한다. 그래서 그 점검마다 같은 판정 함수를
일부러 고장 낸 입력에 먹여 실패하는지 보는 점검을 짝으로 둔다. 짝이 없으면 판정 함수가 늘 빈 목록을 돌려줘도
CI 는 초록이다. 고장 점검의 입력(픽스처)은 이 파일 안에 따로 둔다. 다른 도구의 점검 파일에서 빌려 오면
그 파일의 픽스처가 바뀔 때 이 점검이 무엇을 보는지가 소리 없이 바뀐다.
"""
from __future__ import annotations

import hashlib
import json
import re
import tempfile
from pathlib import Path

from . import (judge5v2_assign_check, judge5v2_export_check, judge5v2_gate_check, judge5v2_report_check,
               judge5v2_search_check)
from .judge5 import MAX_NEW_TOKENS, MODELS, SCALE, sha256_file, smoke_messages
from .judge5_check import (
    check_parse_v2_keeps_result_rules, check_parse_v2_reads_bracket_tail, check_parse_v2_refuses_truncated_tail,
    check_parse_v2_tail_is_strict,
)
from .judge5v2_assign import (
    EXCLUDE_REASONS, EXCLUDED, assigned_types, eligible3, eligible4, eligible6, eligible8, replay_round, run_round,
)
from .judge5v2_export import CASE_KEYS, apply_review, build_cases
from .judge5v2_files import (
    ANSWER_KEY, ASSIGNMENT, CASES, CASES_SHA, DOMAINS, QUESTIONS, QUOTA, RETRIEVED, REVIEW, ROOT, VARIANTS,
    latest_by_qid, read_json, read_jsonl, write_jsonl,
)

NOTEBOOK = ROOT / "notebooks" / "judge5v2_colab.ipynb"


def _notebook_code() -> str:
    nb = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    return "\n".join(c["source"] if isinstance(c["source"], str) else "".join(c["source"])
                     for c in nb["cells"] if c["cell_type"] == "code")


def _final_key() -> dict | None:
    if not ANSWER_KEY.exists():
        return None
    ak = read_json(ANSWER_KEY)
    return ak if ak.get("stage") == "final" else None


def _settings_kind(settings: dict | None) -> str:
    # dict 는 집합에 넣을 수 없어서 키 순서를 고정한 JSON 글자로 바꿔 종류를 센다.
    return json.dumps(settings, ensure_ascii=False, sort_keys=True)


# ---------------------------------------------------------------------------------------------------------------
# 판정 함수. 파일을 읽지 않고 내용만 받는다. 커밋된 파일과 일부러 고장 낸 입력에 똑같이 쓰기 위해서다.
# 모두 문제 목록을 돌려준다. 빈 목록이면 통과다(assert 하나로 멈추지 않고 문제를 전부 보여 주려는 것이다).
# ---------------------------------------------------------------------------------------------------------------

def retrieved_prefix(raw: bytes, sha: str) -> list[dict] | None:
    """raw(retrieved.jsonl 의 바이트)의 줄 경계 앞부분 중 SHA-256 이 sha 인 것을 찾아 그 줄들을 돌려준다.

    retrieved.jsonl 은 덧붙이기만 하는 파일이다(계획 형식 2). 배정 회차는 그때의 파일 해시를 기록하므로, 그 뒤에
    줄이 더 붙어도 기록된 해시는 지금 파일의 어느 줄 경계 앞부분과 같아야 한다. 없으면 앞 줄이 고쳐졌거나 지워진
    것이다. 해시를 한 줄씩 이어 계산하므로(update) 파일 길이에 비례하는 시간만 든다.
    빈 파일의 해시(아무 줄도 없을 때)도 앞부분으로 본다.
    """
    h = hashlib.sha256()
    if h.hexdigest() == sha:
        return []
    start = 0
    while start < len(raw):
        end = raw.find(b"\n", start)
        end = len(raw) if end < 0 else end + 1    # 마지막 줄에 줄바꿈이 없으면 파일 끝까지가 한 줄이다
        h.update(raw[start:end])
        if h.hexdigest() == sha:   # hexdigest 는 해시를 끝내지 않는다. 이어서 update 할 수 있다
            # 맞는 앞부분을 찾은 뒤에만 JSON 으로 읽는다. 그 뒤의 줄(잘렸거나 쓰는 중인 줄)은 읽지 않는다.
            return [json.loads(line) for line in raw[:end].splitlines() if line.strip()]
        start = end
    return None


def assignment_problems(a: dict, questions: list[dict], retrieved_raw: bytes,
                        excluded_raw: bytes | None = None) -> list[str]:
    """배정 파일(계획 형식 3)이 규칙대로인가.

    1. 회차 0 의 후보(pool)는 그 회차를 돌릴 때의 검색 파일에서 검색을 통과하고 멀쩡한 답변이 있는 질문 중
       그 회차가 제외한 질문(회차 기록의 excluded, 스펙 2-3절의 "정답이 근거 청크 밖")을 뺀 전부다
       (pool_for 와 같은 조건). 그때의 검색 파일은 회차에 기록된 retrieved_sha256 으로 지금 파일에서 찾는다.
       제외 목록도 excluded.json 을 다시 읽지 않고 회차 기록을 쓴다. 파일이 나중에 바뀌어도 그 회차가 무엇을
       뺐는지는 기록에 남아 있기 때문이다.
       옛 판(지금 파일 전체로 정답을 만들고 번호 75 이하로 거름)은 두 경우에 거짓 실패했다: 회차 0 의 후보에
       든 076 이후 질문(E5 전 보충)과, 회차 0 뒤에 다시 검색해 ok 가 된 질문. 회차 0 뒤에 덧붙인 076 이후
       질문(E10 보충)은 번호로 걸러져 통과했다. 두 리뷰어의 재현이 갈린 것은 이 두 보충 경로 때문이다.
       후보에서 질문 하나를 빼고 돌려도 재현 점검은
       통과하므로(그 후보로 다시 돌리니까) 후보 자체를 따로 본다.
    2. 각 회차의 후보에는 앞 회차들에서 유형을 받은 질문이 없다(보충 배정, 스펙 7-2절).
    3. 같은 후보, 같은 할당량, 같은 시드로 다시 돌리면 같은 배정이 나온다(스펙 3-3절).
    4. ③, ④, ⑥, ⑧ 을 받은 질문은 그 자격 조건을 만족한다.
    5. 회차 0 의 제외 기록이 excluded.json 과 맞는다(excluded_raw 는 지금 파일의 바이트, 파일이 없으면 None).
       1 은 기록의 excluded 를 믿고 후보를 맞춰 보므로, 기록과 후보가 함께 질문을 더 빼면(excluded.json 에 없는
       질문을 기록에 넣고 후보에서도 뺐다) 1 도 재현도 통과한다. 그래서 기록 자체를 파일과 대조한다.
       기록된 excluded_sha256 이 지금 파일의 해시와 같으면 {qid: 원인} 이 파일 내용과 정확히 같아야 한다.
       다르면 파일이 회차 0 뒤에 바뀐 것이고(제외를 더 적었거나 풀었다), 그때는 기록의 질문마다 지금 파일에
       같은 원인으로 있는지만 본다. 제외를 풀었으면 여기서 실패한다. 풀린 질문은 회차 0 의 후보가 아니었으므로
       보충 회차로 배정해야 하는데, 그 경우는 아직 없다. 생기면 이 규칙을 그 회차의 기록과 대조하도록 넓힌다.
       기록된 해시가 null(그때 파일이 없었다)이면 기록의 제외도 비어 있어야 한다. 원인은 EXCLUDE_REASONS 안이다.
    """
    problems: list[str] = []
    by_id = {q["qid"]: q for q in questions}
    if a["rounds"]:
        rnd0 = a["rounds"][0]
        prefix = retrieved_prefix(retrieved_raw, rnd0.get("retrieved_sha256", ""))
        if prefix is None:
            problems.append("회차 0 에 기록된 retrieved_sha256 과 같은 앞부분이 지금 retrieved.jsonl 에 없다. "
                            "앞 줄이 고쳐졌거나 지워졌다(이 파일은 덧붙이기만 한다)")
        else:
            excluded = set(rnd0.get("excluded") or {})   # 기록에 키가 없거나 null 이면 제외가 없는 것이다
            ok = [r for r in latest_by_qid(prefix) if r["status"] == "ok" and by_id.get(r["qid"], {}).get("answer")
                  and r["qid"] not in excluded]
            want = {d: sorted(r["qid"] for r in ok if r["domain"] == d) for d in DOMAINS}
            got = {d: sorted(rnd0["pool"].get(d, [])) for d in DOMAINS}
            for d in DOMAINS:
                if got[d] != want[d]:
                    missing, extra = sorted(set(want[d]) - set(got[d])), sorted(set(got[d]) - set(want[d]))
                    problems.append(f"회차 0 의 {d} 후보가 그때 검색을 통과한 질문과 다르다"
                                    f"(빠짐 {missing[:5]}, 더 있음 {extra[:5]})")
        problems += _excluded_record_problems(rnd0, excluded_raw)
    used: set[str] = set()
    for no, rnd in enumerate(a["rounds"]):
        pool = {q for d in DOMAINS for q in rnd["pool"].get(d, [])}
        if again := sorted(pool & used):
            problems.append(f"회차 {no} 의 후보에 앞 회차에서 쓴 질문이 있다: {again[:5]}")
        try:
            if replay_round(rnd, by_id, a["seed"], no) != rnd["domains"]:
                problems.append(f"회차 {no} 가 같은 시드로 재현되지 않는다")
        except Exception as e:  # noqa: BLE001 - 질문이 없거나 할당량을 못 채우면 재현이 아니라 실패로 센다
            problems.append(f"회차 {no} 를 다시 돌리지 못했다: {type(e).__name__}: {e}")
        used |= {q for res in rnd["domains"].values() for q in res["types"]}
    rules = {3: eligible3, 4: eligible4, 6: eligible6, 8: eligible8}
    for qid, t in assigned_types(a).items():
        if t in rules and (qid not in by_id or not rules[t](by_id[qid])):
            problems.append(f"{qid}: 유형 {t} 의 자격 조건을 만족하지 않는다")
    return problems


def cases_problems(ak: dict, rows: list[dict], file_sha: str, recorded_sha: str) -> list[str]:
    """시험지 파일에 정답이 새지 않았고 해시 셋이 맞는가. draft 와 final 모두 본다.

    draft 도 보는 이유: 검수 세션(Codex)이 draft 시험지를 읽는다. 거기에 유형이나 정답 점수가 있으면 검수가
    대응표를 베끼게 되어 두 모델이 함께 놓친 실수만 통과시킨다는 검수의 뜻이 없어진다(스펙 4절).
    final 은 검색 설정이 한 가지인지도 본다. 스펙 2-3절은 모든 문항을 같은 기본 설정으로 검색한다. 검색 도구의
    --allow-nondefault 로 돌린 줄이 섞이면 문항마다 근거를 뽑은 방식이 달라진다.
    """
    problems: list[str] = []
    for r in rows:
        if set(r) != CASE_KEYS:
            problems.append(f"{r.get('case_id')}: 시험지 줄의 키가 {sorted(set(r) ^ CASE_KEYS)} 만큼 다르다")
    if not file_sha == ak.get("cases_sha256") == recorded_sha:
        problems.append(f"해시가 다르다: 파일 {file_sha}, 정답 파일 {ak.get('cases_sha256')}, 해시 파일 {recorded_sha}")
    if {r["case_id"] for r in rows} != set(ak["cases"]):
        problems.append("시험지의 문항 id 와 정답 파일의 문항 id 가 다르다")
    if ak.get("stage") == "final":
        if bad := [c for c, v in ak["cases"].items() if v.get("score") not in SCALE]:
            problems.append(f"정답 점수가 1~5 가 아닌 문항: {bad[:5]}")
        if both := sorted(set(ak["cases"]) & set(ak.get("dropped", {}))):
            problems.append(f"남긴 문항과 버린 문항에 함께 있다: {both[:5]}")
        kinds = {_settings_kind(r.get("search_settings")) for r in rows}
        if len(kinds) > 1:
            problems.append(f"최종 시험지의 검색 설정이 {len(kinds)}가지다. 모든 문항을 같은 설정으로 검색해야 한다(스펙 2-3절)")
    return problems


def rebuild_problems(ak: dict, cases_bytes: bytes, questions: list[dict], retrieved: list[dict], assignment: dict,
                     variants: list[dict], reviews: list[dict]) -> list[str]:
    """커밋된 입력으로 최종 시험지를 다시 만들면 커밋된 시험지와 바이트까지 같은가.

    cases_problems 는 시험지와 해시가 서로 맞는지만 본다. 시험지를 만든 뒤 변형 답변이나 검수 판단을 고치고
    final 을 다시 돌리지 않으면 셋은 여전히 서로 맞지만 입력과는 어긋난다. 그걸 여기서 잡는다.
    아래 세 줄은 judge5v2_export.cmd_final 과 같은 순서다(그 함수는 파일을 쓰므로 여기서 부르지 않는다).
    두 곳이 갈라지면 이 점검이 실패하므로 조용히 어긋나지는 않는다.
    """
    try:
        rows, key = build_cases(questions, retrieved, assigned_types(assignment), variants)
    except Exception as e:  # noqa: BLE001 - ExportProblem 등. 다시 만들지 못한 것도 문제로 센다
        return [f"최종 시험지를 다시 만들지 못했다: {type(e).__name__}: {e}"]
    kept, dropped, review_problems = apply_review(key, reviews)
    problems = [f"검수 반영: {p}" for p in review_problems[:5]]
    rows = [r for r in rows if r["case_id"] in kept]
    # 같은 함수(write_jsonl)로 써야 같은 바이트가 나온다. 직렬화 규칙을 여기 한 번 더 적으면 두 곳이 갈라질 수 있다.
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "cases.jsonl"
        write_jsonl(p, rows)
        rebuilt = p.read_bytes()
    if rebuilt != cases_bytes:
        problems.append("커밋된 입력으로 다시 만든 시험지가 커밋된 cases.jsonl 과 다르다. tools.judge5v2_export final 을 다시 실행하라")
    if kept != ak["cases"] or dropped != ak.get("dropped", {}):
        problems.append("커밋된 입력으로 다시 만든 정답 점수나 버린 문항이 answer_key.json 과 다르다")
    return problems


# ---------------------------------------------------------------------------------------------------------------
# 점검
# ---------------------------------------------------------------------------------------------------------------

def check_v2_notebook_matches_the_module() -> None:
    """노트북은 judge5 를 import 하지 못한다(코랩에는 이 저장소가 없다). 그래서 글자가 같은지 여기서 본다."""
    code = _notebook_code()
    assert f"MAX_NEW_TOKENS = {MAX_NEW_TOKENS}" in code
    for key in ("M3", "M4"):
        assert f'"{key}": "{MODELS[key]}"' in code, key
    assert '"M2":' not in code                                         # v2 스펙 5절: M2 를 뺀다
    assert "for key in ('M3', 'M4'):" in code
    assert "zip((1,), paths)" in code and "for r in (1,)]" in code     # 한 번만 채점한다
    assert "/content/drive/MyDrive/alldap_judge5v2'" in code
    assert "alldap_judge5v2_results.zip" in code
    assert "'domain': row['domain']" in code                            # 결과 줄에 분야를 옮긴다
    assert re.search(r"GenerationConfig\([^)]*do_sample=False", code)
    assert "model.generate(**enc, generation_config=gen, use_model_defaults=False)" in code
    line = next(l for l in code.splitlines() if l.startswith("SMOKE_MESSAGES = "))
    assert json.loads(line.split("=", 1)[1]) == smoke_messages()


def check_v2_notebook_hash_matches_final_cases() -> None:
    """최종 시험지가 있으면 노트북의 기대 해시가 그 해시와 같아야 한다. 검수 전 시험지(draft)는 보지 않는다."""
    m = re.search(r'EXPECTED_SHA256\s*=\s*"([0-9a-f]{64}|)"', _notebook_code())
    assert m, "노트북에 EXPECTED_SHA256 줄이 없다"
    ak = _final_key()
    if ak is not None:
        assert m.group(1) == ak["cases_sha256"], "노트북 해시를 최종 시험지 해시로 갱신하라(계획 E11)"


def check_committed_cases_are_blind() -> None:
    """커밋된 시험지(draft 든 final 이든)에 유형, 정답 점수, qid 가 없고 해시 셋이 맞는다."""
    if not ANSWER_KEY.exists():
        return
    ak = read_json(ANSWER_KEY)
    problems = cases_problems(ak, read_jsonl(CASES), sha256_file(CASES), CASES_SHA.read_text(encoding="utf-8").split()[0])
    assert not problems, "\n".join(problems)


def check_committed_final_cases_rebuild() -> None:
    """최종 시험지가 있으면 커밋된 입력으로 다시 만들어 바이트까지 대조한다."""
    ak = _final_key()
    if ak is None:
        return
    problems = rebuild_problems(ak, CASES.read_bytes(), read_jsonl(QUESTIONS), read_jsonl(RETRIEVED),
                                read_json(ASSIGNMENT), read_jsonl(VARIANTS), read_jsonl(REVIEW))
    assert not problems, "\n".join(problems)


def _excluded_record_problems(rnd0: dict, excluded_raw: bytes | None) -> list[str]:
    """assignment_problems 의 5. 회차 0 의 excluded 기록을 지금 excluded.json 바이트와 대조한다."""
    rec: dict[str, str] = rnd0.get("excluded") or {}
    rec_sha = rnd0.get("excluded_sha256")
    out = [f"회차 0 의 제외 {qid}: 원인 {why!r} 는 쓸 수 없다" for qid, why in sorted(rec.items())
           if why not in EXCLUDE_REASONS]
    if rec_sha is None:
        if rec:
            out.append(f"회차 0 은 excluded.json 이 없었다고 기록했는데(excluded_sha256 이 null) 제외가 있다: {sorted(rec)[:5]}")
        return out
    now = {} if excluded_raw is None else {q: e.get("reason") if isinstance(e, dict) else None
                                           for q, e in json.loads(excluded_raw).items()}
    if excluded_raw is not None and hashlib.sha256(excluded_raw).hexdigest() == rec_sha:
        if rec != now:
            diff = sorted(set(rec.items()) ^ set(now.items()))
            out.append(f"회차 0 의 excluded 가 같은 해시의 excluded.json 내용과 다르다: {diff[:5]}")
        return out
    # 파일이 회차 0 뒤에 바뀌었다(또는 지워졌다). 기록의 질문이 지금 파일에 같은 원인으로 남아 있는지만 본다.
    if gone := sorted(q for q, why in rec.items() if now.get(q) != why):
        out.append(f"회차 0 이 제외로 기록한 질문이 지금 excluded.json 에 같은 원인으로 없다: {gone[:5]}")
    return out


def check_committed_assignment_replays_and_is_eligible() -> None:
    """커밋된 배정의 후보, 재현, 자격 조건(assignment_problems)."""
    if not ASSIGNMENT.exists():
        return
    raw = RETRIEVED.read_bytes() if RETRIEVED.exists() else b""
    ex_raw = EXCLUDED.read_bytes() if EXCLUDED.exists() else None
    problems = assignment_problems(read_json(ASSIGNMENT), read_jsonl(QUESTIONS), raw, ex_raw)
    assert not problems, "\n".join(problems)


# ---------------------------------------------------------------------------------------------------------------
# 고장 점검의 픽스처. 다른 점검 파일에서 빌려 오지 않는다(모듈 설명 끝 문단).
# ---------------------------------------------------------------------------------------------------------------

_SEED = 20261005
_CONTRAST = {"asked": {"target": "골드", "value": "10,000원"}, "other": {"target": "실버", "value": "20,000원"},
             "chunk_ids": [1]}


def _questions(domain: str, n: int = 75, start: int = 1) -> list[dict]:
    """할당량을 채울 수 있는 질문 n 개. 0~19 번째는 주장 2개(답 두 가지, ④ 와 ③ 몫), 20~34 번째는 주장 3개,
    나머지는 주장 1개다. 답이 하나인 질문 중 7 번째마다 ⑧ 조건(contrast)을 붙인다. 번호는 start 부터다."""
    out = []
    for i in range(n):
        claims = 2 if i < 20 else 3 if i < 35 else 1
        two_part = i < 20
        out.append({"qid": f"{domain}-{start + i:03d}", "domain": domain, "question": f"질문 {i}", "answer": f"답 {i}",
                    "claims": claims, "two_part": two_part,
                    "contrast": _CONTRAST if not two_part and i % 7 == 0 else None})
    return out


def _lines(rows: list[dict]) -> bytes:
    # 검색 도구가 쓰는 꼴(append_jsonl)과 같게 한 줄에 JSON 하나다.
    return "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows).encode("utf-8")


def _ok(q: dict) -> dict:
    return {"qid": q["qid"], "domain": q["domain"], "status": "ok", "drop_reason": None}


def _excluded_bytes(excluded: dict[str, str]) -> bytes | None:
    """{qid: 원인} 을 excluded.json 꼴의 바이트로. 비었으면 파일이 없는 것(None)으로 본다."""
    if not excluded:
        return None
    return json.dumps({q: {"reason": why, "note": "픽스처"} for q, why in excluded.items()},
                      ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8")


def _assignment_fixture(n: int = 75, excluded: dict[str, str] | None = None) -> tuple[dict, list[dict], bytes]:
    """분야마다 질문 n 개로 회차 0 을 돌린 배정, 질문, 검색 파일 바이트. 고장 내기 전에는 문제가 없어야 한다.
    hr-075 는 회차 0 때 리랭커 호출이 실패해 버려진 상태라 후보에 없다(뒤늦게 ok 가 되는 정상 경로에 쓴다).
    excluded 는 {qid: 원인} 이고, 배정 도구처럼 후보에서 빼고 회차 기록에 적는다. 기록의 excluded_sha256 은
    _excluded_bytes(excluded) 의 해시다(비었으면 null). assignment_problems 에는 그 바이트를 함께 넘긴다."""
    excluded = excluded or {}
    ex_raw = _excluded_bytes(excluded)
    questions = [q for d in DOMAINS for q in _questions(d, n)]
    late = "hr-075"
    lines = [_ok(q) if q["qid"] != late else {"qid": late, "domain": "hr", "status": "dropped",
                                             "drop_reason": "rerank_failed"} for q in questions]
    raw = _lines(lines)
    pools = {d: [q for q in questions if q["domain"] == d and q["qid"] != late and q["qid"] not in excluded]
             for d in DOMAINS}
    domains = run_round(pools, {d: dict(QUOTA) for d in DOMAINS}, _SEED, 0)
    rnd0 = {"retrieved_sha256": hashlib.sha256(raw).hexdigest(), "excluded": dict(excluded),
            "excluded_sha256": hashlib.sha256(ex_raw).hexdigest() if ex_raw is not None else None,
            "pool": {d: [q["qid"] for q in pools[d]] for d in DOMAINS},
            "needs": {d: {str(t): n for t, n in QUOTA.items()} for d in DOMAINS}, "domains": domains}
    return {"seed": _SEED, "rounds": [rnd0]}, questions, raw


def check_assignment_problems_catch_broken_inputs() -> None:
    """assignment_problems 가 고장 하나하나를 잡는가. 커밋된 파일이 없을 때도 이 점검은 실제로 돈다."""
    a, qs, raw = _assignment_fixture()
    assert assignment_problems(a, qs, raw) == []

    # 회차 0 의 후보에서 질문 하나를 뺐다. 재현 점검만으로는 못 잡는 경우다(빠진 후보로 다시 돌리면 같게 나올 수 있다).
    b = json.loads(json.dumps(a))   # 깊은 복사. 고장 낸 것이 다음 경우에 새지 않게 한다
    b["rounds"][0]["pool"]["shop"].remove(sorted(b["rounds"][0]["domains"]["shop"]["unused"])[0])
    assert any("회차 0 의 shop 후보" in p for p in assignment_problems(b, qs, raw))

    # 회차 0 의 후보였던 질문의 멀쩡한 답변을 나중에 지웠다(형식 1: 후보에 든 질문의 줄은 고치지 않는다).
    pooled = a["rounds"][0]["pool"]["finance"][0]
    no_answer = [dict(q, answer=None) if q["qid"] == pooled else q for q in qs]
    assert any("회차 0 의 finance 후보" in p for p in assignment_problems(a, no_answer, raw))

    # 회차 0 뒤에 앞 줄을 고쳤다(덧붙이기만 하는 파일인데 첫 줄의 판정을 바꿨다).
    first, rest = raw.split(b"\n", 1)
    edited = first.replace(b'"status": "ok"', b'"status": "dropped"') + b"\n" + rest
    assert edited != raw
    assert any("앞 줄이 고쳐졌거나" in p for p in assignment_problems(a, qs, edited))
    assert any("앞 줄이 고쳐졌거나" in p for p in assignment_problems(a, qs, raw[: len(raw) // 2]))   # 잘렸다

    # 보충 회차의 후보에 회차 0 에서 쓴 질문이 있다. 그 후보로 배정을 실제로 돌려 재현은 맞게 만든다.
    used_q = sorted(a["rounds"][0]["domains"]["manual"]["types"])[0]
    pools1 = {d: [q for q in qs if q["domain"] == d][:3] for d in DOMAINS}
    pools1["manual"].append(next(q for q in qs if q["qid"] == used_q))
    needs1 = {d: {t: (1 if t == 1 else 0) for t in QUOTA} for d in DOMAINS}
    rnd1 = {"pool": {d: [q["qid"] for q in pools1[d]] for d in DOMAINS},
            "needs": {d: {str(t): n for t, n in needs1[d].items()} for d in DOMAINS},
            "domains": run_round(pools1, needs1, a["seed"], 1)}
    c = {"seed": a["seed"], "rounds": a["rounds"] + [rnd1]}
    got = assignment_problems(c, qs, raw)
    assert any("회차 1 의 후보에 앞 회차에서 쓴 질문" in p for p in got), got

    # 시드가 바뀌었다.
    assert any("재현되지 않는다" in p for p in assignment_problems(dict(a, seed=1), qs, raw))

    # ④ 를 받은 질문의 주장 수를 홀수로 바꿨다.
    q4 = next(q for q, t in assigned_types(a).items() if t == 4)
    qs4 = [dict(q, claims=3) if q["qid"] == q4 else q for q in qs]
    assert any(p.startswith(f"{q4}: 유형 4") for p in assignment_problems(a, qs4, raw))


def check_assignment_problems_pass_normal_later_lines() -> None:
    """회차 0 뒤에 검색 파일에 줄이 덧붙는 정상 경로 둘은 통과해야 한다.
    1. 회차 0 뒤에 보충 질문(076 이후, E10 보충)을 쓰고 검색했다. 2. 호출 실패로 버린 질문(hr-075)을 다시 검색해 ok 가 됐다.
    옛 판은 1 은 번호로 걸러 통과하고 2 에서 거짓 실패했다. 1 은 앞부분 방식으로 바꿔도 깨지지 않는지 보려고 둔다."""
    a, qs, raw = _assignment_fixture()
    extra = [q for d in DOMAINS for q in _questions(d, 3, start=76)]
    later = raw + _lines([_ok(q) for q in extra]) + _lines([{**_ok(qs[0]), "qid": "hr-075"}])
    got = assignment_problems(a, qs + extra, later)
    assert got == [], got


def check_assignment_problems_pass_early_supplement_and_exclusion() -> None:
    """회차 0 전에 생기는 정상 경로 둘도 통과해야 한다.
    1. E5 전 보충: 회차 0 의 질문과 검색 줄에 076 이후 질문이 처음부터 들어 있고 후보에도 들었다. 번호 75 이하로
       거르던 옛 판은 이 질문들을 정답에서 빼서 "더 있음" 으로 거짓 실패했다.
    2. 제외: 회차 0 이 excluded 로 질문을 뺐다(스펙 2-3절). 그 질문은 검색을 통과했고 답변도 있지만 후보가 아니다."""
    a, qs, raw = _assignment_fixture(n=78)
    assert any("-076" in q for q in a["rounds"][0]["pool"]["shop"])
    got = assignment_problems(a, qs, raw)
    assert got == [], got
    ex = {"finance-010": "answer_not_in_top5", "shop-003": "partial_answer_not_in_top5"}
    a, qs, raw = _assignment_fixture(excluded=ex)
    assert "finance-010" not in a["rounds"][0]["pool"]["finance"]
    got = assignment_problems(a, qs, raw, _excluded_bytes(ex))
    assert got == [], got
    # 회차 0 뒤에 제외를 하나 더 적었다(파일 해시가 바뀐다). 기록의 질문은 같은 원인으로 남아 있으니 통과한다.
    got = assignment_problems(a, qs, raw, _excluded_bytes({**ex, "hr-020": "answer_not_in_top5"}))
    assert got == [], got


def check_assignment_problems_catch_excluded_record_mismatch() -> None:
    """회차 0 의 제외 기록이 excluded.json 과 어긋나면 잡는다. 후보와 기록이 함께 질문을 더 뺀 경우는 후보 대조(1)와
    재현(3)을 둘 다 통과하므로(기록을 믿고 맞춰 보니까) 이 점검만 잡는다.
    변이: _excluded_record_problems 를 빈 목록으로 바꾸면 이 점검이 실패한다."""
    ex = {"finance-010": "answer_not_in_top5"}
    more = {**ex, "shop-003": "partial_answer_not_in_top5"}
    a, qs, raw = _assignment_fixture(excluded=more)   # 기록과 후보는 shop-003 까지 일관되게 뺐다

    # 1. 같은 해시인데 내용이 다르다: 기록에 적힌 해시가 shop-003 이 없는 파일의 해시다.
    b = json.loads(json.dumps(a))
    b["rounds"][0]["excluded_sha256"] = hashlib.sha256(_excluded_bytes(ex)).hexdigest()
    got = assignment_problems(b, qs, raw, _excluded_bytes(ex))
    assert any("같은 해시의 excluded.json 내용과 다르다" in p for p in got), got
    assert not any("후보" in p or "재현" in p for p in got), got   # 1 과 3 은 통과한다. 그래서 이 점검이 필요하다

    # 2. 파일이 나중에 바뀌었고, 기록의 shop-003 이 지금 파일에 없다(처음부터 없었든 풀었든).
    got = assignment_problems(a, qs, raw, _excluded_bytes(ex))
    assert any("같은 원인으로 없다" in p and "shop-003" in p for p in got), got
    # 같은 질문이 원인만 달라도 잡는다.
    got = assignment_problems(a, qs, raw, _excluded_bytes({**ex, "shop-003": "answer_not_in_top5"}))
    assert any("같은 원인으로 없다" in p and "shop-003" in p for p in got), got
    # 파일이 지워졌다.
    assert any("같은 원인으로 없다" in p for p in assignment_problems(a, qs, raw, None))

    # 3. 그때 파일이 없었다고(null) 기록했는데 제외가 있다.
    c = json.loads(json.dumps(a))
    c["rounds"][0]["excluded_sha256"] = None
    assert any("excluded_sha256 이 null" in p for p in assignment_problems(c, qs, raw, _excluded_bytes(more)))

    # 4. 원인 이름이 규칙 밖이다. 파일도 같은 내용이라(해시가 같다) 원인 검사만 잡는다.
    bad = {"finance-010": "typo"}
    d, qs_d, raw_d = _assignment_fixture(excluded=bad)
    got = assignment_problems(d, qs_d, raw_d, _excluded_bytes(bad))
    assert got == ["회차 0 의 제외 finance-010: 원인 'typo' 는 쓸 수 없다"], got


def _final_fixture(d: Path) -> tuple[dict, bytes, tuple]:
    """최종 시험지 하나를 만든다. 변형 유형은 ①, ②, ⑤ 만 쓴다(⑥, ⑧ 의 형식 규칙은 내보내기 도구 쪽 점검이 본다).
    검수는 모두 정답 점수와 같다고 둔다."""
    src = [{"chunk_id": 1, "filename": "a.md", "content": "골드 10,000원 / 실버 20,000원 / 브론즈 30,000원."}]
    settings = {"top_k": 5}
    questions = [{"qid": f"shop-00{i}", "domain": "shop", "question": f"{g} 무료 기준은?",
                  "answer": f"{g}는 {v} 이상이면 무료입니다.", "claims": 1, "two_part": False, "contrast": None}
                 for i, (g, v) in enumerate([("골드", "10,000원"), ("실버", "20,000원"), ("브론즈", "30,000원")], start=1)]
    retrieved = [{"qid": q["qid"], "domain": "shop", "status": "ok", "settings": settings, "sources": src} for q in questions]
    types = {"shop-001": 1, "shop-002": 2, "shop-003": 5}
    variants = [{"qid": "shop-001", "type": 1, "answer": questions[0]["answer"], "note": ""},
                {"qid": "shop-002", "type": 2, "answer": "실버 등급은 20,000원부터 배송비가 없습니다.", "note": ""},
                {"qid": "shop-003", "type": 5, "answer": "브론즈는 30,000원 이상이면 무료이고 매달 쿠폰도 나옵니다.", "note": ""}]
    assignment = {"seed": 1, "rounds": [{"domains": {"shop": {"types": types}}}]}
    rows, key = build_cases(questions, retrieved, types, variants)
    reviews = [{"case_id": c, "review_score": k["table_score"]} for c, k in key.items()]
    kept, dropped, _ = apply_review(key, reviews)
    p = d / "cases.jsonl"
    write_jsonl(p, [r for r in rows if r["case_id"] in kept])
    ak = {"stage": "final", "cases_sha256": sha256_file(p), "cases": kept, "dropped": dropped}
    return ak, p.read_bytes(), (questions, retrieved, assignment, variants, reviews)


def check_cases_and_rebuild_problems_catch_broken_inputs() -> None:
    """cases_problems 와 rebuild_problems 가 고장 하나하나를 잡는가."""
    with tempfile.TemporaryDirectory() as tmp:
        ak, raw, inputs = _final_fixture(Path(tmp))
        rows = [json.loads(l) for l in raw.decode("utf-8").splitlines()]
        sha = ak["cases_sha256"]
        assert len(rows) == 3
        assert cases_problems(ak, rows, sha, sha) == []
        assert rebuild_problems(ak, raw, *inputs) == []

        # 시험지 줄에 유형이 샜다. draft 단계에서도 잡아야 한다.
        leaked = [dict(rows[0], type=8)] + rows[1:]
        for stage in ("draft", "final"):
            assert any("키가" in p for p in cases_problems(dict(ak, stage=stage), leaked, sha, sha)), stage
        # 해시 파일이 다른 시험지의 것이다.
        assert any("해시가 다르다" in p for p in cases_problems(ak, rows, sha, "0" * 64))
        # 남긴 문항과 버린 문항에 함께 있다.
        both = dict(ak, dropped={next(iter(ak["cases"])): {}})
        assert any("함께 있다" in p for p in cases_problems(both, rows, sha, sha))
        # 한 문항만 다른 검색 설정으로 뽑았다(final 에서만 본다. draft 는 검수 전이라 보충으로 다시 만든다).
        mixed = [dict(rows[0], search_settings={"top_k": 8})] + rows[1:]
        assert any("검색 설정이 2가지" in p for p in cases_problems(ak, mixed, sha, sha))
        assert not any("검색 설정" in p for p in cases_problems(dict(ak, stage="draft"), mixed, sha, sha))

        questions, retrieved, assignment, variants, reviews = inputs
        # 시험지를 만든 뒤 변형 답변을 고쳤다. 시험지와 해시는 여전히 서로 맞으므로 cases_problems 는 못 잡는다.
        v2 = [dict(v, answer=v["answer"] + " 감사합니다.") if v["type"] == 2 else v for v in variants]
        assert any("다시 만든 시험지" in p for p in rebuild_problems(ak, raw, questions, retrieved, assignment, v2, reviews))
        # 시험지를 만든 뒤 검수 판단을 고쳤다(한 문항을 사용자가 3점으로 고침).
        cid = next(c for c, k in ak["cases"].items() if k["table_score"] == 5)
        r2 = [dict(r, review_score=3, user_decision="override", override_score=3, reason="다시 봤다")
              if r["case_id"] == cid else r for r in reviews]
        assert any("정답 점수나 버린 문항" in p for p in rebuild_problems(ak, raw, questions, retrieved, assignment, variants, r2))


OWN = [
    check_parse_v2_reads_bracket_tail,
    check_parse_v2_tail_is_strict,
    check_parse_v2_refuses_truncated_tail,
    check_parse_v2_keeps_result_rules,
    check_v2_notebook_matches_the_module,
    check_v2_notebook_hash_matches_final_cases,
    check_committed_cases_are_blind,
    check_committed_final_cases_rebuild,
    check_committed_assignment_replays_and_is_eligible,
    check_assignment_problems_catch_broken_inputs,
    check_assignment_problems_pass_normal_later_lines,
    check_assignment_problems_pass_early_supplement_and_exclusion,
    check_assignment_problems_catch_excluded_record_mismatch,
    check_cases_and_rebuild_problems_catch_broken_inputs,
]
CHECKS = (judge5v2_search_check.CHECKS + judge5v2_assign_check.CHECKS + judge5v2_export_check.CHECKS
          + judge5v2_gate_check.CHECKS + judge5v2_report_check.CHECKS + OWN)


def main() -> None:
    for fn in CHECKS:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(CHECKS)}가지 전부 통과.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 점검이 통과하는지 본다**

Run: `cd /Users/cheonjamin/projects/AllDap-judge-v2/ai-service && $PY -m tools.judge5v2_check | tail -1`
Expected: `63가지 전부 통과.` (도구 점검 50 + 이 파일 13. 처음 계획은 31 + 8 = 39 였다. 도구 점검은 `e228b67`, `f17877a`, `4980edf`, `217048d`, `d368ba5`, `a0557d2`, `0ccf49c`, `02c4b5e`, `36fa197` 에서, 이 파일의 점검은 `71a99ae`, `3b494c5`, `1e35626` 에서 늘었다)

- [ ] **Step 3: CI 에 더한다** (`.github/workflows/ci.yml`)

`#    ✅ tools.judge5_check 는 ...` 주석 줄 바로 아래에 더한다.

```yaml
      #    ✅ tools.judge5v2_check 는 채점 모델 비교 v2 의 도구(검색은 가짜 함수로), 노트북 대조, 커밋된 시험지와 배정만 본다.
```

`python -m tools.judge5_check` 줄 바로 아래에 더한다.

```yaml
          python -m tools.judge5v2_check
```

- [ ] **Step 4: 앞 실험 점검도 함께 돌려 본다**

Run: `$PY -m tools.judge5_check | tail -1 && $PY -m tools.judge5v2_check | tail -1`
Expected: `44가지 전부 통과.` 그리고 `63가지 전부 통과.`

- [ ] **Step 5: 커밋한다**

```bash
git add ai-service/tools/judge5v2_check.py .github/workflows/ci.yml
git commit -m "chore: 채점 모델 비교 v2 의 점검을 하나로 묶어 CI 에 더한다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/tools/judge5v2_check.py .github/workflows/ci.yml
```

**리뷰 포인트:** CI 의 이 단계에는 DB 가 없다. `judge5v2_check` 가 불러오는 모듈 중 모듈 최상단에서 DB 나 외부 API 를 부르는 것이 없는가(검색 도구는 `app.db.cursor` 를 함수 안에서만 쓴다). 노트북 대조가 v1 노트북의 점검과 같은 강도인가.

---

## 실행 태스크

실행 태스크는 코드를 쓰지 않는다. 끝나면 만든 데이터 파일만 이름으로 add 해서 커밋한다(E7 의 첫 시험지와 첫 정답 파일은 커밋하지 않는다. E11 에서 최종본을 커밋한다). 리뷰는 다른 세션이 결과 파일을 열어 본다.

### Task E1: 봇 네 개를 만들고 문서를 올린다

**뉴런을 쓴다.** 문서 131개(인사 56, 나머지 셋이 25씩)의 청크 임베딩. 양은 재보지 않았다.

**Files:**
- Create: `ai-service/testdata/judge5v2/bots.json`, `ai-service/testdata/judge5v2/run_log.md`

- [ ] **Step 1: 실행 환경을 확인한다**

```bash
docker ps --format '{{.Names}}' | grep alldap-db          # alldap-b3 세션이 띄워 둔 DB. 없으면 멈추고 오케스트레이터에 알린다
git -C /Users/cheonjamin/projects/AllDap diff --stat main feat/judge-selfhost-v2 -- ai-service/app api   # 비어야 한다
git -C /Users/cheonjamin/projects/AllDap status --porcelain -- ai-service/app api                        # 비어야 한다
ln -s /Users/cheonjamin/projects/AllDap/ai-service/.env /Users/cheonjamin/projects/AllDap-judge-v2/ai-service/.env
git -C /Users/cheonjamin/projects/AllDap-judge-v2 check-ignore ai-service/.env   # 출력이 있어야 한다(커밋되지 않는다)
```

둘째와 셋째 명령이 모두 비어 있으면 워크트리의 서비스 코드가 메인 저장소와 같다. 그래서 Spring 과 Python 서비스는 메인 저장소에서 평소대로 띄운다. 둘째 명령은 두 브랜치의 커밋을 비교하고, 셋째 명령은 메인 저장소 작업 트리의 커밋하지 않은 변경을 본다. 서비스는 메인 저장소의 작업 트리로 뜨므로, 셋째가 비어 있지 않으면 커밋과 다른 코드로 검색하게 된다.

- [ ] **Step 2: Spring 과 Python 서비스를 띄운다** (이미 떠 있으면 건너뛴다)

먼저 떠 있는지 본다.

```bash
curl -s -o /dev/null -w '%{http_code}\n' localhost:8080/api/bots      # 401 이면 Spring 이 떠 있다
curl -s -o /dev/null -w '%{http_code}\n' localhost:8001/internal/debug/cf-stats   # 200 이면 Python 이 떠 있다
```

응답이 없는 쪽만 백그라운드 실행으로 띄운다. Flyway 순서 때문에 Spring 을 먼저 띄운다(AGENTS.md).

```bash
cd /Users/cheonjamin/projects/AllDap/api && ./gradlew bootRun
cd /Users/cheonjamin/projects/AllDap/ai-service && .venv/bin/uvicorn app.main:app --port 8001
```

- [ ] **Step 3: 업로드 전 뉴런을 적는다**

세션의 스크래치 폴더에 저장한다(아래 `$SCRATCH`).

```bash
curl -s localhost:8001/internal/debug/cf-stats > "$SCRATCH/cf-before.json"
```

`cf-stats` 는 Python 프로세스가 시작된 뒤의 누적이다. 그래서 업로드 전후의 차이를 업로드의 뉴런으로 본다. 그 사이에 다른 세션이 같은 프로세스로 평가를 돌리면 섞인다. 섞였을 가능성이 있으면 `run_log.md` 에 그렇게 적는다.

- [ ] **Step 4: 실험용 계정과 봇 넷을 만든다**

```bash
API=http://localhost:8080
curl -s -X POST $API/api/auth/signup -H 'Content-Type: application/json' \
  -d '{"email":"judge5v2@example.com","password":"judge5v2-local","name":"채점실험"}'
TOKEN=$(curl -s -X POST $API/api/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"judge5v2@example.com","password":"judge5v2-local"}' | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')
for d in hr shop manual finance; do
  curl -s -X POST $API/api/bots -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d "{\"name\":\"judge5v2-$d\"}"; echo
done
```

응답의 `id` 를 `testdata/judge5v2/bots.json` 에 `{"hr": N, "shop": N, "manual": N, "finance": N}` 으로 적는다. 1, 7, 8 이 나오면 멈춘다(그럴 수 없지만, 나오면 DB 가 예상과 다른 상태다).

- [ ] **Step 5: 문서를 올린다. README.md 는 올리지 않는다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-v2/ai-service
up() { find "$2" -maxdepth 1 -name '*.md' ! -name README.md | sort | while read -r f; do
  curl -s -o /dev/null -w "%{http_code} $f\n" -X POST "$API/api/bots/$1/documents" -H "Authorization: Bearer $TOKEN" -F "file=@$f"; done; }
up <hr 봇 번호> testdata/corpus
up <shop 봇 번호> testdata/judge5v2/corpus/shop
up <manual 봇 번호> testdata/judge5v2/corpus/manual
up <finance 봇 번호> testdata/judge5v2/corpus/finance
```

Expected: 모든 줄이 `202`. README 를 빼는 이유는 스펙 8-1절 2단계에 있다.

- [ ] **Step 6: 처리가 끝났는지 확인한다**

```bash
docker exec alldap-db psql -U alldap -d alldap -c \
  "SELECT bot_id, status, count(*) FROM documents WHERE bot_id IN (<네 번호>) GROUP BY 1, 2 ORDER BY 1, 2;"
docker exec alldap-db psql -U alldap -d alldap -c \
  "SELECT bot_id, count(*) FROM chunks WHERE bot_id IN (<네 번호>) AND embedding IS NOT NULL GROUP BY 1 ORDER BY 1;"
```

Expected: 봇마다 상태가 `ready` 하나이고 문서 수가 56, 25, 25, 25. 실패 상태가 있으면 그 문서의 오류를 `run_log.md` 에 적고 오케스트레이터에 알린다.

- [ ] **Step 7: 업로드 뒤 뉴런을 적고 커밋한다**

`cf-stats` 를 다시 읽어 모델별 `neurons` 의 차이를 `run_log.md` 의 "업로드 (날짜)" 절에 적는다. 봇 번호, 문서 수, 청크 수도 함께 적는다.

```bash
git add ai-service/testdata/judge5v2/bots.json ai-service/testdata/judge5v2/run_log.md
git commit -m "test: 채점 모델 비교 v2 의 분야별 봇 넷을 만들고 문서를 올린 기록을 남긴다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/testdata/judge5v2/bots.json ai-service/testdata/judge5v2/run_log.md
```

**리뷰 포인트:** README.md 가 올라가지 않았는가(`SELECT filename FROM documents WHERE bot_id IN (...) AND filename = 'README.md'` 가 0행). 봇 1, 7, 8 의 문서 수가 바뀌지 않았는가.

---

### Task E2: 질문을 쓴다 (출제 세션)

**Files:**
- Create: `ai-service/testdata/judge5v2/questions.jsonl`, `ai-service/testdata/judge5v2/hr_targets.md`

문서만 있으면 시작할 수 있다. 코드 태스크와 동시에 진행한다.

- [ ] **Step 1: 재료를 읽는다**

1. 스펙 2절, 3절 전체.
2. 분야마다 `testdata/judge5v2/corpus/{shop,manual,finance}/README.md` 의 **대상에 따라 값이 갈리는 규정** 표. 인사 규정은 README 가 없다. 출제 세션이 `testdata/corpus/` 의 56문서에서 대상별 규정(정규직과 계약직, 인턴, 파견 등)을 같은 모양의 표로 뽑아 `testdata/judge5v2/hr_targets.md` 에 먼저 남긴다. 각 행에 규정, 대상과 값, 파일, 소제목, 같은 문단 여부를 적는다.
3. 아래 **값이 같은 칸** 목록. 이 칸들은 대상이 달라도 값이 같거나, 숫자 대 숫자로 비교되지 않는다. 그래서 ⑧(다른 대상의 값으로 답하기)을 만들 수 없다(청커로 자른 결과를 alldap-d4 세션이 확인했다). 이 칸을 묻는 질문은 써도 되지만 `contrast` 를 붙이지 않는다.
   - 금융 6: 3개월 미만 해지 이율은 예금과 적금 모두 0.10% 다.
   - 금융 12: 신용대출과 사업자 대출의 1년 경과 면제가 같다. 사망과 상속에 따른 면제는 네 상품 공통이다.
   - 금융 13: 신용과 사업자는 1개월, 주담대와 전세는 2개월로 묶음 안에서 같다(묶음 사이는 다르다).
   - 금융 27: 재발급 수수료는 클래식 분실 2,000원만 다르고 나머지는 같다.
   - 금융 1, 2, 23: 값이 숫자 대 숫자가 아니다.
   - 금융 18: 현금서비스와 카드론의 금리 범위가 17.5~18.0% 에서 겹친다.
   - 설명서 7: B1 6시간과 B2 Pro 의 ANC 켬 6시간이 같다.
   - 설명서 15: 보증 기간에 공통값이 많다(본체 2년 등).
   - 설명서 가습기: H10 과 H20 의 강 단계 연속 가습 시간이 둘 다 13시간이다.
4. 말투 견본 `testdata/judge5v2/style_samples.json` 의 다섯 답변. 질문 자체에는 말투 제약이 없지만, 답이 짧은 평서문 한두 개로 끝나는 질문이 되게 쓴다. 견본 하나에서 지운 일본어 낱말(`original_answer` 칸)은 따라 쓰지 않는다.

- [ ] **Step 2: 분야마다 질문 75개를 쓴다**

조건:

- 그 분야의 문서만 보고 답할 수 있는 질문만 쓴다. 서비스 평가 질문 세트(`testdata/eval_questions.json`)를 보지도 베끼지도 않는다(스펙 3-1절).
- 75개 중 약 30개는 답이 두 가지인 질문(`two_part: true`)이다. 예: "연차는 며칠이고, 언제까지 신청하나요?". 이유: 견본 말투를 따르면 멀쩡한 답변의 주장이 대개 하나가 되어, 주장이 둘 이상이어야 만들 수 있는 ③과 ④의 자격 질문이 모자란다(스펙 3-1절). 분야마다 ③과 ④가 합쳐 18문항 필요하다. 그중 ④ 9문항은 주장 수가 짝수여야 하므로, 답이 두 가지인 질문이 주장 2개짜리 답변을 가장 쉽게 만든다.
- 분야마다 최소 15개는 위 표의 **대상별 규정** 중 같은 문단에 두 대상의 값이 있는 규정을 묻는다. ⑧ 할당량은 분야마다 6이다. 하지만 검색 결과에 두 값이 함께 들어오는지는 E3 뒤에야 알 수 있으므로 넉넉히 쓴다. 이 질문은 대상 하나를 정확히 지정해 묻는다(예: "골드 등급은 ..."). 이 질문은 답이 하나인 질문(`two_part: false`)으로 쓴다. ⑥과 ⑧은 답이 하나인 질문에만 만들기 때문이다(스펙 3-2절). 이 조건은 질문 300개를 커밋(54db617)한 뒤에 정했다. 이미 쓴 질문은 고치지 않고 E4 Step 3 의 하한으로 확인한다.
- 대상을 좁히는 수식어는 정답 문서에 실제로 있는 낱말로만 쓴다(AGENTS.md 의 평가 문항 검수 기준).
- 한 질문이 여러 문서를 이어 읽어야만 답할 수 있게 만들지 않는다. 검색 결과 다섯 청크 안에서 답이 끝나야 한다.
- 개정 전의 옛 값을 묻는 질문은 쓰지 않는다(`23_2026년_금리_및_수수료_변경.md`, 인사 규정 `01_정규직_인사규정.md` 의 2026년 개정 사항 절). 옛 값과 새 값이 함께 검색되면 ⑥을 만들 수 없는 문항이 생긴다(스펙 3-2절).

형식은 이 계획의 형식 1 이다. `answer`, `claims`, `contrast`, `answer_note` 는 `null` 로 둔다. 분야 순서는 `hr`, `shop`, `manual`, `finance` 이고 `qid` 는 분야마다 001~075 다.

- [ ] **Step 3: 형식을 확인한다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-v2/ai-service
$PY - <<'EOF'
from collections import Counter
from tools.judge5v2_files import QUESTIONS, read_jsonl
qs = read_jsonl(QUESTIONS)
print(Counter(q["domain"] for q in qs), Counter((q["domain"], q["two_part"]) for q in qs))
assert len({q["qid"] for q in qs}) == len(qs)
assert all(q["answer"] is None and q["claims"] is None and q["contrast"] is None for q in qs)
EOF
```

Expected: 분야마다 75, `two_part` 가 `True` 인 질문이 분야마다 약 30.

- [ ] **Step 4: 커밋한다**

```bash
git add ai-service/testdata/judge5v2/questions.jsonl ai-service/testdata/judge5v2/hr_targets.md
git commit -m "test: 채점 모델 비교 v2 의 분야별 질문 75개를 쓴다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/testdata/judge5v2/questions.jsonl ai-service/testdata/judge5v2/hr_targets.md
```

**리뷰 포인트:** 질문 열 개를 무작위로 골라 정답 문서에서 답을 찾을 수 있는지 본다. 값이 같은 칸을 묻는 질문에 대상별 규정 표기가 잘못 붙어 있지 않은가.

---

### Task E3: 검색한다

**뉴런을 쓴다.** 질문 약 300개의 임베딩과 Cloudflare 리랭커 호출. 양은 재보지 않았다. E1 과 같은 날 끝내는 것이 좋다(M1 을 다음 날 돌리기 위해서다).

**Files:**
- Create: `ai-service/testdata/judge5v2/retrieved.jsonl`
- Modify: `ai-service/testdata/judge5v2/run_log.md`

- [ ] **Step 1: 열 개로 먼저 돌려 본다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-v2/ai-service
BOTS=$($PY -c "import json; b=json.load(open('testdata/judge5v2/bots.json')); print(' '.join(f'--bot {k}={v}' for k, v in b.items()))")
$PY -m tools.judge5v2_search $BOTS --limit 10
```

Expected: 분야별 `ok` 와 버린 원인의 수, 그리고 `이번 실행의 뉴런: {...}`. 이 뉴런 값으로 300개의 양을 어림해 `run_log.md` 에 적는다. 오늘 남은 한도를 넘을 것 같으면 나머지를 다음 날 돌리고 E12 를 하루 더 미룬다.

- [ ] **Step 2: 나머지를 돌린다**

```bash
$PY -m tools.judge5v2_search $BOTS
```

Expected: 종료 코드 0. 중간에 실패하면 같은 명령을 다시 실행한다(판정이 정해진 질문은 건너뛴다). `run_log.md` 에 실행의 시작과 끝 시각(한국 시각)을 적는다. M1 채점 날을 정할 때 쓴다(날짜와 뉴런 절).

- [ ] **Step 3: 결과를 확인하고 적는다**

```bash
$PY - <<'EOF'
from collections import Counter
from tools.judge5v2_files import RETRIEVED, read_jsonl
from tools.judge5v2_files import latest_by_qid
rows = latest_by_qid(read_jsonl(RETRIEVED))   # 질문마다 마지막 줄이 판정이다(계획 형식 2)
print(Counter((r["domain"], r["drop_reason"] or "ok") for r in rows))
print("200자 이하 근거만 있는 질문:", sum(1 for r in rows if r["sources"] and all(len(s["content"]) <= 200 for s in r["sources"])))
EOF
```

분야별, 원인별 수와 실행 뉴런을 `run_log.md` 의 "검색 (날짜)" 절에 적는다. `max_distance` 원인이 0이 아니면 검색 설정이 기본값과 다르다는 신호다(스펙 2-3절). 멈추고 오케스트레이터에 알린다.

`rerank_failed` 나 `keyword_failed` 가 하나라도 있으면 수와 관계없이 Step 2 의 명령을 **한 번 더** 돌린다. 검색 도구는 그 질문만 다시 검색한다(형식 2). 다시 해도 실패한 질문은 그 줄을 판정으로 두고 시험지에서 뺀다. 첫 시도의 실패 수와 다시 한 뒤의 실패 수를 둘 다 `run_log.md` 에 적는다. 줄을 손으로 지우지 않는다. 다시 해도 실패가 분야마다 5개 이상이면 Cloudflare 상태를 확인하고 오케스트레이터에 알린다.

**이 다시 하기는 E5(배정) 전에 끝낸다.** 이유: CI 의 배정 점검(`71a99ae`)은 회차 0 의 후보가 "질문 001~075 중 검색 마지막 줄이 `ok` 인 질문 전부" 와 같은지 본다. E5 뒤에 다시 검색해 001~075 의 질문 하나가 `ok` 로 바뀌면 그 질문은 회차 0 의 후보에 없으므로 이 점검이 실패한다.

보충 때(E4 Step 3, E10) 이 명령을 다시 돌리면 새 질문과 함께, 앞서 호출 실패로 남은 질문도 다시 검색된다. 검색 도구에는 이것을 막는 인자가 없다. 그 질문이 번호 001~075 이고 E5 뒤에 `ok` 가 되면 위 이유로 배정 점검이 실패한다. **보충 검색 뒤에는 `$PY -m tools.judge5v2_check` 를 돌리고, 회차 0 의 후보가 다르다는 실패가 나오면 멈추고 오케스트레이터에 알린다.** 이 경우의 처리(그 줄을 남길지, 점검을 고칠지)는 아직 정하지 않았다. 번호 076 이후의 보충 질문이 `ok` 가 되면 E4 에서 그 질문의 멀쩡한 답변을 쓴다. 배정 도구가 답변이 빈 질문을 거절하기 때문이다.

- [ ] **Step 4: 커밋한다**

```bash
git add ai-service/testdata/judge5v2/retrieved.jsonl ai-service/testdata/judge5v2/run_log.md
git commit -m "test: 채점 모델 비교 v2 의 질문마다 근거 청크를 실제 검색으로 뽑는다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/testdata/judge5v2/retrieved.jsonl ai-service/testdata/judge5v2/run_log.md
```

Step 1, 2 의 명령이 "검색 설정이 config.py 의 기본값과 다릅니다" 로 멈추면 셸에 남은 환경변수나 `.env` 를 고친 뒤 다시 실행한다. `--allow-nondefault` 는 쓰지 않는다(쓰면 결과 줄에 `nondefault` 가 남고, 그 줄로 만든 문항은 기본 설정의 검색이 아니다). "--bot 이 testdata/judge5v2/bots.json 과 다릅니다" 로 멈추면 Step 1 의 `BOTS` 변수를 다시 만든다. "retrieved.jsonl 에 지금과 다른 검색 설정으로 뽑은 줄이 N개 있습니다" 로 멈추면(`4980edf`) 설정을 그 줄들과 같게 맞춘다. `--allow-nondefault` 를 줘도 이 경우는 멈춘다. 줄을 옮기거나 지우지 않는다. 꼭 해야 하면 그 전에 오케스트레이터에 알린다. 옮긴 질문은 다시 검색해 뉴런을 쓰고, E5 뒤라면 배정 점검(회차에 기록된 검색 파일 해시)이 깨진다(`217048d`).

**리뷰 포인트:** `settings` 가 모든 줄에서 같은가, 그리고 `reranker_enabled`, `hybrid_enabled` 가 `true` 인가. `nondefault` 키가 있는 줄이 없는가. 근거 전문이 앞 200자로 잘리지 않았는가(Step 3 의 둘째 줄).

---

### Task E4: 멀쩡한 답변을 쓴다 (출제 세션)

**Files:**
- Modify: `ai-service/testdata/judge5v2/questions.jsonl` (`answer`, `claims`, `contrast`, `answer_note` 를 채운다)

- [ ] **Step 1: 말투 견본을 다시 읽는다**

`style_samples.json` 의 다섯 답변을 읽는다. 짧은 평서문, 존댓말, 대개 한두 문장이다. 원문의 일본어 낱말(`ただ`)처럼 언어가 섞인 표현은 따라 하지 않는다(스펙 3-1절). 근거 번호(`근거 1에서는`)를 답변에 적지 않는다. 견본 중 하나가 그렇게 썼지만 따라 할 습관이 아니다.

- [ ] **Step 2: 검색을 통과한 질문마다 멀쩡한 답변을 쓴다**

`retrieved.jsonl` 에서 질문마다 마지막 줄(형식 2)의 `status` 가 `ok` 인 질문만 쓴다. 버린 질문은 `answer` 를 `null` 로 둔다.

**정답이 근거 5청크 밖인 질문은 `excluded.json` 에 적는다**(스펙 2-3절, `5cb9a46`). `status` 가 `ok` 여도 그 질문의 근거 청크 다섯 개에 답이 없으면 근거만으로 멀쩡한 답변을 쓸 수 없다. 이유는 `reason` 에 `answer_not_in_top5` 로 적는다. 답이 두 가지인 질문에서 한쪽 답만 없으면 `partial_answer_not_in_top5` 다. `note` 에 무엇이 없었는지 한 줄을 적는다. 배정 도구가 이 질문을 후보에서 뺀다. 이 판단은 근거만 보고 한다. 문서 원문에 답이 있는지는 보지 않는다(검색이 못 찾은 것이 원인이다). 2026-10-05 의 E4 에서 9개를 적었다(`e9afd8c`. 금융 7, 인사 1, 쇼핑몰 1, 그중 2개가 `partial_answer_not_in_top5`).

- **근거 청크 전문만 보고 쓴다.** 문서 원문을 다시 열어 근거에 없는 사실을 보태지 않는다. 답변 생성 모델(llama)은 부르지 않는다(스펙 3-1절).
- 답이 두 가지인 질문의 답변도 같은 말투(짧은 평서문, 존댓말)로 두 사실을 모두 답한다.
- `claims`: 답변에서 근거와 대조해 참과 거짓을 따로 가릴 수 있는 사실의 수다. "연차는 15일이고, 3일 전까지 신청하면 됩니다." 는 2다. 질문을 되풀이하는 말("문의하신 연차는")은 세지 않는다. 두 가지를 묻는 질문의 답이 세 사실이 되면 그대로 3으로 적는다(억지로 2에 맞추지 않는다. 배정 도구가 자격에 맞는 질문만 고른다).
- `contrast`: **답이 하나인 질문(`two_part: false`)에만** 적는다. 이 질문의 근거 청크(그 질문의 `sources`)에 묻는 대상과 다른 대상의 값이 **글자 그대로 함께** 있고 **두 값이 다를 때만** 형식 1 대로 적는다. `chunk_ids` 는 두 값이 적힌 청크의 id 다. 값 글자는 청크에 적힌 그대로 옮긴다(`10,000원` 을 `1만 원` 으로 바꾸지 않는다. 배정 도구가 글자로 확인한다). 위 **값이 같은 칸** 목록에 해당하면 적지 않는다. 대상이 셋 이상이면 묻는 대상과 값이 가장 다른 대상 하나를 `other` 로 고른다.

- [ ] **Step 3: 배정 도구의 검사를 미리 돌린다**

```bash
$PY - <<'EOF'
from tools.judge5v2_assign import eligible3, eligible4, eligible6, eligible8, pool_for
from tools.judge5v2_files import QUESTIONS, QUOTA, RETRIEVED, read_jsonl
pools = pool_for(read_jsonl(QUESTIONS), read_jsonl(RETRIEVED))
# 하한. ④ 와 ③ 은 같은 질문을 두고 다투므로 ③ 자격은 둘의 할당량 합만큼 있어야 한다. ⑥ 과 ⑧ 도 같은 이유로
# 답이 하나인 질문이 둘의 합만큼 있어야 한다. 하한을 넘어도 배정에서 모자랄 수는 있다(E5 Step 1 이 다시 본다).
need = {"④자격": QUOTA[4], "③자격": QUOTA[3] + QUOTA[4], "⑧자격": QUOTA[8], "답이 하나": QUOTA[6] + QUOTA[8]}
short = []
for d, ps in pools.items():
    got = {"④자격": sum(map(eligible4, ps)), "③자격": sum(map(eligible3, ps)),
           "⑧자격": sum(map(eligible8, ps)), "답이 하나": sum(map(eligible6, ps))}
    print(d, len(ps), got)
    short += [f"{d} {k} {got[k]} < {n}" for k, n in need.items() if got[k] < n]
print("모자람:", short or "없음")
EOF
```

Expected: 오류 없이 분야마다 한 줄, 그리고 `모자람: 없음`. `sum(map(eligible4, ps))` 는 자격 함수를 질문마다 불러 True 의 수를 센다(파이썬에서 True 는 1 로 더해진다).

모자란 분야가 있으면 그 분야의 질문을 E2 Step 2 의 조건으로 더 쓴다(qid 는 이어서). ④자격이나 ③자격이 모자라면 답이 두 가지인 질문(`two_part: true`) 위주로 쓴다. ⑧자격이 모자라면 대상별 규정을 묻는 답이 하나인 질문을 쓴다. 답이 하나인 질문이 모자라면 `two_part: false` 질문을 쓴다. 더 쓴 질문은 E3 으로 검색한 뒤(뉴런) 이 태스크를 이어 한다. 이 경우 E12 는 그 검색 다음 날 이후다.

⑧자격에 하한을 거는 이유: 배정 도구는 ⑧ 이 모자라면 ⑥ 으로 돌리고(스펙 3-3절 5), 보충 배정은 돌린 수만큼 ⑧ 목표를 줄인다. 따라서 E5 뒤에 ⑧ 이 모자라면 관문 4(⑧ 15문항 이상)를 보충으로 회복할 길이 없다. 그래서 ⑧ 이 모자란 것을 배정 전인 이 단계에서 잡는다.

- [ ] **Step 4: 커밋한다**

```bash
git add ai-service/testdata/judge5v2/questions.jsonl
git commit -m "test: 채점 모델 비교 v2 의 멀쩡한 답변과 주장 수, 다른 대상 조건을 적는다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/testdata/judge5v2/questions.jsonl
```

**리뷰 포인트:** 답변 열 개를 골라 모든 주장이 그 질문의 근거 청크에 있는지, `claims` 가 위 정의대로인지 본다. 답변 길이가 견본과 비슷한가(대개 20~150자).

---

### Task E5: 배정한다

**Files:**
- Create: `ai-service/testdata/judge5v2/assignment.json`

**먼저 확인한다:** `excluded.json`(E4, `e9afd8c`)이 커밋돼 있고, 배정 도구가 그 질문을 후보에서 빼는 커밋(`a0557d2`)이 들어와 있다. 뒤의 것이 없으면 `first` 가 제외할 질문 9개를 후보에 넣는다(그 질문들은 `answer` 가 채워져 있다). 회차는 커밋 뒤 고치지 않으므로 배정 전에 본다. `excluded.json` 의 내용이 규칙에 어긋나면(원인 이름, 없는 질문, 검색에서 이미 버린 질문) `first` 가 종료 코드 1 로 고칠 곳을 알린다. 그 출력을 세션 가에 넘긴다.

- [ ] **Step 1: 배정 도구를 돌린다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-v2/ai-service
$PY -m tools.judge5v2_assign first
```

Expected: 분야마다 `배정 60, 쓰지 않음 N, ⑧ 을 ⑥ 으로 0`, 종료 코드 0. 종료 코드로 다음 할 일이 갈린다(`echo $?` 로 본다).

- 0: Step 2 로 간다.
- 1: 배정하지 못했다. `assignment.json` 은 만들어지지 않는다. 질문 파일에 잘못된 줄이 있으면 고칠 줄이 한국어로 나온다. 그 출력을 세션 가에 넘겨 E4 에서 고치게 한다.
- 2: 배정은 했지만 `멈춘다: 계획 E5.` 로 시작하는 줄이 나온다. ⑧ 을 ⑥ 으로 돌린 분야가 있다는 뜻이다. `assignment.json` 은 남아 있다. 아래 굵은 글씨 문단대로 한다.

할당량을 채우지 못했다는 출력이 나오면 그 출력을 세션 가(출제)에 넘겨 E4 Step 3 의 보충을 하게 하고, 끝난 뒤 다시 돌린다. 이때는 `assignment.json` 이 만들어지지 않는다.

**`⑧ 을 ⑥ 으로` 가 0 이 아닌 분야가 있으면 멈춘다.** 커밋하지 않고, 오케스트레이터가 사용자에게 분야별 수를 보인다. E4 Step 3 의 하한을 넘었어도 먼저 뽑는 ④ 가 ⑧ 자격 질문(주장이 2개인 답이 하나인 질문)을 가져가면 이 일이 생길 수 있다. 사용자가 보충을 고르면 `assignment.json` 을 지우고(아직 커밋 전이고 변형 답변도 없다) E4 Step 3 의 ⑧ 보충을 한 뒤 `first` 를 다시 돌린다. 사용자가 그대로 가기로 하면 네 분야의 ⑧ 합이 관문 4 의 15 이상인지 확인하고, 그 판단을 `run_log.md` 에 적는다. 그대로 가는 것은 E9 에서 ⑧ 이 버려져 관문 4 가 실패할 위험을 받아들이는 것이다.

- [ ] **Step 2: 재현을 확인한다**

```bash
$PY -m tools.judge5v2_check 2>&1 | grep -E 'replays|전부 통과'
```

Expected: `✅ check_committed_assignment_replays_and_is_eligible` 와 `63가지 전부 통과.` 이 점검은 회차 0 의 후보가 그 회차를 돌릴 때의 검색 파일(기록된 `retrieved_sha256` 의 앞부분)에서 검색을 통과하고 멀쩡한 답변이 있는 질문 중 그 회차가 제외한 질문(회차 기록의 `excluded`)을 뺀 전부인지도 본다(`3b494c5`, `1e35626`). E5 뒤에 줄이 덧붙는 것(보충 질문, 다시 검색)은 괜찮고, 앞 줄을 고치거나 지우면 실패한다.

- [ ] **Step 3: 커밋한다**

```bash
git add ai-service/testdata/judge5v2/assignment.json
git commit -m "test: 채점 모델 비교 v2 의 변형 유형을 시드로 배정한다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/testdata/judge5v2/assignment.json
```

**리뷰 포인트:** `eighth_to_sixth` 가 모든 분야에서 0 인가. 0 이 아니면 사용자의 판단이 `run_log.md` 에 적혀 있는가.

---

### Task E6: 변형 답변을 쓴다 (출제 세션)

**Files:**
- Create: `ai-service/testdata/judge5v2/variants.jsonl`

- [ ] **Step 1: 배정을 읽고 문항마다 변형 답변을 쓴다**

`assignment.json` 의 모든 회차에서 배정된 qid 마다 한 줄을 쓴다(형식 4). `note` 에는 무엇을 바꿨는지 한 줄을 적는다. 사용자가 불일치 문항을 판단할 때 읽는다.

**`questions.jsonl` 은 고치지 않는다.** 배정 회차의 `pool` 에 든 질문의 줄(`answer`, `claims`, `contrast`, `two_part`)은 E5 뒤로 고치지 않는다. 이유는 둘이다. 첫째, CI 의 배정 재현 점검(`check_committed_assignment_replays_and_is_eligible`)이 이 줄들로 배정을 다시 돌려 보므로, `claims` 나 `contrast` 를 고치면 재현이 깨진다. 둘째, `answer` 를 고치면 ① 문항의 답변이 바뀌어 `case_id` 가 바뀌고, 이미 받은 검수 줄이 짝을 잃는다. 변형 답변을 쓰다가 자격이 틀린 질문(예: `claims` 를 잘못 셌다)을 발견하면 배정된 유형대로 쓸 수 있는 만큼 쓰고, `note` 첫머리에 `자격 의심:` 과 이유를 적는다. 그 문항은 검수와 사용자 판단(E9 의 `drop`)으로 처리한다. 보충 때 새 질문 줄을 더하거나, 어느 `pool` 에도 들지 않은 질문의 빈 칸을 채우는 것은 된다.

유형마다 만드는 방법(스펙 3-2절). **근거 청크 전체** 는 그 질문의 `sources` 다섯 청크 모두다. 질문과 관계없는 청크도 포함한다.

- ① 원본 그대로: 멀쩡한 답변을 글자 하나 바꾸지 않고 옮긴다.
- ② 표현만 바꿈: 뜻과 주장 수는 그대로 두고 문장만 바꾼다. 값(숫자, 기간, 조건)은 근거의 글자 그대로 둔다. 근거에 없는 말을 한 마디도 보태지 않는다.
- ③ 사소한 말 하나 추가: 멀쩡한 답변 끝에 **근거 청크 전체 어디에도 다뤄지지 않는 주제** 의 사소한 문장 하나를 더한다. 근거가 다루는 주제(예: 신청 방법, 수수료)를 다른 값으로 덧붙이면 근거와 반대로 읽혀 1점이 될 수 있다. 질문의 핵심 답은 건드리지 않는다.
- ④ 절반 바꾸기: 주장의 정확히 절반을 근거 청크 전체가 다루지 않는 주제의 주장으로 바꾼다. 주장 2개면 1개, 4개면 2개다. 남는 주장은 글자 그대로 둔다.
- ⑤ 대부분 지어냄: 근거에 있는 주장 하나만 남기고, 근거에 없는 주장을 셋 이상 더한다. 더하는 주장도 근거가 다루지 않는 주제여야 한다.
- ⑥ 핵심을 근거와 반대로: 질문의 핵심 답을 **근거 청크 어디에도 없는 다른 값** 으로 바꾼다. 숫자는 크기와 관계없이 다른 숫자면 된다. 바꾼 값이 근거의 다른 청크(옛 값, 다른 대상의 값)에 글자로 있으면 안 된다. 바꿔 넣은 값은 `new_value` 에 답변의 글자 그대로 적고, 바꾸기 전의 값은 `old_value` 에 멀쩡한 답변의 글자 그대로 적는다(형식 4). 두 값 모두 따옴표로 감싼 글자로 적는다(숫자로 적으면 거절된다, `d368ba5`). 내보내기 도구가 `new_value` 는 답변에 있고 `sources` 전문 어디에도 없는지, `old_value` 는 멀쩡한 답변에 있고 변형 답변에는 없는지 확인한다. 옛 값을 "기존 기준은 ..." 처럼 답변에 남기지 않는다. `old_value` 가 없는 ⑥ 줄은 E7 에서 거절된다. ⑥ 은 답이 하나인 질문에만 배정된다(배정 도구가 보장한다).
- ⑦ 통째로 지어냄: 근거와 관계없는 절차와 숫자로 그럴듯하게 답한다. 근거 청크 전체가 다루는 주제를 쓰지 않는다.
- ⑧ 다른 대상의 규정 끌어오기: 묻는 대상의 값(`contrast.asked.value`) 자리에 다른 대상의 값(`contrast.other.value`)을 글자 그대로 넣는다. 값이 숫자가 아니라 구절(예: `가입 후 30일 이내`)이어도 조사, 띄어쓰기, 단위까지 한 글자도 바꾸지 않고 담는다. 내보내기 도구는 값을 글자로 찾으므로(형식 1 의 값을 글자로 찾는 규칙) 바꿔 쓰면 거절한다. 묻는 대상의 값은 답변에 남기지 않는다("골드는 10,000원, 실버는 20,000원입니다" 처럼 두 값을 다 쓰면 거절된다). 말투와 나머지 문장은 멀쩡한 답변과 같게 둔다. ⑧ 도 답이 하나인 질문에만 배정된다.

만들지 않는 것: 질문의 핵심이 아닌 부가 정보만 근거와 반대로 바꾸는 변형(스펙 3-2절 끝). 이런 변형이 되어 버리면 다른 방식으로 다시 쓴다.

- [ ] **Step 2: 내보내기 도구의 검사를 미리 돌린다**

```bash
$PY -c "
from tools.judge5v2_export import ExportProblem, load_and_build
try:
    rows, key = load_and_build(); print('문항', len(rows))
except ExportProblem as e:
    print('\n'.join(e.problems))
"
```

Expected: `문항 240` (보충이 있었으면 그 수만큼 더).

- [ ] **Step 3: 커밋한다**

```bash
git add ai-service/testdata/judge5v2/variants.jsonl
git commit -m "test: 채점 모델 비교 v2 의 변형 답변을 쓴다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/testdata/judge5v2/variants.jsonl
```

**리뷰 포인트:** ⑥ 의 `new_value` 가 실제로 핵심 답 자리의 값이고 `old_value` 가 멀쩡한 답변의 핵심 값인지 다섯 개를 골라 본다(근거에 없는지, 옛 값이 남았는지는 내보내기 도구가 확인한다). ③, ④, ⑤ 에서 더한 주장이 근거가 다루는 주제가 아닌지 본다. `questions.jsonl` 이 이 태스크에서 바뀌지 않았는가(`git diff --stat`).

---

### Task E7: 첫 시험지를 만든다

**Files:**
- Create(커밋하지 않음): `ai-service/testdata/judge5v2/cases.jsonl`, `cases.sha256`, `answer_key.json`

- [ ] **Step 1: 내보낸다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-v2/ai-service
$PY -m tools.judge5v2_export draft
```

Expected: `시험지 240문항, SHA-256 ...` 과 `검수 점수가 아직 없는 문항 240개.`

이 단계의 파일은 커밋하지 않는다. 검수가 끝나면 E11 이 같은 이름으로 최종본을 다시 만든다. 검수 세션에는 이 파일을 직접 주지 않는다. E8 Step 1 이 저장소 밖 폴더로 사본을 옮긴다.

**리뷰 포인트:** `cases.jsonl` 의 줄을 하나 열어 키가 `case_id`, `domain`, `messages`, `search_settings` 넷뿐인지 본다.

---

### Task E8: 검수한다 (Codex 검수 세션)

**검수 세션은 Claude 가 아니라 Codex(OpenAI) 세션이다.** 사용자가 저장소 밖의 전용 폴더에서 새로 연다. 오케스트레이터는 Codex 에 메시지를 보낼 수 없다. 그래서 오케스트레이터가 폴더를 준비하고(Step 1), 사용자가 Codex 를 열어 아래 지시문을 붙여 넣고(Step 2), 끝난 결과를 오케스트레이터가 워크트리로 옮긴다(Step 3).

Codex 로 검수하는 이유는 둘이다.

1. **출제와 검수의 모델 계열을 다르게 둔다.** 출제 세션은 Claude 다. 검수도 Claude 이면 Claude 가 함께 놓치는 실수는 검수를 통과한다. 계열이 다른 모델이 검수하면 두 모델이 함께 놓친 실수만 통과한다. 서비스에서 답변 생성 모델과 채점 모델의 계열을 다르게 둔 것과 같은 원리다. 비교 대상 M1, M3, M4 에는 OpenAI 계열이 없으므로 검수 모델이 비교 대상과 겹치지 않는다.
2. **검수 세션이 정답이 적힌 파일에 닿지 않게 한다.** 워크트리에는 `answer_key.json`(draft, 문항마다 유형과 대응표 점수), `variants.jsonl`(무엇을 바꿨는지), `assignment.json`, `questions.jsonl`(① 문항은 시험지의 답변과 글자까지 같다), 재검수 때는 `mismatches.md` 까지 있다. 저장소 안에서 일하면 파일 목록 한 번이면 이 파일들이 보인다. 또 Codex 는 시작할 때 `AGENTS.md` 를 자동으로 읽고, 이 저장소의 `AGENTS.md` 는 최신 핸드오프를 먼저 읽게 한다. 핸드오프에는 유형 구성과 비율이 적혀 있다. 그래서 검수 세션은 시험지 사본 하나만 든 저장소 밖 폴더에서 일한다. 지시문의 금지는 그대로 두되 유일한 방어선이 아니다.

시험지의 문서는 모두 가상 문서다(인사 규정은 저장소의 시험용 코퍼스, 나머지 셋은 출제 세션이 쓴 문서). 고객 데이터가 아니므로 OpenAI 로 보내도 된다. 앞 스펙이 코랩(Google 서버)에 시험지를 올린 것과 같은 이유다.

**Files:**
- Create(저장소 밖): `/Users/cheonjamin/judge5v2_review/r<회차>/cases.jsonl`, 같은 폴더의 `review.jsonl`
- Create 또는 Modify: `ai-service/testdata/judge5v2/review.jsonl`(옮긴 결과를 덧붙인다), `ai-service/testdata/judge5v2/run_log.md`

- [ ] **Step 1: 검수 폴더를 만들고 시험지를 옮긴다** (오케스트레이터)

검수 회차 `R` 은 첫 검수가 1 이고, 보충 뒤 재검수(E10)마다 1 씩 올린다. 회차마다 새 폴더를 쓴다. 옮기는 줄은 `review.jsonl` 에 검수 점수가 아직 없는 문항뿐이다. 첫 검수에서는 전부이고, 재검수에서는 보충 문항뿐이다.

```bash
R=1
DIR=/Users/cheonjamin/judge5v2_review/r$R
mkdir -p "$DIR" && test -z "$(ls -A "$DIR")" || echo "빈 새 폴더가 아니다. 멈춘다"
cd /Users/cheonjamin/projects/AllDap-judge-v2/ai-service
$PY - "$DIR" <<'EOF'
import json, sys
from pathlib import Path
from tools.judge5v2_files import CASES, REVIEW, read_jsonl
done = {r["case_id"] for r in read_jsonl(REVIEW)}
todo = [r for r in read_jsonl(CASES) if r["case_id"] not in done]
out = Path(sys.argv[1]) / "cases.jsonl"
out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in todo), encoding="utf-8")
print(len(todo), "문항을 옮겼다:", out)
EOF
ls -A "$DIR"                                                     # cases.jsonl 하나뿐이어야 한다
for d in "$DIR" /Users/cheonjamin/judge5v2_review /Users/cheonjamin /Users/cheonjamin/.codex; do
  test -e "$d/AGENTS.md" && echo "AGENTS.md 가 있다: $d. 멈춘다"
done
git -C "$DIR" rev-parse --show-toplevel 2>/dev/null && echo "git 저장소 안이다. 멈춘다"
```

Expected: `N 문항을 옮겼다`, `ls` 의 출력은 `cases.jsonl` 하나, 그 밖의 출력은 없다. `AGENTS.md` 를 확인하는 이유: Codex 는 `~/.codex/AGENTS.md` 와, git 저장소 안이면 저장소 꼭대기에서 작업 폴더까지의 `AGENTS.md` 를 읽는다. 이 폴더가 git 저장소 밖이고 위 자리에 `AGENTS.md` 가 없으면 Codex 가 읽는 지침은 붙여 넣은 지시문뿐이다.

- [ ] **Step 2: 사용자가 Codex 를 열고 지시문을 붙여 넣는다** (사용자)

오케스트레이터가 사용자에게 아래 셋을 안내한다.

1. 새 터미널에서 `cd /Users/cheonjamin/judge5v2_review/r<회차> && codex` 로 Codex 를 새로 연다. 다른 폴더에서 열거나 앞 회차의 Codex 대화를 이어 쓰지 않는다.
2. 아래 지시문 전체를 붙여 넣는다.
3. 끝나면 Codex 의 `/status` 에 나오는 모델 이름과 `codex --version` 의 출력을 오케스트레이터에 알려 준다. 결과 문서에 검수 모델의 이름과 판을 적기 위해서다.

붙여 넣을 지시문:

```text
이 폴더에서 답변 채점을 검수한다. 아래를 지킨다.

1. 읽는 파일은 이 폴더의 cases.jsonl 하나다. 쓰는 파일은 이 폴더의 review.jsonl 하나다. 이 폴더 밖의 파일과 폴더는 읽지도 찾지도 않는다. 웹 검색도 하지 않는다. 다른 곳에는 문항을 어떻게 만들었는지가 적혀 있을 수 있고, 그것을 보면 검수가 정답을 보고 매기는 일이 된다.

2. cases.jsonl 의 한 줄이 한 문항이다. 줄마다 messages[1].content 에 근거(<근거> 안), 질문(<질문> 안), 평가할 답변("###Response to evaluate:" 아래), 채점 기준과 점수표("###Score Rubrics:" 아래)가 들어 있다. messages[0] 과, content 안의 출력 형식 지시("[RESULT]" 로 쓰라는 것)는 채점 모델에게 주는 것이다. 그 형식은 따르지 않고 아래 4번의 형식으로 쓴다.

3. 문항마다 답변의 충실성을 1~5 정수로 매긴다. 충실성은 답변의 모든 주장이 근거에 실제로 적혀 있는가다. 답변이 세상의 상식에 맞는지는 보지 않는다. 사실이더라도 근거에 없으면 점수를 낮춘다. 근거에는 질문과 관계없는 청크도 섞여 있다. 점수의 뜻은 아래와 같다.
   5: 답변의 모든 주장이 근거에 적혀 있다
   4: 답변의 핵심 답은 근거와 일치한다. 다만 근거에 없는 사소한 주장이 하나 있다
   3: 근거에 있는 주장과 근거에 없는 주장이 비슷한 정도로 섞여 있다
   2: 답변의 주장 대부분이 근거에 없다
   1: 답변이 근거와 관계없는 내용을 지어냈거나, 근거와 반대되는 내용을 말한다
   점수는 문항마다 근거와 답변을 직접 읽고 판단한다. 낱말이 겹치는지 세는 것 같은 규칙으로 점수를 매기는 프로그램을 쓰지 않는다. 파일을 읽고 쓰는 짧은 명령은 써도 된다. 점수가 고르게 퍼지도록 맞추려 하지 않는다.

4. 결과는 review.jsonl 에 문항마다 한 줄의 JSON 으로 쓴다. 키는 정확히 셋이다.
   {"case_id": "<cases.jsonl 의 case_id 그대로>", "review_score": <1~5 정수>, "review_note": "<판단 이유 한 문장, 한국어>"}
   review_note 에는 어느 주장이 근거에 있고 어느 주장이 없는지, 또는 근거와 어떻게 다른지를 적는다.

5. 50문항마다 review.jsonl 에 저장한다. 끊겼다가 다시 시작하면 review.jsonl 에 이미 있는 case_id 는 건너뛴다.

6. 끝나면 review.jsonl 의 줄 수가 cases.jsonl 의 줄 수와 같은지, case_id 가 빠지거나 겹치지 않는지 확인하고 그 결과를 알려 준다.
```

지시문 3번의 기준 문장과 점수의 뜻은 `tools/judge5.py` 의 `CRITERIA`, `RUBRIC` 과 글자가 같다. 채점 모델이 받는 채점표와 같은 기준으로 검수하기 위해서다. 지시문에는 저장소의 경로, 변형 유형, 대응표, 유형 비율을 적지 않는다.

- [ ] **Step 3: 결과의 형식을 확인하고 워크트리로 옮긴다** (오케스트레이터)

`$DIR` 은 Step 1 에서 정한 이번 회차의 폴더다.

```bash
cd /Users/cheonjamin/projects/AllDap-judge-v2/ai-service
$PY - "$DIR" <<'EOF'
import sys
from pathlib import Path
from tools.judge5v2_files import REVIEW, append_jsonl, read_jsonl
d = Path(sys.argv[1])
cases, rows = read_jsonl(d / "cases.jsonl"), read_jsonl(d / "review.jsonl")
want = {c["case_id"] for c in cases}
ids = [r.get("case_id") for r in rows]
already = {r["case_id"] for r in read_jsonl(REVIEW)}
problems = []
if len(ids) != len(set(ids)):
    problems.append("case_id 가 겹치는 줄이 있다")
if set(ids) != want:
    problems.append(f"빠진 문항 {len(want - set(ids))}개, 시험지에 없는 문항 {len(set(ids) - want)}개")
if set(ids) & already:
    problems.append("이미 review.jsonl 에 있는 문항이다")
for r in rows:
    # type(x) is int: True 와 False 도 int 의 한 종류라서 isinstance 로는 걸러지지 않는다.
    if set(r) != {"case_id", "review_score", "review_note"}:
        problems.append(f"{r.get('case_id')}: 키가 셋(case_id, review_score, review_note)이 아니다")
    elif type(r["review_score"]) is not int or r["review_score"] not in (1, 2, 3, 4, 5):
        problems.append(f"{r['case_id']}: review_score 가 1~5 정수가 아니다")
    elif not isinstance(r["review_note"], str) or not r["review_note"].strip():
        problems.append(f"{r['case_id']}: review_note 가 비었다")
if problems:
    print("옮기지 않았다.", *problems[:20], sep="\n  - ")
    sys.exit(1)
for r in rows:
    append_jsonl(REVIEW, r)
print("옮겼다:", len(rows), "문항. review.jsonl 은 이제", len(read_jsonl(REVIEW)), "줄")
EOF
```

Expected: `옮겼다: N 문항`. "옮기지 않았다" 가 나오면 그 목록을 사용자에게 보이고, 같은 Codex 대화에서 고치게 한 뒤 이 단계를 다시 한다. 결과를 손으로 고쳐 맞추지 않는다.

그다음 `run_log.md` 에 "검수 (회차 R)" 절을 더한다. 적을 것: 검수 모델의 이름(`/status`), Codex CLI 의 판(`codex --version`), 폴더 경로, 옮긴 문항 수, 시작과 끝 시각.

- [ ] **Step 4: 커밋한다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-v2
git add ai-service/testdata/judge5v2/review.jsonl ai-service/testdata/judge5v2/run_log.md
git commit -m "test: 채점 모델 비교 v2 의 문항을 변형 유형을 모르는 Codex 세션이 검수한다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/testdata/judge5v2/review.jsonl ai-service/testdata/judge5v2/run_log.md
```

**리뷰 포인트:** 검수 폴더에 `cases.jsonl` 말고 다른 파일을 두지 않았는가(Step 1 의 `ls`). 사용자가 Codex 화면에서 폴더 밖 파일을 연 기록이 없는지 확인했는가. `run_log.md` 에 검수 모델의 이름과 판이 있는가.

---

### Task E9: 불일치 문항을 사용자가 판단한다

**사람이 판단한다.** 검수 점수와 정답 점수가 다른 문항은 사용자가 정한다(스펙 4절).

**Files:**
- Create(커밋하지 않음): `ai-service/testdata/judge5v2/mismatches.md`
- Modify: `ai-service/testdata/judge5v2/review.jsonl` (불일치 문항에 `user_decision`, `override_score`, `reason` 을 더한다)

- [ ] **Step 1: 불일치 목록을 만든다**

```bash
$PY -m tools.judge5v2_export mismatches
```

- [ ] **Step 2: 오케스트레이터가 사용자에게 문항을 보여 판단을 받는다**

한 번에 열 문항 안팎으로 나눠 보인다. 문항마다 변형 유형, 대응표 점수, 검수 점수, 검수 메모(Codex 의 `review_note`), 출제 메모를 보이고 셋 중 하나를 받는다. 출제 메모가 `자격 의심:` 으로 시작하면(E6) 그 사실도 함께 보인다.

- `keep`: 대응표 점수가 맞다. 이유 한 줄.
- `override`: 정답 점수를 고친다. 고친 점수와 이유 한 줄.
- `drop`: 정답이 애매하다, 또는 판단하지 않는다. 이유 한 줄(판단하지 않은 경우 "사용자가 판단하지 않음").

받은 판단을 `review.jsonl` 의 그 줄에 더한다(형식 7).

- [ ] **Step 3: 빠진 판단이 없는지 확인하고 커밋한다**

```bash
$PY -m tools.judge5v2_export mismatches   # "사용자 판단이 필요한 문항 0개" 여야 한다
git add ai-service/testdata/judge5v2/review.jsonl
git commit -m "test: 채점 모델 비교 v2 의 검수 불일치 문항에 사용자 판단을 적는다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/testdata/judge5v2/review.jsonl
```

**리뷰 포인트:** `override` 와 `keep` 에 이유가 모두 있는가. 한 유형에 불일치가 몰렸으면(예: ③ 의 절반) 그 사실을 결과 문서의 재료로 오케스트레이터가 적어 두었는가.

---

### Task E10: 변별력 관문을 확인한다

**Files:**
- Create: `ai-service/testdata/judge5v2/gate.md`

- [ ] **Step 1: 관문을 돌린다**

```bash
$PY -m tools.judge5v2_gate; echo "종료 코드 $?"
```

Expected(통과): 다섯 줄 모두 `통과`, 종료 코드 0. 그러면 E11 로 간다.

- [ ] **Step 2: 통과하지 못하면 보충한다**

먼저 실패 원인이 아래 5번(보충으로 고칠 수 없는 경우)에 해당하는지 본다. 해당하지 않으면 1~4번을 한다.

1. 조건 1, 3, 4 가 버린 문항 때문에 실패하면 할당량이 모자란 것이다. `$PY -m tools.judge5v2_assign supplement; echo "종료 코드 $?"` 를 먼저 돌린다. 종료 코드가 1 이고 "이미 배정된 질문" 을 말하면(`85cbb89`) 앞 회차에서 유형을 받은 질문이 `excluded.json` 에 들어간 것이다. 그 줄을 `excluded.json` 에서 빼고, 그 문항은 검수에서 `drop` 한다(E9). 종료 코드가 2 이면(`d368ba5`) 그 회차는 파일에 붙었지만 ⑧ 을 ⑥ 으로 돌린 분야가 있다. 출력이 "멈춘다: 계획 E10, ..." 으로 시작하고 되돌리는 명령을 함께 찍는다(`a0557d2`). 커밋하지 않고 멈춘다. 보충 배정은 돌린 ⑧ 을 다시 요구하지 않으므로 아래 5번의 셋째 경우가 된다. 사용자에게 분야별 수를 보이고, 사용자가 ⑧ 자격 질문을 더 쓰기로 하면 `assignment.json` 을 커밋된 판으로 되돌린 뒤(`git checkout -- ai-service/testdata/judge5v2/assignment.json`) 세션 가가 ⑧ 자격 질문을 더 쓰고 E3, E4 를 거쳐 다시 `supplement` 를 돌린다. 그대로 가기로 하면 그 판단을 `run_log.md` 에 적고 커밋한다. 보충 배정은 앞 회차들에서 쓰지 않은 질문도 다시 뽑는다(스펙 3-3절 6). 할당량을 채우지 못했다는 출력이 나오면, 그 분야의 질문을 세션 가가 더 쓰고(E2 Step 2, qid 를 이어서), E3(검색, **뉴런**), E4 를 거쳐 다시 `supplement` 를 돌린다. 출제 세션이 질문을 보고 유형을 고르지 않는다(스펙 7-2절).
2. 세션 가가 새 배정분의 변형 답변을 쓴다(E6). 이미 쓴 줄은 고치지 않는다.
3. `$PY -m tools.judge5v2_export draft` 로 시험지를 다시 만든다. 출력의 "검수 점수가 아직 없는 문항" 만 E8 을 다음 회차로 다시 해서 매긴다. 새 폴더(`r2`, `r3`, ...)에 그 문항만 옮기고, 사용자가 그 폴더에서 Codex 를 새로 연다.
4. E9, E10 을 다시 한다.
5. 아래 경우는 보충으로 고칠 수 없다. 멈추고 사용자에게 `gate.md` 와 원인을 보인다. 결과 문서에 그 경위를 적는다.
   - 조건 2 나 5 만 실패하고 `supplement` 가 보충할 할당량이 없다고 낸 경우. 할당량으로는 고칠 수 없는 쏠림이다.
   - 조건 3 이 사용자의 `override` 때문에 실패한 경우. 예: ③ 여러 개를 5점으로 고쳐 4점 문항이 20개 밑으로 줄었다. `supplement` 는 유형의 수만 보고 최종 정답 점수는 보지 않는다. 그래서 유형 수가 그대로이면 보충할 할당량이 0 으로 나온다.
   - 조건 4 의 ⑧ 이 모자라고, 어느 회차의 `eighth_to_sixth` 가 0 이 아닌 경우. 보충 배정은 ⑥ 으로 돌린 수만큼 ⑧ 목표를 줄이므로 ⑧ 을 다시 요구하지 않는다.

관문 결과는 통과 여부와 관계없이 남긴다. 실패한 회차의 `gate.md` 내용은 `run_log.md` 의 "관문 (회차)" 절에 옮겨 적는다.

- [ ] **Step 3: 커밋한다**

```bash
git add ai-service/testdata/judge5v2/gate.md ai-service/testdata/judge5v2/run_log.md
git commit -m "test: 채점 모델 비교 v2 의 변별력 관문 결과를 남긴다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/testdata/judge5v2/gate.md ai-service/testdata/judge5v2/run_log.md
```

**리뷰 포인트:** 보충이 있었다면 보충 질문의 유형을 출제 세션이 아니라 `supplement` 가 정했는가(`assignment.json` 의 회차 수).

---

### Task E11: 최종 시험지를 만들고 동결 커밋을 한다

이 커밋 뒤에 모델을 돌린다(스펙 8-1절 9단계). 이 커밋 뒤로는 `judge5v2_export draft` 가 거절된다(정답 파일이 최종본이라서. `f17877a`). 판정 규칙(스펙 6절)과 읽는 규칙 코드(태스크 2)는 이미 커밋돼 있다.

**Files:**
- Create: `ai-service/testdata/judge5v2/cases.jsonl`, `cases.sha256`, `answer_key.json`
- Modify: `ai-service/notebooks/judge5v2_colab.ipynb` (`EXPECTED_SHA256` 한 줄)

- [ ] **Step 1: 최종본을 만든다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-v2/ai-service
$PY -m tools.judge5v2_export final
```

Expected: `최종 시험지 N문항(버린 문항 M개). SHA-256: <해시>`. N 은 200 이상이다(관문 1).

- [ ] **Step 2: 노트북의 기대 해시를 넣는다**

노트북 둘째 코드 칸의 `EXPECTED_SHA256 = ""` 를 `EXPECTED_SHA256 = "<해시>"` 로 바꾼다. 다른 곳은 건드리지 않는다.

```bash
$PY - <<'EOF'
import json, pathlib
from tools.judge5v2_files import CASES_SHA
p = pathlib.Path("notebooks/judge5v2_colab.ipynb")
nb = json.loads(p.read_text(encoding="utf-8"))
sha = CASES_SHA.read_text(encoding="utf-8").split()[0]
hits = 0
for c in nb["cells"]:
    if c["cell_type"] == "code" and 'EXPECTED_SHA256 = ""' in c["source"]:
        c["source"] = c["source"].replace('EXPECTED_SHA256 = ""', f'EXPECTED_SHA256 = "{sha}"'); hits += 1
assert hits == 1
p.write_text(json.dumps(nb, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"); print(sha)
EOF
```

- [ ] **Step 3: 모든 점검을 돌린다**

```bash
$PY -m tools.judge5_check | tail -1 && $PY -m tools.judge5v2_check | tail -1
```

Expected: `44가지 전부 통과.` 그리고 `63가지 전부 통과.`

- [ ] **Step 4: 동결 커밋을 한다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-v2
git add ai-service/testdata/judge5v2/cases.jsonl ai-service/testdata/judge5v2/cases.sha256 \
        ai-service/testdata/judge5v2/answer_key.json ai-service/notebooks/judge5v2_colab.ipynb
git commit -m "test: 채점 모델 비교 v2 의 최종 시험지와 정답 파일을 모델을 돌리기 전에 동결한다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/testdata/judge5v2/cases.jsonl ai-service/testdata/judge5v2/cases.sha256 \
        ai-service/testdata/judge5v2/answer_key.json ai-service/notebooks/judge5v2_colab.ipynb
git log -1 --format=%H   # 이 해시를 run_log.md 와 결과 문서에 적는다
```

**리뷰 포인트:** 이 커밋 뒤에 `testdata/judge5v2/` 의 입력 파일(`questions`, `retrieved`, `assignment`, `variants`, `review`, `cases`, `answer_key`)이 다시 바뀌지 않는가. 바뀌면 동결이 깨진 것이다.

---

### Task E12: M1 을 채점한다

**뉴런을 쓴다(약 7,400).** 업로드(E1)와 검색(E3, 보충 검색 포함)을 한 날의 **다음 날 이후**, 그날 다른 뉴런 사용이 없을 때 돌린다.

**Files:**
- Create: `ai-service/testdata/judge5v2/results/M1_run1.jsonl` (실패가 있었으면 `M1_failures.jsonl` 도)
- Modify: `ai-service/testdata/judge5v2/run_log.md`

- [ ] **Step 1: 연결과 오늘의 한도를 확인한다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-v2/ai-service
$PY -m tools.judge5_cloudflare --smoke
```

Expected: 출력 끝에 `[RESULT]` 가 있고 `읽은 결과=(4, 'ok')` 근처의 값. 호출이 한도 초과로 실패하면 오늘은 돌리지 않는다.

- [ ] **Step 2: 열 문항으로 먼저 잰다**

```bash
$PY -m tools.judge5_cloudflare --cases testdata/judge5v2/cases.jsonl --results-dir testdata/judge5v2/results --limit 10
```

출력의 뉴런을 10 으로 나눠 건당 뉴런을 `run_log.md` 의 "M1 채점 (날짜)" 절에 적고, 문항 수를 곱해 전체를 어림한다. 어림값이 오늘 남은 한도를 넘을 것 같으면 나머지는 다음 날(한도 초기화 뒤) 이어 한다. 이어 하기는 이미 받은 문항을 다시 부르지 않는다. 시작 시각도 한국 시각으로 적는다(날짜와 뉴런 절).

- [ ] **Step 3: 나머지를 채점한다**

```bash
$PY -m tools.judge5_cloudflare --cases testdata/judge5v2/cases.jsonl --results-dir testdata/judge5v2/results
```

Expected: `M1_run1.jsonl: N/N건. ... 뉴런 {...}`. 끝나면 결과 줄의 `finish` 값을 센다.

```bash
$PY -c "
import json, collections
rows = [json.loads(l) for l in open('testdata/judge5v2/results/M1_run1.jsonl', encoding='utf-8') if l.strip()]
print(collections.Counter(r['finish'] for r in rows))
"
```

세 값(`stop`, `length`, `None`)의 수를 `run_log.md` 에 적는다. 이유: v2 의 대괄호 끝 규칙은 `finish` 가 `stop` 인 출력에만 적용된다(`adc2aea`, 스펙 6-4절 세부 규칙 2). Cloudflare 가 응답 형식에 따라 `finish` 를 주지 않으면 `None` 으로 남고, 그 출력은 `[RESULT]` 가 없을 때 끝이 `[4]` 여도 못 읽음이 된다. `None` 이 있다고 해서 다시 돌리거나 규칙을 바꾸지 않는다(규칙은 출력을 보기 전에 고정됐다). 보고서와 결과 문서에 그 수를 적는다. 빠진 문항이 있으면 같은 명령을 다시 실행한다(빠진 문항만 부른다). 여러 번 다시 불러도 받지 못한 문항이 남으면 보고서를 만들지 않고 오케스트레이터에 알린다(스펙 6-5절).

- [ ] **Step 4: 뉴런과 끝난 시각을 적고 커밋한다**

```bash
P="ai-service/testdata/judge5v2/results/M1_run1.jsonl ai-service/testdata/judge5v2/run_log.md"
F=ai-service/testdata/judge5v2/results/M1_failures.jsonl
test -e "$F" && P="$P $F"     # 실패 기록은 실패가 있었을 때만 생긴다
git add $P
git commit -m "test: 채점 모델 비교 v2 의 시험지를 M1 으로 채점한다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- $P
```

**리뷰 포인트:** 모든 줄에 `domain` 이 있고 `cases_sha256` 이 동결 커밋의 해시와 같은가. 이 태스크에서 출력을 보고 무엇을 고치지 않았는가.

---

### Task E13: 코랩에서 M3, M4 를 채점한다

**사용자가 돌린다.** 약 2.3시간(한 모델 약 68분).

**Files:**
- Create: `ai-service/testdata/judge5v2/results/{M3_run1.jsonl, M4_run1.jsonl, M3_smoke.json, M4_smoke.json, env.json}` (건너뛴 모델이 있으면 `{모델}_skipped.json`)

- [ ] **Step 1: 사용자에게 안내한다**

1. Google Drive 에 `MyDrive/alldap_judge5v2/` 폴더를 만들고 `ai-service/testdata/judge5v2/cases.jsonl` 을 올린다.
2. `ai-service/notebooks/judge5v2_colab.ipynb` 를 코랩에서 연다. 노트북 머리말의 실행 방법을 따른다(T4, `HF_TOKEN`, 모두 실행).
3. 끝나면 내려받은 `alldap_judge5v2_results.zip` 의 경로를 알려 준다.

- [ ] **Step 2: 결과를 풀고 확인한다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-v2/ai-service
unzip -o <zip 경로> -d testdata/judge5v2/results
$PY -c "
import json
from tools.judge5v2_files import ANSWER_KEY, RESULTS_DIR, read_json, read_jsonl
ak = read_json(ANSWER_KEY)
for m in ('M3', 'M4'):
    rows = read_jsonl(RESULTS_DIR / f'{m}_run1.jsonl')
    print(m, len(rows), all(r['cases_sha256'] == ak['cases_sha256'] for r in rows), all('domain' in r for r in rows))
"
```

Expected: 두 줄 모두 문항 수, `True`, `True`.

- [ ] **Step 3: 커밋한다**

```bash
git add ai-service/testdata/judge5v2/results/
git commit -m "test: 채점 모델 비교 v2 의 시험지를 코랩에서 M3, M4 로 채점한 결과를 더한다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/testdata/judge5v2/results/
```

**리뷰 포인트:** `env.json` 의 GPU 가 T4 이고 transformers 판이 노트북의 고정 판과 같은가. `{모델}_smoke.json` 의 `generation` 에 `repetition_penalty` 1.0 이 적혔는가.

---

### Task E14: 보고서, 결과 문서, PR

**Files:**
- Create: `ai-service/testdata/judge5v2/report.md`, `docs/superpowers/plans/2026-10-05-judge-selfhost-v2-results.md`
- Modify: `docs/decisions.md` (한 줄)

- [ ] **Step 1: 보고서를 만든다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-v2/ai-service
$PY -m tools.judge5v2_report
```

Expected: `보고서: .../report.md`. "보고서를 만들지 않았습니다" 가 나오면 그 이유를 오케스트레이터에 알린다. 결과 파일을 손으로 고쳐 맞추지 않는다.

- [ ] **Step 2: 결과 문서를 쓴다**

앞 결과 문서(`plans/2026-10-02-judge-selfhost-results.md`)의 구조를 따른다. 반드시 담는 것:

1. 동결 커밋 해시, 시험지 해시, 문항 수.
2. 문항이 줄어든 경위: 검색에서 버린 질문(분야별, 원인별, `keyword_failed` 가 스펙에 없던 원인이라는 점 포함, 호출 실패는 첫 시도와 다시 한 뒤의 수), 정답이 근거 청크 밖이라 뺀 질문(분야별, 원인별. 스펙 2-3절. 출제 세션의 판단이 들어갔다는 점과, 금융에 몰린 것은 검색 품질 관찰로 남기되 이 실험의 주제가 아니라는 점을 함께 적는다. 스펙 9절), 쓰지 않은 질문(모든 회차 뒤), ⑧ 을 ⑥ 으로 돌린 수, 검수 불일치(유지, 고침, 버림)와 유형별 분포.
3. 검수 모델: 회차마다 Codex 의 모델 이름과 판, Codex CLI 의 판(`run_log.md` 의 검수 절).
4. 관문 결과(보충 회차가 있었으면 회차마다).
5. 보고서의 수치와 판정(스펙 6-2절, 6-3절의 문장 그대로). "사람과 비슷하다" 는 쓰지 않는다(스펙 9절).
6. 뉴런(업로드, 검색, M1)과 코랩 시간의 실측.
7. 스펙 9절의 한계와, 실행하면서 새로 알게 된 한계.

- [ ] **Step 3: 결정 로그에 한 줄을 남긴다**

`docs/decisions.md` 형식(`날짜 | 무엇을 | 왜 그렇게 | 검토한 대안`)으로 이 실험의 결론 한 줄.

- [ ] **Step 4: 커밋하고 PR 을 연다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge-v2
git add ai-service/testdata/judge5v2/report.md docs/superpowers/plans/2026-10-05-judge-selfhost-v2-results.md docs/decisions.md
git commit -m "docs: 채점 모델 비교 v2 의 결과와 결정을 남긴다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ai-service/testdata/judge5v2/report.md docs/superpowers/plans/2026-10-05-judge-selfhost-v2-results.md docs/decisions.md
git push -u origin feat/judge-selfhost-v2
gh pr create --title "채점 모델 비교 v2: 점수가 정해진 시험 문제로 다시 비교한다" --body-file <PR 템플릿을 채운 파일>
```

PR 본문은 `.github/PULL_REQUEST_TEMPLATE.md` 를 채운다. **한계와 트레이드오프** 칸과 **검토한 대안** 칸을 비우지 않는다. 본문 끝에 `🤖 Generated with [Claude Code](https://claude.com/claude-code)` 를 붙인다. CI 를 기다리지 않는다.

**리뷰 포인트:** 결과 문서의 모든 숫자가 `report.md` 와 `run_log.md` 에 있는 숫자인가. 판정 문장이 "대응표에 더 가깝다" 또는 "구별되지 않음" 중 하나인가.
