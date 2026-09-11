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
 │ Next.js (App Router) :3000                       │  ← 관리자 대시보드 + 공개 페이지 + 위젯 페이지
 │  /dashboard  /bot/[botId]/{documents,chat,       │     (전 화면 브라우저 실측 통과)
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

| 테이블 | 쓰기 | 읽기 | 들어온 마이그레이션 |
|---|---|---|---|
| `users`, `bots` | Spring | Python | V1 (`users.plan` 은 V8) |
| `documents` | **Python** | Spring | V1 |
| `chunks` | **Python** | — | V1 |
| `conversations`, `messages` | Spring | — | V1 |
| `eval_*` | **Python** | Spring | V1 (+V3 이 실행별 분모 컬럼 추가) |
| `doc_conflicts` | **Python** | Spring (Python 경유) | V4 |
| `usage_events` | Spring | — | V5 |
| `billing_methods` | Spring | — | V6 (V7 에서 계정당 여러 장) |

`usage_events` 는 append-only 과금 원장이고, `billing_methods.billing_key_enc` 는
앱에서 AES-256-GCM 으로 암호화한 **암호문**이라 SQL 로 읽어도 쓸 수 없다.
Python 은 이 둘을 건드리지 않는다.

스키마의 단일 진실 공급원은 `api/src/main/resources/db/migration/` 의 Flyway 마이그레이션이다.
Spring의 `ddl-auto`는 반드시 `validate` 또는 `none`.
마이그레이션은 Flyway가 관리하며 **Spring이 기동할 때** 적용됩니다. `V1__init.sql`은 수정 금지 — 변경은 `V2__*.sql`로만. (근거: `docs/decisions.md`)

**왜 나눴나:** AI 파이프라인(문서 파싱·임베딩·평가)은 Python 생태계가 사실상 필수고,
인증·트랜잭션·권한은 Spring이 강하다. 국내에서도 카카오페이(모델은 Python,
서빙은 Kotlin+Spring), 쏘카 등이 같은 구조를 쓴다.

**알려진 약점(숨기지 말 것):**
- 공유 DB는 마이크로서비스 안티패턴이다. 1인 개발에서는 데이터 동기화 비용이 분리 이득보다 커서 택했지만, 팀·트래픽이 커지면 DB를 나누고 API로만 통신해야 한다.
- Spring이 Python을 동기 호출하므로 Python이 죽으면 채팅이 죽는다. 2026-08-17에 `AiServiceClient.call()` 안에 타임아웃·재시도·서킷브레이커를 붙였다. **재시도는 연결 실패에만 한다** (5xx는 Python이 이미 요청을 받았다는 뜻이라, 재시도하면 문서 행이 중복되거나 LLM이 두 번 과금된다).
- 프론트를 Next.js로 분리하면서 **배포 대상이 3개**가 됐다. "운영할 것의 개수를 최소화한다"는 원칙과 충돌하는 선택이며, 풀스택 역량 증명을 위해 알고 택했다. (PRD §11.3)

---

## 디렉터리 구조

```
AllDap/
├── web/           Next.js (App Router): 관리자 대시보드 · 위젯 페이지     ✅ 전 화면 동작 (브라우저 실측)
│   ├── app/(site)/          랜딩 · 인증
│   ├── app/(dashboard)/     봇 목록 · 봇별 화면
│   ├── components/          공통 UI 조각
│   └── lib/{api,types}.ts   Spring API 호출 래퍼 · 응답 타입
├── api/           Spring Boot API (:8080)                             ✅ 인증·봇·문서·채팅·로그·위젯·평가·사용량·결제
│   ├── src/main/java/com/alldap/api/{global,domain}/...
│   └── src/main/resources/db/migration/
│       └── V1__init.sql ~ V8__*.sql   스키마 단일 진실 공급원 (Flyway가 api 기동 시 적용)
├── ai-service/    Python FastAPI AI 서비스 (:8001)                     ✅ W1 완료 조건 실측 통과
│   └── app/{parsers,chunker,retriever,generator,db,config,schemas,main}.py
├── widget/        임베드용 위젯 스크립트 (한 줄 설치)                     ✅ 별도 origin 실제 설치 실측
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

> **✅ 는 실제로 돌려봤다는 뜻입니다.** `web/`과 `widget/`은 2026-08-02에 브라우저로
> 가입 → 봇 생성 → 문서 업로드 → 근거가 붙은 답변 → fallback → 로그 → 별도 origin의
> 가짜 고객 사이트에 위젯 설치까지 한 번에 돌려서 확인했습니다.
> 그 과정에서 **통합 테스트가 전부 초록불인 채로 두 개의 버그가 나왔습니다**
> (새로고침 시 로그아웃, iframe에서 나가는 요청의 Origin이 고객 사이트가 아니라 우리 앱이라
> 위젯 설정 조회가 반드시 403). 자세한 내용은 `AGENTS.md`의 "브라우저 실측" 절에 있습니다.

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
- Node.js 20+

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

기동하면서 Flyway가 `db/migration/`의 마이그레이션을 번호 순서대로 적용해 테이블을 만듭니다.
그다음 Hibernate가 `ddl-auto: validate`로 엔티티와 스키마가 맞는지 검사합니다.
**둘 중 하나라도 실패하면 앱이 뜨지 않습니다** — 이건 버그가 아니라 의도된 안전장치입니다.

확인:

```bash
# 🔴 8080 이 아니라 8081 이다. actuator 는 management 포트로 분리돼 있다
# (api/src/main/resources/application.yaml 의 management.server.port).
# 운영에서는 이 포트를 호스트에 아예 열지 않아 밖에서 부를 수 없다.
curl localhost:8081/actuator/health
# → {"status":"UP"}
```

> **`api/`의 엔드포인트는 전부 구현돼 있습니다.** 인증·봇 CRUD·문서·관리자 채팅·대화 로그·
> 위젯 공개 API·평가·사용량·결제 수단·요금제까지, 진짜 톰캣 + 진짜 PostgreSQL(Testcontainers)
> 위에서 도는 통합 테스트로 검증합니다.
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
# .env 열어서 GOOGLE_API_KEY(질문 생성용) 와
# CF_ACCOUNT_ID · CF_API_TOKEN(임베딩 · 답변 생성 · 채점 · 리랭커) 채우기
# 나머지 값(모델·검색 설정)은 기본값 그대로 두면 됩니다

uvicorn app.main:app --reload --port 8001
```

API 문서(자동 생성): http://localhost:8001/docs

> 🔴 **V1 시드 봇(`pk_local_dev`)을 지우지 마세요.** 이름은 "테스트 봇"이지만 더 이상
> 로컬 전용이 아닙니다. 공개 `/demo` 화면이 `NEXT_PUBLIC_DEMO_PUBLIC_KEY` 미설정 시
> 이 키로 떨어지고(`web/components/DemoConsole.tsx`), `api/`의 통합 테스트도 이 봇이
> 있다고 전제합니다. 시드는 `bots` 한 행뿐이고 `users`는 건드리지 않으므로
> **로그인 가능한 계정은 들어 있지 않습니다.** 근거는 `docs/decisions.md`.

#### 동작 확인

```bash
BOT=00000000-0000-0000-0000-000000000001   # V1 시드 봇 (publicKey: pk_local_dev)

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

> `api`(:8080)가 떠 있어야 화면이 동작합니다. 브라우저는 Spring만 호출하므로,
> Spring이 없으면 로그인부터 막힙니다.

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

> ⚠️ **당시 10/10은 2차 방어선(`NO_ANSWER`)이 혼자 막아낸 결과였다.**
> 환각 억제는 두 겹이다. 검색 단계 컷오프(`max_distance`)와 생성 단계(`NO_ANSWER`).
> 그런데 1차인 `max_distance=0.55`는 거의 작동하지 않아서,
> "근거가 없으면 LLM을 아예 호출하지 않는다"는 비용 절감 경로가 열리지 않았다.
>
> ✅ **2026-09-06에 1차 방어선을 되살렸다. 다만 `max_distance`를 낮춰서가 아니다.**
> 낮추는 쪽은 실측으로 기각됐다. 컷을 낮추면 근거로 쓸 청크가 **함께** 줄어들고,
> 근거가 줄면 답이 틀린다(0.45는 회당 오답 2건, 0.43은 3건). 그래서 살린 방법은
> **판정과 컷을 분리한 것**이다. 한 값이 반대 방향을 원하는 두 일을 겸하고 있었다.
>
> | 역할 | 원하는 값 |
> |---|---|
> | 어떤 청크를 근거로 쓸지 (개수) | **높아야** 한다 → `max_distance = 0.55` 유지 |
> | 근거가 있기는 한가 (판정) | **낮아야** 한다 → `answerable_max_distance = 0.44` 신설 |
>
> 벡터 최근접 거리가 `answerable_max_distance`보다 멀면 근거를 통째로 버리고 LLM을 부르지 않는다.
> 그 결과 **검색컷(LLM 미호출)이 1/10에서 8/10으로 올라갔고**, 평가 문항은 하나도 걸리지 않아
> 전체 충실성·관련성·응답률이 소수점까지 그대로다. "효과가 없다"가 아니라 "부작용이 없다"로 읽어야 한다.
>
> 옛 기록의 "0.33 근처면 작동한다"는 **반증됐다.** 그 숫자는 정답 청크까지의 거리였고,
> 판정에 쓰는 최근접 거리(`d1`)의 최대는 0.4026이라 0.33으로 자르면 멀쩡한 문항이 잘린다.
> 재현: `cd ai-service && .venv/bin/python -m app.answerable_check`
>
> ⚠️ 이 값은 코퍼스와 임베딩 모델에 딸려 있다. 둘 중 하나라도 바뀌면 무효다.

### PDF·DOCX 는 어디까지 확인됐나 (섞어서 말하지 말 것)

축이 다섯이다. **2026-09-11 에 <종단>과 <재현 가능성>이 닫혔고, <대용량> 하나가 열려 있다.**
(여러 문서는 그전부터 닫혀 있었고, 파서 단위는 ✅ 였지만 재현할 수 없는 ✅ 였다)

| 축 | 판정 |
|---|---|
| 파서 단위 (파일 → 텍스트 추출) | ✅ 저장소 안 한글 PDF·DOCX·HWPX 로 확인. **CI 에서 돈다** (그 자산이 못 덮는 것은 아래) |
| 업로드 파이프라인 종단 (→ `status=ready`) | ✅ 세 형식 전부 `ready` 까지. Spring 경유도 봤지만 **자동화는 Python 직행만** |
| 여러 문서에서의 동작 | ✅ 코퍼스 50문서·306청크 |
| **대용량 문서** | ❌ **미검증. 아래 이유로 일부러 안 닫았다** |
| 재현 가능성 | ✅ 자산이 저장소에 있다 |

**닫은 방법.** `ai-service/testdata/fixtures/` 에 한글 PDF(2페이지)·DOCX(본문+표)·
HWPX(`<hp:run>` 3분할 문단)를 넣고 점검 둘을 붙였다.

```
cd ai-service && .venv/bin/python -m app.parsers_check      # 파일 → 텍스트 (DB·외부 API 없음)
cd ai-service && .venv/bin/python -m app.upload_e2e_check   # 업로드 → ready (진짜 DB·진짜 임베딩)
```

- `parsers_check` 15건은 **CI 에서 돈다**(DB 도 외부 API 도 안 쓴다). 이 저장소는 짜둔 검사가
  아무 데서도 안 도는 사고를 두 번 냈다(오픈 리다이렉트, `Forwarded` 점검 명령).
- **파서를 일부러 셋 망가뜨려 점검이 빨간불이 되는 것을 보고 되돌렸다.** HWPX run 병합 제거,
  DOCX 표 순회 제거, PDF 페이지 구분자 제거. 통과하는 검사를 만드는 것과 **실패할 줄 아는**
  검사를 만드는 것은 다른 일이다.
- `upload_e2e_check` 는 `ready` 가 무엇을 뜻하는지까지 본다: `chunk_count` 컬럼만 보지 않고
  DB 의 청크 수·**임베딩이 전부 찼는지**·차원이 `EMBEDDING_DIM` 과 맞는지를 직접 센다.
  그 컬럼은 *INSERT 하려던 개수*고 임베딩이 실제로 들어갔는지는 다른 사실이다.
- 종단은 셋 다 태웠다. **Python `/internal` 직행 · 진짜 uvicorn + 진짜 HTTP · Spring 경유.**
  Spring 경유는 자동화돼 있지 않고 손으로 한 번 돌렸다(`pending → processing → ready` 전이를
  직접 봤다. 한글 파일명과 camelCase 변환도 정상). 자동화하지 않은 이유는 계정·봇을 만들어야
  하는데 `users`·`bots` 쓰기가 Spring 소유이기 때문이다.
- 옛 간접 증거("실제 PDF 51쌍 0 오탐")는 이제 근거로 쓰지 않는다. 직접 본 것이 생겼다.

🔴 **대용량 문서는 ❌ 그대로다. 못 한 것이 아니라 안 한 것이다.**
fixture 는 수 KB 라 pymupdf 가 PDF 를 통째로 메모리에 올리는 문제(운영 1GB 인스턴스 OOM)의
구간에 아예 못 간다. 거길 재려면 **수십 MB PDF 를 저장소에 커밋해야 하는데 그건 재현 자산이
아니라 짐이다.** 메모리 프로파일이 필요한 별도 슬라이스다. 지금 그 구간을 피해 가는 방법은
업로드 상한을 환경변수로 빼둔 것뿐이다(`docs/DEPLOY.md`).

⚠️ **위 ✅ 가 덮지 않는 것 셋.** 적어두지 않으면 ✅ 가 실제보다 넓게 읽힌다.

- **줄바꿈된 PDF 는 검증되지 않는다.** pymupdf 의 `insert_text` 는 줄바꿈을 하지 않고 넘치면
  조용히 자르므로, fixture 는 각 줄을 페이지 폭 안에 맞춰 만들었다(생성기가 폭 초과를 빌드
  시점에 막는다). **실제 PDF 는 문단이 여러 줄로 접혀 오고 추출 결과도 그 줄바꿈을 갖는다.**
- **fixture PDF 는 "한글·워드가 만든 PDF" 가 아니다.** pymupdf 내장 CJK 폰트로 우리가 만든
  것이라, 그 도구들이 내는 글리프 매핑·CID 인코딩 변종은 못 잡는다(외부 폰트를 저장소에 넣지
  않으려고 택했다).
- **fixture HWPX 는 최소 골격이다.** `Contents/section*.xml` 의 `<hp:p>`·`<hp:t>` 만 갖췄다.
  파서가 읽는 것이 정확히 그 둘뿐이라 파서 관점에서는 충분하지만 "진짜 한글 파일" 은 아니다.

**"안 나빠졌다" 와 "재보지 않았다" 는 다르다.** 대용량 축이 후자다.

---

## Python 내부 API 컨트랙트 (Spring이 호출하는 대상)

Spring이 이 규격에 맞춰 호출합니다. JSON 필드는 전부 **snake_case**입니다.
(프론트가 보는 camelCase 로의 변환은 Spring 이 DTO 로 받아서 합니다. Python 응답을 그대로 흘려보내지 않습니다)

| 메서드 | 경로 | 요청 | 응답 |
|---|---|---|---|
| GET | `/health` | — | `{"status":"ok"}` |
| POST | `/internal/bots/{bot_id}/documents` | multipart, 필드명 **`file`** | `202` + `DocumentOut` |
| GET | `/internal/bots/{bot_id}/documents` | — | `DocumentOut[]` |
| DELETE | `/internal/bots/{bot_id}/documents/{doc_id}` | — | `204` |
| POST | `/internal/chat` | `{bot_id, message(1~2000자), session_id(≤64자)}` | `ChatResponse` |

```
DocumentOut  = { id, filename, file_type, status, error_message, char_count, chunk_count }
               status ∈ pending | processing | ready | failed
ChatResponse = { answer, sources[], is_fallback, latency_ms }
Source       = { chunk_id, document_id, filename, score, preview }
               score 는 0~1 (1 - 코사인거리, 높을수록 관련성 높음), preview 는 본문 앞 200자
```

평가(W3)와 문서 충돌 스캔도 같은 규칙으로 열려 있습니다.

| 메서드 | 경로 | 하는 일 |
|---|---|---|
| POST | `/internal/bots/{bot_id}/eval/questions/generate` | 청크 표본에서 (질문, 정답) 쌍 생성 (동기 200, 재호출은 누적) |
| GET · PATCH | `/internal/bots/{bot_id}/eval/questions[/{id}]` | 테스트 질문 목록 · 부분 수정 |
| POST · GET | `/internal/bots/{bot_id}/eval/runs` | 평가 실행 (202 + 폴링) · 실행 이력 |
| POST · GET · PATCH | `/internal/bots/{bot_id}/conflicts[/scan\|/{id}]` | 문서끼리 어긋나는 곳 스캔 · 목록 · 오탐 치우기 |

정확한 요청·응답 스키마는 `ai-service/app/schemas.py`와 자동 생성 문서(`/docs`)를 보세요.
README에 전부 옮겨 적으면 반드시 어긋납니다.

### 봇별 설정(`system_prompt` · `fallback_message`)은 이 요청에 실리지 않는다

`POST /internal/chat`은 **둘 중 어느 것도 받지 않습니다.** 이건 지금도 사실입니다.
그런데 **둘 다 실제로 반영됩니다.** 반영 경로가 서로 다를 뿐입니다.

- `fallback_message` → Spring이 응답의 `is_fallback == true`를 보고 봇의 문구로 **치환**한다.
  (`ChatService.resolveAnswer`. Python은 봇별 문구를 모른다)
- `system_prompt` → **Python이 `bots` 테이블에서 직접 읽는다.** (2026-08-13부터, PRD F-06 충족)
  `ai-service/app/generator.py`의 `fetch_bot_prompt` + `build_system_prompt`.

**왜 Spring이 실어 보내지 않고 Python이 직접 읽는가.** 성능이 아니라 **평가** 때문입니다.
`evalrun`은 Spring을 거치지 않으므로, Spring이 실어 보내는 방식이면 평가만 기본 프롬프트로 돌아
"평가에서는 좋았는데 실사용은 다르다"가 됩니다. 부수 효과로 Spring은 한 줄도 고치지 않았습니다.
→ **`AiChatRequest`에 `system_prompt` 필드를 추가하지 마세요.** 경로가 둘이 되면 어느 쪽이
이겼는지 알 수 없어지고, 평가와 실사용이 다시 갈라집니다.

⚠️ **한계: 봇 지침으로 `NO_ANSWER` 규칙을 뚫을 수 있다는 것이 실측됐습니다.** 결합은 대체가
아니라 덧붙임이고("충돌하면 봇 지침이 우선") 기본 규칙을 앞에 두지만, 프롬프트로 프롬프트를
막는 데는 한계가 있습니다. 막지 못하니 대신 **잽니다**: `.venv/bin/python -m app.bot_prompt_check`.
봇 지침을 설정하거나 바꾼 뒤 이걸 돌려 깨지는지 보세요.

---

## 다음 단계

| 주차 | 할 일 | 상태 |
|---|---|---|
| 0 | W1 첫 실행 검증 + 코드 이해 게이트 4문항 | ✅ 완료 (`docs/W1-이해노트.md`) |
| W1 | Python AI 서비스 (파싱→청킹→임베딩→검색→생성) | ✅ 완료 조건 3개 실측 통과 |
| W2 | Spring Boot API 계층 + Next.js 화면 + 임베드 위젯 | ✅ 완료 (브라우저 · 위젯 실제 설치까지 실측) |
| W3 | **품질 대시보드**: 테스트 질문 자동 생성 → LLM-as-judge 채점 → 리포트 | ✅ 완료 |
| W4 | 하이브리드 검색 + 리랭커 → **평가로 before/after 비교** | ✅ 완료 (2026-08-13) |

**W4 결과 (같은 16문항 · 50문서 · 306청크 · 같은 모델 · `temperature=0` · 설정당 3회 이상)**

| 설정 | 전체 충실성 | 회당 오답 | 회당 완전오답 | 채팅 지연 |
|---|---|---|---|---|
| 벡터만 (before) | 0.781 | 1.75 | 1.00 | 0.67초 |
| 리랭커 + 하이브리드 (after, 현재 기본값) | **0.875** | **0.00** | **0.00** | 1.56초 |

🔴 **결정적 근거는 평균이 아니라 오답이다.** fallback 개수는 네 설정 모두 2로 같다.
즉 켠다고 "못 답하는 질문"이 느는 게 아니라, fallback의 **내용물**이 바뀌면서
**자신 있게 틀린 답이 사라진다.** fallback은 안전한 실패("담당자에게 문의하세요")지만
오답은 사용자가 잘못된 정보를 신뢰하게 만든다. 이 제품이 존재하는 이유가 그것이다.

그리고 면접에서 더 강한 재료는 수치 자체가 아니라 **측정을 믿을 수 있게 만든 과정**이다.
올랐다고 생각한 것이 생존 편향이었고, 채점자가 근거의 앞 200자만 보고 있었고,
진짜 병목은 검색 알고리즘이 아니라 청킹이었다. 자세한 기록은 `AGENTS.md`에 있다.

배포는 2026-09-07에 끝났다(EC2 + RDS + Vercel). 절차와 함정은 `docs/DEPLOY.md`.

---

## 알아둘 것

- 임베딩 모델을 바꾸면 `EMBEDDING_DIM`과 마이그레이션의 `VECTOR(n)`을 **함께** 바꿔야 한다.
  (V1은 수정 금지. Flyway 체크섬이 깨진다. 새 마이그레이션으로 `ALTER` 할 것.
  `V2__embedding_1024.sql`이 그 예다)
  순서도 중요하다: 인덱스 드롭 → `UPDATE chunks SET embedding = NULL` → `ALTER ... TYPE VECTOR(n)`
  → 인덱스 재생성 → 재임베딩(`.venv/bin/python -m app.reembed`).
  데이터가 있는 채로 `ALTER` 하면 실패한다.
- 🔴 **`V1__init.sql`의 "1536 = OpenAI text-embedding-3-small 기준" 주석은 사실이 아니고, 차원도 1536이 아니다.**
  현재 임베딩은 **Cloudflare Workers AI `@cf/baai/bge-m3`(1024차원)**이고, V2에서 차원을 바꿨다.
  주석 한 글자만 고쳐도 Flyway 체크섬이 깨져 기동이 막히므로 **일부러 두었다.** 이 줄이 그 정정본이다.
- ⚠️ **임베딩과 생성의 제공자가 다르다.** 임베딩·답변 생성·채점·리랭커는 Cloudflare,
  테스트 질문 생성만 Google Gemini다. 한쪽만 보고 "Cloudflare로 옮겼다"고 말하면 안 된다.
  임베딩을 옮긴 이유는 성능이 아니라 **약관과 한도**다. Gemini 무료 등급은 입력을 학습에 쓰는데,
  이 제품은 고객 사내 문서를 받는 것이 목적이다.
- 구버전 `.hwp`는 바이너리 포맷이라 미지원. 사용자에게 `.hwpx` 저장을 안내한다.
  (Java 쪽 `hwplib`으로 붙이는 것도 방법이지만 아직 안 했다)
- 백그라운드 처리는 FastAPI `BackgroundTasks`라 프로세스가 죽으면 작업이 유실된다.
  트래픽이 붙으면 Redis + RQ로 교체할 것.
- 에러 응답 포맷은 전 계층 공통이다:
  `{ "error": { "code": "...", "message": "무엇을 어떻게 하면 되는지까지 담은 한국어 설명" } }`
- `.env`는 커밋되지 않는다(`.gitignore`). 새 키가 필요해지면 `.env.example`에 항목만 추가할 것.
