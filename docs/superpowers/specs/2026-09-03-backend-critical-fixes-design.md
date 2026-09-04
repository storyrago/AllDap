# 백엔드 코드 리뷰 지적 사항 수정 — 설계

- 날짜: 2026-09-03
- 대상: `api/` (Spring), `ai-service/` (Python), `Caddyfile`
- 근거: 2026-09-03 백엔드 전수 리뷰 (Critical 2 · Important 6)

## 왜 이걸 지금 하나

리뷰에서 나온 8건 중 **둘은 제품의 두 기둥을 직접 무너뜨린다.**

1. **요금 방어선이 없다** — 인증 없이 열린 유일한 문(위젯 채팅)의 rate limit이 헤더 한 줄로 우회된다. 요청당 외부 LLM 호출 = 실제 돈이므로, 요금 폭탄이 곧 서비스 거부다.
2. **측정이 거짓말한다** — 채점 실패가 "충실성 0점"으로 환산되면서 실행은 `completed`로 남는다. W4의 before/after 비교표가 이 프로젝트의 최종 목표물인데, 그 숫자를 만드는 파이프라인이 조용히 틀린 값을 낸다.

나머지 6건은 이 둘을 고치는 김에 **같은 파일·같은 이야기**로 흡수되거나(4건), 앞으로 들어올 문서를 위한 그물이다(2건).

## 원칙 — 이 문서 전체에 적용

- **최소 수정.** 새 추상화·새 의존성을 만들지 않는다. 결함을 고치는 데 필요한 만큼만 바꾼다.
- **고친 것마다 실행 가능한 검사를 하나 남긴다.** 로직이 깨지면 실패하는 가장 작은 것.
- **PR 하나 = 한 문장으로 설명되는 작업 하나.** 트레이드오프가 두 개면 PR도 두 개다.
- 커밋 메시지는 `<타입>: <한국어 요약>`. PR 본문은 `.github/PULL_REQUEST_TEMPLATE.md`.

---

## PR 1 — 위젯 rate limit 우회 차단 · 로그인 제한 추가

**브랜치** `fix/widget-xff-ratelimit` · **모델 Opus**
(AGENTS.md 모델 선택: *"보안 관련 코드는 비용이 더 들어도 Opus를 유지한다"*)

### 무엇이 문제인가

`WidgetController.clientKey()`가 클라이언트가 보낸 `X-Forwarded-For`의 **맨 앞 값**을 그대로 신뢰한다.

```java
: forwarded.split(",")[0].trim();   // 맨 앞이 원 클라이언트
```

### 왜 실패하는가 — 전제를 잘못 잡았다

`application-prod.yaml:46-48`은 이렇게 적어놨다:

> ⚠️ 프록시를 반드시 거친다는 전제에서만 안전하다. 우리 구성은 Caddy 만 포트를 열므로 그 전제가 성립한다.

**성립하지 않는다.** 문제는 "누가 포트에 닿는가"가 아니라 **"프록시가 헤더를 덮어쓰는가"**다.
`Caddyfile:24`의 `reverse_proxy`는 기본 동작이 **덮어쓰기가 아니라 잇기(append)** — 클라이언트가 보낸 값 뒤에 실제 IP를 덧붙인다. 따라서 위조값이 항상 0번 자리에 남고, 코드는 정확히 그 0번을 읽는다.
`server.forward-headers-strategy: framework`도 구제하지 못한다. Spring의 `ForwardedHeaderFilter` 역시 XFF의 첫 항목을 remoteAddr로 삼는다.

### 실패 시나리오

```
POST /api/w/{publicKey}/chat
X-Forwarded-For: 1.2.3.<매 요청마다 증가>
```

rate-limit 키(`ip|publicKey`)가 매번 달라져 분당 한도가 **무제한**이 된다.

**부수 피해:** 그 루프로 키를 10만 개 넘기면 `RateLimiter:65`의 `counters.clear()`가 돌아 **그 순간 모든 봇·모든 방문자의 카운터가 리셋된다.** 공격자 한 명이 전역 제한을 주기적으로 지울 수 있다.

### 고치는 방법

**주 수정 — `Caddyfile` 한 줄.** 모든 소비자를 한 번에 고치고, 프록시 없이 뜨는 사고에도 견딘다.

```
{$API_DOMAIN} {
	# 클라이언트가 보낸 X-Forwarded-For 를 버리고 실제 접속 IP 로 덮어쓴다.
	# Caddy 기본값은 잇기(append)라 위조값이 맨 앞에 남고, clientKey() 가 그 맨 앞을 읽는다.
	header_up X-Forwarded-For {remote_host}
	reverse_proxy api:8080
```

`Caddyfile:19-22`의 낡은 TODO(*"`forward-headers-strategy: framework` 가 필요하다. 배포 후 바로 확인할 것"* — 이미 `application-prod.yaml:49`에 들어가 있다)도 함께 정정한다.
`application-prod.yaml:46-48`의 잘못된 전제 설명도 사실에 맞게 고친다.

**함께 — 로그인 요청 제한 (Important #7).**
`/api/auth/login`은 permitAll이고 실패 카운트도 지연도 없다. 유일한 방어가 BCrypt 비용(약 100ms/회)뿐이라 병렬 커넥션이면 분당 수천 회 추측이 가능하고, `PasswordEncoder.matches`가 요청당 CPU를 태우므로 그 자체가 저비용 DoS다.

이미 있는 `RateLimiter` 빈을 재사용한다. **키는 IP** — 이메일로 잡으면 남의 계정을 잠글 수 있다.
한도는 **분당 10회**로 두고, 위젯과 같은 방식(`WidgetProperties`처럼 `@ConfigurationProperties`)으로 `application.yaml`에서 주입한다(하드코딩하지 않는다).
10회 근거: 사람이 비밀번호를 잘못 치는 횟수의 상한으로 넉넉하고, 흔한 비밀번호 목록 대입에는 턱없이 부족한 값이다. 실측으로 조정할 값이며 그 사실을 주석에 남긴다.

**같은 PR인 이유:** 같은 `RateLimiter`를 쓰고, **XFF 수정이 선행 조건**이다. 먼저 고치지 않으면 로그인 제한도 똑같이 위조된 IP로 우회된다.

### 검사

**회귀 테스트 1건** — `WidgetIntegrationTest` (Important #8).

기존 rate limit 테스트 3건은 `X-Forwarded-For`를 **한 번도 보내지 않는다.** 그래서 `getRemoteAddr()` 분기로만 돌고, 실제 배포에서 열려 있는 우회 경로가 검증 범위 밖이다. 이 저장소가 반복해 겪은 부류다(통합 테스트 71건 초록불 상태에서 난 HTTP/2·iframe Origin 버그).

```
[비용] X-Forwarded-For 를 바꿔가며 보내도 한도를 우회할 수 없다
  → 한도까지 채운 뒤, 헤더만 바꾼 요청이 여전히 429 인가
```

로그인 제한도 같은 형태로 1건.

> ⚠️ **테스트는 Spring 계층만 검증한다.** `header_up` 수정 자체는 Caddy 설정이라 통합 테스트가 닿지 않는다. 이 PR의 검증은 **테스트 2건 + 배포 후 실제 요청으로 확인**의 둘로 나뉜다. 후자를 안 한 채 "고쳤다"고 쓰지 않는다.

### 한계 & 트레이드오프 (PR 본문에 그대로 옮길 것)

- **여전히 "프록시를 반드시 거친다"는 전제 위에 서 있다.** Spring 컨테이너 포트를 직접 노출하면 다시 뚫린다. 바뀐 것은 전제가 **성립하게 만든 것**이지 전제를 없앤 것이 아니다.
- 신뢰 프록시가 **정확히 1단**일 때만 맞다. 앞에 CDN을 하나 더 세우면 다시 계산해야 한다.
- 인메모리 고정 윈도우라는 기존 한계는 그대로다(인스턴스 늘면 무력, 경계 문제). 이건 AGENTS.md에 이미 알고 택한 것으로 적혀 있다.

---

## PR 2 — 평가 측정이 실패를 fallback으로 뭉개지 않게

**브랜치** `fix/eval-measurement` · **모델 Sonnet**

### 무엇이 문제인가

`evalrun.py:191`에서 `judge.score()`가 `None`을 돌려줄 때, 두 가지 **원인이 다른 사실**이 한 값이 된다.

| 사실 | `scored_count`에서 빠지는 게 | 맞나 |
|---|---|---|
| fallback (근거가 없어 못 답함) | 빠진다 | ✅ 맞다. 전체 충실성이 내려가야 옳다 |
| **채점 실패** (judge JSON 파싱 실패·5xx·잘림) | 빠진다 | ❌ 측정이 **안 된** 것이다 |

그런데 최종 지표는 Spring이 이렇게 만든다 (`EvalRunResponse.java:84`):

```
overallFaithfulness = avgFaithfulness × scoredCount / questionCount
```

즉 **채점 실패한 문항은 "충실성 0점"으로 환산된다.** 그리고 `processed`는 검색·생성만 세므로 `status`는 그대로 `completed` — 화면에서 "완료"로 보이고 `partial` 필터에도 안 걸린다.

### 실패 시나리오

16문항, 전부 정상 답변, 실제 충실성 1.000.
judge 모델이 2건에서 코드펜스 없는 잡소리를 뱉어 `_extract_json`이 `None` 반환.
(**실제로 발생하는 경로다** — `config.py`가 `gpt-oss-120b`를 "JSON 파싱 실패"로 탈락시킨 기록이 있다)

→ `avg_f=1.000`, `scored_count=14`, `processed=16`, `status='completed'`
→ 대시보드 전체 충실성 **0.875** (실제 1.000)
→ 이 값을 다른 설정의 0.875와 나란히 놓고 **"차이 없음"이라고 결론낸다.**

### 왜 이게 특별히 나쁜가

🔴 **AGENTS.md의 "낸 버그 4건"과 정확히 같은 부류다.** 넷 다 *원인이 다른 두 사실을 같은 값으로 뭉갠 것*이었고, 그 절은 **"다섯 번째를 조심할 것"**으로 끝난다. 이게 다섯 번째다.

그리고 `partial` 상태는 **바로 이 상황을 잡으려고 만든 것**인데, 검색·생성 실패만 잡고 채점 실패를 놓쳤다.

### 고치는 방법

```python
judge_failed = 0   # 채점까지 못 간 것. fallback 과 다른 사실이다

if sc is None:
    judge_failed += 1
    ...

if not processed:
    status = "failed"
elif processed < total or judge_failed:
    status = "partial"
else:
    status = "completed"
```

`partial`은 스키마에 CHECK 제약이 없고 Spring·프론트가 이미 아는 값이라 그대로 흘러간다.

**함께 — `judge.fetch_contents`를 try 안으로 (Important #6).**

`judge.py:139`의 `fetch_contents`가 `try` 밖이고, `evalrun.py:190`의 `judge.score(...)` 호출도 `try` 블록 바깥이다. 따라서 `fetch_contents`가 던지면(`PoolTimeout`, DB 재시작) 예외가 `_execute`를 뚫고 나가 `status='failed'`만 남는다.

**결과: 그때까지 모은 `rows`가 한 건도 저장되지 않는다** — INSERT가 루프 종료 후 일괄이기 때문이다. 16문항 중 15문항을 다 채점하고 마지막에 DB가 1초 딸꾹하면 뉴런 800개를 쓰고 결과가 0건이다.

`fetch_contents`를 judge의 `try` 안으로 옮긴다. 이미 "실패하면 `None`"이 계약이라 의미가 바뀌지 않는다.

**같은 PR인 이유:** 순서가 강제된다. #6만 먼저 고치면 DB 딸꾹이 `None`이 되어 **"충실성 0점"으로 둔갑한다** — 지금보다 나빠진다. 둘은 반드시 함께 간다.

### 검사

`evalrun`에 채점 실패를 주입해 `status == 'partial'`이 되는지 보는 자체 점검 1건.
(모델을 부르지 않고 `judge.score`를 `None` 반환으로 갈아끼운다 — 비용 0)

### 한계 & 트레이드오프

- **`partial`의 의미가 넓어진다.** 원래는 "일부 문항을 처리하지 못했다"였는데 이제 "일부를 채점하지 못했다"도 포함한다. 화면에서 둘을 구분하려면 사유 컬럼이 필요하지만, **지금 필요한 것은 "이 실행을 유효한 측정으로 쓰면 안 된다"는 신호 하나**라 컬럼을 늘리지 않는다.
- **과거 실행은 소급 정정하지 않는다.** `judge_failed`를 기록한 적이 없어 지금 와서 알 방법이 없다. 이미 쌓인 측정치는 그대로 두고, 이 사실을 `docs/decisions.md`에 남긴다.

---

## PR 3 — `/internal/*`에 빠진 `bot_id` 조건 채우기

**브랜치** `fix/internal-bot-scope` · **모델 Sonnet**

### 무엇이 문제인가

`/internal/*`에는 **인증이 없다.** SQL의 `bot_id` 조건이 봇 간 격리의 전부다.
같은 파일의 `update_conflict_status`(`main.py:540`)는 **정확히 이 위험을 근거로** 경로에 `bot_id`를 요구하고 `WHERE id=%s AND bot_id=%s`로 좁힌다. 두 곳만 그 규칙에서 빠져 있다.

**③ `delete_document` (`main.py:183`)**

```python
cur.execute("DELETE FROM documents WHERE id=%s", (doc_id,))  # 청크는 CASCADE
```

파괴력이 가장 크다 — 문서 + 전 청크 + `doc_conflicts`가 CASCADE로 함께 사라지고 **되돌릴 수 없다.**

**④ `list_eval_results` (`main.py:442`)**

`run_id`만으로 조회하고, 응답에 `generated_answer`·`ground_truth`·`retrieved_chunks`(파일명 포함)가 들어간다 = 남의 봇 문서 내용이다.
그런데 **Spring은 이 엔드포인트를 부르지 않는다** — `EvalService.findResults`가 `findByIdAndBotId`로 소유권을 먼저 확인하고 DB를 직접 읽는다. 격리가 약한 **죽은 코드**다.

### 실패 시나리오

지금은 Spring의 `findByIdAndBotUserId`가 막아준다. 즉 **격리 전체가 Spring 한 겹**이고 Python 쪽에는 그물이 없다.
Python이 내부망에 노출되거나(AGENTS.md가 배포 시 알려진 위험으로 적어둔 것), Spring에 소유권 검사를 빠뜨린 경로가 하나라도 생기면, `doc_id` 하나로 남의 봇 코퍼스가 통째로 지워진다.

AGENTS.md의 원칙 — *"소유권을 검사하지 않고 조회 쿼리에 못박는다. `findById` 후 `if (남의 것) throw`는 검사를 빠뜨려도 컴파일이 통과한다"* — 을 어긴 유일한 쓰기 경로다.

### 고치는 방법

**③** 경로에 `bot_id`를 넣고 WHERE에 함께 건다.

```python
@app.delete("/internal/bots/{bot_id}/documents/{doc_id}", status_code=204, response_model=None)
def delete_document(bot_id: UUID, doc_id: UUID) -> None:
    cur.execute("DELETE FROM documents WHERE id=%s AND bot_id=%s", (doc_id, bot_id))
```

Spring 쪽은 `AiServiceClient`의 uri와 `DocumentService.delete()` 한 줄씩. `DocumentService`는 이미 `document`를 손에 들고 있어 봇 id를 꺼낼 수 있다.

**④ 지운다.** 아무도 안 부르고, 남기면 격리가 약한 채로 남는다. 나중에 필요해지면 `/internal/bots/{bot_id}/eval/runs/{run_id}/results`로 다시 만든다.
지우기 전에 호출부가 정말 없는지 `api/`·`web/`·`widget/` 전체를 grep해 확인한다.

### 검사

Spring `DocumentIntegrationTest`에 **"남의 봇 문서는 지워지지 않는다"** 1건.
확인할 것은 "404가 났다"가 아니라 **"요청이 Python까지 가지 않았다"**이다(AGENTS.md의 명시적 지시).

### 한계 & 트레이드오프

- **경로가 바뀌므로 Spring과 Python을 함께 배포해야 한다.** 한쪽만 올리면 404다. 무중단이 아니라 잠깐 멈추고 둘 다 올린다 — 1인 개발·단일 인스턴스라 이 대가가 싸다.
- ④를 지우는 것은 **되돌릴 수 있는 결정**이다(코드가 git에 남는다). 반면 남겨두는 것은 되돌릴 수 없는 유출의 가능성을 남긴다.

---

## PR 4 — 청킹: 마침표 없는 긴 줄에 마지막 그물

**브랜치** `fix/chunker-hard-split` · **모델 Sonnet**

### 무엇이 문제인가

`chunker._split_sentences`는 `line.split(".")`로만 자른다. **마침표가 없으면 조각이 하나뿐이라 길이 상한이 전혀 적용되지 않는다.**

재현 (2026-09-03 실측):

```
text = "## 긴 표\n" + "가나다라마바사아자차" * 300     # size=500
→ 청크 2개, 길이 [6, 3008]
```

두 가지가 동시에 깨진다.

- **3008자 청크** — 이 모듈의 존재 이유("청크 하나에 주제 하나")가 정면으로 무너진다. 2026-08-03에 478자 청크에 조항 4개가 들어가 fallback이 났던 것과 **같은 실패 모드이고 규모가 6배**다.
- **제목이 6자 단독 청크로 떨어진다** — `_pack`에서 `candidate`가 size를 넘는 순간 제목만 든 `buf`를 먼저 뱉기 때문이다. 설계 주석("제목은 뒤따르는 절에 붙는다")과 반대다.

**현실적인 입력:** PDF·HWPX 표 한 행, 마침표 없이 `·`나 개행으로만 구분된 조항 나열. `parsers._parse_docx`가 표를 ` | `로 이어 붙인 줄이 정확히 이 모양이다.

**`chunker_check`는 못 잡는다** — `check_long_section_still_splits`의 지문이 `"가나다라마바사아자차. " * 80`으로 **마침표를 갖고 있다.**

### 고치는 방법

`_split_sentences`의 마지막 줄에 강제 분할을 건다.

```python
# 마침표가 없는 줄은 위에서 한 조각도 안 쪼개진다. 마지막 그물로 강제로 자른다.
return [p[i : i + size] for p in (out or [line]) for i in range(0, len(p), size)]
```

`chunker_check`에 **마침표 없는 케이스 1건**을 회귀 검사로 추가한다.

### 검증 — 여기가 이 PR의 핵심이다

🔴 **기존 코퍼스의 청크가 바뀌면 W4 측정치가 전부 무효가 된다.** 그러니 먼저 **안 바뀌는지 확인한다.**

AGENTS.md에 이미 근거가 있다: 현재 코퍼스 50문서는 **청크가 최대 217자**이고 인접 청크 256쌍 중 겹치는 것이 0개다(`chunk_split_headings=True`라 제목 단위로 잘려 `chunk_size=500`에 한참 못 미친다). 즉 **마침표 없는 긴 줄이 없을 것으로 예상된다.**

예상은 근거가 아니므로 **직접 대조한다.** 2026-08-17에 복원본을 검증할 때 쓴 방법 그대로:

```
ai-service/testdata/corpus/ 50개를 고친 청커로 다시 청킹
  → DB의 chunks 와 문자열 단위로 대조
```

| 결과 | 다음 행동 |
|---|---|
| **전부 동일** (예상) | 재임베딩·재측정 없음. PR 본문에 "기존 코퍼스는 영향 없음"을 **실측으로** 적는다 |
| 하나라도 다름 | 재청킹·재임베딩·평가 재측정이 필요하다. **이 PR을 멈추고 결정을 다시 받는다** |

### 한계 & 트레이드오프

- **강제 분할은 문장 중간을 자른다.** 마침표가 없는 줄에서는 그것 말고 자를 자리를 알 수 없다. 3008자 한 덩어리보다는 낫다는 판단이고, 형태소·문장 경계 인식이 필요해지면 그때 별도 슬라이스다.
- **제목이 단독 청크로 떨어지는 문제는 이 수정으로 완전히 사라지지 않는다.** 본문이 강제 분할되면 첫 조각에는 제목이 붙지만, 그 뒤 조각들은 제목 없이 남는다. 근본 해결은 `_pack`이 제목을 각 조각에 복제하는 것인데, 그건 청크 내용을 바꾸는 변경이라 **기존 측정치를 무효화한다.** 이번 범위에서 뺀다.

---

## PR 5 — W1 fallback 검사가 봇 지침을 태우게

**브랜치** `fix/fallback-check-prompt` · **모델 Sonnet**

### 무엇이 문제인가

`fallback_e2e_check.py`는 파일 주석에서 *"1차·2차 방어선이 함께 걸린다"*고 주장하지만, 실제로는 **봇 지침을 태우지 않는다.**

```python
answer, is_fallback = generate(question, sources)   # system_prompt 없음 → 기본 SYSTEM_PROMPT
```

프로덕션 두 경로는 모두 결합한다:
- `main.chat` → `system_prompt=build_system_prompt(fetch_bot_prompt(req.bot_id))`
- `evalrun._execute` → 같은 결합

### 왜 이게 위험한가

AGENTS.md와 `bot_prompt_check.py`가 **2026-08-13 실측으로 기록해둔 사실**이 있다 — 봇 지침 하나로 fallback 판정이 실제로 뚫린다. 지침 *"모르는 것도 아는 척 답해"*를 넣으니 근거 없는 질문에 `is_fallback=False`로 답했다.

**실패 시나리오:** 그 봇의 `system_prompt`에 그런 문구가 들어간다 → 실제 채팅은 뚫린다 → 그런데 이 검사는 **`fallback 10/10 · 대조군 3/3`을 찍는다.** W1 완료 조건이 통과했다고 보고하는데 제품은 뚫려 있다.

### 고치는 방법

```python
from .generator import build_system_prompt, fetch_bot_prompt, generate

system_prompt = build_system_prompt(fetch_bot_prompt(BOT_ID))
...
answer, is_fallback = generate(question, sources, system_prompt=system_prompt)
```

호출 세 군데 전부. `bot_prompt_check`는 검색을 뺀 프롬프트 전용 도구라 이걸 대체하지 못한다.

### 검사

이 파일 자체가 검사 도구다. 수정 후 **실제로 한 번 돌려 10/10·3/3이 유지되는지 확인**한다.
(현재 `BOT_ID` 봇에 `system_prompt`가 비어 있다면 결과가 그대로일 것이다 — 그 경우 "지침이 없어서 같았다"를 PR 본문에 명시한다. **"돌려봤다"가 아니라 실행 결과를 붙인다.**)

### 한계 & 트레이드오프

- **검사가 봇의 현재 설정에 의존하게 된다.** 지침을 바꾸면 이 검사 결과도 바뀐다 — 그게 의도다(프로덕션이 그렇게 동작한다). 대신 **"코퍼스가 같으면 결과가 같다"는 성질을 잃는다.** 결과를 비교할 때 지침도 함께 기록해야 한다.

---

## 실행 계획 — 멀티 에이전트

### 병렬성

5개 브랜치가 **파일을 하나도 공유하지 않는다.**

| PR | 파일 |
|---|---|
| 1 | `Caddyfile`, `application*.yaml`, `WidgetController`, `AuthController`, `WidgetIntegrationTest`, `AuthIntegrationTest` |
| 2 | `ai-service/app/evalrun.py`, `judge.py` |
| 3 | `ai-service/app/main.py`, Spring `AiServiceClient`·`DocumentService`·`DocumentIntegrationTest` |
| 4 | `ai-service/app/chunker.py`, `chunker_check.py` |
| 5 | `ai-service/app/fallback_e2e_check.py` |

→ 전부 `main`에서 따고 **동시에 진행할 수 있다.**

### 모델 배정

| PR | 모델 | 근거 |
|---|---|---|
| 1 | **Opus** | AGENTS.md 모델 선택의 명시적 예외 — 보안 코드. 여기서 틀리면 되돌리는 비용이 더 크다 |
| 2·3·4·5 | **Sonnet** | 스펙이 이 문서에서 확정됐다. 헤맬 여지가 없는 기계적 작업 |

계획(이 문서)은 Opus가 썼다. AGENTS.md의 기준은 *"구현이냐 아니냐"가 아니라 "스펙이 확정됐느냐"*다.

### 각 에이전트의 완료 조건

1. 브랜치를 `main`에서 딴다
2. 위 명세대로 고친다 — **최소 수정.** 새 추상화·새 의존성 금지
3. 검사를 실제로 **돌린다**. 출력을 남긴다
4. 커밋 (`<타입>: <한국어 요약>`)
5. `gh pr create` — 본문은 `.github/PULL_REQUEST_TEMPLATE.md`, **"한계 & 트레이드오프"와 "검토한 대안"을 위 각 절에서 그대로 옮긴다**
6. **CI는 기다리지 않는다** (PR 생성까지가 범위)

### 검증되지 않는 것 — 미리 적어둔다

- **PR 1의 `header_up`은 통합 테스트가 닿지 않는다.** Caddy 설정이라 실제 배포 후 확인이 필요하다. 그 전까지 "고쳤다"고 단정하지 않는다.
- **PR 4의 "기존 코퍼스 영향 없음"은 예상이지 사실이 아니다.** 대조 실행 전에는 그렇게 쓰지 않는다.
- **PR 2의 과거 실행 소급 정정은 불가능하다.** 이미 쌓인 측정치가 채점 실패를 포함하는지 알 방법이 없다.

### 결정 로그

머지 후 `docs/decisions.md`에 3줄:

```
2026-09-03 | 위젯 rate limit 의 클라이언트 IP 를 Caddy 가 덮어쓰게 했다 | XFF 는 클라이언트가 위조할 수 있고 Caddy 기본값은 잇기라 위조값이 맨 앞에 남는다 | Spring 에서 맨 뒤 항목 읽기(프록시 1단 전제라 직접 노출 시 다시 뚫림)
2026-09-03 | 채점 실패를 partial 로 갈랐다 | fallback 과 뭉개지면 "충실성 0점"으로 환산되는데 실행은 completed 로 남아 거짓 측정이 된다 | 사유 컬럼 추가(지금 필요한 신호는 "쓰면 안 된다" 하나)
2026-09-03 | /internal 문서 삭제 경로에 bot_id 를 넣었다 | 격리가 Spring 한 겹이었고 삭제는 CASCADE 라 되돌릴 수 없다 | Python 에서 소유권 조회 후 검사(빠뜨려도 통과하므로 조회 조건에 못박는다)
```
