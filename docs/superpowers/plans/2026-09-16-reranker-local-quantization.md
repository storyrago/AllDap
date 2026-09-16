# 리랭커 로컬 실행 + 양자화 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (권장) 또는 superpowers:executing-plans 로 이 계획을 한 태스크씩 실행할 것. 각 단계는 체크박스(`- [ ]`) 로 추적한다.

**설계문서:** [`docs/superpowers/specs/2026-09-16-reranker-local-quantization-design.md`](../specs/2026-09-16-reranker-local-quantization-design.md)

**목표:** 지금 Cloudflare API 로 부르는 리랭커(`bge-reranker-base`)를 이 컴퓨터에서 ONNX Runtime 으로 직접 돌리고, 동적 INT8 로 양자화한 뒤, 기존 평가 16문항으로 A(Cloudflare) · B(로컬 fp32) · C(로컬 INT8) 을 설정당 3회 이상 재서 표로 남긴다.

**아키텍처:** 제공자마다 파일 하나(`friendli.py` 가 세운 규칙). 새 파일 `app/local_reranker.py` 가 Cloudflare 와 **똑같은 출력 계약**(`{"response": [{"id": 입력인덱스, "score": float}], 점수 내림차순}`)을 돌려주므로, `retriever._rerank` 의 나머지 로직(실패 시 원래 순서 유지 · 빠진 인덱스 보전 · `rerank_fusion`)은 한 줄도 안 고친다. 제공자 선택은 설정값 `reranker_provider` 하나다. 실험용 의존성(torch · optimum · transformers · onnxruntime)은 `requirements-lab.txt` 로 갈라 운영 이미지에 싣지 않는다.

**기술 스택:** Python 3.13 / ONNX Runtime(동적 INT8 내장) / optimum[exporters] + transformers + torch(내보낼 때만) / 기존 평가 파이프라인(`app/evalrun.py`) / PostgreSQL + pgvector

**브랜치:** `feat/reranker-local-quantization` (마이그레이션은 없지만 "왜 그렇게 했는지를 설명해야 하는 변경" 이므로 PR 로 간다)

---

## Global Constraints

이 절의 값은 **모든 태스크의 요구사항에 암묵적으로 포함된다.**

- **범위는 `ai-service/` 안이다.** `api/`(Spring) · `web/` · `widget/` 은 한 글자도 고치지 않는다.
- **기본값은 실험 내내 `reranker_provider = "cloudflare"` 다.** 로컬 제공자는 측정할 때만 환경변수로 켠다. 지금 지키고 있는 **회당 오답 0건**을 실험이 깨뜨리면 안 된다.
- **`requirements.txt` 는 건드리지 않는다.** 실험 의존성은 전부 `requirements-lab.txt` 로 간다. 운영 이미지(`ai-service/Dockerfile`)가 `requirements.txt` 를 읽고 그 이미지를 1GB 짜리 t3.micro 가 받는다.
- **모델 가중치는 커밋하지 않는다.** `ai-service/models/` 는 `.gitignore` 로 막고, 재현은 리비전을 못박은 스크립트가 책임진다.
- **CI 에서 도는 점검은 `requirements.txt` 만으로 import 가능해야 한다.** `onnxruntime` · `transformers` 는 반드시 **함수 안에서 늦게 import** 한다. 모듈 최상단에서 import 하면 CI 가 그 자리에서 죽는다.
- **조용히 다른 제공자로 떨어지지 않는다.** 로컬을 골랐는데 모델이 없으면 명확한 한국어 오류를 낸다. 조용히 Cloudflare 로 떨어지면 "무엇을 쟀는지" 를 잃는다.
- **동시에 리랭커 실패가 채팅을 죽이면 안 된다.** `_rerank` 의 기존 성질(실패하면 원래 순서 유지)을 보존한다. 위 두 줄은 모순이 아니다. 평가·점검은 **시작 전에 preflight 로 거절**하고, 운영 경로(채팅)는 **실패해도 벡터 순서로 살아남는다.**
- **측정 반복은 설정당 3회 이상.** `temperature=0` 에서도 편차 폭이 **0.032** 다. 그보다 작은 차이는 "나빠졌다" 가 아니라 **"구별되지 않는다"** 로 적는다.
- **em dash 를 쓰지 않는다.** 코드 주석 · 문서 · 커밋 메시지 전부. 쉼표 · 콜론 · 괄호로 대체한다.
- **주석과 에러 메시지는 한국어.** 사용자에게 보이는 오류는 "무엇을 어떻게 하면 되는지" 까지 적는다.
- 커밋 메시지는 `<타입>: <한국어 요약>` (feat / fix / refactor / test / docs / chore).

**미리 정해둔 이름** (태스크끼리 어긋나지 않게 여기서 못박는다)

| 이름 | 무엇 |
|---|---|
| `app/local_reranker.py` | 로컬 추론 제공자 파일 |
| `local_reranker.rerank(query, texts, *, variant) -> dict` | Cloudflare 와 같은 계약 |
| `local_reranker.preflight(variant, models_dir=None) -> Path` | 모델 파일 확인. 없으면 `ModelUnavailable` |
| `local_reranker.ModelUnavailable` | `RuntimeError` 하위 |
| `local_reranker.latency_percentiles() -> dict` | `cf.latency_percentiles()` 와 같은 모양 |
| `local_reranker.max_rss_mb() -> float` | 프로세스 최대 상주 메모리 |
| `retriever._rerank_order(query, texts) -> list[int]` | 제공자를 고르는 이음매 |
| `retriever._apply_order(sources, order) -> list[Source]` | 재정렬 + 빠진 인덱스 보전 |
| `evalrun._run_config(s) -> dict` | 실행 설정 박제(순수 함수로 분리) |
| `config.Settings.reranker_provider` | `"cloudflare"` \| `"local"` \| `"local_int8"` |
| `app/export_reranker.py` | 내려받기 → ONNX 변환 → INT8 양자화 |
| `app/rerank_compare.py` | A/B/C 결과 집계 리포트(읽기 전용) |

---

## File Structure

| 파일 | 책임 | 태스크 |
|---|---|---|
| `AGENTS.md` · `docs/BACKLOG.md` · `docs/decisions.md` | 규칙을 **리랭커 추론에 한해** 연다 | 1 |
| `ai-service/requirements-lab.txt` (신규) | 실험 전용 의존성 | 2 |
| `.gitignore` | `ai-service/models/` 차단 | 2 |
| `ai-service/app/export_reranker.py` (신규) | 리비전 고정 · ONNX 변환 · INT8 양자화 · 산출물 검증 | 2 |
| `ai-service/app/export_reranker_check.py` (신규, CI) | 경로 · 리비전 · 산출물 검증 함수의 순수 로직 | 2 |
| `ai-service/app/local_reranker.py` (신규) | 로컬 추론. Cloudflare 와 같은 출력 계약 + 지연 · RSS 계측 | 3 |
| `ai-service/app/local_reranker_check.py` (신규, CI) | 출력 계약 · 오류 문구 · 늦은 import 보장 | 3 |
| `ai-service/app/config.py` | `reranker_provider` 추가 | 4 |
| `ai-service/app/retriever.py` | `_rerank` 를 `_rerank_order` · `_apply_order` 로 가르고 제공자 분기 | 4 |
| `ai-service/app/retriever_check.py` | 실패 시 원래 순서 유지 회귀 검사 | 4 |
| `ai-service/app/evalrun.py` | `_run_config` 분리 + `reranker_provider` 박제 + preflight 거절 | 5 |
| `ai-service/app/evalrun_check.py` | 박제 누락 회귀 검사 | 5 |
| `ai-service/app/local_reranker_e2e_check.py` (신규, 손으로) | 진짜 모델로 계약 · 크기 · 지연 · RSS | 6 |
| `ai-service/app/rerank_compare.py` (신규) | eval_runs 3설정 × 3회 집계표 | 7 |
| `.github/workflows/ci.yml` | 새 점검 2개 등록 | 3 |

---

## Task 1: 규칙을 먼저 고친다

설계문서 §7 이 못박은 것이다. 규칙을 안 고치고 코드를 쓰면 저장소가 자기 규칙을 어기는 상태가 되고, 이 저장소가 반복해 당한 실패가 정확히 **"고쳤는데 그것을 설명하는 자리를 안 고친 것"** 이다.

**Files:**
- Modify: `AGENTS.md` (작업 규칙 7번)
- Modify: `docs/BACKLOG.md` (§7)
- Modify: `docs/decisions.md` (맨 위 최신 항목 자리)

**Interfaces:**
- Consumes: 없음 (첫 태스크)
- Produces: 이후 태스크가 "규칙이 열렸다" 를 전제한다

- [ ] **Step 1: 브랜치를 판다**

```bash
cd /Users/cheonjamin/projects/AllDap
git checkout main && git pull
git checkout -b feat/reranker-local-quantization
```

- [ ] **Step 2: `AGENTS.md` 7번을 좁힌다**

`AGENTS.md` 의 "작업 규칙" 7번 전체를 아래로 교체한다.

```markdown
7. **범위를 넓히지 말 것 (2026-09-16 에 <리랭커 추론에 한해> 열었다).**
   ⬜ **여전히 범위 밖:** 생성 모델(llama-3.3-70b) 셀프호스팅 · 경량화, 임베딩 모델 셀프호스팅,
   온디바이스 추론 일반. 원래 기각 사유가 그대로 유효하다(t3.micro 1GB 로 불가능하다).
   ✅ **연 것은 하나뿐이다: 리랭커(`bge-reranker-base`, 2억 7천만 파라미터) 추론을
   로컬에서 돌리고 양자화하는 것.** 근거는
   `docs/superpowers/specs/2026-09-16-reranker-local-quantization-design.md` 와
   `docs/decisions.md` 2026-09-16 항목.
   🔴 **기각 사유의 <전제>가 바뀌어서 연 것이지, 사유가 틀렸던 것이 아니다.**
   원래 사유는 "지금 끌어들이면 Python 학습 · Spring 구현 · 경량화가 전부 어중간해진다" 였고,
   그것은 프로젝트가 미완일 때 쓴 문장이다. W1~W4 · 배포 · 결제 · 부하테스트가 끝나
   **어중간해질 대상이 남아 있지 않다.**
   겨냥하는 실제 문제도 있다: `docs/BACKLOG.md` §5 의 "리랭커가 정답을 밀어내는 실패 2건"
   (재택 · 기간제). 순위 융합(`rerank_fusion`)으로 풀려다 제로섬인 것이 반증됐고,
   남은 길이 **리랭커 파인튜닝**이다. 로컬 추론은 그 선행 배관이다.
```

- [ ] **Step 3: `docs/BACKLOG.md` §7 에서 해당 행을 뺀다**

§7("되살리지 말 것") 에서 모델 경량화 · 양자화 · 온디바이스 추론 행을 지우고, 그 자리에 아래를 넣는다.

```markdown
- ~~모델 경량화 · 양자화 · 온디바이스 추론~~ → 🔴 **2026-09-16 에 <리랭커 추론에 한해> 열었다.**
  기각 사유("전부 어중간해진다")의 전제가 바뀌었다. W1~W4 · 배포 · 결제 · 부하테스트가 끝나
  어중간해질 대상이 남아 있지 않다. 설계는
  `docs/superpowers/specs/2026-09-16-reranker-local-quantization-design.md`.
  ⚠️ **생성 모델 · 임베딩 모델의 셀프호스팅 · 경량화는 여전히 되살리지 말 것.**
  t3.micro 1GB 로 불가능하다는 원래 사유가 그대로 유효하다.
```

- [ ] **Step 4: `docs/decisions.md` 에 한 줄 남긴다**

파일의 최신 항목 자리에 추가한다(형식: `날짜 | 무엇을 | 왜 그렇게 | 검토한 대안`).

```markdown
## 2026-09-16 | 모델 경량화 금지 규칙을 <리랭커 추론에 한해> 연다

**무엇을**: `AGENTS.md` 7번과 `BACKLOG.md` §7 이 "하지 않기로 한 것" 으로 못박아둔
모델 경량화 · 양자화를, 리랭커(`bge-reranker-base`) 추론에 한정해 연다.
로컬 ONNX Runtime 실행 + 동적 INT8 양자화까지.

**왜 그렇게**: 기각 사유가 틀렸던 것이 아니라 **그 사유의 전제가 바뀌었다.**
사유는 "지금 끌어들이면 Python 학습 · Spring 구현 · 경량화가 전부 어중간해진다" 였고
프로젝트가 미완일 때 쓴 문장이다. 지금은 W1~W4 · 배포 · 결제 · 부하테스트가 끝났고
`BACKLOG.md` 에 남은 항목은 대부분 트리거가 "실사용자가 생기면" 이다.
겨냥하는 실제 문제도 있다: BACKLOG §5 의 "리랭커가 정답을 밀어내는 실패 2건"(재택 · 기간제).
`rerank_fusion` 으로 풀려다 제로섬인 것이 반증됐고, 남은 길이 파인튜닝이며
로컬 추론은 그 선행 배관이다. 지금 리랭커는 이 저장소의 문서를 한 번도 본 적이 없다.

**검토한 대안**:
① 규칙을 그대로 두고 조용히 코드만 추가 → 문서끼리 어긋난다. 이 저장소가 반복해 당한 실패다.
② 범위를 통째로 열기 → 생성 모델(llama-70b) 셀프호스팅은 t3.micro 로 불가능하고
   원래 기각 사유가 그대로 유효하다. 그래서 리랭커 추론 하나만 연다.
③ 임베딩부터 바꾸기 → `answerable_max_distance` 가 임베딩 모델에 딸려 있어
   306청크 재임베딩 + 임계값 재측정이 따라온다. 리랭커에는 그것이 없다. 작은 쪽부터 한다.

**배포 명분은 쓰지 않는다**: t3.micro 1GB 에 INT8(약 280MB)이 "들어갈 수도 있다" 이상을
주장하지 않는다. 배포 축은 이미 증명됐고, 재는 것(크기 · 속도 · 품질)은 맥북에서 재도 유효하다.
```

- [ ] **Step 5: 어긋난 자리가 더 없는지 확인한다**

```bash
grep -rn "경량화\|양자화\|온디바이스" AGENTS.md docs/BACKLOG.md | grep -v "2026-09-16"
```
Expected: 남는 줄이 있으면 전부 읽고 "여전히 범위 밖" 과 모순되지 않는지 확인한다. 모순되면 그 자리도 이 태스크에서 함께 고친다. (기능을 고치고 그것을 설명하는 자리를 안 고치는 것이 이 저장소의 상습 실패다.)

- [ ] **Step 6: 커밋**

```bash
git add AGENTS.md docs/BACKLOG.md docs/decisions.md
git commit -m "docs: 모델 경량화 금지 규칙을 리랭커 추론에 한해 연다"
```

---

## Task 2: 실험 의존성과 내보내기 스크립트

**Files:**
- Create: `ai-service/requirements-lab.txt`
- Create: `ai-service/app/export_reranker.py`
- Create: `ai-service/app/export_reranker_check.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `export_reranker.REPO_ID: str`, `export_reranker.REVISION: str`
  - `export_reranker.VARIANT_DIRS: dict[str, str]`, `export_reranker.ONNX_FILENAME: dict[str, str]`
  - `export_reranker.variant_dir(variant, models_dir=None) -> Path`
  - `export_reranker.artifact_status(models_dir=None) -> dict[str, bool]`
  - `export_reranker.missing_message(variant) -> str` (Task 3 이 그대로 쓴다)

- [ ] **Step 1: 실패하는 점검을 먼저 쓴다**

Create `ai-service/app/export_reranker_check.py`:

```python
"""내보내기 스크립트의 <순수 로직> 점검. 모델도 네트워크도 건드리지 않는다.

여기서 보는 것은 셋이다.
  ① 리비전이 못박혀 있는가 (안 박으면 나중에 다른 가중치가 와서
     "양자화 때문인가 모델이 바뀐 것인가" 를 구분할 수 없다)
  ② 산출물이 <부분적으로> 있을 때 "있다" 고 말하지 않는가
  ③ 없을 때 나가는 안내가 무엇을 어떻게 하면 되는지 말하는가
"""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from .export_reranker import (
    ONNX_FILENAME,
    REPO_ID,
    REVISION,
    VARIANT_DIRS,
    artifact_status,
    missing_message,
)


def check_revision_is_pinned() -> None:
    """🔴 리비전이 커밋 해시로 못박혀 있어야 한다.

    `main` 같은 움직이는 이름이면 나중에 다른 가중치가 온다. 그러면
    B(로컬 원본)와 C(로컬 INT8)의 차이를 양자화 탓으로 읽을 수 없게 된다.
    """
    assert REPO_ID == "BAAI/bge-reranker-base", REPO_ID
    assert len(REVISION) == 40, f"리비전이 40자 커밋 해시가 아니다: {REVISION}"
    assert all(c in "0123456789abcdef" for c in REVISION), REVISION
    assert REVISION.strip("0") != "", "REVISION 이 아직 자리표시자다"


def check_missing_artifacts_are_not_reported_as_present() -> None:
    """산출물이 하나라도 빠지면 False 여야 한다.

    ⚠️ 디렉터리 존재만 보면 안 된다. 변환이 중간에 죽어 디렉터리만 남은 상태와
       정상 산출물을 <같은 값으로 뭉갠다.> 이 저장소가 여덟 번 낸 버그의 부류다.
    """
    with TemporaryDirectory() as tmp:
        models = Path(tmp)
        assert artifact_status(models) == {"local": False, "local_int8": False}

        # 디렉터리만 만든다 (변환이 죽은 상태)
        (models / VARIANT_DIRS["local"]).mkdir(parents=True)
        assert artifact_status(models)["local"] is False, "빈 디렉터리를 산출물로 셌다"

        # onnx 파일만 있고 토크나이저가 없는 상태도 False 다
        (models / VARIANT_DIRS["local"] / ONNX_FILENAME["local"]).write_bytes(b"x")
        assert artifact_status(models)["local"] is False, "토크나이저 없이 완성으로 셌다"

        (models / VARIANT_DIRS["local"] / "tokenizer.json").write_text("{}")
        (models / VARIANT_DIRS["local"] / "tokenizer_config.json").write_text("{}")
        assert artifact_status(models)["local"] is True


def check_missing_message_tells_what_to_do() -> None:
    """안내는 <무엇을 어떻게 하면 되는지> 까지 말해야 한다(저장소 규칙)."""
    msg = missing_message("local_int8")
    assert "app.export_reranker" in msg, msg
    assert "requirements-lab.txt" in msg, msg
    assert "local_int8" in msg, msg


def main() -> None:
    checks = [
        check_revision_is_pinned,
        check_missing_artifacts_are_not_reported_as_present,
        check_missing_message_tells_what_to_do,
    ]
    for fn in checks:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(checks)}가지 전부 통과.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 점검을 돌려 실패를 확인한다**

```bash
cd ai-service && .venv/bin/python -m app.export_reranker_check
```
Expected: FAIL. `ModuleNotFoundError: No module named 'app.export_reranker'`

- [ ] **Step 3: 실험 의존성 파일을 만든다**

Create `ai-service/requirements-lab.txt`:

```
# 실험(lab) 전용 의존성. <운영 이미지에 싣지 않는다.>
#
# 🔴 requirements.txt 와 갈라둔 이유는 하나다: ai-service/Dockerfile 이 requirements.txt 를
#    읽고, 그 이미지를 1GB 짜리 t3.micro 가 받는다. torch 를 넣으면 이미지가 수 GB 늘어
#    <실험이 운영 배포를 무겁게 만든다.> prometheus-fastapi-instrumentator 를 기각한 것과
#    같은 계열의 판단이다.
#
# ⚠️ 그 결과 reranker_provider="local" 은 운영 이미지에서 <기동하지 않는다.> 의도한 것이다.
#    기본값은 "cloudflare" 이고, 로컬을 골랐는데 모델이 없으면 조용히 떨어지지 않고
#    한국어 오류를 낸다(app/local_reranker.py).
#
# 설치:  cd ai-service && .venv/bin/pip install -r requirements-lab.txt
#
# 🔴 torch 는 <내보낼 때만> 필요하고 돌릴 때는 필요 없다. 이 분리가 이 슬라이스의 핵심이다.
#    ONNX 로 내보내는 것은 한 번이고, 그 산출물을 돌리는 데는 onnxruntime 하나면 된다.
onnxruntime==1.20.1
optimum[exporters]==1.24.0
transformers==4.48.0
torch==2.5.1
```

⚠️ 버전은 설치해보고 resolve 되는 값으로 맞춘다. `requirements.txt` 의 pydantic 주석이 남긴 교훈이 정확히 이것이다 (파일에 적힌 버전과 실제 설치되는 버전이 달라 깨끗한 환경에서 resolve 가 안 됐다). Step 7 에서 실제로 설치한 뒤 `pip freeze | grep -E 'onnxruntime|optimum|transformers|^torch'` 로 확인해 값을 맞출 것.

- [ ] **Step 4: 모델 디렉터리를 git 에서 막는다**

`.gitignore` 맨 아래에 추가한다.

```gitignore
# 리랭커 모델 가중치. 원본 약 1.1GB · INT8 약 280MB 라 git 에 넣을 크기가 아니다.
#
# ⚠️ testdata/fixtures/ 와는 판단이 다르다. 거기는 바이너리를 <커밋했고> 그 이유가
#    "돌릴 때마다 바이트가 달라지면 파서가 회귀했는지 생성기가 달라졌는지 구분할 수 없다"
#    였다. 모델 가중치에는 그 문제가 없다. 같은 리비전을 받으면 같은 바이트가 온다.
#    그래서 app/export_reranker.py 가 리비전을 못박는 것으로 재현성을 대신한다.
ai-service/models/
```

- [ ] **Step 5: 내보내기 스크립트를 만든다**

Create `ai-service/app/export_reranker.py`:

```python
"""리랭커를 내려받아 ONNX 로 바꾸고 INT8 로 양자화한다.

    cd ai-service && .venv/bin/python -m app.export_reranker

한 번만 돌리면 된다. 산출물은 ai-service/models/ 아래에 남고 git 에는 올라가지 않는다.

🔴 리비전을 못박는 이유
─────────────────────────────────────────────────────────────────────────────
태그 없이 받으면 나중에 다른 가중치가 와서 <양자화 때문인가 모델이 바뀐 것인가> 를
구분할 수 없게 된다. 이 저장소가 여덟 번 낸 버그가 전부 "원인이 다른 사실들을
같은 값으로 뭉갠 것" 이었다. 같은 함정을 여기서 미리 가른다.

🔴 왜 동적(dynamic) 양자화인가
─────────────────────────────────────────────────────────────────────────────
가중치를 8비트 정수로 줄이고 활성값은 추론 중에 그때그때 양자화한다.
<보정 데이터(calibration set)가 필요 없다.> 정적 양자화는 대표 입력 표본이 필요한데,
그것을 고르는 순간 표본 선택이 결과에 섞인다. 변수를 하나만 바꾸려면 없는 쪽이 낫다.
BERT 계열 인코더에서 가장 많이 쓰이는 기본 경로이기도 하다.
정적 양자화 · INT4 는 이번 범위가 아니다(설계문서 §3-5).

⚠️ 이 파일은 requirements-lab.txt 를 설치한 환경에서만 <내보내기가> 돈다.
   무거운 import 는 전부 함수 안에 있다 (모듈 최상단에 두면 CI 가 그 자리에서 죽는다).
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ID = "BAAI/bge-reranker-base"
# 🔴 실행 전에 <반드시> 실제 커밋 해시로 채운다. 얻는 방법은 main() 의 안내 문구에 있다.
REVISION = "0000000000000000000000000000000000000000"

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"

VARIANT_DIRS = {
    "local": "bge-reranker-base-onnx",
    "local_int8": "bge-reranker-base-onnx-int8",
}
ONNX_FILENAME = {
    "local": "model.onnx",
    "local_int8": "model_quantized.onnx",
}
# 토크나이저까지 있어야 <돌릴 수 있는> 산출물이다. onnx 파일만 보면
# 변환이 중간에 죽은 상태를 완성으로 착각한다.
_REQUIRED_EXTRA = ("tokenizer.json", "tokenizer_config.json")


def variant_dir(variant: str, models_dir: Path | None = None) -> Path:
    """변형 이름 → 산출물 디렉터리."""
    if variant not in VARIANT_DIRS:
        raise ValueError(f"모르는 리랭커 변형입니다: {variant}")
    return (models_dir or MODELS_DIR) / VARIANT_DIRS[variant]


def artifact_status(models_dir: Path | None = None) -> dict[str, bool]:
    """변형별로 <돌릴 수 있는 산출물이 다 있는가>. 디렉터리 존재만 보지 않는다."""
    out: dict[str, bool] = {}
    for variant in VARIANT_DIRS:
        d = variant_dir(variant, models_dir)
        needed = [ONNX_FILENAME[variant], *_REQUIRED_EXTRA]
        out[variant] = all((d / name).is_file() for name in needed)
    return out


def missing_message(variant: str) -> str:
    """모델이 없을 때 나가는 안내. <무엇을 어떻게 하면 되는지> 까지 적는다."""
    return (
        f"로컬 리랭커 모델({variant})이 없습니다. "
        f"ai-service 에서 `.venv/bin/pip install -r requirements-lab.txt` 로 실험 의존성을 설치한 뒤 "
        f"`.venv/bin/python -m app.export_reranker` 를 한 번 돌려 모델을 준비해주세요. "
        f"(운영 이미지에는 이 의존성이 없습니다. 기본값 reranker_provider=cloudflare 로 두세요.)"
    )


def export() -> None:
    """내려받기 → ONNX 변환 → INT8 양자화. 무거운 import 는 전부 여기 안에 있다."""
    from optimum.onnxruntime import (  # noqa: PLC0415 - 늦은 import 가 의도다
        AutoQuantizationConfig,
        ORTModelForSequenceClassification,
        ORTQuantizer,
    )
    from transformers import AutoTokenizer  # noqa: PLC0415

    fp32_dir = variant_dir("local")
    int8_dir = variant_dir("local_int8")
    fp32_dir.mkdir(parents=True, exist_ok=True)
    int8_dir.mkdir(parents=True, exist_ok=True)

    print(f"① 내려받기 + ONNX 변환: {REPO_ID}@{REVISION[:8]}")
    model = ORTModelForSequenceClassification.from_pretrained(
        REPO_ID, revision=REVISION, export=True
    )
    model.save_pretrained(fp32_dir)
    AutoTokenizer.from_pretrained(REPO_ID, revision=REVISION).save_pretrained(fp32_dir)

    print("② 동적 INT8 양자화")
    quantizer = ORTQuantizer.from_pretrained(fp32_dir)
    # avx512_vnni 는 x86 가속 힌트일 뿐이고, 양자화된 가중치 자체는 어느 CPU 에서도 돈다.
    # ⚠️ 그래서 <속도>는 아키텍처마다 다르다. M4 Pro(ARM)에서 잰 속도를 EC2(x86_64)의
    #    속도라고 말하면 안 된다(설계문서 §5).
    qconfig = AutoQuantizationConfig.avx512_vnni(is_static=False, per_channel=False)
    quantizer.quantize(save_dir=int8_dir, quantization_config=qconfig)
    AutoTokenizer.from_pretrained(REPO_ID, revision=REVISION).save_pretrained(int8_dir)


def _report() -> None:
    for variant, ok in artifact_status().items():
        d = variant_dir(variant)
        if not ok:
            print(f"❌ {variant}: 산출물이 완전하지 않다 ({d})")
            continue
        onnx = d / ONNX_FILENAME[variant]
        print(f"✅ {variant}: {onnx} ({onnx.stat().st_size / 1024 / 1024:.1f} MB)")


def main() -> None:
    if REVISION.strip("0") == "":
        print(
            "REVISION 이 비어 있습니다. 아래로 실제 커밋 해시를 얻어 "
            "app/export_reranker.py 의 REVISION 에 박아주세요.\n"
            '  .venv/bin/python -c "from huggingface_hub import HfApi; '
            f"print(HfApi().model_info('{REPO_ID}').sha)\"",
            file=sys.stderr,
        )
        raise SystemExit(1)
    export()
    _report()


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: 점검을 다시 돌린다**

```bash
cd ai-service && .venv/bin/python -m app.export_reranker_check
```
Expected: `check_revision_is_pinned` 만 FAIL (`AssertionError: REVISION 이 아직 자리표시자다`). 나머지 둘은 ✅.

- [ ] **Step 7: 실험 의존성을 설치하고 실제 리비전을 박는다**

```bash
cd ai-service && .venv/bin/pip install -r requirements-lab.txt
.venv/bin/pip freeze | grep -E 'onnxruntime|optimum|transformers|^torch'
.venv/bin/python -c "from huggingface_hub import HfApi; print(HfApi().model_info('BAAI/bge-reranker-base').sha)"
```
`pip freeze` 값이 `requirements-lab.txt` 와 다르면 **파일 쪽을 실제 값으로 고친다.** 출력된 40자 해시는 `app/export_reranker.py` 의 `REVISION` 에 그대로 박는다.

- [ ] **Step 8: 점검 3가지가 전부 통과하는지 확인한다**

```bash
cd ai-service && .venv/bin/python -m app.export_reranker_check
```
Expected: `3가지 전부 통과.`

- [ ] **Step 9: 커밋**

```bash
git add ai-service/requirements-lab.txt ai-service/app/export_reranker.py \
        ai-service/app/export_reranker_check.py .gitignore
git commit -m "feat: 리랭커 ONNX 변환·INT8 양자화 스크립트를 더한다"
```

---

## Task 3: 로컬 리랭커 제공자

**Files:**
- Create: `ai-service/app/local_reranker.py`
- Create: `ai-service/app/local_reranker_check.py`
- Modify: `.github/workflows/ci.yml` (자체 점검 목록과 그 위 주석)

**Interfaces:**
- Consumes: `export_reranker.{ONNX_FILENAME, artifact_status, missing_message, variant_dir}` (Task 2)
- Produces:
  - `rerank(query: str, texts: list[str], *, variant: str) -> dict`
  - `preflight(variant: str, models_dir: Path | None = None) -> Path`
  - `ModelUnavailable(RuntimeError)`
  - `latency_percentiles() -> dict[str, dict[str, float]]`
  - `max_rss_mb() -> float`

- [ ] **Step 1: 실패하는 점검을 먼저 쓴다**

Create `ai-service/app/local_reranker_check.py`:

```python
"""로컬 리랭커의 <계약> 점검. 모델도 onnxruntime 도 필요 없다.

CI 에서 도는 점검이다. 그래서 진짜 추론은 여기서 하지 않는다
(진짜 모델로 돌리는 것은 app/local_reranker_e2e_check.py 이고 사람이 손으로 돌린다).

여기서 보는 것은 넷이다.
  ① 출력이 Cloudflare 와 <같은 모양> 인가. 다르면 retriever._rerank 가 조용히 망가진다
  ② 점수 내림차순이고 입력 인덱스를 하나도 잃지 않는가
  ③ 모델이 없을 때 <조용히 넘어가지 않고> 한국어 오류를 내는가
  ④ 모듈 최상단에서 onnxruntime 을 import 하지 않는가 (하면 운영 이미지와 CI 가 죽는다)
"""
from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from . import local_reranker
from .local_reranker import ModelUnavailable, _to_response


def check_response_shape_matches_cloudflare() -> None:
    """Cloudflare 응답과 같은 모양이어야 한다.

    {"response": [{"id": <입력 인덱스>, "score": float}, ...]}  점수 내림차순.
    이 계약이 맞으면 retriever._rerank 의 나머지 로직을 한 줄도 안 고쳐도 된다.
    """
    out = _to_response([0.1, 0.9, 0.5])
    assert set(out) == {"response"}, out
    assert [item["id"] for item in out["response"]] == [1, 2, 0], out
    assert all(isinstance(item["score"], float) for item in out["response"]), out


def check_scores_are_descending() -> None:
    scores = [item["score"] for item in _to_response([-3.0, 2.0, 0.0, 7.5])["response"]]
    assert scores == sorted(scores, reverse=True), scores


def check_every_input_index_survives() -> None:
    """입력 인덱스가 하나도 사라지면 안 된다.

    _rerank 가 빠진 인덱스를 뒤에 붙여 보전하긴 하지만, 제공자가 <잃어버리는 것> 자체가
    버그다. 잃으면 "리랭커가 아래로 내렸다" 와 "제공자가 빠뜨렸다" 가 뭉개진다.
    """
    ids = sorted(item["id"] for item in _to_response([1.0] * 5)["response"])
    assert ids == [0, 1, 2, 3, 4], ids


def check_empty_input_is_empty_response() -> None:
    assert _to_response([]) == {"response": []}


def check_missing_model_raises_korean_error() -> None:
    """🔴 조용히 Cloudflare 로 떨어지지 않는다. 떨어지면 <무엇을 쟀는지> 를 잃는다."""
    with TemporaryDirectory() as tmp:
        try:
            local_reranker.preflight("local_int8", models_dir=Path(tmp))
        except ModelUnavailable as e:
            assert "app.export_reranker" in str(e), str(e)
            assert "requirements-lab.txt" in str(e), str(e)
        else:
            raise AssertionError("모델이 없는데 preflight 가 통과했다")


def check_onnxruntime_is_not_imported_at_module_load() -> None:
    """🔴 무거운 의존성은 <함수 안에서> 늦게 import 한다.

    모듈 최상단에서 import 하면 requirements.txt 만 깔린 CI 와 운영 이미지가
    이 파일을 import 하는 순간 죽는다.
    """
    assert "onnxruntime" not in sys.modules, "import 만 했는데 onnxruntime 이 올라왔다"
    assert "torch" not in sys.modules, "import 만 했는데 torch 가 올라왔다"


def main() -> None:
    checks = [
        check_response_shape_matches_cloudflare,
        check_scores_are_descending,
        check_every_input_index_survives,
        check_empty_input_is_empty_response,
        check_missing_model_raises_korean_error,
        check_onnxruntime_is_not_imported_at_module_load,
    ]
    for fn in checks:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(checks)}가지 전부 통과.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 점검을 돌려 실패를 확인한다**

```bash
cd ai-service && .venv/bin/python -m app.local_reranker_check
```
Expected: FAIL. `ModuleNotFoundError: No module named 'app.local_reranker'`

- [ ] **Step 3: 제공자를 구현한다**

Create `ai-service/app/local_reranker.py`:

```python
"""리랭커를 <이 컴퓨터에서> 돌리는 제공자 파일 (ONNX Runtime).

왜 별도 파일인가
─────────────────────────────────────────────────────────────────────────────
friendli.py 가 세워둔 규칙 그대로다. `cf.py` 는 <Cloudflare 를 어떻게 부르는가>만
아는 파일이고, 거기에 두 번째 제공자를 끼워 넣으면 "어느 분기가 어느 제공자였더라" 가
시작된다. **제공자마다 파일을 하나씩 두고, 부르는 쪽이 고른다.**

출력 계약을 Cloudflare 와 <똑같이> 맞춘다
─────────────────────────────────────────────────────────────────────────────
    {"response": [{"id": <입력 인덱스>, "score": float}, ...]}   점수 내림차순

이 모양을 지키면 retriever._rerank 의 나머지 로직(실패 시 원래 순서 유지 · 빠진 인덱스
보전 · rerank_fusion)을 한 줄도 안 고쳐도 된다.

⚠️ 실패 모드가 Cloudflare 와 다르다
─────────────────────────────────────────────────────────────────────────────
Cloudflare 는 네트워크와 HTTP 오류뿐이지만 여기는 모델 파일 없음 · 의존성 없음 ·
메모리 부족 · 스레드 고갈이 있다. <새 실패 모드가 느는 것>이므로 부르는 쪽(_rerank)의
try/except 를 넓게 잡는다. 리랭커는 순서를 개선하는 부가 기능이고,
리랭커가 죽었다고 채팅이 죽으면 안 된다.

🔴 그러나 <조용히 Cloudflare 로 떨어지지는 않는다.> 로컬을 골랐는데 결과가 Cloudflare
   것이면 "무엇을 쟀는지" 를 잃는다. 그래서 평가는 preflight() 로 <시작 전에> 거절하고,
   운영 경로(채팅)만 벡터 순서로 살아남는다. 둘은 모순이 아니라 역할이 다른 것이다.

⚠️ onnxruntime · transformers 는 requirements-lab.txt 에만 있다. 그래서 import 를
   전부 함수 안에 둔다. 모듈 최상단에 두면 운영 이미지와 CI 가 import 하는 순간 죽는다.
"""
from __future__ import annotations

import logging
import resource
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any

from .export_reranker import ONNX_FILENAME, artifact_status, missing_message, variant_dir

_log = logging.getLogger(__name__)

# 한 번에 넘기는 최대 토큰 수. bge-reranker-base 의 학습 길이가 512 다.
MAX_LENGTH = 512


class ModelUnavailable(RuntimeError):
    """모델 산출물이 없거나 실험 의존성이 안 깔린 상태."""


def preflight(variant: str, models_dir: Path | None = None) -> Path:
    """산출물이 <돌릴 수 있는 상태로> 있는지 확인하고 디렉터리를 돌려준다.

    없으면 ModelUnavailable 이다. 표식(None)이 아니라 예외인 이유는,
    분기를 빠뜨린 호출부가 조용히 지나가지 못하게 하려는 것이다
    (metrics 의 MetricUnreadable 과 같은 판단이다).
    """
    if not artifact_status(models_dir).get(variant, False):
        raise ModelUnavailable(missing_message(variant))
    return variant_dir(variant, models_dir)


def _to_response(scores: list[float]) -> dict:
    """점수 목록을 Cloudflare 와 같은 모양으로 바꾼다. 인덱스는 하나도 버리지 않는다."""
    ranked = sorted(enumerate(scores), key=lambda pair: pair[1], reverse=True)
    return {"response": [{"id": i, "score": float(s)} for i, s in ranked]}


# 변형별로 세션과 토크나이저를 한 번만 만든다. 매 호출 로드하면 1GB 짜리 파일을
# 질문마다 다시 읽어 <측정이 로딩 시간을 재게> 된다.
_sessions: dict[str, tuple[Any, Any]] = {}


def _session(variant: str) -> tuple[Any, Any]:
    if variant in _sessions:
        return _sessions[variant]

    model_dir = preflight(variant)
    try:
        import onnxruntime as ort  # noqa: PLC0415 - 늦은 import 가 의도다
        from transformers import AutoTokenizer  # noqa: PLC0415
    except ImportError as e:
        # 의존성이 없는 것도 "이 제공자를 쓸 수 없다" 는 같은 사실이다.
        # 다만 안내 문구가 설치 방법을 담고 있어야 한다(missing_message 가 담고 있다).
        raise ModelUnavailable(missing_message(variant)) from e

    session = ort.InferenceSession(
        str(model_dir / ONNX_FILENAME[variant]),
        providers=["CPUExecutionProvider"],
    )
    tokenizer = AutoTokenizer.from_pretrained(str(model_dir))
    _sessions[variant] = (session, tokenizer)
    return _sessions[variant]


def rerank(query: str, texts: list[str], *, variant: str) -> dict:
    """(질문, 청크) 쌍마다 점수를 매겨 Cloudflare 와 같은 모양으로 돌려준다.

    ⚠️ texts 는 preview(앞 200자)가 아니라 <전체 본문>이어야 한다.
       덜 보여주고 "못 맞힌다" 고 판정하면 그건 모델이 아니라 우리 잘못이다
       (retriever._rerank 주석의 교훈).
    """
    if not texts:
        return {"response": []}

    session, tokenizer = _session(variant)
    started = time.perf_counter()
    encoded = tokenizer(
        [query] * len(texts),
        texts,
        padding=True,
        truncation=True,
        max_length=MAX_LENGTH,
        return_tensors="np",
    )
    # 모델이 실제로 받는 입력 이름만 넘긴다. token_type_ids 가 없는 그래프도 있다.
    wanted = {i.name for i in session.get_inputs()}
    feed = {k: v for k, v in encoded.items() if k in wanted}
    logits = session.run(None, feed)[0]
    _record_latency(variant, (time.perf_counter() - started) * 1000)

    # 교차 인코더라 출력이 (N, 1) 이다. 첫 열이 관련성 점수다.
    return _to_response([float(row[0]) for row in logits])


# ── 지연 계측 (cf._record_latency 와 같은 모양을 일부러 맞춘다) ──────────
#
# 같은 모양으로 두는 이유: A(Cloudflare)와 B·C(로컬)의 지연을 <같은 방식으로> 읽어야
# 비교가 성립한다. 한쪽은 p50, 한쪽은 평균이면 표가 거짓말을 한다.
# ⚠️ 스레드 안전하지 않다. cf.py 와 같은 한계이고 같은 이유로 괜찮다(측정용 근사치).
_LATENCY_WINDOW = 2000
_latencies: dict[str, deque[float]] = {}
_call_counts: dict[str, int] = {}


def _record_latency(variant: str, ms: float) -> None:
    if variant not in _latencies:
        _latencies[variant] = deque(maxlen=_LATENCY_WINDOW)
    _latencies[variant].append(ms)
    _call_counts[variant] = _call_counts.get(variant, 0) + 1


def latency_percentiles() -> dict[str, dict[str, float]]:
    """변형별 호출 수와 p50/p95/p99(ms). 평균은 주지 않는다(느린 꼬리를 감춘다)."""
    out: dict[str, dict[str, float]] = {}
    for variant, values in _latencies.items():
        ordered = sorted(values)

        def pct(p: float, ordered: list[float] = ordered) -> float:
            # nearest-rank. cf.latency_percentiles 와 같은 식이어야 비교가 성립한다.
            idx = max(0, min(len(ordered) - 1, int(-(-len(ordered) * p // 100)) - 1))
            return ordered[idx]

        out[variant] = {
            "count": _call_counts.get(variant, len(ordered)),
            "latency_window": len(ordered),
            "p50": pct(50),
            "p95": pct(95),
            "p99": pct(99),
        }
    return out


def max_rss_mb() -> float:
    """이 프로세스가 지금까지 쓴 <최대> 상주 메모리(MB).

    🔴 단위가 OS 마다 다르다. macOS 는 바이트, 리눅스는 킬로바이트다.
       나누는 수를 하나로 두면 1024배 틀린 값이 조용히 표에 실린다.
       ("원인이 다른 사실을 같은 값으로 뭉개지 말 것" 과 같은 부류다.)

    ⚠️ 프로세스 전체의 최대치라 <리랭커만의 사용량이 아니다.> t3.micro 판단의
       재료로 쓰되, 이 값으로 "들어간다" 를 주장하지 말 것(설계문서 §5).
    """
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return raw / (1024 * 1024) if sys.platform == "darwin" else raw / 1024
```

- [ ] **Step 4: 점검이 통과하는지 본다**

```bash
cd ai-service && .venv/bin/python -m app.local_reranker_check
```
Expected: `6가지 전부 통과.`

⚠️ 여기서 `check_onnxruntime_is_not_imported_at_module_load` 가 실패하면, Task 2 에서 lab 의존성을 설치한 venv 라 다른 모듈이 먼저 올렸을 수 있다. Step 6 의 깨끗한 venv 결과가 진짜 판정이다.

- [ ] **Step 5: CI 에 등록한다**

`.github/workflows/ci.yml` 의 "자체 점검 (DB·외부 API 없이 도는 것만)" 목록에서 `python -m app.openapi_check` 다음 줄에 추가한다.

```yaml
          python -m app.export_reranker_check
          python -m app.local_reranker_check
```

그리고 그 위 주석 블록에서 `app.openapi_check` 설명 아래에 한 문단을 더한다. (그 파일이 "개수를 늘리거나 줄일 때는 위 문장의 수도 함께 고칠 것" 이라고 지시하고 있으므로, **못 태우는 점검 개수를 5개에서 6개로 고치고** 새 항목을 목록에 더한다.)

```yaml
      #    ✅ app.local_reranker_check · app.export_reranker_check 는 <계약과 순수 로직>만 본다.
      #       onnxruntime · transformers 를 import 하지 않고(늦은 import) 모델 파일도 안 읽는다.
      #         · app.local_reranker_e2e_check  진짜 모델 1.1GB + requirements-lab.txt  ← 못 태우는 것 6번째
```

- [ ] **Step 6: 깨끗한 환경에서 도는지 확인한다 (이 태스크의 핵심 검증)**

CI 는 `requirements.txt` 만 깐다. 실험 의존성 없이 도는지가 핵심이다.

```bash
cd /Users/cheonjamin/projects/AllDap/ai-service
python3 -m venv /tmp/ci-like && /tmp/ci-like/bin/pip install -q -r requirements.txt \
  && /tmp/ci-like/bin/python -m app.local_reranker_check \
  && /tmp/ci-like/bin/python -m app.export_reranker_check
```
Expected: 양쪽 다 전부 통과. 여기서 `ModuleNotFoundError: No module named 'onnxruntime'` 이 나면 늦은 import 가 깨진 것이다.

- [ ] **Step 7: 커밋**

```bash
git add ai-service/app/local_reranker.py ai-service/app/local_reranker_check.py .github/workflows/ci.yml
git commit -m "feat: 리랭커를 로컬 ONNX 로 돌리는 제공자를 더한다"
```

---

## Task 4: 제공자 선택을 설정으로 연결한다

**Files:**
- Modify: `ai-service/app/config.py` (`reranker_model` 다음 줄)
- Modify: `ai-service/app/retriever.py` (`_rerank` 와 그 아래)
- Modify: `ai-service/app/retriever_check.py`
- Modify: `ai-service/.env.example`

**Interfaces:**
- Consumes: `local_reranker.rerank` (Task 3)
- Produces:
  - `config.Settings.reranker_provider: str`
  - `retriever._rerank_order(query: str, texts: list[str]) -> list[int]`
  - `retriever._apply_order(sources: list[Source], order: list[int]) -> list[Source]`

- [ ] **Step 1: 실패하는 점검을 먼저 쓴다**

`ai-service/app/retriever_check.py` 의 맨 위 import 를 아래로 바꾼다.

```python
from . import retriever
from .retriever import _keywords, _rrf_reorder
from .schemas import Source
```

`_check_rerank_fusion` 아래에 두 함수를 추가한다.

```python
def _sources(*chunk_ids: int) -> list[Source]:
    return [
        Source(chunk_id=i, document_id=1, filename=f"{i}.pdf", score=0.9, preview=f"p{i}")
        for i in chunk_ids
    ]


def _check_rerank_survives_provider_failure() -> None:
    """🔴 리랭커가 죽어도 채팅은 살아야 한다. 원래 순서를 그대로 돌려준다.

    로컬 제공자는 Cloudflare 에 없던 실패 모드를 들고 온다(모델 파일 없음 · 의존성 없음 ·
    메모리 부족 · 스레드 고갈). 그래서 <제공자가 무엇이든> 실패가 검색 실패가 되지 않는 것을
    여기서 못박는다. 이건 기존 성질이고, 이 슬라이스가 그것을 깨뜨리지 않았다는 회귀 검사다.
    """
    sources = _sources(1, 2, 3)

    def boom(query: str, texts: list[str]) -> list[int]:
        raise RuntimeError("모델 파일이 없다")

    original_order, original_fetch = retriever._rerank_order, retriever.fetch_contents
    retriever._rerank_order = boom
    retriever.fetch_contents = lambda ids: {}
    try:
        out = retriever._rerank("질문", sources)
    finally:
        retriever._rerank_order = original_order
        retriever.fetch_contents = original_fetch

    assert [s.chunk_id for s in out] == [1, 2, 3], [s.chunk_id for s in out]


def _check_apply_order_keeps_missing_indexes() -> None:
    """응답에 빠진 인덱스가 있어도 청크를 잃지 않는다(기존 성질).

    잃으면 "리랭커가 아래로 내렸다" 와 "제공자가 빠뜨렸다" 가 뭉개진다.
    """
    sources = _sources(1, 2, 3)

    out = retriever._apply_order(sources, [2, 0])  # 인덱스 1 이 응답에서 빠졌다
    assert [s.chunk_id for s in out] == [3, 1, 2], [s.chunk_id for s in out]

    # 범위 밖 인덱스가 와도 터지지 않는다(제공자가 거짓말을 해도 채팅이 죽으면 안 된다).
    out = retriever._apply_order(sources, [9, 1])
    assert [s.chunk_id for s in out] == [2, 1, 3], [s.chunk_id for s in out]
```

`main()` 을 아래로 바꾼다.

```python
def main() -> None:
    _check_keywords()
    _check_rrf()
    _check_rerank_fusion()
    _check_rerank_survives_provider_failure()
    _check_apply_order_keeps_missing_indexes()
    print("OK — 낱말 추출 8가지 · RRF 4가지 · 리랭커 융합 3가지 · 제공자 실패 2가지 통과")
```

- [ ] **Step 2: 점검을 돌려 실패를 확인한다**

```bash
cd ai-service && .venv/bin/python -m app.retriever_check
```
Expected: FAIL. `AttributeError: module 'app.retriever' has no attribute '_rerank_order'`

- [ ] **Step 3: 설정값을 더한다**

`ai-service/app/config.py` 의 `reranker_model` 다음 줄(즉 `rerank_candidates` 주석 위)에 추가한다.

```python
    # 리랭커를 <어디서> 돌릴 것인가. 2026-09-16 에 붙였다.
    #
    #   "cloudflare"  @cf/baai/bge-reranker-base 를 API 로 부른다 (기본값 · 지금까지의 전부)
    #   "local"       내려받아 ONNX 로 바꾼 원본을 이 컴퓨터에서 돌린다 (fp32)
    #   "local_int8"  그것을 동적 INT8 로 양자화한 것
    #
    # 🔴 기본값을 "cloudflare" 로 두는 이유: 리랭커는 <이미 기본값으로 켜져 있는> 경로다.
    #    이 실험은 꺼진 기능을 켜는 것이 아니라 켜져 있는 경로를 갈아 끼우는 것이고,
    #    잘못되면 지금 지키고 있는 <회당 오답 0건>이 깨진다. 측정할 때만 환경변수로 바꾼다.
    #
    # 🔴 "local" 계열은 운영 이미지에서 <기동하지 않는다.> onnxruntime 이
    #    requirements-lab.txt 에만 있기 때문이고, 의도한 것이다. 모델이나 의존성이 없으면
    #    조용히 cloudflare 로 떨어지지 않고 한국어 오류를 낸다(local_reranker.ModelUnavailable).
    #    조용히 떨어지면 <무엇을 쟀는지> 를 잃는다. friendli.py 가 토큰 없을 때 하는 것과 같다.
    #
    # ⚠️ 이 값을 바꾸면 그 실행은 <다른 실험>이다. evalrun 의 config 박제에 함께 들어간다.
    reranker_provider: str = "cloudflare"
```

- [ ] **Step 4: `retriever._rerank` 를 가른다**

`ai-service/app/retriever.py` 의 `_rerank` 에서 `contents = fetch_contents(...)` 부터 `if not s.rerank_fusion:` 까지를 아래로 바꾼다. (독스트링과 그 위 주석은 그대로 둔다.)

```python
    contents = fetch_contents([src.chunk_id for src in sources])
    texts = [contents.get(src.chunk_id, src.preview) for src in sources]
    try:
        order = _rerank_order(query, texts)
    except Exception as e:  # noqa: BLE001 - 순서 개선 실패가 검색 실패가 되면 안 된다
        # ⚠️ 로컬 제공자는 Cloudflare 에 없던 실패 모드를 들고 온다
        #    (모델 파일 없음 · 의존성 없음 · 메모리 부족 · 스레드 고갈).
        #    그래서 예외 종류를 좁히지 않는다. 다만 <어느 제공자에서> 떨어졌는지는 남긴다.
        #    조용히 벡터 순서로 도는 것과, 그 사실을 아는 것은 다르다.
        _log.warning(
            "리랭킹 실패(원래 순서 유지) provider=%s: %s: %s",
            s.reranker_provider, type(e).__name__, e,
        )
        return sources

    reranked = _apply_order(sources, order)
    if not s.rerank_fusion:
        return reranked
```

그리고 `_rerank` 아래(`fetch_contents` 위)에 두 함수를 새로 만든다.

```python
def _rerank_order(query: str, texts: list[str]) -> list[int]:
    """제공자를 골라 <입력 인덱스의 새 순서>를 받아온다.

    제공자마다 파일이 하나씩 있고 여기가 고르는 자리다(friendli.py 주석의 규칙).
    어느 제공자든 응답 계약은 같다:
        {"response": [{"id": <입력 인덱스>, "score": float}, ...]}   점수 내림차순
    계약이 같으므로 이 아래 로직은 제공자를 몰라도 된다.
    """
    s = get_settings()
    if s.reranker_provider == "cloudflare":
        result = cf.run(s.reranker_model, {
            "query": query,
            "contexts": [{"text": text} for text in texts],
        })
    else:
        # 여기서 import 하는 이유: local_reranker 자체는 가볍지만(무거운 것은 그 안에서
        # 다시 늦게 import 한다), 제공자 파일을 고르는 자리가 여기임을 코드로 보이려는 것이다.
        from . import local_reranker
        result = local_reranker.rerank(query, texts, variant=s.reranker_provider)
    return [item["id"] for item in result["response"]]


def _apply_order(sources: list[Source], order: list[int]) -> list[Source]:
    """새 순서를 적용하되 <아무 청크도 잃지 않는다.>

    응답에 빠진 인덱스가 있어도 뒤에 붙인다. 잃으면 "리랭커가 아래로 내렸다" 와
    "제공자가 빠뜨렸다" 가 같은 결과로 보여 구분할 수 없게 된다.
    """
    seen = {i for i in order if 0 <= i < len(sources)}
    return [sources[i] for i in order if 0 <= i < len(sources)] + [
        src for i, src in enumerate(sources) if i not in seen
    ]
```

- [ ] **Step 5: 점검이 통과하는지 본다**

```bash
cd ai-service && .venv/bin/python -m app.retriever_check
```
Expected: `OK — 낱말 추출 8가지 · RRF 4가지 · 리랭커 융합 3가지 · 제공자 실패 2가지 통과`

- [ ] **Step 6: 기본값(Cloudflare)이 그대로 도는지 확인한다**

갈아 끼운 뒤에도 A 경로가 멀쩡해야 한다. 여기서 깨지면 기준선 자체가 사라진다.

```bash
docker compose up -d
cd ai-service && .venv/bin/uvicorn app.main:app --port 8001 &
sleep 5
curl -s -X POST localhost:8001/internal/chat -H 'Content-Type: application/json' \
  -d '{"bot_id": 1, "message": "정규직의 업무용 컴퓨터 교체 주기는?", "session_id": "local-test"}' | head -20
```
Expected: 근거가 붙은 답변. 서버 로그에 `리랭킹 실패` 가 **없다.**

- [ ] **Step 7: `.env.example` 에 적는다**

```
# 리랭커를 어디서 돌릴 것인가: cloudflare(기본) | local | local_int8
# 🔴 local 계열은 requirements-lab.txt 와 app/export_reranker.py 산출물이 있어야 돈다.
#    운영에서는 쓰지 않는다(이미지에 onnxruntime 이 없다). 측정할 때만 켠다.
RERANKER_PROVIDER=cloudflare
```

- [ ] **Step 8: 커밋**

```bash
git add ai-service/app/config.py ai-service/app/retriever.py \
        ai-service/app/retriever_check.py ai-service/.env.example
git commit -m "feat: 리랭커 제공자를 설정으로 고를 수 있게 한다"
```

---

## Task 5: 실행 설정 박제와 preflight 거절

측정이 뒤섞이지 않게 하는 태스크다. `eval_runs.config` 에 `reranker_provider` 가 없으면 **A · B · C 실행의 박제가 완전히 같아져 나중에 구분할 방법이 없다.** 이 저장소가 `answerable_max_distance` 와 `rerank_fusion` 을 박제한 것과 같은 이유다.

**Files:**
- Modify: `ai-service/app/evalrun.py`
- Modify: `ai-service/app/evalrun_check.py`

**Interfaces:**
- Consumes: `config.Settings.reranker_provider` (Task 4), `local_reranker.preflight` (Task 3)
- Produces: `evalrun._run_config(s) -> dict`

- [ ] **Step 1: 실패하는 점검을 먼저 쓴다**

`ai-service/app/evalrun_check.py` 의 import 를 아래로 바꾼다.

```python
from .config import Settings
from .evalrun import _run_config, _run_status
```

아래 두 함수를 추가하고 `main()` 의 `checks` 목록에도 더한다.

```python
def check_config_records_reranker_provider() -> None:
    """🔴 A(Cloudflare) · B(로컬) · C(로컬 INT8)는 <다른 실험>이다.

    이 값이 config 에 없으면 세 실행의 박제가 완전히 같아져,
    나중에 "이 0.875 는 어느 제공자였지?" 를 알 방법이 없다.
    answerable_max_distance 와 rerank_fusion 을 박제한 것과 같은 이유다.
    """
    cfg = _run_config(Settings(reranker_enabled=True, reranker_provider="local_int8"))
    assert cfg["reranker_provider"] == "local_int8", cfg


def check_config_omits_provider_when_reranker_is_off() -> None:
    """리랭커가 꺼져 있으면 제공자는 의미가 없다. None 으로 남긴다.

    다른 리랭커 설정들(rerank_candidates · rerank_fusion)이 이미 그렇게 한다.
    끈 실행에 제공자가 적혀 있으면 "껐는데 로컬로 돌았나?" 라는 없는 질문이 생긴다.
    """
    cfg = _run_config(Settings(reranker_enabled=False, reranker_provider="local"))
    assert cfg["reranker_provider"] is None, cfg
```

- [ ] **Step 2: 점검을 돌려 실패를 확인한다**

```bash
cd ai-service && .venv/bin/python -m app.evalrun_check
```
Expected: FAIL. `ImportError: cannot import name '_run_config' from 'app.evalrun'`

- [ ] **Step 3: 설정 박제를 순수 함수로 가른다**

`ai-service/app/evalrun.py` 에서 `create_run` 안의 `config = { ... }` 딕셔너리를 통째로 잘라내 모듈 수준 함수로 옮긴다. **키와 주석은 한 글자도 바꾸지 않고 그대로 옮긴 뒤**, `reranker_model` 다음 줄에 한 항목만 추가한다.

```python
def _run_config(s) -> dict:
    """실행 시점의 설정을 박제한다. 나중에 이 실행이 어떤 조건이었는지 아는 유일한 단서다.

    순수 함수로 갈라둔 이유: DB 없이 <무엇이 박제되는가> 를 점검할 수 있어야 하기 때문이다.
    박제 누락은 실행을 돌려보기 전에는 안 보이고, 돌려본 뒤에는 이미 늦는다.
    """
    return {
        # ... (기존 키와 주석 전부 그대로) ...
        "reranker": s.reranker_enabled,
        "reranker_model": s.reranker_model if s.reranker_enabled else None,
        # 🔴 제공자도 박제한다. cloudflare · local · local_int8 은 <다른 실험>이고,
        #    안 적으면 셋의 config 가 완전히 같아져 구분할 방법이 없다
        #    (answerable_max_distance · rerank_fusion 을 박제한 것과 같은 이유).
        "reranker_provider": s.reranker_provider if s.reranker_enabled else None,
        "rerank_candidates": s.rerank_candidates if s.reranker_enabled else None,
        # ... (나머지 기존 키 전부 그대로) ...
    }
```

`create_run` 의 해당 부분은 두 줄로 줄어든다.

```python
    s = get_settings()
    config = _run_config(s)
```

- [ ] **Step 4: 평가 시작 전에 preflight 로 거절한다**

`create_run` 의 `s = get_settings()` 바로 다음에 추가한다.

```python
    # 🔴 로컬 제공자를 골랐으면 <시작하기 전에> 모델이 있는지 확인하고, 없으면 거절한다.
    #
    #    채팅(운영 경로)은 리랭커가 실패해도 벡터 순서로 살아남는다. 그게 옳다.
    #    그런데 <평가>에서 같은 일이 벌어지면 리랭커 없이 돈 결과가
    #    "로컬 리랭커 측정치" 로 표에 실린다. 원인이 다른 두 사실을 같은 값으로 뭉개는 것이고,
    #    이 저장소가 여덟 번 낸 버그가 전부 그 부류였다.
    #    실행을 <시작도 하지 않는> 것이 유일하게 안전한 처리다.
    if s.reranker_enabled and s.reranker_provider != "cloudflare":
        from . import local_reranker
        local_reranker.preflight(s.reranker_provider)
```

- [ ] **Step 5: 점검이 통과하는지 본다**

```bash
cd ai-service && .venv/bin/python -m app.evalrun_check
```
Expected: 기존 5가지 + 새 2가지 = `7가지 전부 통과.`

- [ ] **Step 6: 커밋**

```bash
git add ai-service/app/evalrun.py ai-service/app/evalrun_check.py
git commit -m "feat: 평가 실행에 리랭커 제공자를 박제하고 모델 없으면 거절한다"
```

---

## Task 6: 진짜 모델로 내보내고 완료 조건 1~3 을 실측한다

여기서 처음으로 진짜 모델이 돈다. **CI 로 태울 수 없다**(모델 1.1GB + lab 의존성). 사람이 손으로 돌리고 출력을 기록한다.

**Files:**
- Create: `ai-service/app/local_reranker_e2e_check.py`
- Modify: `AGENTS.md` ("▶ 다음 세션은 여기서 시작한다" 절에 실행 방법)

**Interfaces:**
- Consumes: `local_reranker.{rerank, latency_percentiles, max_rss_mb}`, `export_reranker.{artifact_status, variant_dir, ONNX_FILENAME}`
- Produces: 크기 · 지연 · RSS · 순위 일치 실측값 (Task 8 의 표 재료)

- [ ] **Step 1: 실제 내보내기를 돌린다**

```bash
cd ai-service && .venv/bin/python -m app.export_reranker
```
Expected: 아래 모양. 내려받기 때문에 수십 분 걸릴 수 있다.
```
① 내려받기 + ONNX 변환: BAAI/bge-reranker-base@<8자리>
② 동적 INT8 양자화
✅ local: .../models/bge-reranker-base-onnx/model.onnx (약 1,100 MB)
✅ local_int8: .../models/bge-reranker-base-onnx-int8/model_quantized.onnx (약 280 MB)
```

- [ ] **Step 2: 종단 점검 스크립트를 쓴다**

Create `ai-service/app/local_reranker_e2e_check.py`:

```python
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
```

- [ ] **Step 3: 돌린다**

```bash
cd ai-service && .venv/bin/python -m app.local_reranker_e2e_check
```
Expected: 두 변형 모두 `순서=[1, ...]` (정답인 인덱스 1 이 1위). 크기 · 지연 · RSS 출력. **출력 전체를 그대로 복사해 둔다.** Task 8 의 표 재료다.

- [ ] **Step 4: 채팅이 로컬 제공자로 실제 도는지 본다 (완료 조건 1)**

```bash
docker compose up -d
cd ai-service && RERANKER_PROVIDER=local_int8 .venv/bin/uvicorn app.main:app --port 8001
```
다른 창에서:
```bash
curl -s -X POST localhost:8001/internal/chat -H 'Content-Type: application/json' \
  -d '{"bot_id": 1, "message": "정규직의 업무용 컴퓨터 교체 주기는?", "session_id": "local-test"}' | head -40
```
Expected: `answer` 가 나오고 `sources` 에 근거가 **지금과 같은 모양(chunk_id · filename · score · preview)** 으로 붙는다. 서버 로그에 `리랭킹 실패` 경고가 **없어야** 한다.

- [ ] **Step 5: 모델이 없을 때 조용히 넘어가지 않는지 본다 (완료 조건 2)**

```bash
cd ai-service && mv models/bge-reranker-base-onnx-int8 /tmp/int8-hidden
RERANKER_PROVIDER=local_int8 .venv/bin/python -c "
from app.config import get_settings
from app import local_reranker
local_reranker.preflight(get_settings().reranker_provider)
"
```
Expected: `ModelUnavailable: 로컬 리랭커 모델(local_int8)이 없습니다. ... requirements-lab.txt ... app.export_reranker ...`

이어서 평가 실행이 **시작조차 안 되는지** 본다 (Task 5 의 preflight).

```bash
cd ai-service && RERANKER_PROVIDER=local_int8 .venv/bin/uvicorn app.main:app --port 8001 &
sleep 5
curl -s -X POST localhost:8001/internal/bots/1/eval/runs
```
Expected: 실행이 만들어지지 않고 오류가 나간다. `eval_runs` 에 새 행이 없어야 한다.
```bash
docker compose exec -T db psql -U alldap -d alldap -c "SELECT id, status, created_at FROM eval_runs ORDER BY id DESC LIMIT 3;"
```

- [ ] **Step 6: 그 상태에서 채팅은 살아 있는지 본다 (완료 조건 3)**

모델을 숨긴 채로 Step 4 의 curl 을 다시 보낸다.

Expected: 답변이 **나온다**(벡터 순서로). 서버 로그에 `리랭킹 실패(원래 순서 유지) provider=local_int8: ModelUnavailable: ...` 이 찍힌다. 두 사실(사용자는 답을 받았다 / 리랭커는 안 돌았다)이 **각각 보이는 것**이 이 단계의 확인 대상이다.

```bash
mv /tmp/int8-hidden ai-service/models/bge-reranker-base-onnx-int8
```

- [ ] **Step 7: `AGENTS.md` 에 실행 방법을 남긴다**

"▶ 다음 세션은 여기서 시작한다" 절의 로컬 실행 순서 블록 아래에 추가한다.

````markdown
**리랭커를 로컬에서 돌리려면** (2026-09-16 슬라이스)

```
cd ai-service && .venv/bin/pip install -r requirements-lab.txt
.venv/bin/python -m app.export_reranker          # 한 번만. 산출물은 models/ (git 제외)
.venv/bin/python -m app.local_reranker_e2e_check # 진짜 모델로 계약·크기·지연·RSS 확인
RERANKER_PROVIDER=local_int8 .venv/bin/uvicorn app.main:app --port 8001
```

🔴 기본값은 `cloudflare` 다. 운영 이미지에는 `onnxruntime` 이 없어 로컬 제공자가 기동하지
않는다(의도한 것이다). 모델이나 의존성이 없으면 조용히 Cloudflare 로 떨어지지 않고
한국어 오류를 낸다. 채팅은 그때도 벡터 순서로 살아남지만, **평가는 시작조차 하지 않는다.**
리랭커 없이 돈 결과가 "로컬 리랭커 측정치" 로 표에 실리면 안 되기 때문이다.
````

- [ ] **Step 8: 커밋**

```bash
git add ai-service/app/local_reranker_e2e_check.py AGENTS.md
git commit -m "test: 진짜 모델로 로컬 리랭커 계약·크기·지연을 확인한다"
```

---

## Task 7: A · B · C 를 각각 3회 재고 표로 뽑는다

**Files:**
- Create: `ai-service/app/rerank_compare.py`

**Interfaces:**
- Consumes: `eval_runs.config->>'reranker_provider'` (Task 5 가 박제한 값)
- Produces: 설정별 집계표 · 문항별 표 (Task 8 이 문서로 옮긴다)

- [ ] **Step 1: 집계 스크립트를 쓴다**

Create `ai-service/app/rerank_compare.py`:

```python
"""A(cloudflare) · B(local) · C(local_int8) 실행을 <읽어서> 표로 뽑는다.

    cd ai-service && .venv/bin/python -m app.rerank_compare --bot-id 1

🔴 새로 재는 것이 없다. 이미 저장된 eval_runs · eval_results 를 읽을 뿐이다.
   "새 평가 도구를 만들지 않는다" 는 설계문서 §4-1 을 지키는 것이다.

🔴 status='completed' 인 실행만 본다. 이유가 둘이다.
   ① partial 은 <분모가 달라> 애초에 비교할 수 없다.
   ② 무엇보다 채점 실패가 섞이면 "fallback 했다" 와 "재지 못했다" 를 SQL 로 가를 수 없다
      (둘 다 faithfulness IS NULL 이다). completed 는 judge_failed=0 이 보장되므로
      그 안에서만 아래 해석이 <확정적>이다:
          generated_answer IS NOT NULL AND faithfulness IS NULL  →  fallback
          generated_answer IS NULL                               →  처리 실패(있으면 completed 가 아니다)

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

    by_provider: dict[str, list[tuple]] = {}
    for row in runs:
        by_provider.setdefault(row[1] or UNRECORDED, []).append(row)

    print("설정             회수  전체충실성(회차별)              폭      관련성  응답률")
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
```

- [ ] **Step 2: A 실행만 있는 상태로 한 번 돌려 본다**

```bash
cd ai-service && .venv/bin/python -m app.rerank_compare --bot-id 1
```
Expected: 기존 실행들이 `(박제 없음)` 으로 묶여 나온다. Task 5 이전 실행에는 `reranker_provider` 가 없으므로 **정상이다.** SQL 오류가 나면 여기서 고친다.

- [ ] **Step 3: A(Cloudflare)를 3회 잰다**

```bash
docker compose up -d
cd ai-service && .venv/bin/uvicorn app.main:app --port 8001   # 기본값 cloudflare
```
다른 창에서:
```bash
for i in 1 2 3; do curl -s -X POST localhost:8001/internal/bots/1/eval/runs; echo; done
```
Expected: 실행 3건이 `completed` 로 끝난다. **`partial` 이 나오면 그 실행은 버리고 다시 돌린다**(분모가 달라 비교할 수 없다).

⚠️ 회당 804 뉴런이고 하루 한도가 10,000 이라 **하루 12회**다. 9회면 하루 안에 끝나지만, 다른 실험을 같은 날 돌리지 말 것.

- [ ] **Step 4: B(로컬 fp32)를 3회 잰다**

```bash
cd ai-service && RERANKER_PROVIDER=local .venv/bin/uvicorn app.main:app --port 8001
```
같은 for 루프. Expected: 3건 `completed`.

- [ ] **Step 5: C(로컬 INT8)를 3회 잰다**

```bash
cd ai-service && RERANKER_PROVIDER=local_int8 .venv/bin/uvicorn app.main:app --port 8001
```
같은 for 루프. Expected: 3건 `completed`.

- [ ] **Step 6: 뉴런 · 지연 · RSS 를 기록한다**

각 설정의 마지막 실행 직후 서버 로그에서 모델별 뉴런 합계를 읽는다.
Expected: A 는 리랭커(`bge-reranker-base`) 항목이 회당 약 13.6 뉴런, **B · C 는 그 항목이 아예 없다**(로컬에서 돌았으므로). 그 사실이 "정말 로컬로 돌았는가" 의 가장 단단한 증거다.

지연과 메모리:
```bash
cd ai-service && RERANKER_PROVIDER=local_int8 .venv/bin/python -m app.local_reranker_e2e_check | tail -5
```

- [ ] **Step 7: 표를 뽑는다**

```bash
cd ai-service && .venv/bin/python -m app.rerank_compare --bot-id 1
```
Expected: `cloudflare` · `local` · `local_int8` 세 묶음이 각 3회로 나오고, 회당 오답 · 완전오답 · fallback 과 문항별 표가 찍힌다. **출력을 그대로 저장해 둔다.**

- [ ] **Step 8: 커밋**

```bash
git add ai-service/app/rerank_compare.py
git commit -m "feat: 리랭커 제공자별 평가 결과를 집계하는 리포트를 더한다"
```

---

## Task 8: 결과를 문서에 남기고 완료 조건을 대조한다

**Files:**
- Modify: `AGENTS.md` (결과 절 하나)
- Modify: `docs/decisions.md`
- Modify: `docs/BACKLOG.md` (§5 에 다음 단계)

**Interfaces:**
- Consumes: Task 6 · 7 의 실측값 전부
- Produces: 없음 (마지막 태스크)

- [ ] **Step 1: `AGENTS.md` 에 결과 절을 쓴다**

"💰 회당 비용" 절 아래에 넣는다. **A 와 B 가 달랐다면 그 사실을 숨기지 않는다**(완료 조건 5).

```markdown
### 🔴 리랭커 로컬 실행 + 양자화 (2026-09-16): A · B · C 실측

같은 16문항 · 50문서 · 306청크 · `temperature=0` · 리랭커 + 하이브리드 ON · 설정당 3회.
바꾼 것은 **리랭커를 어디서 돌리는가** 하나다.

| 설정 | 리랭커 | 전체충실성 | 관련성 | 응답률 | 회당 오답 | 회당 완전오답 | 회당 fallback |
|---|---|---|---|---|---|---|---|
| A | Cloudflare (기본값) | (실측) | | | | | |
| B | 로컬 원본 ONNX fp32 | (실측) | | | | | |
| C | 로컬 양자화 ONNX INT8 | (실측) | | | | | |

| | 모델 파일 | 리랭커 지연 p50 | 최대 RSS | 회당 리랭커 뉴런 |
|---|---|---|---|---|
| A | (Cloudflare 가 갖고 있다) | (실측) | (해당 없음) | 13.6 |
| B | (실측) MB | (실측) | (실측) MB | **0** |
| C | (실측) MB | (실측) | (실측) MB | **0** |

🔴 **B 를 재는 것이 이 표의 핵심이다.** B 없이 A 와 C 만 비교하면 차이가 생겼을 때
<양자화 탓인지 실행 환경 탓인지> 구분할 수 없다. 같은 이름의 모델이라도 Cloudflare 가
무엇을 돌리는지 우리는 모른다(가중치 리비전 · 내부 양자화 여부 · 전처리).
**A 와 B 가 다르게 나오는 것 자체가 결과다.**

⚠️ **속도는 Apple M4 Pro(ARM) 기준이다.** EC2 는 x86_64 이고 INT8 가속은 아키텍처마다
다르다. 운영 속도를 알려면 거기서 재야 한다.

⚠️ **t3.micro 투입 여부는 이 측정으로 알 수 없다.** 파일 크기와 상주 메모리는 다르고,
1GB 에 이미 Spring · Caddy · Python 이 올라가 있다. "들어갈 수도 있다" 이상을 주장하지 않는다.

⚠️ **편차 규칙이 여기에도 적용된다.** 설정 간 차이가 0.032 보다 작으면
"나빠졌다" 가 아니라 **"구별되지 않는다"** 가 정확한 서술이다.

**기본값은 (바꾸지 않았다 / 바꿨다. 실측 결과에 따라 적는다).**
품질이 눈에 띄게 떨어지면 기본값을 바꾸지 않고 측정만 남긴다. 코드는 지우지 않는다
(`rerank_fusion` 을 남긴 것과 같은 이유다. 지우면 재현할 수 없는 주장이 된다).

**재현**: `cd ai-service && .venv/bin/pip install -r requirements-lab.txt`
→ `python -m app.export_reranker` → `RERANKER_PROVIDER=local_int8` 로 평가 실행
→ `python -m app.rerank_compare --bot-id 1`
```

- [ ] **Step 2: `docs/decisions.md` 에 결과 항목을 더한다**

Task 1 에서 쓴 2026-09-16 항목 아래에 덧붙인다. 형식은 `날짜 | 무엇을 | 왜 그렇게 | 검토한 대안` 이고, **예상과 달랐던 것을 반드시 적는다**(이 저장소에서 가장 강한 재료다. "올랐습니다" 보다 "예상이 틀렸고 이렇게 찾아 고쳤습니다" 가 면접에서 더 강하다).

- [ ] **Step 3: `docs/BACKLOG.md` §5 에 다음 단계를 못박는다**

"리랭커가 정답을 밀어내는 실패 2건" 항목에 덧붙인다.

```markdown
  ✅ **2026-09-16 에 선행 배관이 깔렸다**: 리랭커를 로컬 ONNX 로 돌리고 INT8 로 양자화하는
  경로. 결과는 `AGENTS.md` 의 해당 절.
  🔴 **다음은 리랭커 파인튜닝이다.** `bge-reranker-base` 는 2억 7천만 파라미터라
  M4 Pro 24GB 에서 학습된다(GPU 를 빌리지 않는다). 학습 데이터도 이미 있다:
  `evaluator.make_question` 이 청크에서 (질문, 정답) 쌍을 만들고, 정답 청크가 positive,
  같은 질문에 검색됐지만 틀린 청크가 negative 다.
  🔴 **순서는 파인튜닝 → 양자화다.** 줄여놓고 학습하는 것(QLoRA 류)은 메모리가 모자랄 때의
  타협이고 우리는 모자라지 않다. 그리고 학습 결과를 원본으로 갖고 있어야
  양자화 강도를 바꿔가며 여러 번 잴 수 있다. `app/export_reranker.py` 를 한 번 더 돌리면 되고
  버리는 코드가 없다. 최종 표는 D(파인튜닝) · E(파인튜닝 + 양자화) 로 완성된다.
```

- [ ] **Step 4: 완료 조건 6개를 대조한다**

설계문서 §8 을 한 줄씩 짚는다. **돌려본 명령과 그 출력이 있는 것만 ✅ 로 적는다.** ("돌려봤다" 가 아니라 실제 실행 결과를 붙이라는 PR 템플릿의 요구와 같은 것이다.)

| # | 조건 | 어디서 확인했나 |
|---|---|---|
| 1 | `reranker_provider="local"` 로 채팅이 동작하고 근거·출처가 같은 모양 | Task 6 Step 4 |
| 2 | 모델이 없을 때 조용히 떨어지지 않고 한국어 오류 | Task 6 Step 5 |
| 3 | 로컬 추론이 실패해도 채팅이 죽지 않고 원래 순서 유지 | Task 6 Step 6 · `retriever_check` |
| 4 | A · B · C 를 각각 3회 이상 돌린 결과표(§4-2 의 모든 축) | Task 7 Step 7 |
| 5 | 결과를 `AGENTS.md` 에 한 절로 남겼고 A ≠ B 를 숨기지 않았다 | Step 1 |
| 6 | §7 의 문서 셋(AGENTS.md · BACKLOG.md · decisions.md)이 함께 고쳐졌다 | Task 1 · Step 2 · 3 |

- [ ] **Step 5: 로컬 검사를 전부 돌린다**

```bash
cd /Users/cheonjamin/projects/AllDap/ai-service
for m in retriever_check evalrun_check local_reranker_check export_reranker_check \
         chunker_check generator_check conflicts_check metrics_check openapi_check; do
  .venv/bin/python -m app.$m > /dev/null && echo "✅ $m" || echo "❌ $m"
done
```
Expected: 전부 ✅. 하나라도 ❌ 면 고치고 다시 돌린다.

- [ ] **Step 6: 커밋하고 PR 을 연다**

```bash
git add AGENTS.md docs/decisions.md docs/BACKLOG.md
git commit -m "docs: 리랭커 로컬 실행·양자화 측정 결과를 남긴다"
git push -u origin feat/reranker-local-quantization
gh pr create --title "리랭커를 로컬에서 돌리고 양자화한다 (A·B·C 실측)" --body-file <(cat <<'BODY'
`.github/PULL_REQUEST_TEMPLATE.md` 를 채운다. 특히 두 칸이 핵심이다.

**한계 & 트레이드오프**
- 속도는 M4 Pro(ARM) 기준이다. EC2 는 x86_64 이고 INT8 가속이 다르다. 운영 속도는 재보지 않았다.
- t3.micro 투입 가능 여부는 이 슬라이스로 알 수 없다. 파일 크기와 상주 메모리는 다르다.
- 16문항은 작다. 한 문항이 0.0625 를 움직이고 측정 편차가 0.032 다. 겹치는 크기다.
- Cloudflare 가 무엇을 돌리는지 공개돼 있지 않다. 그래서 B 를 쟀고, 그 불확실성은 측정으로만 좁혀진다.
- 로컬 제공자는 운영 이미지에서 기동하지 않는다(onnxruntime 이 requirements-lab.txt 에만 있다). 의도한 것이다.

**검토한 대안과 선택 이유**
- PyTorch + transformers 추론: 런타임 의존성이 2GB 대다. 추론만 하는데 학습 프레임워크를 싣는다.
- llama.cpp / GGUF: 생성 모델용 생태계다. BERT 계열 리랭커는 주 대상이 아니다.
- 정적 양자화: 보정 데이터 표본 선택이 결과에 섞인다. 변수를 하나만 바꾸려면 없는 쪽이 낫다.
- requirements.txt 에 함께 넣기: 운영 이미지가 수 GB 늘어 실험이 배포를 무겁게 만든다.
- A 와 C 만 비교: 차이가 생겼을 때 양자화 탓인지 실행 환경 탓인지 구분할 수 없다. 그래서 B 를 넣었다.
BODY
)
```

⚠️ PR 을 올리는 데까지가 이 태스크다. **CI 결과를 기다리며 폴링하지 않는다.**

---

## 실행 순서 요약

| 태스크 | 무엇 | 검증 |
|---|---|---|
| 1 | 규칙을 연다 (문서 3개) | grep 으로 모순 확인 |
| 2 | 의존성 분리 + 내보내기 스크립트 | `export_reranker_check` 3가지 |
| 3 | 로컬 제공자 | `local_reranker_check` 6가지 + 깨끗한 venv |
| 4 | 설정 · 제공자 분기 | `retriever_check` 제공자 실패 2가지 + 기본값 채팅 |
| 5 | 박제 + preflight 거절 | `evalrun_check` 7가지 |
| 6 | 진짜 모델 · 완료 조건 1~3 | 손으로 (curl · 모델 숨기기) |
| 7 | A · B · C 각 3회 + 표 | `rerank_compare` |
| 8 | 결과 문서화 + PR | 완료 조건 6개 대조 |

**태스크 1~5 는 진짜 모델 없이 끝난다.** 내려받기가 오래 걸리므로 Task 2 Step 7 에서 리비전을 박아둔 뒤 Task 6 Step 1 의 내보내기를 백그라운드로 돌려놓고 3~5 를 진행해도 된다.

**하루 뉴런 한도가 실험 횟수의 상한이다.** 평가 1회 804 뉴런 · 하루 10,000 = 12회이고 이 계획은 9회를 쓴다. 같은 날 다른 측정을 돌리지 말 것.
