# 로컬 실행 가이드

> README 에 있던 "실행 방법" 절을 옮겨온 문서입니다.
> 저장소 개요와 아키텍처는 [`../README.md`](../README.md) 를 보세요.

의존 순서대로 **db → api → ai-service → web** 으로 올립니다.
아래로 갈수록 위의 것이 떠 있어야 동작합니다.

> ⚠️ **`api`가 `ai-service`보다 먼저입니다.** 2026-07-31에 스키마를 Flyway로 옮기면서
> 순서가 바뀌었습니다. 예전에는 컨테이너만 띄우면 테이블이 생겼지만, 이제는
> **Spring이 한 번 기동해야 테이블이 만들어집니다.** Python을 먼저 띄우면 테이블이 없어 실패합니다.

## 0. 사전 준비

- Docker Desktop
- Python 3.11+
- JDK 21
- Node.js 20+

## ⚠️ 예전 볼륨이 남아 있다면 첫 기동이 막힙니다

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
**파일럿 이후에는 이 명령을 쓸 수 없고, 그때부터가 Flyway를 도입한 이유입니다.**
스키마를 고칠 때 볼륨을 날리는 대신 `V2__*.sql`을 추가하면 됩니다.

## 1. DB 띄우기

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

## 2. Spring API 실행 (:8080): 여기서 테이블이 만들어집니다

```bash
cd api
./gradlew bootRun
```

기동하면서 Flyway가 `db/migration/`의 마이그레이션을 번호 순서대로 적용해 테이블을 만듭니다.
그다음 Hibernate가 `ddl-auto: validate`로 엔티티와 스키마가 맞는지 검사합니다.
**둘 중 하나라도 실패하면 앱이 뜨지 않습니다.** 이건 버그가 아니라 의도된 안전장치입니다.

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

API 문서(springdoc)는 **로컬에서만 열립니다.** 운영에서는 경로 차단과 생성 차단 두 겹으로 막습니다.

`application.yaml`에서 절대 바꾸면 안 되는 것:

```yaml
spring:
  jpa:
    hibernate:
      ddl-auto: validate    # ← update / create 절대 금지. Python 쪽 스키마가 깨진다.
```

## 3. AI 서비스 실행 (:8001)

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
> **로그인 가능한 계정은 들어 있지 않습니다.** 근거는 [`decisions.md`](decisions.md).

### 동작 확인

```bash
BOT=00000000-0000-0000-0000-000000000001   # V1 시드 봇 (publicKey: pk_local_dev)

curl localhost:8001/health
# → {"status":"ok"}

# 문서 업로드 (202 즉시 응답, 처리는 백그라운드)
curl -F "file=@규정.pdf" localhost:8001/internal/bots/$BOT/documents

# 처리 상태 확인. status가 ready 될 때까지 (pending → processing → ready | failed)
curl localhost:8001/internal/bots/$BOT/documents

# 질문
curl -X POST localhost:8001/internal/chat \
  -H 'Content-Type: application/json' \
  -d "{\"bot_id\":\"$BOT\",\"message\":\"휴학 신청 기간이 언제야?\"}"
```

## 4. 웹 프론트 실행 (:3000)

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

## 밀기 전에 돌릴 검사

PR 이 없으면 CI 는 민 뒤에 돕니다. 깨진 것이 곧바로 `main` 에 올라갑니다.

```bash
cd web && npx tsc --noEmit && npm run lint
cd api && ./gradlew test
cd ai-service && .venv/bin/python -m app.parsers_check     # 파서 (DB·외부 API 없음)
cd ai-service && .venv/bin/python -m app.retriever_check   # 하이브리드 검색 자체 점검
```

## 운영 배포

절차와 그 과정에서 밟은 함정은 [`DEPLOY.md`](DEPLOY.md) 에 있습니다.
