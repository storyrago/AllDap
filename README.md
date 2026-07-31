# AllDap

문서를 올리면 **출처가 표시되는 한국어 RAG 챗봇**을 만들어주고,
그 챗봇이 얼마나 정확한지 **자동 평가 리포트로 증명**하는 서비스.

> 상세 기획은 [`docs/PRD_v0.4.md`](docs/PRD_v0.4.md), 설계 결정 이력은 [`docs/decisions.md`](docs/decisions.md).

---

## 아키텍처 (하이브리드)

```
 [브라우저]
      │
      ▼
 ┌──────────────────────────────────────────────────┐
 │ Next.js (App Router) :3000                       │  ← 관리자 대시보드 + 위젯 페이지
 │  /dashboard  /bot/[botId]/{documents,chat,       │     (뼈대 있음 · API 미연결)
 │   quality,logs,settings}  /w/[publicKey]         │
 └──────────────────────────────────────────────────┘
      │ HTTPS (REST + JWT)
      ▼
 ┌──────────────────────────────────────────────────┐
 │ Spring Boot API :8080                            │  ← 외부에 노출되는 유일한 서비스
 │  인증(JWT)·권한·봇/문서 메타·대화 로그             │     (W2)
 └──────────────────────────────────────────────────┘
      │ REST (내부망 전용 · 인증 없음)
      ▼
 ┌──────────────────────────────────────────────────┐
 │ Python AI Service :8001                          │  ← 외부 비노출. /internal/* 만 제공
 │  파싱·청킹·임베딩·검색·생성·평가                    │     (W1)
 └──────────────────────────────────────────────────┘
      │ SQL                        │ HTTPS
      ▼                            ▼
 ┌───────────────────┐   ┌──────────────────────┐
 │ PostgreSQL :5432  │   │ 외부 LLM API         │
 │  + pgvector       │   │  임베딩 / 답변 생성   │
 └───────────────────┘   └──────────────────────┘
      ▲
      └── Spring Boot API (JPA)
```

**원칙**
- 외부 트래픽은 Spring만 받는다. `/internal/*`은 인증이 없으므로 **절대 외부 노출 금지**.
- 외부 LLM API 키는 Python 서비스만 가진다. Spring도 Next.js도 키를 갖지 않는다.
- 브라우저는 Python(:8001)을 직접 부르지 않는다. 반드시 Spring(:8080)을 거친다.

### 테이블 소유권 (두 서비스가 같은 DB를 공유하므로 반드시 지킬 것)

| 테이블 | 쓰기 | 읽기 |
|---|---|---|
| `users`, `bots` | Spring | Python |
| `documents` | **Python** | Spring |
| `chunks` | **Python** | — |
| `conversations`, `messages` | Spring | — |
| `eval_*` | **Python** | Spring |

스키마의 단일 진실 공급원은 `api/src/main/resources/db/migration/V1__init.sql`.
Spring의 `ddl-auto`는 반드시 `validate` 또는 `none`.
마이그레이션은 Flyway가 관리하며 **Spring이 기동할 때** 적용됩니다. `V1__init.sql`은 수정 금지 — 변경은 `V2__*.sql`로만. (근거: `docs/decisions.md`)

**왜 나눴나:** AI 파이프라인(문서 파싱·임베딩·평가)은 Python 생태계가 사실상 필수고,
인증·트랜잭션·권한은 Spring이 강하다. 국내에서도 카카오페이(모델은 Python,
서빙은 Kotlin+Spring), 쏘카 등이 같은 구조를 쓴다.

**알려진 약점(숨기지 말 것):**
- 공유 DB는 마이크로서비스 안티패턴이다. 1인 개발에서는 데이터 동기화 비용이 분리 이득보다 커서 택했지만, 팀·트래픽이 커지면 DB를 나누고 API로만 통신해야 한다.
- Spring이 Python을 동기 호출하므로 Python이 죽으면 채팅이 죽는다 → W2에서 타임아웃·재시도를 반드시 설정할 것.
- 프론트를 Next.js로 분리하면서 **배포 대상이 3개**가 됐다. "운영할 것의 개수를 최소화한다"는 원칙과 충돌하는 선택이며, 풀스택 역량 증명을 위해 알고 택했다. (PRD §11.3)

---

## 디렉터리 구조

```
AllDap/
├── web/           Next.js (App Router) — 관리자 대시보드 · 위젯 페이지   🚧 뼈대만 있음
│   ├── app/(site)/          랜딩 · 인증
│   ├── app/(dashboard)/     봇 목록 · 봇별 화면
│   ├── components/          공통 UI 조각
│   └── lib/{api,types}.ts   Spring API 호출 래퍼 · 응답 타입
├── api/           Spring Boot API (:8080)                             🚧 인증·봇 CRUD 완료 · 나머지 TODO
│   ├── src/main/java/com/alldap/api/{global,domain}/...
│   └── src/main/resources/db/migration/
│       └── V1__init.sql   스키마 단일 진실 공급원 (Flyway가 api 기동 시 적용)
├── ai-service/    Python FastAPI AI 서비스 (:8001)                     ✅ W1 완료 조건 실측 통과
│   └── app/{parsers,chunker,retriever,generator,db,config,schemas,main}.py
├── widget/        임베드용 위젯 스크립트 (한 줄 설치)                     🚧 초안
│   └── alldap-widget.js
├── .github/       CI 워크플로 · PR 템플릿
├── docs/
│   ├── PRD_v0.4.md    제품 요구사항 정의서
│   └── decisions.md   설계 결정 로그 (날짜 | 무엇을 | 왜 | 검토한 대안)
├── docker-compose.yml  PostgreSQL + pgvector
├── AGENTS.md           AI 협업 컨텍스트 (원본)
├── CLAUDE.md           └ @AGENTS.md 포인터 한 줄
└── README.md           이 파일
```

> **"뼈대"의 뜻을 정확히 해둡니다.** `web/`과 `widget/`에 파일이 생겼지만, 이것은
> **경로·타입·호출 지점이 제자리에 있다**는 뜻이지 화면이 동작한다는 뜻이 아닙니다.
> 붙일 백엔드(`api/`)가 아직 없으므로 실제 데이터가 흐르는 것은 W2 이후입니다.
> 미구현 지점은 각 파일의 `TODO` 주석에 "무엇을 / 어느 주차에" 할지 적혀 있습니다.

---

## 실행 방법

의존 순서대로 **db → api → ai-service → web** 으로 올립니다.
아래로 갈수록 위의 것이 떠 있어야 동작합니다.

> ⚠️ **`api`가 `ai-service`보다 먼저입니다.** 2026-07-31에 스키마를 Flyway로 옮기면서
> 순서가 바뀌었습니다. 예전에는 컨테이너만 띄우면 테이블이 생겼지만, 이제는
> **Spring이 한 번 기동해야 테이블이 만들어집니다.** Python을 먼저 띄우면 테이블이 없어 실패합니다.

### 0. 사전 준비

- Docker Desktop
- Python 3.11+
- JDK 21
- Node.js 20+ (web 착수 이후 필요)

### ⚠️ 예전 볼륨이 남아 있다면 첫 기동이 막힙니다

두 가지가 바뀌었습니다.
① DB명·계정·비밀번호가 `dadap` → `alldap`,
② 스키마 적용이 Docker init → **Flyway**로 이관.

②가 특히 문제입니다. 예전 방식으로 테이블이 이미 들어간 볼륨에는 Flyway 이력 테이블이
없어서, Spring이 이렇게 말하며 기동을 거부합니다:

```
Found non-empty schema(s) "public" but no schema history table.
```

볼륨을 비우고 다시 시작하세요.

```bash
docker compose down -v      # -v 가 핵심: 데이터 볼륨까지 삭제한다
docker compose up -d
```

`-v`는 데이터를 지웁니다. 로컬 개발 데이터뿐이라 지금은 괜찮습니다.
**파일럿 이후에는 이 명령을 쓸 수 없고, 그때부터가 Flyway를 도입한 이유입니다** —
스키마를 고칠 때 볼륨을 날리는 대신 `V2__*.sql`을 추가하면 됩니다.

### 1. DB 띄우기

```bash
docker compose up -d
docker compose logs -f db     # "database system is ready" 뜨면 완료
```

이 단계에서는 **빈 데이터베이스만 생깁니다.** 테이블은 다음 단계에서
Spring이 Flyway로 만듭니다(`api/src/main/resources/db/migration/V1__init.sql`).

접속 정보: `postgresql://alldap:alldap@localhost:5432/alldap`
(포트는 `127.0.0.1`에만 바인딩돼 있어 외부에서 접근할 수 없습니다)

**스키마를 바꿔야 한다면** `V1__init.sql`을 고치지 말고 `V2__설명.sql`을 새로 추가하세요.
이미 적용된 마이그레이션을 수정하면 체크섬이 안 맞아 다음 기동이 실패합니다.

### 2. Spring API 실행 (:8080) — 여기서 테이블이 만들어집니다

```bash
cd api
./gradlew bootRun
```

기동하면서 Flyway가 `V1__init.sql`을 적용해 테이블 9개를 만듭니다.
그다음 Hibernate가 `ddl-auto: validate`로 엔티티와 스키마가 맞는지 검사합니다.
**둘 중 하나라도 실패하면 앱이 뜨지 않습니다** — 이건 버그가 아니라 의도된 안전장치입니다.

확인:

```bash
curl localhost:8080/actuator/health
# → {"status":"UP"}
```

> **현재 `api/`는 뼈대입니다.** 패키지 구조·엔티티·설정·Python 호출 클라이언트까지
> 자리를 잡았고 기동도 검증됐지만, **엔드포인트 내부는 전부 TODO입니다.**
> 스택: Gradle-Groovy / Java 21(Temurin) / Spring Boot **4.0.7** / Gradle 9.5.1 / `com.alldap.api`

`application.yaml`에서 절대 바꾸면 안 되는 것:

```yaml
spring:
  jpa:
    hibernate:
      ddl-auto: validate    # ← update / create 절대 금지. Python 쪽 스키마가 깨진다.
```

### 3. AI 서비스 실행 (:8001)

> 2단계(Spring 기동)를 먼저 하세요. 테이블이 없으면 여기서 실패합니다.

```bash
cd ai-service
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# .env 열어서 OPENAI_API_KEY, ANTHROPIC_API_KEY 채우기

uvicorn app.main:app --reload --port 8001
```

API 문서(자동 생성): http://localhost:8001/docs

#### 동작 확인

```bash
BOT=00000000-0000-0000-0000-000000000001   # 시드로 넣어둔 테스트 봇

curl localhost:8001/health
# → {"status":"ok"}

# 문서 업로드 (202 즉시 응답, 처리는 백그라운드)
curl -F "file=@규정.pdf" localhost:8001/internal/bots/$BOT/documents

# 처리 상태 확인 — status가 ready 될 때까지 (pending → processing → ready | failed)
curl localhost:8001/internal/bots/$BOT/documents

# 질문
curl -X POST localhost:8001/internal/chat \
  -H 'Content-Type: application/json' \
  -d "{\"bot_id\":\"$BOT\",\"message\":\"휴학 신청 기간이 언제야?\"}"
```

### 4. 웹 프론트 실행 (:3000)

> `web/`은 **뼈대만 있는 상태**입니다. 라우트와 타입·API 래퍼는 자리를 잡았지만
> 붙일 백엔드(`api/`)가 아직 없어 화면에는 자리표시자(placeholder)가 보입니다.

```bash
cd web
npm install

cp .env.local.example .env.local
# NEXT_PUBLIC_API_BASE_URL 이 http://localhost:8080 인지 확인

npm run dev        # http://localhost:3000
```

브라우저는 Spring(:8080)만 호출합니다. Python(:8001)을 직접 부르지 않습니다.
Next.js는 API 게이트웨이가 아니며, 인증·권한·`bot_id` 격리는 전부 Spring이 책임집니다.

---

## W1 완료 기준 — ✅ 3개 전부 실측 통과 (2026-07-31)

- [x] 문서 업로드 → 상태가 `ready`로 바뀜
- [x] 질문 → 출처(`sources`)가 포함된 답변이 나옴
- [x] **문서에 없는 질문 10개 → 10개 모두 `is_fallback: true`** (기준: 8개 이상)

세 번째가 가장 중요하다. 환각을 막지 못하면 이 제품은 의미가 없다.

> ⚠️ **10/10은 2차 방어선이 혼자 막아낸 결과다.**
> 환각 억제는 두 겹이다 — 검색 단계 컷오프(`max_distance`)와 생성 단계(`NO_ANSWER`).
> 그런데 **1차인 `max_distance=0.55`는 한 번도 작동하지 않았다.**
> 근거 없는 질문 10개가 전부 청크 1건을 달고 통과했고, `NO_ANSWER`가 10개를 다 막았다.
> 즉 "근거가 없으면 LLM을 아예 호출하지 않는다"는 비용 절감 경로가 열리지 않았다.
>
> 실측 거리는 근거 있는 질문 0.27~0.28, 없는 질문 0.38~0.48로 깔끔히 갈려서 0.33 근처면 작동한다.
> **그럼에도 지금 바꾸지 않는다** — 표본이 청크 1개·질문 7개뿐이라 조정하면 이 문서 하나에 과적합된다.
> 이 값은 W4에서 평가 점수를 근거로 정한다. (`docs/decisions.md`)

아직 검증 안 된 것: **실제 PDF·DOCX 파일 파싱**, 여러 문서·대용량 문서에서의 동작.

---

## Python 내부 API 컨트랙트 (Spring이 호출하는 대상)

W2에서 Spring이 이 규격에 맞춰 호출합니다. JSON 필드는 전부 **snake_case**입니다.

| 메서드 | 경로 | 요청 | 응답 |
|---|---|---|---|
| GET | `/health` | — | `{"status":"ok"}` |
| POST | `/internal/bots/{bot_id}/documents` | multipart, 필드명 **`file`** | `202` + `DocumentOut` |
| GET | `/internal/bots/{bot_id}/documents` | — | `DocumentOut[]` |
| DELETE | `/internal/documents/{doc_id}` | — | `204` |
| POST | `/internal/chat` | `{bot_id, message(1~2000자), session_id(≤64자)}` | `ChatResponse` |

```
DocumentOut  = { id, filename, file_type, status, error_message, char_count, chunk_count }
               status ∈ pending | processing | ready | failed
ChatResponse = { answer, sources[], is_fallback, latency_ms }
Source       = { chunk_id, document_id, filename, score, preview }
               score 는 0~1 (1 - 코사인거리, 높을수록 관련성 높음), preview 는 본문 앞 200자
```

`/internal/eval/*`는 **아직 없습니다.** W3에서 구현합니다.

### ⚠️ 알려진 컨트랙트 갭 — 봇별 설정이 Python까지 전달되지 않는다

`bots` 테이블에는 `system_prompt`와 `fallback_message` 컬럼이 있고 PRD F-06은 봇별 설정을 요구하지만,
현재 `POST /internal/chat`은 **둘 중 어느 것도 받지 않습니다.** 그래서 W2에서는 이렇게 처리합니다.

- `fallback_message` → Spring이 응답의 `is_fallback == true`를 보고 봇의 문구로 **치환**한다. (우회 가능)
- `system_prompt` → **반영할 방법이 없다.** Python의 `/internal/chat` 요청 스키마를 고치기 전까지는 불가능.

숨기지 않고 적어둡니다. 언제 고칠지는 PRD 부록 A에 열린 항목으로 남아 있습니다.

---

## 다음 단계

| 주차 | 할 일 | 상태 |
|---|---|---|
| 0 | W1 첫 실행 검증 + 코드 이해 게이트 4문항 | ✅ 완료 (`docs/W1-이해노트.md`) |
| W1 | Python AI 서비스 (파싱→청킹→임베딩→검색→생성) | ✅ 완료 조건 3개 실측 통과 |
| W2 | Spring Boot API 계층 + Next.js 화면 + 임베드 위젯 | 🚧 **현재 여기** — 인증·봇 CRUD 완료, 나머지 TODO |
| W3 | **품질 대시보드** — 테스트 질문 자동 생성 → LLM-as-judge 채점 → 리포트 | ⬜ |
| W4 | 키워드 검색(형태소+tsvector) + 하이브리드 + 리랭커 → **평가로 before/after 비교** | ⬜ |

W4의 before/after 비교표가 면접에서 쓸 핵심 자산이다.
"리랭커 도입으로 충실성 0.71 → 0.86" 같은 문장을 만드는 게 목표.

---

## 알아둘 것

- 임베딩 모델을 바꾸면 `EMBEDDING_DIM`과 `api/src/main/resources/db/migration/V1__init.sql`의 `VECTOR(1536)`를 **함께** 바꿔야 한다.
  (V1은 수정 금지 — Flyway 체크섬이 깨진다. 새 마이그레이션으로 `ALTER` 할 것)
- **`V1__init.sql`의 "1536 = OpenAI text-embedding-3-small 기준" 주석은 이제 사실이 아니다.**
  실제 제공자는 Google Gemini(`gemini-embedding-001`, 출력 차원 1536 지정)다.
  주석 한 글자만 고쳐도 Flyway 체크섬이 깨져 기동이 막히므로 **일부러 두었다.**
- 구버전 `.hwp`는 바이너리 포맷이라 미지원. 사용자에게 `.hwpx` 저장을 안내한다.
  (Java 쪽 `hwplib`으로 W2에서 붙이는 것도 방법)
- 백그라운드 처리는 FastAPI `BackgroundTasks`라 프로세스가 죽으면 작업이 유실된다.
  트래픽이 붙으면 Redis + RQ로 교체할 것.
- 에러 응답 포맷은 전 계층 공통이다:
  `{ "error": { "code": "...", "message": "무엇을 어떻게 하면 되는지까지 담은 한국어 설명" } }`
- `.env`는 커밋되지 않는다(`.gitignore`). 새 키가 필요해지면 `.env.example`에 항목만 추가할 것.
