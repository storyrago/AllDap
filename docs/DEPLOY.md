# 배포 (AWS 프리티어)

프론트는 **Vercel**, 앱은 **EC2 t3.micro 한 대**, DB 는 **RDS(Postgres 16 + pgvector)**.

```
[Vercel]  web  ──HTTPS──┐
                         ▼
[EC2 t3.micro 1GB]  Caddy :80/:443  ← Let's Encrypt 자동
                      ├── api (Spring)   ← 바깥에 노출되는 유일한 서비스
                      └── ai-service     ← 포트를 아예 안 연다
                             │ 같은 VPC
                             ▼
[RDS db.t3.micro]  Postgres 16 + pgvector   ← 퍼블릭 액세스 비활성
```

---

## 📋 진행 체크리스트

각 단계에 **확인법**이 붙어 있다. 중간에 끊겨도 확인법을 위에서부터 돌려보면
어디까지 됐는지 알 수 있다. 상세는 아래 각 절을 볼 것.

| # | 할 일 | 됐는지 확인 |
|---|---|---|
| 0 | PR 머지 → Actions 초록불 → GHCR 패키지 public 전환 | GitHub → Packages 에 `api`·`ai-service` 가 보인다 |
| 1 | **RDS 생성** (PostgreSQL 16, `db.t3.micro`, 퍼블릭 액세스 **끔**, 초기 DB `alldap`) | 콘솔에 "사용 가능", 엔드포인트 주소가 나온다 |
| 2 | **EC2 생성** (Ubuntu 24.04 **x86_64**, `t3.micro`) + **탄력적 IP 할당** | `ssh -i key.pem ubuntu@<탄력적IP>` 접속됨 |
| 3 | **보안 그룹**: EC2 ← 22(내 IP)·80·443 / RDS ← 5432(**EC2 의 SG**) | 4번에서 드러난다 |
| 4 | **swap 2GB** + **Docker 설치** | `free -h` 에 Swap 2.0Gi · `docker ps` 됨 |
| 5 | EC2 에서 **RDS 연결 확인** | `nc -zv <RDS엔드포인트> 5432` → succeeded |
| 6 | **DuckDNS** 서브도메인 → 탄력적 IP | `dig +short <도메인>` 이 탄력적 IP 를 뱉음 |
| 7 | `git clone` → `.env.prod` 채우기 | `DB_HOST`·`JWT_SECRET`·`CF_*` 가 비어 있지 않음 |
| 8 | **`docker compose … up -d`** | `docker compose … ps` 에서 api 가 `healthy` (2~3분 걸림) |
| 9 | **HTTPS 확인** | `curl https://<도메인>/actuator/health` → `{"status":"UP"}` |
| 10 | 🔴 **격리 확인** | `curl http://<탄력적IP>:8001/health` → **연결 실패해야 정상** |
| 11 | **Vercel** 배포 (Root `web`, `NEXT_PUBLIC_API_BASE_URL`) | Vercel 주소로 로그인 화면이 뜸 |
| 12 | `CORS_ALLOWED_ORIGINS` 에 Vercel 주소 넣고 api 재시작 | 브라우저에서 가입이 됨 |
| 13 | **종단 테스트** — 문서 업로드 → 채팅 → 내보내기 → 다른 사이트에 설치 | 남의 사이트에서 근거 붙은 답변이 나옴 |

**막혔을 때 먼저 볼 곳**

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod ps       # 누가 안 떴나
docker compose -f docker-compose.prod.yml --env-file .env.prod logs api # 왜 안 떴나
free -h                                                                  # 메모리가 말랐나
```

Spring 이 기동 실패하면 **로그 첫 줄에 무엇이 빠졌는지 나온다**(fail-closed).
Python 도 마찬가지다 — 빠진 환경변수 이름을 대며 죽는다.

---

## 왜 이 구조인가

**🔴 배포의 1순위 제약은 Python 을 인터넷에서 보이지 않게 하는 것이다.**
`/internal/*` 에는 인증이 **전혀** 없다. 포트가 하나라도 열리면 publicKey 도 JWT 도 없이
누구나 남의 봇 문서와 청크를 읽는다.

`docker-compose.prod.yml` 에서 **`ports:` 를 여는 서비스는 caddy 하나뿐**이다.
방화벽 규칙으로 "막는" 게 아니라 **애초에 호스트에 뜨지 않게** 한다 —
규칙은 잊거나 실수로 지울 수 있지만, 안 열린 포트는 실수할 여지가 없다.

**DB 를 RDS 로 뺀 이유는 메모리다.** t3.micro 는 1GB 인데 우리 스택을 다 합치면 넘는다.
Postgres 를 빼면 약 120MB 가 살아나 여유가 생긴다. 자동 백업·스냅샷은 덤이다.

**이미지를 CI 에서 만드는 이유도 메모리다.** 1GB 에서 Gradle 컴파일은 OOM 이다.
GitHub Actions 가 GHCR 에 올리고 서버는 `pull` 만 한다. 서버에 JDK·Gradle 을 둘 필요가
없어졌고, 배포가 몇 초로 줄었으며, `IMAGE_TAG` 를 이전 SHA 로 바꾸면 즉시 롤백된다.

**HTTPS 는 선택이 아니다.** 관리자 화면이 Vercel(HTTPS)에 있어서, HTTP API 를 부르면
브라우저가 mixed content 로 차단한다. 로컬에서는 둘 다 http 라 안 겪는 문제다.

---

## 1. 비용

| | 프리티어 | 이후 |
|---|---|---|
| EC2 t3.micro | 750h/월 · 12개월 | 약 $8/월 |
| RDS db.t3.micro | 750h/월 · 20GB · 12개월 | 약 $15/월 |
| Vercel · DuckDNS · GHCR | 계속 무료 | — |

⚠️ **EC2 와 RDS 는 같은 12개월 창을 쓴다.** 계정이 2025-07-15 이후면 이 프리티어가
아예 없다(크레딧 $100~200 / 6개월로 바뀌었다). 콘솔 → Billing → Free Tier 에서 확인할 것.

## 2. RDS 먼저 만든다

앱보다 DB 가 먼저 있어야 한다.

- **엔진**: PostgreSQL 16
- **템플릿**: 프리 티어
- **인스턴스**: `db.t3.micro` · 스토리지 20GB gp2 · 스토리지 자동 확장 **끔**(과금 방지)
- **퍼블릭 액세스**: **아니요** ← 중요
- **AZ**: EC2 와 **같은 AZ** (다른 AZ 면 데이터 전송에 과금된다)
- **초기 데이터베이스 이름**: `alldap` (안 적으면 DB 가 안 만들어진다)
- 마스터 사용자/비밀번호를 `.env.prod` 의 `DB_USERNAME`/`DB_PASSWORD` 에 넣는다

> **pgvector 는 RDS 에서 지원된다**(PostgreSQL 15.2+). `V1__init.sql` 의
> `CREATE EXTENSION IF NOT EXISTS vector;` 를 마스터 사용자(`rds_superuser`)가
> 그대로 실행할 수 있다. 따로 할 일은 없다.

## 3. EC2

- **AMI**: Ubuntu 24.04 LTS (**x86_64** — t3 는 Intel/AMD 다)
- **타입**: `t3.micro`
- **스토리지**: 16~20GB gp3 (프리티어 30GB 한도)
- **키 페어**: 만들고 `.pem` 을 저장. `chmod 400`
- **탄력적 IP 할당** — 재부팅으로 IP 가 바뀌면 DuckDNS·인증서가 전부 어긋난다

### 보안 그룹 — 여기가 격리의 핵심이다

| 대상 | 인바운드 | 소스 |
|---|---|---|
| EC2 SG | 22 (SSH) | **내 IP만** |
| EC2 SG | 80, 443 | 0.0.0.0/0 |
| **RDS SG** | 5432 | **EC2 의 보안 그룹** (IP 가 아니라 SG 를 지정) |

RDS 인바운드에 `0.0.0.0/0` 을 넣지 말 것. SG 를 소스로 지정하면 EC2 IP 가 바뀌어도 계속 맞는다.

> AWS 의 Ubuntu AMI 는 OS 방화벽이 기본으로 열려 있다. 보안 그룹만 맞추면 된다.

### swap — 1GB 에서는 필수다

없으면 문서 업로드 한 번에 OOM killer 가 돌고, **누구를 죽일지는 커널이 정한다.**

```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -h   # Swap 2.0Gi 확인
```

### Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER   # 다시 로그인해야 적용된다
```

## 4. DuckDNS

1. https://www.duckdns.org 에서 서브도메인 생성 (예: `alldap`)
2. **탄력적 IP** 를 등록
3. `dig +short alldap.duckdns.org` 가 그 IP 를 뱉는지 확인.
   **이게 맞아야 Let's Encrypt 인증서가 나온다** — 발급 과정에서 그 주소로 실제 접속해 확인한다.

## 5. 이미지 준비

`main` 에 푸시되면 `.github/workflows/publish.yml` 이 두 이미지를 GHCR 에 올린다.
Actions 탭에서 초록불인지 확인할 것.

GHCR 패키지는 기본이 **private** 이다. 둘 중 하나를 택한다.

- **패키지를 public 으로 전환** (GitHub → Packages → 각 패키지 → Change visibility)
  → 서버에서 로그인 없이 `pull` 된다. 가장 단순하다
- **또는 서버에서 로그인** — `read:packages` 권한만 준 PAT 를 만들어
  ```bash
  echo <PAT> | docker login ghcr.io -u <github-id> --password-stdin
  ```

## 6. 배포

```bash
git clone https://github.com/storyrago/AllDap.git && cd AllDap
cp .env.prod.example .env.prod
vi .env.prod          # DB_HOST(RDS 엔드포인트)·비밀번호·API 키 채우기

docker compose -f docker-compose.prod.yml --env-file .env.prod up -d
```

**기동 순서는 compose 가 강제한다**: `api(healthy) → ai-service`.
스키마는 Spring 이 뜨면서 Flyway 로 만들기 때문에 **Python 이 먼저 뜨면 안 된다.**

t3.micro 는 느려서 Spring 기동에 2~3분 걸릴 수 있다(`start_period: 180s`).

## 7. Vercel (프론트)

- **Root Directory**: `web`
- **환경변수**: `NEXT_PUBLIC_API_BASE_URL=https://alldap.duckdns.org`
- 배포 후 그 주소를 `.env.prod` 의 `CORS_ALLOWED_ORIGINS` 에 넣고 api 를 재시작한다.

> ⚠️ Vercel 은 브랜치마다 **프리뷰 도메인**을 만든다. 프리뷰에서도 API 를 쓰려면
> 그 도메인도 `CORS_ALLOWED_ORIGINS` 에 넣어야 한다(쉼표 구분).

## 8. 배포 후 확인 — 순서대로

```bash
# ① Spring 이 밖에서 보이는가
curl -s https://alldap.duckdns.org/actuator/health        # {"status":"UP"}

# ② 위젯 JS 가 나오는가 (설치 코드가 이 주소를 가리킨다)
curl -sI https://alldap.duckdns.org/widget/alldap-widget.js | head -1

# 🔴 ③ Python 이 <안 보이는가> — 가장 중요한 확인
curl -s -m 5 http://<탄력적IP>:8001/health                # 연결 실패해야 정상
curl -s -m 5 http://<탄력적IP>:8080/actuator/health       # 연결 실패해야 정상

# ④ RDS 도 밖에서 안 보이는가 (로컬 노트북에서)
nc -zv <RDS엔드포인트> 5432                                # 실패해야 정상

# ⑤ 내부에서는 되는가
docker compose -f docker-compose.prod.yml exec api curl -s http://ai-service:8001/health

# ⑥ 메모리 여유 (1GB 라 눈으로 봐둘 것)
free -h && docker stats --no-stream
```

그다음 **브라우저로**: 가입 → 봇 생성 → 문서 업로드(`ready` 까지) → 테스트 채팅 →
내보내기에서 스니펫 복사 → 아무 정적 사이트에 붙여 실제 대화.

⚠️ **내보내기 스니펫의 도메인이 배포 주소인지 반드시 눈으로 확인할 것.**
`src` 는 `NEXT_PUBLIC_API_BASE_URL`, `data-app-base` 는 Vercel 주소가 나와야 한다.

## 9. 운영

**갱신 배포는 아래 순서를 반드시 지킬 것.** ⚠️ `pull` → `up -d` 두 줄만 돌리고 끝내지 말 것 —
`Caddyfile` 은 3번에서 `up -d` 로는 갱신되지 않는다(아래 4번 참고).

```bash
# 1. git pull — Caddyfile 은 bind mount(docker-compose.prod.yml:94, `./Caddyfile:/etc/caddy/Caddyfile:ro`)라
#    이미지 안이 아니라 서버 디스크의 파일을 그대로 읽는다. 서버에 새 Caddyfile 이 없으면
#    아래 어떤 명령을 돌려도 옛 설정 그대로다.
git pull

# 2. 이미지 갱신
docker compose -f docker-compose.prod.yml --env-file .env.prod pull

# 3. api·ai-service 갱신 — 이 둘은 반드시 같이 올린다.
#    문서 삭제 경로가 /internal/documents/{id} → /internal/bots/{botId}/documents/{docId} 로 바뀌었다.
#    ai-service 가 api 의 healthcheck 를 기다리는 동안(depends_on: condition: service_healthy)
#    그 사이에 들어온 삭제 요청은 502 AI_SERVICE_ERROR 로 실패할 수 있다 — 데이터는 안 없어지고,
#    이 4xx 는 서킷브레이커 실패로도 안 세므로(의도된 설계) 서킷이 열리지도 않는다. 재시도하면 된다.
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d

# 4. 🔴 Caddy 강제 재생성 — 별도 단계다. 절대 건너뛰지 말 것.
#    bind mount 는 "파일 내용이 바뀌었다"를 Compose 의 재생성 트리거로 보지 않는다.
#    Compose 는 이미지 다이제스트나 서비스 정의가 바뀔 때만 컨테이너를 다시 만드는데,
#    caddy:2-alpine 은 태그가 고정 버전이 아니라 그때그때 다른 이미지를 가리킬 수 있어
#    3번의 pull 이 우연히 새 이미지를 받아오면 재생성되고, 안 받아오면 재생성되지 않는다 —
#    즉 이 단계를 생략하면 Caddyfile 갱신이 "가끔 되고 가끔 안 된다." 겉으로는 항상 성공한 것처럼 보인다.
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --force-recreate caddy

# 롤백 — .env.prod 의 IMAGE_TAG 를 이전 커밋 SHA 로 바꾸고 위를 다시
docker compose -f docker-compose.prod.yml --env-file .env.prod logs -f api

# DB 백업은 RDS 자동 스냅샷이 맡는다. 수동 덤프가 필요하면
docker compose -f docker-compose.prod.yml exec -T api sh -c 'apt-get install -y postgresql-client' # 또는 로컬에서
```

### rate limit 종단 확인 (4번 이후 매번 할 것)

`Forwarded` 헤더 제거는 자동 테스트로 검증할 수 없다 — 진짜 Caddy 를 거쳐야만 재현되는
문제이기 때문이다. 배포마다 직접 확인한다. `$API_DOMAIN` 은 실제 배포 도메인,
`<publicKey>` 는 아무 봇의 공개 위젯 키로 바꿔서 돌릴 것.

```bash
for i in $(seq 1 25); do
  curl -s -o /dev/null -w "%{http_code}\n" \
    -X POST "https://$API_DOMAIN/api/w/<publicKey>/chat" \
    -H "Content-Type: application/json" \
    -H "Forwarded: for=203.0.113.$i" \
    -d '{"message":"test"}'
done
```

25번 중 뒤쪽에서 `429` 가 나와야 정상이다. **25개가 전부 `200`(또는 동일 코드)이면
4번(`--force-recreate caddy`)이 이번 배포에 실제로 적용되지 않은 것이다** — 컨테이너가
재생성됐는지(`docker compose ps` 의 `caddy` 생성 시각)부터 다시 확인할 것.

## 알려진 구멍 (배포 후 처리)

- **1GB 는 여유가 없다.** 문서 업로드 시 pymupdf 가 파일을 통째로 메모리에 올린다.
  `.env.prod` 의 `UPLOAD_MAX_SIZE`/`UPLOAD_MAX_BYTES` 를 10MB 로 낮춰뒀지만,
  큰 PDF 가 몰리면 여전히 위험하다. `docker stats` 로 지켜볼 것.
- **rate limit 이 인메모리다.** 인스턴스를 늘리면 각자 세므로 실질 한도가 배가 된다.
  수평 확장 시작 시점이 Redis 교체 시점이다.
- **백그라운드 문서 처리가 FastAPI `BackgroundTasks` 다.** 컨테이너를 재시작하면
  처리 중이던 업로드가 `pending` 에 갇힌다.
- **테스트 질문 생성이 Gemini 무료 등급을 쓴다.** 약관상 입력을 학습에 쓴다 —
  실제 고객 문서를 받기 전에 정리할 것.
- **프리티어 12개월이 끝나면 월 $23 쯤 나간다.** 만료 전에 정리하거나 옮길 것.
