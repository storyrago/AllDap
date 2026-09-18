# 평가셋 난이도 확보 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 활성 평가 문항을 16 → 26 으로 늘리고(질문 난이도 ①) 필요하면 코퍼스에 같은 주제·다른 대상 문서 5~7개를 더해(②), 전체충실성을 0.9375 에서 **0.75~0.88 구간**으로 내린다. 그래야 다음 개선(리랭커 파인튜닝)의 효과를 측정할 수 있다.

**Architecture:** 새 평가 도구를 만들지 않는다. 이미 있는 네 도구(`eval_set` dump/load · `eval_set_review` · `eval_set_check` · `rank_trace`)와 기존 평가 실행 경로(`POST /internal/bots/{id}/eval/runs`)를 그대로 쓴다. 코드 변경은 **`difficulty` 필드 하나를 파일에 배관하고 CI 가 그것을 검증하게 하는 것**이 전부이고, 나머지는 데이터(질문·문서) 변경과 측정이다. 질문과 코퍼스를 **다른 측정점으로 나눠** 바꿔, 점수가 내려간 원인을 둘로 갈라 말할 수 있게 한다.

**Tech Stack:** Python 3.12 · FastAPI · psycopg(+pgvector) · PostgreSQL 16 · Cloudflare Workers AI(임베딩·생성·채점·리랭커) · 저장소 관례상 pytest 없이 `python -m app.*_check` 자체 점검

**설계문서:** `docs/superpowers/specs/2026-09-18-eval-set-difficulty-design.md` (아래 "§" 는 전부 이 문서를 가리킨다)

## Global Constraints

- **완료 조건은 전체충실성 0.75~0.88, 3회 반복 편차 0.04 이내.** 판정 분포(①②③④)는 게이트가 아니라 기록이다.
- 🔴 **판정 ① 의 개수를 완료 조건으로 삼지 않는다.** ① 을 노리고 질문을 깎으면 평가셋이 리랭커 전용으로 기운다.
- **기존 16문항은 한 글자도 안 건드린다.** 회귀 감지기(대조군)로 남긴다. 비활성 4문항도 `active: false` 그대로 둔다.
- **중단 조건(돌리기 전에 정한 것, §중단 조건):**
  - 1단계 후 0.88 초과 → 멈추지 않고 2단계로 가되 "질문만으로는 안 내려간다" 를 결론으로 기록
  - 2단계 후에도 0.88 초과 → **3단계로 밀지 않고 멈춘다.** 가설 반증이 성과다
  - 0.75 미만 → `rank_trace` 로 원인 문항을 본다. 결함이면 `active: false`, 정당한 난이도면 그대로
  - 편차 0.04 초과 → 경계 문항 수를 세어 **기록한다. 문항을 빼서 편차를 맞추지 않는다**
- **변형 규칙 셋의 판정 기준(2026-09-18 에 세운 것을 그대로 쓴다):** 질문의 낱말이 <다른 문서에> 있으면 **결함**, <아무 데도> 없으면 **난이도**.
- **대상 구분(규칙 2)에 쓰는 낱말은 정답 문서 안에 실제로 있어야 한다** (2026-08-11 교훈: 정답 문서에 없는 말로 물으면 정답 문서가 오히려 불리해진다).
- `eval_set_check` 는 **CI 에서 돌므로 DB 도 외부 API 도 쓰지 않는 검사만** 추가한다. 코퍼스 파일 읽기는 이 조건을 만족한다.
- 비용: 26문항 = 회당 약 1,300 뉴런. 측정점당 3회 = 3,900. 하루 한도 10,000. **측정점 ① 과 ② 는 다른 날에 돌린다**(실패 여유). 한도를 소진하면 리셋은 문서의 00:00 UTC 가 아니라 **소진 시각 + 약 24~33시간**이다.
- 에러 메시지·주석은 한국어. em dash 금지.
- 아래 명령들이 쓰는 `$SCRATCH` 는 이 세션의 스크래치패드다. 셸을 새로 열 때마다 먼저 정한다:
  `export SCRATCH=/private/tmp/claude-501/-Users-cheonjamin-projects-AllDap/449db453-d421-40ee-85c8-047a64214fee/scratchpad`
- 🔴 **`load` 쪽은 고칠 것이 없다.** `difficulty` 는 파일에만 있는 칸이고 `eval_questions` 에 그 컬럼이 없다.
  load 가 그것을 DB 에 넣으려 들면 스키마를 바꾸게 되는데, 이 값은 <사람이 파일에 적는 검수 산출물>이지
  평가 실행이 쓰는 값이 아니다. 값을 가진 쪽이 하나여야 어긋났을 때 어느 쪽이 맞는지 알 수 있다.
- 브랜치는 이미 `feat/eval-set-difficulty` 다. 커밋 메시지는 `<타입>: <한국어 요약>`.

## 파일 구조

| 파일 | 책임 | 이 계획에서 |
|---|---|---|
| `ai-service/app/eval_set.py` | DB ↔ 파일 왕복 | dump 가 사람이 적은 `difficulty` 를 이어받게 한다 (Task 1) |
| `ai-service/app/eval_set_review.py` | 검수 재료 출력(DB 안 씀) | 낱말 빈도 세는 함수를 밖에서 쓸 수 있게 빼고, `difficulty` 를 함께 찍는다 (Task 1) |
| `ai-service/app/eval_set_check.py` | 파일 자체 점검(CI) | `difficulty` 규칙 검증 + 어휘 치환 낱말 0회 검증 + 활성 문항 수 26 (Task 2 · 3) |
| `ai-service/testdata/eval_questions.json` | 평가셋 원본 | 새 문항 10개 + 전 문항에 `difficulty` 칸 (Task 1 · 3) |
| `ai-service/testdata/corpus/` | 코퍼스 | 같은 주제·다른 대상 문서 5~7개 (Task 5) |
| `AGENTS.md` · `docs/decisions.md` · `docs/BACKLOG.md` | 기록 | 결과와 판정 분포 (Task 7) |

---

### Task 1: `difficulty` 필드를 파일에 배관한다

**왜 먼저인가:** `difficulty` 는 사람이 적는 값이고 `eval_questions` 테이블에 그 칸이 없다. 즉 `review` 와 똑같이 **dump 가 파일에서 이어받지 않으면 dump 를 한 번 돌리는 순간 사람이 적은 것이 지워진다.** 문항을 먼저 추가하고 나중에 배관하면 그 사이의 dump 한 번이 전부를 날린다.

**Files:**
- Modify: `ai-service/app/eval_set.py` (`previous_reviews` → `previous_annotations`, `build_payload`, `dump`)
- Modify: `ai-service/app/eval_set_review.py` (`count_in_corpus` 추출 + `difficulty` 출력)
- Modify: `ai-service/testdata/eval_questions.json` (전 20문항에 빈 `difficulty` 칸)

**Interfaces:**
- Produces: `eval_set._empty_difficulty() -> dict` = `{"rule": "", "words": [], "note": ""}`
- Produces: `eval_set.previous_annotations() -> dict[str, dict]` — 질문 본문 → `{"review": {...}, "difficulty": {...}}`
- Produces: `eval_set.build_payload(rows, annotations=None) -> dict`
- Produces: `eval_set_review.count_in_corpus(word: str, corpus: dict[str, str]) -> list[tuple[str, int]]` — `[(문서명, 등장횟수)]`, 등장 횟수 내림차순. Task 2 의 `eval_set_check` 가 이 함수를 그대로 쓴다.

- [ ] **Step 1: `difficulty` 의 모양을 정하고 파일에 빈 칸을 넣는다**

`review` 와 같은 자리에 같은 모양으로 둔다. 세 칸의 뜻:

| 칸 | 뜻 |
|---|---|
| `rule` | `""`(생성기 원본, 손대지 않음) · `"lexical"`(어휘 치환) · `"target"`(대상 구분) · `"clause"`(조항 지목) |
| `words` | 그 규칙이 실제로 쓴 낱말. `lexical` 이면 코퍼스 0회여야 하는 말, `target` 이면 정답 문서에 있어야 하는 말 |
| `note` | 왜 그 변형이 어렵게 만드는지 한 줄 |

`ai-service/testdata/eval_questions.json` 의 **모든** 문항(비활성 4개 포함)에 아래 칸을 `review` 바로 뒤에 넣는다. 기존 20문항은 전부 생성기 원본이므로 `rule` 이 빈 문자열이다.

```json
      "difficulty": {
        "rule": "",
        "words": [],
        "note": ""
      }
```

- [ ] **Step 2: dump 가 `difficulty` 를 이어받게 한다**

`ai-service/app/eval_set.py` 에서 `_empty_review` 바로 아래에 추가:

```python
def _empty_difficulty() -> dict:
    """난이도 칸의 빈 모양. `review` 와 같은 이유로 한 군데서만 만든다.

    `rule` 이 빈 문자열이면 <생성기가 준 것을 손대지 않았다>는 뜻이다.
    "칸이 없다" 와 "손대지 않았다" 를 같은 값으로 뭉개지 않으려고 빈 칸도 미리 만든다.
    """
    return {"rule": "", "words": [], "note": ""}
```

그리고 `previous_reviews()` 를 아래 `previous_annotations()` 로 **대체**한다. 이어받는 대상이 둘(`review` · `difficulty`)이 되었을 뿐, 질문 본문으로 맞추는 것도 중복이면 둘 다 버리는 것도 그대로다. 함수 이름을 바꾸는 이유는 **이제 review 만 이어받지 않기 때문**이고, 이름이 남아 있으면 다음 사람이 difficulty 도 이어받는다는 것을 모른다.

```python
# 파일에만 있고 DB 에는 없는 칸들. 이 목록에 있는 것은 dump 가 <기존 파일에서> 이어받는다.
# 여기 빠뜨리면 dump 한 번으로 사람이 적은 것이 지워진다(설계 §7-2 의 왕복 검증이 그 지뢰다).
_FILE_ONLY_KEYS = {"review": _empty_review, "difficulty": _empty_difficulty}


def previous_annotations() -> dict[str, dict]:
    """기존 파일에서 <질문 본문 → 사람이 적은 칸들> 표를 만든다. 파일이 없으면 빈 표.

    왜 DB 가 아니라 파일에서 이어받는가
      `review` 도 `difficulty` 도 사람이 적는 값이고 `eval_questions` 에 그 칸이 없다.
      즉 DB 를 아무리 읽어도 나오지 않는다. 유일한 사본이 이 파일이라,
      dump 가 기존 파일을 안 읽으면 <사람이 적은 것을 dump 가 지운다.>

    왜 `id` 가 아니라 질문 본문으로 맞추는가
      `id` 는 파일 안에서만 쓰는 <순번>이다. 문항이 하나 추가되거나 빠지면 뒤가 전부
      밀려서, q5 의 사유가 엉뚱한 질문에 붙는다. 질문 본문은 그 문항의 정체 자체라 안 밀린다.

    ⚠️ `active` 는 여기서 이어받지 않는다. DB 의 `is_active` 를 그대로 쓴다.
       값을 가진 쪽이 하나여야 파일과 DB 가 어긋났을 때 어느 쪽이 맞는지 알 수 있다.
    """
    if not EVAL_SET_PATH.exists():
        return {}
    try:
        old = json.loads(EVAL_SET_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        # 여기서 죽이지 않는다. 깨진 파일 때문에 dump 자체가 막히면 DB 의 질문을
        # 건져낼 방법이 없어진다. 대신 이어받기를 포기했다는 사실은 반드시 찍는다.
        print("⚠️  기존 평가셋 파일이 올바른 JSON 이 아니라 사람이 적은 칸을 이어받지 못했습니다.")
        return {}

    table: dict[str, dict] = {}
    duplicated: set[str] = set()
    for q in old.get("questions") or []:
        question = q.get("question")
        if not question:
            continue
        ann = {key: (q.get(key) or empty()) for key, empty in _FILE_ONLY_KEYS.items()}
        if question in table and table[question] != ann:
            # 같은 질문이 두 번 있는데 적힌 내용이 다르면 어느 쪽인지 고를 수 없다.
            # 조용히 하나를 고르는 것이 이 저장소가 반복해 낸 실수라, 둘 다 버린다.
            duplicated.add(question)
        table[question] = ann
    for question in duplicated:
        table.pop(question, None)
        print(f"⚠️  기존 파일에 같은 질문이 두 번 있고 적힌 내용이 달라 이어받지 않았습니다: "
              f"{question[:40]}...")
    return table
```

`build_payload` 의 시그니처와 본문을 아래처럼 바꾼다(바뀌는 줄만 보인다).

```python
def build_payload(rows: list[tuple], annotations: dict[str, dict] | None = None) -> dict:
```

```python
    annotations = annotations or {}
```

```python
        ann = annotations.get(question) or {}
        questions.append({
            "id": f"q{n}",
            "question": question,
            "ground_truth": ground_truth,
            "source_doc": filename,
            "source_text": content,
            "active": bool(is_active),
            # 검수와 난이도는 사람이 적는다. 빈 칸을 <미리 만들어 두는> 이유는,
            # 칸이 아예 없으면 적는 사람이 무엇을 적어야 하는지 모르기 때문이다.
            "review": ann.get("review") or _empty_review(),
            "difficulty": ann.get("difficulty") or _empty_difficulty(),
        })
```

`dump()` 안의 호출 두 줄:

```python
    reviews = previous_reviews()
    payload = build_payload(rows, reviews)
```

를

```python
    annotations = previous_annotations()
    payload = build_payload(rows, annotations)
```

로 바꾸고, 그 아래 `carried`/`new` 계산과 출력의 `reviews` 를 `annotations` 로 바꾼다. 출력 문구도 "검수 내용" → "사람이 적은 칸" 으로 고친다.

```python
    carried = sum(1 for _db_id, question, *_ in rows if question in annotations)
    new = len(rows) - carried
    if annotations:
        print(f"기존 파일에서 사람이 적은 칸 {carried}건을 이어받았습니다 "
              f"(파일에 없던 새 질문 {new}건은 빈 칸으로 둡니다).")
    elif EVAL_SET_PATH.exists():
        print("기존 파일에서 이어받을 내용이 없어 전 문항을 빈 칸으로 씁니다.")
```

- [ ] **Step 3: `eval_set_review` 에서 낱말 빈도 함수를 빼내고 `difficulty` 를 찍는다**

`ai-service/app/eval_set_review.py` 의 `word_stats` 안에 인라인돼 있는 빈도 계산을 함수로 뺀다. Task 2 의 `eval_set_check` 가 **같은 함수**를 써야 검수와 CI 가 같은 기준으로 센다(다르면 검수에서 0회였던 낱말이 CI 에서 1회가 되는 일이 생긴다).

`load_corpus` 아래에 추가:

```python
def count_in_corpus(word: str, corpus: dict[str, str]) -> list[tuple[str, int]]:
    """그 낱말이 코퍼스의 어느 문서에 몇 번 나오는가. [(문서명, 횟수)] 등장 횟수 내림차순.

    `str.count` 는 겹치지 않는 부분 문자열의 개수를 센다. 하이브리드 검색도 LIKE
    부분 문자열 매칭이라 기준이 같다 - 검색이 보는 것과 검수가 보는 것을 일부러 맞춘 것이다.

    빈 목록이면 코퍼스 전체에 0회라는 뜻이고, 그것이 <정당한 난이도>의 판정 기준이다
    (설계 §변형 규칙 1: 다른 문서에 있으면 결함, 아무 데도 없으면 난이도).
    """
    hits = [(name, text.count(word)) for name, text in corpus.items()]
    hits = [h for h in hits if h[1] > 0]
    # 등장 횟수 내림차순, 같으면 파일명 순. 어느 문서가 이 낱말의 '본거지' 인지 먼저 보인다.
    hits.sort(key=lambda h: (-h[1], h[0]))
    return hits
```

`word_stats` 안의 세 줄

```python
        hits = [(name, text.count(word)) for name, text in corpus.items()]
        hits = [h for h in hits if h[1] > 0]
        hits.sort(key=lambda h: (-h[1], h[0]))
```

을 한 줄로 바꾼다:

```python
        hits = count_in_corpus(word, corpus)
```

그리고 `print_question` 안, `if review.get("note"):` 블록 바로 아래에 난이도를 찍는다. 검수자가 "이 문항은 어떤 규칙으로 어렵게 한 것인가" 를 표와 함께 봐야 하기 때문이다.

```python
    difficulty = item.get("difficulty") or {}
    if difficulty.get("rule"):
        words = ", ".join(difficulty.get("words") or []) or "(없음)"
        print(f"     난이도   규칙={difficulty['rule']} · 낱말={words}")
        if difficulty.get("note"):
            print(f"              {difficulty['note']}")
```

- [ ] **Step 4: 왕복이 사람이 적은 칸을 지우지 않는지 확인한다**

이 배관의 유일한 목적이 "dump 가 지우지 않는다" 이므로, **그것을 실제로 돌려서 본다.** DB 가 필요하므로 도커와 ai-service 가 떠 있어야 한다(`docker compose up -d` → `api` 기동 → 코퍼스가 봇 1에 적재돼 있어야 한다).

먼저 지워지면 안 되는 값을 하나 심는다. 파일의 q1 의 `difficulty` 를 임시로 채운다:

```bash
cd ai-service
python - <<'PY'
import json, pathlib
p = pathlib.Path("testdata/eval_questions.json")
d = json.loads(p.read_text(encoding="utf-8"))
d["questions"][0]["difficulty"] = {"rule": "lexical", "words": ["왕복시험용낱말"], "note": "왕복 시험용"}
p.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
.venv/bin/python -m app.eval_set dump --bot-id 1
grep -c "왕복시험용낱말" testdata/eval_questions.json
```

Expected: dump 가 "기존 파일에서 사람이 적은 칸 20건을 이어받았습니다" 를 찍고, `grep -c` 가 **1** 을 낸다. 0 이면 이어받기가 안 된 것이므로 Step 2 로 돌아간다.

확인했으면 심어둔 값을 되돌린다(git 이 원본이다):

```bash
git diff --stat testdata/eval_questions.json
git checkout -- testdata/eval_questions.json
```

⚠️ **여기서 `git checkout` 이 Step 1 의 빈 `difficulty` 칸까지 지운다.** Step 1 을 먼저 커밋해두면 안 지워진다. 순서대로 밟는다면 Step 5 의 커밋을 이 시험 <앞>에서 해도 된다.

- [ ] **Step 5: 파일 점검이 여전히 통과하는지 보고 커밋**

```bash
cd ai-service && .venv/bin/python -m app.eval_set_check
```

Expected: `전부 통과.` (아직 `difficulty` 검사를 안 넣었으므로 새 칸은 무시된다. 활성 16개 그대로)

```bash
cd /Users/cheonjamin/projects/AllDap
git add ai-service/app/eval_set.py ai-service/app/eval_set_review.py ai-service/testdata/eval_questions.json
git commit -m "feat: 평가셋 파일에 difficulty 칸을 배관한다

dump 가 사람이 적은 difficulty 를 이어받게 한다. review 와 같은 이유다 -
DB 에 그 칸이 없어 파일이 유일한 사본이고, 이어받지 않으면 dump 한 번으로 지워진다.
낱말 빈도 함수(count_in_corpus)를 빼서 다음 커밋의 CI 검사가 검수와 같은 기준으로 세게 한다.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `eval_set_check` 가 `difficulty` 를 검증하게 한다

**왜 문항 추가보다 먼저인가:** 검사를 나중에 붙이면 **이미 적어둔 10문항에 맞춰 검사를 쓰게 된다.** 그러면 검사가 아니라 받아쓰기다. 규칙 셋을 먼저 코드로 못박고 그 위에서 문항을 만든다.

**Files:**
- Modify: `ai-service/app/eval_set_check.py`
- Test(자체 점검의 점검): `/private/tmp/claude-501/-Users-cheonjamin-projects-AllDap/449db453-d421-40ee-85c8-047a64214fee/scratchpad/bad_difficulty.json` (`--file` 로 먹인다)

**Interfaces:**
- Consumes: `eval_set_review.count_in_corpus`, `eval_set_review.load_corpus` (Task 1)
- Produces: `eval_set_check.DIFFICULTY_RULES = ("lexical", "target", "clause")`
- Produces: `eval_set_check._check_difficulty(questions: list[dict], corpus_dir: Path, report: _Report) -> None`

- [ ] **Step 1: 실패하는 입력을 먼저 만든다**

이 저장소에는 pytest 가 없고 `*_check.py` 가 스스로 데이터를 검사한다. 그래서 "실패하는 테스트" 는 **검사에 걸려야 하는 가짜 평가셋 파일**이다. `eval_set_check` 는 `--file` 을 받으므로 그대로 먹일 수 있다.

```bash
SCRATCH=/private/tmp/claude-501/-Users-cheonjamin-projects-AllDap/449db453-d421-40ee-85c8-047a64214fee/scratchpad
cd /Users/cheonjamin/projects/AllDap/ai-service
python - <<PY
import json, pathlib
src = json.loads(pathlib.Path("testdata/eval_questions.json").read_text(encoding="utf-8"))
qs = [q for q in src["questions"] if q["active"]][:3]
# ① 없는 규칙 이름  ② lexical 인데 낱말이 코퍼스에 있다("회의실" 은 20_회의실_및_공용공간.md 에 있다)
#  ③ target 인데 낱말이 정답 문서에 없다
qs[0]["difficulty"] = {"rule": "어려움", "words": [], "note": "규칙 이름이 틀렸다"}
qs[1]["difficulty"] = {"rule": "lexical", "words": ["회의실"], "note": "코퍼스에 있는 낱말"}
qs[2]["difficulty"] = {"rule": "target", "words": ["본사"], "note": "정답 문서에 없는 말"}
src["questions"] = qs
pathlib.Path("$SCRATCH/bad_difficulty.json").write_text(
    json.dumps(src, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("wrote")
PY
```

- [ ] **Step 2: 지금은 안 걸리는 것을 확인한다**

```bash
cd /Users/cheonjamin/projects/AllDap/ai-service
.venv/bin/python -m app.eval_set_check --file $SCRATCH/bad_difficulty.json; echo "종료코드=$?"
```

Expected: 활성 문항 수(3 ≠ 16) 때문에만 실패하고, **`difficulty` 에 대한 실패는 한 건도 없다.** 이것이 지금 검사에 구멍이 있다는 증거다.

- [ ] **Step 3: 검사를 구현한다**

`ai-service/app/eval_set_check.py` 의 import 에 추가:

```python
from .eval_set_review import count_in_corpus, load_corpus
```

`REQUIRED_CHUNKING` 아래에 규칙 목록을 둔다:

```python
# 난이도 변형 규칙 셋. 설계문서(2026-09-18-eval-set-difficulty-design.md §1단계)가 정한 것이다.
#   lexical  어휘 치환   - 코퍼스 전체에 0회인 동의어로 바꾼다
#   target   대상 구분   - distractor 와 갈리게 대상을 명시한다(그 말이 정답 문서에 있어야 한다)
#   clause   조항 지목   - 한 청크의 여러 조항 중 예외 조항 하나를 콕 집어 묻는다
# 빈 문자열("")은 <생성기가 준 것을 손대지 않았다>는 뜻이라 규칙이 아니지만 허용한다.
DIFFICULTY_RULES = ("lexical", "target", "clause")
```

그리고 `_check_source_texts` 아래에 검사 함수를 넣는다:

```python
def _check_difficulty(questions: list[dict], corpus_dir: Path, report: _Report) -> None:
    """`difficulty` 칸이 규칙을 지키는지 본다.

    🔴 여기서 잡는 것은 <난이도인가 결함인가>의 기계적 부분뿐이다.
       2026-09-18 에 세운 기준을 그대로 코드로 옮긴 것이다.
         lexical  그 낱말이 코퍼스 <어디에도> 없어야 한다. 다른 문서에 있으면 질문이
                  그 문서를 겨냥하는 것이므로 난이도가 아니라 결함이다.
         target   그 낱말이 <정답 문서 안에> 실제로 있어야 한다. 2026-08-11 교훈이다 -
                  정답 문서에 없는 말("본사" 같은)로 물으면 정답 문서가 오히려 불리해진다.
       질문이 좋은 질문인가는 여전히 사람 검수(`eval_set_review`)의 몫이다.

    DB 도 외부 API 도 쓰지 않는다. 코퍼스 파일만 읽으므로 CI 에서 돈다.
    """
    if not corpus_dir.is_dir():
        # `_check_source_texts` 가 이미 같은 실패를 보고했다. 두 번 찍지 않는다.
        return

    try:
        corpus = load_corpus(corpus_dir)
    except SystemExit as e:
        # load_corpus 는 .md 가 하나도 없으면 SystemExit 을 던진다(사람이 직접 돌리는
        # 검수 도구라 그 자리에서 죽는 것이 맞다). 여기서는 그대로 두면 <점검이 중간에
        # 끊겨> 나머지 실패가 화면에 안 나온다. 보고서 한 줄로 바꿔 담는다.
        report.fail(f"코퍼스를 읽지 못해 난이도 검사를 건너뜁니다: {e}")
        return

    checked = 0

    for q in questions:
        qid = q["id"]
        difficulty = q.get("difficulty")
        if not isinstance(difficulty, dict):
            report.fail(
                f"[{qid}] `difficulty` 칸이 없거나 객체가 아닙니다. "
                '손대지 않은 문항도 {"rule": "", "words": [], "note": ""} 로 명시하세요.'
            )
            continue

        rule = difficulty.get("rule")
        words = difficulty.get("words")
        note = difficulty.get("note")

        if not isinstance(rule, str) or not isinstance(words, list) or not isinstance(note, str):
            report.fail(f"[{qid}] `difficulty` 는 rule(문자열) · words(배열) · note(문자열) 이어야 합니다.")
            continue
        if any(not isinstance(w, str) or not w.strip() for w in words):
            report.fail(f"[{qid}] `difficulty.words` 에 빈 값이나 문자열이 아닌 값이 있습니다.")
            continue

        if rule == "":
            # 생성기가 준 것을 손대지 않은 문항. words 나 note 가 채워져 있으면
            # "규칙을 적는 것을 잊었다" 일 가능성이 높으므로 드러낸다.
            if words or note.strip():
                report.fail(
                    f"[{qid}] `rule` 이 비어 있는데 words/note 가 채워져 있습니다. "
                    f"어떤 규칙으로 어렵게 했는지 적어주세요: {', '.join(DIFFICULTY_RULES)}"
                )
            continue

        if rule not in DIFFICULTY_RULES:
            report.fail(
                f"[{qid}] 모르는 난이도 규칙 '{rule}' 입니다. "
                f"셋 중 하나여야 합니다: {', '.join(DIFFICULTY_RULES)}"
            )
            continue
        if not note.strip():
            report.fail(
                f"[{qid}] 규칙이 '{rule}' 인데 `note` 가 비어 있습니다. "
                "왜 그 변형이 어렵게 만드는지 한 줄 적어야 나중에 규칙별로 셀 수 있습니다."
            )
            continue

        if rule == "lexical":
            if not words:
                report.fail(f"[{qid}] 규칙이 'lexical' 인데 `words` 가 비어 있습니다. "
                            "코퍼스에 0회여야 하는 낱말을 적어주세요.")
                continue
            violated = False
            for word in words:
                hits = count_in_corpus(word, corpus)
                if hits:
                    violated = True
                    where = ", ".join(f"{n}({c}회)" for n, c in hits[:3])
                    report.fail(
                        f"[{qid}] 'lexical' 낱말 '{word}' 이 코퍼스에 {len(hits)}개 문서에 있습니다: {where}\n"
                        "   → 다른 문서에 있는 말로 물으면 난이도가 아니라 <결함>입니다. "
                        "코퍼스 전체에 0회인 말로 바꾸세요."
                    )
            # 🔴 걸린 문항은 세지 않는다. 아래 ✅ 줄이 "규칙을 지킨 문항 수" 를 말하는데,
            #    실패한 것까지 세면 같은 화면에서 ❌ 로 찍힌 문항을 ✅ 가 "지킨다" 고 센다.
            #    "검사했다" 와 "지켰다" 를 한 값으로 뭉개는 것이고, 이 저장소가 여덟 번 낸 부류다.
            checked += 0 if violated else 1

        elif rule == "target":
            if not words:
                report.fail(f"[{qid}] 규칙이 'target' 인데 `words` 가 비어 있습니다. "
                            "정답 문서에 실제로 있는 대상 낱말을 적어주세요.")
                continue
            doc_text = corpus.get(q["source_doc"], "")
            violated = False
            for word in words:
                if word not in doc_text:
                    violated = True
                    report.fail(
                        f"[{qid}] 'target' 낱말 '{word}' 이 정답 문서({q['source_doc']})에 없습니다.\n"
                        "   → 정답 문서에 없는 말로 물으면 정답 문서가 오히려 불리해집니다"
                        "(2026-08-11 교훈). 그 문서가 실제로 쓰는 말로 바꾸세요."
                    )
            checked += 0 if violated else 1

        else:  # clause
            checked += 1

    if checked:
        report.ok(f"난이도 규칙이 적힌 문항 {checked}개가 규칙을 지킵니다 "
                  f"(lexical 은 코퍼스 0회 · target 은 정답 문서에 있음)")
```

`main()` 의 검사 호출부에 한 줄 더한다:

```python
        if chunking is not None and questions:
            # `corpus` 는 ai-service/ 기준 상대 경로다(예: "testdata/corpus").
            corpus = ROOT / str(raw.get("corpus", "testdata/corpus"))
            _check_source_texts(questions, corpus, chunking, report)
            _check_difficulty(questions, corpus, report)
```

모듈 docstring 의 "닫는 축 / 안 닫는 축" 목록에 한 줄 추가:

```
  ✅ `difficulty` 가 규칙 셋 중 하나인가 · lexical 낱말이 코퍼스에 0회인가
```

- [ ] **Step 4: 가짜 파일이 이제 걸리는지 확인한다**

```bash
cd /Users/cheonjamin/projects/AllDap/ai-service
.venv/bin/python -m app.eval_set_check --file $SCRATCH/bad_difficulty.json; echo "종료코드=$?"
```

Expected: 세 문항에 대해 각각 실패가 찍힌다 - `모르는 난이도 규칙 '어려움'`, `'lexical' 낱말 '회의실' 이 코퍼스에 ... 있습니다`, `'target' 낱말 '본사' 이 정답 문서(...)에 없습니다`. 종료코드 1.

🔴 **실패만 보고 끝내지 말 것.** 실패만 확인하면 "아무거나 다 거르는 검사" 와 구별되지 않는다.
규칙을 <지키는> 가짜 파일(lexical 낱말이 코퍼스 0회 · target 낱말이 정답 문서에 있음 · clause)도
따로 만들어 `✅ 난이도 규칙이 적힌 문항 3개가 규칙을 지킵니다` 가 찍히는 것까지 보라.

- [ ] **Step 5: 진짜 파일이 여전히 통과하는지 확인한다**

```bash
cd /Users/cheonjamin/projects/AllDap/ai-service && .venv/bin/python -m app.eval_set_check; echo "종료코드=$?"
```

Expected: `전부 통과.` 종료코드 0 (전 문항이 `rule: ""` 이므로 난이도 검사는 아무것도 잡지 않는다).

- [ ] **Step 6: 커밋**

```bash
cd /Users/cheonjamin/projects/AllDap
git add ai-service/app/eval_set_check.py
git commit -m "feat: 난이도 변형 규칙을 CI 가 검증하게 한다

lexical 낱말이 코퍼스에 0회인지, target 낱말이 정답 문서에 있는지를 파일만 읽고 검사한다.
문항을 만들기 <전에> 규칙을 못박는다 - 나중에 붙이면 검사가 아니라 받아쓰기가 된다.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: 새 문항 10개를 만든다 (생성기 초안 → 사람 변형)

**Files:**
- Modify: `ai-service/testdata/eval_questions.json` (q21~q30 추가)
- Modify: `ai-service/app/eval_set_check.py` (`ACTIVE_EXPECTED` 16 → 26)

**전제:** 도커·ai-service 가 떠 있고 봇 1에 코퍼스 50문서가 적재돼 있다.

- [ ] **Step 1: 지금 세트를 백업한다**

`--replace` 는 `eval_results` 를 CASCADE 로 지운다. 2026-09-18 에 실제로 과거 실행 상세 144행이 이 자리에서 날아갔다.

```bash
cd /Users/cheonjamin/projects/AllDap
pg_dump "$DATABASE_URL" -t eval_questions -t eval_runs -t eval_results --data-only \
  > "$SCRATCH/eval_backup_$(date +%Y%m%d_%H%M).sql"
ls -la $SCRATCH/eval_backup_*.sql
```

Expected: 0바이트가 아닌 파일 하나. (`DATABASE_URL` 이 없으면 `ai-service/.env` 의 값을 쓴다)

- [ ] **Step 2: 생성기로 후보를 뽑는다**

사실(무엇이 정답인가)은 생성기가 준다. 정답 청크가 생성기가 본 그 청크로 고정되므로 꼬리표가 틀릴 위험이 없다.

```bash
curl -s -X POST localhost:8001/internal/bots/1/eval/questions/generate \
  -H 'content-type: application/json' -d '{"count": 20}' | python -m json.tool | head -60
```

Expected: 생성된 (질문, 정답) 쌍 목록. **20개를 뽑아 그중 10개를 고른다** - 2026-09-18 에 후보 4개 중 2개가 결함이었으므로 여유가 필요하다.

🔴 이 호출은 `eval_questions` 에 **바로 저장한다**(누적). 그래서 다음 Step 에서 파일로 내리고 DB 는 다시 파일 기준으로 되돌린다.

- [ ] **Step 3: 후보를 파일로 내린다**

```bash
cd ai-service && .venv/bin/python -m app.eval_set dump --bot-id 1
git diff --stat testdata/eval_questions.json
```

Expected: "사람이 적은 칸 20건을 이어받았습니다 (파일에 없던 새 질문 20건은 빈 칸으로 둡니다)" 그리고 파일에 q21~q40 이 붙는다. 기존 20문항의 `review`·`difficulty` 는 그대로다.

- [ ] **Step 4: 후보를 검수해 10개를 고른다 (사람이 한다)**

```bash
cd ai-service && .venv/bin/python -m app.eval_set_review | less
grep -rn "<후보 질문의 핵심 낱말>" testdata/corpus/ | wc -l
```

고르는 기준은 **결함이 아닌 것**이다(2026-09-18 기준 그대로):
- 질문이 겨냥하는 대상과 정답 청크가 규정하는 대상이 **같아야** 한다. `03_인턴_운영지침.md` 에서 나온 후보가 "수습" 을 묻고 있으면 버린다 - 이 결함은 우연이 아니라 구조적이다(생성기가 청크 하나만 본다).
- 🔴 는 판정이 아니라 읽을 순서다. 대상을 가리키는 **명사**에 붙은 것만 본다.

고른 10개를 파일에 남기고 **나머지 10개는 파일에서 지운다**(DB 에서는 Step 7 의 `--replace` 가 지운다).

- [ ] **Step 5: 고른 10개에 변형을 입힌다 (사람이 한다)**

`question` 본문을 고치고 `difficulty` 를 채운다. `ground_truth` · `source_doc` · `source_text` 는 **건드리지 않는다**(정답 청크가 바뀌면 꼬리표가 거짓이 된다).

규칙별 예시(실제 문항은 코퍼스를 보고 정한다):

```json
    {
      "id": "q21",
      "question": "기간제 직원이 자택 근무를 신청하려면 누구의 확인이 더 필요한가요?",
      "ground_truth": "팀장 외에 인사팀 확인이 추가로 필요합니다.",
      "source_doc": "02_계약직_인사규정.md",
      "source_text": "## 재택근무\n계약직의 재택근무는 주 1회까지 허용한다. 신청 절차는 정규직과 같으나 팀장 외에 인사팀 확인이 추가로 필요하다.\n계약 기간이 6개월 미만인 경우 재택근무를 신청할 수 없다.",
      "active": true,
      "review": { "verdict": "", "note": "" },
      "difficulty": {
        "rule": "lexical",
        "words": ["자택 근무"],
        "note": "문서는 전부 '재택근무' 라고 쓴다. '자택 근무' 는 코퍼스 0회라 키워드 순위가 안 오르고 벡터만으로 풀어야 한다."
      }
    }
```

```json
      "difficulty": {
        "rule": "target",
        "words": ["계약직"],
        "note": "같은 항목을 정규직·인턴·파견인력도 다른 숫자로 규정한다. 대상을 명시하지 않으면 distractor 가 상위를 먹는다."
      }
```

```json
      "difficulty": {
        "rule": "clause",
        "words": [],
        "note": "이 청크에 조항이 넷이라 임베딩이 네 주제의 평균이 된다. 그중 예외 조항 하나만 콕 집어 물어 청크 전체와의 유사도를 떨어뜨린다."
      }
```

🔴 `lexical` 낱말은 적기 전에 반드시 직접 확인한다:

```bash
cd ai-service && grep -ro "자택 근무" testdata/corpus/ | wc -l
```

Expected: **0**. 1 이상이면 그 말은 난이도가 아니라 결함이다.

⚠️ `target` 낱말은 반대다. 정답 문서 안에 **있어야** 한다:

```bash
grep -c "계약직" testdata/corpus/02_계약직_인사규정.md
```

Expected: 1 이상.

- [ ] **Step 6: 활성 문항 수 기대값을 26으로 올린다**

`ai-service/app/eval_set_check.py`:

```python
# 활성 문항 수를 <고정>한다. 결함 문항을 뺄 때 대체 문항을 넣어 수를 유지해야
# 한 문항의 무게(1/26 = 0.038)가 안 바뀌고 표들끼리 축이 맞는다.
# 2026-09-18 에 16 -> 26 으로 올렸다(난이도 확보 슬라이스). 한 문항의 무게가
# 0.0625 -> 0.038 로 줄어 측정 편차(0.032)와 개선을 가를 여지가 생긴다.
# 🔴 이 숫자를 고칠 때는 설계문서와 AGENTS.md 의 해당 절도 함께 고칠 것.
ACTIVE_EXPECTED = 26
```

같은 파일의 실패 메시지에 있는 `1/{ACTIVE_EXPECTED}` 문구는 그대로 두면 자동으로 26 을 가리킨다. 설계문서 참조는 `§5` 에서 이번 설계문서로 바꾼다:

```python
            f"활성 문항이 {len(active)}개입니다. {ACTIVE_EXPECTED}개여야 합니다 "
            f"(전체 {len(questions)}개 중). 한 문항의 무게(1/{ACTIVE_EXPECTED})가 달라지면 "
            "과거 표와 축이 어긋납니다 - 2026-09-18-eval-set-difficulty-design.md."
```

- [ ] **Step 7: 파일 점검을 돌린다**

```bash
cd /Users/cheonjamin/projects/AllDap/ai-service && .venv/bin/python -m app.eval_set_check; echo "종료코드=$?"
```

Expected: `전부 통과.` · 종료코드 0. 특히 두 줄이 보여야 한다:
- `활성 문항 26개 · 전체 30개 · id 중복 없음`
- `난이도 규칙이 적힌 문항 10개가 규칙을 지킵니다`

실패하면 **문항을 고친다. 검사를 고치지 않는다.**

- [ ] **Step 8: 파일을 DB 로 되돌린다**

```bash
cd ai-service && .venv/bin/python -m app.eval_set load --bot-id 1 --replace
```

Expected: `봇 1 에 30문항을 넣었습니다 (활성 26문항).` 앞서 지우는 건수 경고가 함께 찍힌다. 청크를 못 찾는 문항이 하나라도 있으면 **하나도 안 들어간다** - 그때는 Step 5 에서 `source_text` 를 건드린 것이다.

- [ ] **Step 9: 커밋**

```bash
cd /Users/cheonjamin/projects/AllDap
git add ai-service/testdata/eval_questions.json ai-service/app/eval_set_check.py
git commit -m "feat: 난이도 변형을 입힌 평가 문항 10개를 더한다 (활성 26)

생성기로 후보 20개를 뽑아 결함을 걸러낸 뒤 10개에 변형 규칙(lexical/target/clause)을 입혔다.
기존 16문항은 한 글자도 안 건드린다 - 회귀 감지기(대조군)로 남긴다.
한 문항의 무게가 0.0625 에서 0.038 로 줄어 측정 편차(0.032)와 개선을 가를 여지가 생긴다.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: 측정점 ① - 질문만 어렵게 한 상태로 3회 잰다

**Files:** 코드 변경 없음. 산출물은 수치와 `rank_trace` 판정 분포다.

**전제:** Task 3 의 load 가 끝나 DB 에 활성 26문항이 있다. 리랭커·하이브리드는 **기본값 그대로**(`reranker_provider=cloudflare`) 둔다 - 이 슬라이스가 바꾸는 변수는 평가셋 하나뿐이다.

- [ ] **Step 1: 돌리기 전에 상한부터 본다 (`rank_trace`)**

평가를 돌리기 전에 판정 분포를 먼저 본다. 2026-08-11 에 리랭커를 처음 잴 때 "돌리기 전에 상한부터 쟀다" 던 것과 같은 일이고, 임베딩 26회뿐이라 비용이 사실상 0 이다.

```bash
cd ai-service && RERANKER_PROVIDER=local .venv/bin/python -m app.rank_trace --bot-id 1 | tee $SCRATCH/rank_trace_step1.txt
```

Expected: 활성 26문항의 표와 요약(판정 ①②③④ 개수 · `경계` 표시). **이 숫자를 그대로 받아적는다.** ① 이 0 이어도 그것이 결론이다(§알려진 한계).

⚠️ `RERANKER_PROVIDER=local` 은 모델이 있어야 한다(`.venv/bin/python -m app.export_reranker`). 없으면 그 변수 없이 돌린다 - Cloudflare 리랭커를 쓰므로 뉴런을 조금 더 쓴다.

- [ ] **Step 2: 평가를 3회 돌린다**

```bash
cd /Users/cheonjamin/projects/AllDap
for i in 1 2 3; do
  echo "=== run $i ==="
  curl -s -X POST localhost:8001/internal/bots/1/eval/runs | python -m json.tool
  # 끝날 때까지 기다린다. 26문항이면 2~4분이다.
  until [ "$(curl -s localhost:8001/internal/bots/1/eval/runs | python -c 'import json,sys; print(json.load(sys.stdin)[0]["status"])')" != "running" ]; do
    sleep 15
  done
done
```

Expected: 세 번 모두 `status` 가 `completed` 로 끝난다. 🔴 `failed` 면 전 문항이 실패한 것이고(한도 소진이 흔한 원인), `partial` 이면 분모가 달라 **비교에 쓸 수 없다.**

- [ ] **Step 3: 수치를 읽는다**

```bash
psql "$DATABASE_URL" -c "
SELECT id, status, question_count AS 분모, scored_count AS 채점,
       round(avg_faithfulness, 3) AS 충실성,
       round(avg_faithfulness * scored_count / question_count, 4) AS 전체충실성,
       round(avg_relevancy, 3) AS 관련성,
       round(answered_rate, 3) AS 응답률
  FROM eval_runs WHERE bot_id = 1 ORDER BY id DESC LIMIT 3;"
```

그리고 평균만 보지 않는다 - 기본값을 정할 때 결정적이었던 것은 평균이 아니라 **회당 오답 0건**이었다. 위에서 나온 run id 셋을 넣는다:

```bash
psql "$DATABASE_URL" -c "
SELECT run_id,
       count(*) FILTER (WHERE generated_answer IS NOT NULL AND faithfulness IS NULL) AS fallback,
       count(*) FILTER (WHERE faithfulness IS NOT NULL AND faithfulness < 1.0) AS 오답,
       count(*) FILTER (WHERE faithfulness = 0.0) AS 완전오답,
       count(*) FILTER (WHERE generated_answer IS NULL) AS 처리실패
  FROM eval_results WHERE run_id IN (<run1>, <run2>, <run3>) GROUP BY run_id ORDER BY run_id;"
```

🔴 **`처리실패` 가 0 이 아니면 그 실행은 오염된 것이다.** `scored_count` 가 작은 것과는 다른 사실이다(fallback 이 많으면 `scored_count` 는 자연히 작아진다. 2026-08-13 에 이걸로 틀린 결론을 한 번 냈다).

- [ ] **Step 4: 중단 조건에 대입한다**

| 관측 | 다음 |
|---|---|
| 전체충실성 0.75~0.88 · 3회 편차 ≤ 0.04 | ✅ **목표 달성. Task 5·6(코퍼스)을 건너뛰고 Task 7 로 간다.** 질문만으로 됐다는 것이 결론이다 |
| 0.88 초과 | Task 5 로 간다. **"질문만으로는 안 내려간다" 를 결론으로 기록**한다 |
| 0.75 미만 | `rank_trace --qid <번호>` 로 원인 문항을 본다. 결함이면 `active: false` + 사유, 정당한 난이도면 그대로 둔다 |
| 편차 > 0.04 | 경계 문항 수(`rank_trace` 의 `경계`)를 세어 기록한다. **문항을 빼서 편차를 맞추지 않는다** |

- [ ] **Step 5: 결과를 파일에 적고 커밋한다**

수치를 `$SCRATCH` 에만 두면 다음 세션에 사라진다. 측정점 ① 의 표를 `docs/superpowers/plans/2026-09-18-eval-set-difficulty-results.md` 에 적는다(측정점 ② 를 같은 파일에 덧붙인다).

```bash
cd /Users/cheonjamin/projects/AllDap
git add docs/superpowers/plans/2026-09-18-eval-set-difficulty-results.md
git commit -m "docs: 측정점 1(질문만 어렵게) 3회 실측 결과

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: 코퍼스에 같은 주제·다른 대상 문서를 더한다

**언제 하는가:** Task 4 Step 4 에서 0.88 을 넘었을 때만. 목표 구간에 들었으면 **이 Task 와 Task 6 을 건너뛴다.**

**Files:**
- Create: `ai-service/testdata/corpus/56_*.md` ~ `60_*.md` (5~7개)

- [ ] **Step 1: 새 대상 5~7개를 고른다**

기존 50문서에 없는 신분이어야 한다. 이미 있는 것: 정규직 · 계약직 · 인턴 · 파견인력 · 부설연구소 · 생산공장 · 해외지사 · 자회사 · 협력사 상주인력 · 임원.

후보(§2단계): **시간제 근로자 · 재택근무 전담자 · 수습사원 별도 규정 · 촉탁직(정년 후 재고용) · 프로젝트 계약직 · 현장실습생**.

```bash
cd ai-service && grep -rl "시간제" testdata/corpus/ | head
```

Expected: 비어 있거나 스쳐 지나가는 언급뿐. 이미 규정이 있는 대상을 또 만들면 대상이 둘이 되어 평가셋 자체가 모호해진다.

- [ ] **Step 2: 문서를 쓴다**

기존 문서와 **같은 항목을 다른 숫자로** 규정한다(연차 · 장비 교체 주기 · 건강검진 · 경조사 · 식대 · 재택 횟수). 기존 문서 하나를 열어 형식을 그대로 따른다:

```bash
cd ai-service && cat testdata/corpus/51_생산공장_근무규정.md
```

각 문서에 **"정규직에게는 적용하지 않는다"** 를 명시한다. 그 문장이 그 문서에 "정규직" 토큰을 주고, 벡터 검색은 부정문을 구분하지 못하므로 정확히 그 성질을 찌른다. 리랭커가 고칠 수 있는 부류(판정 ①)가 나올 자리이기도 하다.

🔴 **청크 수를 늘리는 것이 목적이 아니다.** 2026-08-11 에 주제가 겹치지 않는 문서 30개로 청크를 80 → 250 으로 키웠는데 지표가 하나도 안 움직였다. 난이도를 만드는 것은 **의미적 근접성**이다.

- [ ] **Step 3: 꼬리표가 안 깨졌는지 확인한다**

새 문서는 기존 청크를 안 건드리므로 통과가 예상되지만, **예상은 근거가 아니라 확인 대상이다**(§코퍼스를 바꾸면 딸려오는 일 2).

```bash
cd ai-service && .venv/bin/python -m app.eval_set_check; echo "종료코드=$?"
```

Expected: `전부 통과.` 종료코드 0.

🔴 `lexical` 낱말이 새 문서에 들어갔으면 여기서 **실패로 잡힌다.** 그때는 새 문서의 표현을 바꾸거나 그 문항의 낱말을 바꾼다 - 결함인 채로 두지 않는다.

- [ ] **Step 4: 새 문서를 봇 1에 올린다**

```bash
cd ai-service
for f in testdata/corpus/5[6-9]_*.md testdata/corpus/60_*.md; do
  [ -e "$f" ] || continue
  curl -s -X POST localhost:8001/internal/bots/1/documents -F "file=@$f" | python -m json.tool
done
# 전부 ready 가 될 때까지 기다린다
curl -s localhost:8001/internal/bots/1/documents | python -c '
import json,sys
docs = json.load(sys.stdin)
from collections import Counter
print(Counter(d["status"] for d in docs))'
```

Expected: 전 문서가 `ready`. 청크 수도 적어둔다:

```bash
psql "$DATABASE_URL" -c "SELECT count(*) FROM chunks WHERE bot_id = 1;"
```

- [ ] **Step 5: `answerable_max_distance` 가 여전히 유효한지 다시 잰다**

`0.44` 는 **코퍼스와 임베딩 모델에 딸려 있다**고 AGENTS.md 가 명시해뒀다. 코퍼스가 바뀌었으므로 무효일 수 있다.

```bash
cd ai-service && .venv/bin/python -m app.answerable_check | tee $SCRATCH/answerable_after_corpus.txt
```

Expected: 근거있음 유지 / 근거없음 차단 표. `0.44` 가 여전히 좋은 자리면 그대로 둔다.

🔴 **바꿔야 하면 홀드아웃을 <보기 전에> 고른다.** 보고 나서 고르면 홀드아웃이 아니게 된다. 표가 "결과가 바뀌는 지점" 만 보여준다는 것에도 주의한다(2026-09-06 에 같은 구간의 더 여유 있는 값을 놓칠 뻔했다).

- [ ] **Step 6: 커밋**

```bash
cd /Users/cheonjamin/projects/AllDap
git add ai-service/testdata/corpus/
git commit -m "feat: 같은 주제·다른 대상 문서 N개를 코퍼스에 더한다

기존 항목(연차·장비·건강검진·경조사)을 다른 숫자로 규정하고 '정규직에게는 적용하지
않는다' 를 명시해 그 문서가 '정규직' 토큰을 갖게 한다. 벡터 검색이 부정문을 구분하지
못하는 성질을 찌르는 것이고, 2026-08-11 에 1.000 을 0.781 로 내린 검증된 레버다.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: 측정점 ② - 코퍼스까지 바꾼 상태로 3회 잰다

**언제 하는가:** Task 5 를 했을 때만. **측정점 ① 과 다른 날에 돌린다**(하루 한도 10,000 뉴런, 측정점당 약 3,900 + 실패 여유).

- [ ] **Step 1: 판정 분포를 먼저 본다**

```bash
cd ai-service && RERANKER_PROVIDER=local .venv/bin/python -m app.rank_trace --bot-id 1 | tee $SCRATCH/rank_trace_step2.txt
diff $SCRATCH/rank_trace_step1.txt $SCRATCH/rank_trace_step2.txt | head -40
```

Expected: 판정 ② 나 ① 이 늘었을 것이다(distractor 가 정답을 밀어내면 ①). **늘지 않았으면 그것도 결론**이다 - 코퍼스로도 난이도가 안 생긴다는 뜻이다.

- [ ] **Step 2: 평가를 3회 돌린다**

Task 4 Step 2 의 명령을 그대로 쓴다.

- [ ] **Step 3: 수치를 읽는다**

Task 4 Step 3 의 SQL 두 개를 그대로 쓴다(run id 만 새것으로).

- [ ] **Step 4: 중단 조건에 대입한다**

| 관측 | 다음 |
|---|---|
| 0.75~0.88 · 편차 ≤ 0.04 | ✅ 목표 달성. Task 7 |
| 0.88 초과 | 🔴 **3단계로 밀지 않고 멈춘다.** 가설 반증이고 **그것이 성과다.** Task 7 에 그렇게 적는다 |
| 0.75 미만 | `rank_trace` 로 원인 문항을 본다. 결함이면 `active: false`(그러면 `ACTIVE_EXPECTED` 도 함께 내린다), 정당한 난이도면 그대로 |
| 편차 > 0.04 | 경계 문항 수를 세어 기록한다. 문항을 빼지 않는다 |

- [ ] **Step 5: 결과 파일에 ② 를 덧붙이고 커밋**

```bash
cd /Users/cheonjamin/projects/AllDap
git add docs/superpowers/plans/2026-09-18-eval-set-difficulty-results.md
git commit -m "docs: 측정점 2(코퍼스까지) 3회 실측 결과

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: 기록하고 PR 을 연다

**Files:**
- Modify: `AGENTS.md` (평가셋 정비 절 뒤에 새 절)
- Modify: `docs/decisions.md`
- Modify: `docs/BACKLOG.md` §5

- [ ] **Step 1: `AGENTS.md` 에 결과 절을 추가한다**

"✅ 평가셋 정비 (2026-09-18)" 절 **바로 뒤**에 새 절을 넣는다. 이 저장소의 기록 관례를 따른다 - 표 · 🔴 로 짚는 함정 · 재현 명령 · **닫지 못한 것**.

반드시 담을 것:
- ⓪ · ① · ② 표(전체충실성 3회 · 편차 · 관련성 · 응답률 · 회당 오답/완전오답/fallback)
- 🔴 **⓪ 와 ① 을 이어 붙이지 말라는 경고** - 16문항은 26문항의 부분집합이라 같은 16문항의 점수는 따로 볼 수 있지만 **전체충실성은 분모가 다르다.** ⓪ 는 1회뿐이기도 하다
- `rank_trace` 판정 분포 ①②③④ 를 측정점마다
- 🔴 **판정 ① 개수를 완료 조건으로 삼지 않았다는 것과 그 이유**
- **어떤 변형 규칙이 실제로 난이도를 만들었는가** - `difficulty.rule` 별로 fallback/오답이 난 문항 수를 센다. 규칙 하나만 듣고 나머지가 무효라면 그것도 결론이다
- 한 문항의 무게가 0.0625 → 0.038 로 바뀐 것
- 알려진 한계: **우리가 만든 난이도**라 실제 고객 질문의 분포와 같다는 근거가 없다
- 재현 명령:

```
cd ai-service
.venv/bin/python -m app.eval_set load --bot-id 1        # 파일 -> DB
.venv/bin/python -m app.eval_set_check                  # 파일이 거짓말하지 않는지
RERANKER_PROVIDER=local .venv/bin/python -m app.rank_trace --bot-id 1
curl -X POST localhost:8001/internal/bots/1/eval/runs
```

그리고 "▶ 다음 세션은 여기서 시작한다" 절의 **평가셋 문항 수(16)** 를 언급한 자리를 찾아 고친다:

```bash
cd /Users/cheonjamin/projects/AllDap && grep -n "16문항" AGENTS.md | head -20
```

⚠️ 과거 측정표의 "16문항" 은 **그때의 사실이므로 고치지 않는다.** 고칠 것은 "지금 평가셋이 몇 문항인가" 를 말하는 문장뿐이다.

- [ ] **Step 2: `docs/decisions.md` 에 한 줄 남긴다**

형식: `날짜 | 무엇을 | 왜 그렇게 | 검토한 대안`. 최소 두 항목:

1. **난이도를 질문과 코퍼스 <두 측정점으로 나눠> 넣은 것** - 한꺼번에 바꾸면 낮아진 점수의 원인을 분리해 말할 수 없다. 대안: 한 번에 바꾸고 3단계로 되돌려 원인을 찾는 것(측정 횟수가 두 배로 든다)
2. **판정 ① 개수를 완료 조건에서 뺀 것** - ① 을 강제하면 평가셋이 리랭커 전용으로 기울어 그 위에서 잰 파인튜닝 효과가 과대평가된다. 대안: ① 을 3개 이상 만들 때까지 질문을 깎는 것

0.88 을 넘어 멈췄다면 **그 반증도 한 줄로 남긴다.**

- [ ] **Step 3: `docs/BACKLOG.md` §5 를 갱신한다**

"① 평가 질문 세트를 저장소에 남긴다" 항목 아래의 🔴 문단("이 슬라이스는 ②를 가능하게 만들지 못했다. 난이도 확보는 별도 슬라이스다")이 **이 슬라이스가 한 일**이다. 새 항목으로 결과를 적고, ②(리랭커 파인튜닝)의 전제가 **섰는지 안 섰는지**를 판정 ① 개수로 명시한다.

🔴 ① 이 0 이면 "파인튜닝을 기각한다" 가 아니라 **"이 방법으로는 측정 가능한 난이도를 못 만들었다"** 로 적는다. 둘은 다른 사실이다.

- [ ] **Step 4: 검사를 전부 돌린다**

```bash
cd /Users/cheonjamin/projects/AllDap/ai-service
for m in parsers_check chunker_check eval_set_check retriever_check evalrun_check \
         evaluator_check generator_check conflicts_check metrics_check openapi_check \
         local_reranker_check export_reranker_check; do
  echo "=== $m ==="
  .venv/bin/python -m app.$m > /dev/null || echo "❌ $m 실패"
done
```

Expected: `❌` 가 한 줄도 없다. (CI 가 이 목록을 돌린다)

- [ ] **Step 5: 커밋하고 PR 을 연다**

```bash
cd /Users/cheonjamin/projects/AllDap
git add AGENTS.md docs/decisions.md docs/BACKLOG.md
git commit -m "docs: 평가셋 난이도 확보 결과를 기록한다

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
git push -u origin feat/eval-set-difficulty
```

PR 본문은 `.github/PULL_REQUEST_TEMPLATE.md` 를 채운다. 두 칸이 핵심이다:

- **한계 & 트레이드오프**: 우리가 만든 난이도라 실제 고객 질문 분포와 같다는 근거가 없다 · ⓪ 와 ① 은 분모가 달라 엄밀히 비교되지 않는다 · 판정 ① 이 0 이면 파인튜닝 전제가 여전히 안 선 것이다 · 문항이 늘어 하루 실행 횟수가 12회에서 7회로 줄었다
- **검토한 대안과 선택 이유**: 생성기를 다시 돌리기만 하는 것(난이도가 오르면 우연이고 결함이 다시 섞인다는 것이 2026-09-18 에 실측됐다) · 질문과 코퍼스를 한 번에 바꾸는 것(원인을 분리해 말할 수 없다) · 판정 ① 을 완료 조건으로 삼는 것(평가셋이 리랭커 전용으로 기운다)

**어떻게 해결했나요** 칸에는 "돌려봤다" 가 아니라 **실제 실행 결과**(3회 수치 표와 판정 분포)를 붙인다.

```bash
gh pr create --title "feat: 평가셋 난이도 확보" --body-file <(cat <<'BODY'
...위 내용을 템플릿에 맞춰 채운 본문...

🤖 Generated with [Claude Code](https://claude.com/claude-code)
BODY
)
```

🔴 **PR 을 올린 뒤 CI 를 폴링하지 않는다.** `gh pr create` 까지가 이 작업의 끝이다.
