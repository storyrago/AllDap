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
| 7 | `git clone` → `.env.prod` 채우기 | `DB_HOST`·`JWT_SECRET`·`CF_*`·`BILLING_CRYPTO_KEY`·`TOSS_SECRET_KEY` 가 비어 있지 않음 |
| 8 | **`docker compose … up -d`** | `docker compose … ps` 에서 api 가 `healthy` (2~3분 걸림) |
| 9 | **HTTPS 확인** | `curl https://<도메인>/actuator/health` → `{"status":"UP"}` |
| 10 | 🔴 **격리 확인** | `curl http://<탄력적IP>:8001/health` → **연결 실패해야 정상** |
| 11 | **Vercel** 배포 (Root `web`, `NEXT_PUBLIC_API_BASE_URL`, `NEXT_PUBLIC_TOSS_CLIENT_KEY`) | Vercel 주소로 로그인 화면이 뜸 |
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

**순서는 사실 상관없다** — EC2 를 먼저 만들어도 된다. 실질 제약은 **AZ 하나**이고,
먼저 만든 쪽의 AZ 에 나중 것을 맞추면 된다.

> 🔴 **"데이터베이스 생성" 을 누르면 함정이 둘 겹쳐 있다. 2026-09-07 에 실제로 걸렸다.**
> ① 생성 방식에서 **"전체 구성"** 을 고를 것(콘솔이 라벨을 바꿨다 — 옛 "표준 생성"이 지금 **전체 구성**,
>    옛 "손쉬운 생성"이 **빠른 구성**이다). "빠른 구성"은 **Aurora Serverless v2** 를 만든다.
> ② **전체 구성으로 가도 엔진 옵션의 기본 선택이 `Aurora (PostgreSQL Compatible)` 다.**
>    한 칸 더 내려가 **그냥 `PostgreSQL`** 을 눌러야 한다. 둘이 나란히 있다.
>
> **리트머스 시험지: 템플릿에 "프리 티어" 가 보이는가.** Aurora 에는 그 항목이 없다.
> 안 보이면 Aurora 쪽에 와 있는 것이니 뒤로 갈 것.

- **엔진**: PostgreSQL 16
- **템플릿**: 프리 티어
- **인스턴스**: `db.t3.micro` · 스토리지 20GB gp2 · 스토리지 자동 확장 **끔**(과금 방지)
- **퍼블릭 액세스**: **아니요** ← 중요
- **AZ**: EC2 와 **같은 AZ** (다른 AZ 면 데이터 전송에 과금된다)
- **초기 데이터베이스 이름**: `alldap` — **"추가 구성" 안에 접혀 있다.** 🔴 안 적으면 DB 가
  만들어지지 않고, 증상은 여기가 아니라 **Spring 기동 실패**로 나타난다(`FlywaySqlUnableToConnectToDbException:
  database "alldap" does not exist`). 접속·인증은 성공한 뒤 나는 오류라 SG 나 비밀번호를 의심하게 된다.
  이미 만들어버렸으면 인스턴스를 다시 만들 필요 없다 — EC2 에서 `postgres` DB 로 붙어 만들면 된다:
  ```bash
  sudo apt-get install -y postgresql-client
  psql -h $(grep -m1 '^DB_HOST=' .env.prod | cut -d= -f2) \
       -U $(grep -m1 '^DB_USERNAME=' .env.prod | cut -d= -f2) \
       -d postgres -c 'CREATE DATABASE alldap;'
  ```
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

> ⚠️ **RDS 생성 마법사가 만든 새 SG 에는 <네 노트북 IP> 가 인바운드로 들어간다.** 그대로 두면
> EC2 에서 `nc -zv <엔드포인트> 5432` 가 타임아웃난다. 그런데 **그 규칙 행을 고쳐서 SG 참조로
> 바꿀 수 없다** — `기존 IPv4 CIDR 규칙에 참조된 그룹 ID를 지정할 수 없습니다` 로 거부된다.
> **행을 삭제하고 "규칙 추가" 로 새로 만들어야 한다.**

> ⚠️ **탄력적 IP 는 재활용된다.** 예전에 그 IP 를 쓰던 서버의 키가 `~/.ssh/known_hosts` 에
> 남아 있으면 첫 SSH 가 `REMOTE HOST IDENTIFICATION HAS CHANGED` 로 막힌다.
> 방금 만든 인스턴스라면 정상이다 — `ssh-keygen -R <탄력적IP>` 로 옛 키를 지우면 된다.

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

### 결제 수단(토스) 환경변수 — 2026-09-06 추가

`.env.prod` 에 두 개가 더 필요하다. **다만 비었을 때 동작이 서로 다르다 — 둘 다 fail-closed 가 아니다.**

- **`BILLING_CRYPTO_KEY`** 가 비어 있으면(또는 `${` 로 시작·Base64 형식이 아님·32바이트 아님) `BillingCrypto`
  생성자가 컨텍스트 초기화 단계에서 예외를 던져 **기동 자체가 실패한다**(fail-closed).
- **`TOSS_SECRET_KEY`** 는 비어 있어도 **기동을 막지 않는다.** `TossProperties` 는 `@Validated`·`@NotBlank`
  가 없는 순수 record 고, `TossClientConfig` 가 `null` 을 빈 문자열로 바꿔 그대로 받는다 — `docker-compose.prod.yml`
  이 `TOSS_SECRET_KEY: ${TOSS_SECRET_KEY}` 라, `.env.prod` 에 값이 없으면 **빈 문자열이 그대로 주입되고
  컨테이너는 정상 `healthy` 로 뜬다.** 🔴 **증상은 배포 시점이 아니라 사용자가 카드를 등록할 때 나타난다** —
  토스가 401 을 주고 `TossClient` 가 그걸 503 으로 바꿔 내보내, 카드 등록이 전부 조용히 실패한다
  (`application.yaml` 의 주석도 같은 말을 한다 — *"비워두면 토스가 401 을 주고…"*). "떴으니 괜찮다"고
  읽으면 안 되는 값이다.

```bash
# 빌링키 암호화 키 — Base64 32바이트. 반드시 이 명령으로 만든다.
openssl rand -base64 32
```

```
BILLING_CRYPTO_KEY=<위 명령의 출력>
TOSS_SECRET_KEY=test_sk_...
```

> 🔴 **`BILLING_CRYPTO_KEY` 를 잃으면 전 고객이 카드를 다시 등록해야 한다.**
> 토스에는 **빌링키를 조회하는 API 가 없다** — 우리 DB 의 `billing_methods.billing_key_enc` 가
> 세상에 하나뿐인 사본이고, 그 값은 이 키로만 열린다. 키를 잃으면 DB 가 멀쩡해도 내용물이 영원히 잠긴다.
> **이 키는 DB 백업과 <함께> 백업 대상이다.** RDS 자동 스냅샷은 암호문만 지킬 뿐 키를 지켜주지 않는다.
> 서버를 옮기거나 `.env.prod` 를 새로 만들 때 **이 값만은 새로 만들지 말고 그대로 옮길 것.**
> 키 회전 기능은 없다(`docs/decisions.md` 2026-09-06 항목 참고).
>
> ⚠️ **길이가 정확히 32바이트여야 한다.** JCE 는 16바이트 키를 주면 **말없이 AES-128 로 돈다.**
> `BillingCrypto` 생성자가 길이를 확인해 아니면 기동을 중단하지만, 애초에 위 명령을 그대로 쓰면 된다.
>
> ⚠️ **키 <종류>를 틀리면 `INVALID_API_KEY` 가 난다.** 자동결제는 **API 개별 연동 키**
> (`test_ck_` / `test_sk_`)를 쓴다. 결제위젯 키(`test_gck_` / `test_gsk_`)가 아니다.
> 토스는 서비스마다 다른 MID 에 각각 키를 발급하고, 세트가 아닌 키를 섞으면 거부한다.
> 클라이언트 키(`test_ck_`)와 시크릿 키(`test_sk_`)는 **같은 세트**여야 한다.

### 🔴 배포한다고 결제가 되는 것은 아니다

토스 문서(https://docs.tosspayments.com/guides/v2/billing) 원문:

> "자동결제는 리스크 검토 및 추가 계약 후 사용할 수 있습니다. 정기 구독형 서비스가 아니라면
> 정책적으로 자동결제 사용이 제한되니 유의하세요."

라이브 키를 받으려면 **전자결제 계약 + 자동결제 추가 계약** 두 개가 필요하고 둘 다 사업자등록이 전제다.
**토스 문서상**으로는 테스트 키(`test_sk_` / `test_ck_`)로 사업자등록 없이 전 흐름 — 카드 등록창·빌링키
발급·삭제 — 이 돈다고 한다. 그래서 이 기능의 배포 완료 조건을 **테스트 키 기준**으로 잡았고, 배포된
화면 어디에도 "결제됩니다"라고 쓰지 않는다. 실제 청구(4번 조각)는 아직 만들지도 않았다 —
**지금 카드를 등록해도 돈이 빠져나가는 경로가 코드에 없다.**

> ⚠️ **이 흐름은 아직 실제 테스트 키로 돌려보지 못했다 (2026-09-06 기준).** `NEXT_PUBLIC_TOSS_CLIENT_KEY`
> 를 확보하지 못해, 카드 등록창 진입·`authKey` 발급·등록 성공은 브라우저로 확인한 적이 없다
> (`AGENTS.md` 결제 수단 등록 항목 참고). 확인한 것은 취소·실패 콜백 리다이렉트와 404 재조회
> 화면뿐이다. 통합 테스트 148건이 초록불이어도, 이 저장소는 HTTP/2 업로드 422·위젯 iframe Origin
> 403 을 진짜 상대와 붙여보고서야 잡았다 — **테스트 키를 구해 실제로 한 번 돌려보기 전까지는
> 이 경로를 검증했다고 말하지 않는다.**

## 7. Vercel (프론트)

- **Root Directory**: `web`
- **환경변수**: `NEXT_PUBLIC_API_BASE_URL=https://alldap.duckdns.org`
  ⚠️ **Vercel 이 `web/.env.local.example` 에서 이름을 긁어와 미리 채워 넣는데, 예시값이 그대로 들어간다.**
  `http://localhost:8080` 인 채로 배포하면 배포된 화면이 <개발자 노트북>을 호출하다 전부 실패한다.
  값은 마스킹돼 보이므로 👁 아이콘으로 눈으로 확인할 것.
  ⚠️ 루트 `.env.example` 의 **백엔드 변수**(`JWT_SECRET`·`AI_SERVICE_BASE_URL`·`TOSS_SECRET_KEY`)까지
  딸려 들어온다. 빈 값이라 빌드는 되지만 **여기 시크릿을 넣을 자리를 만들어두는 셈**이라 지우는 게 낫다.
- **환경변수**: `NEXT_PUBLIC_TOSS_CLIENT_KEY=test_ck_...` — 토스 카드 등록창을 여는 데 쓴다.
  `NEXT_PUBLIC_` 이라 **브라우저 번들에 그대로 들어간다.** 클라이언트 키는 원래 공개돼도 되는 값이라
  괜찮지만, **시크릿 키(`test_sk_`)를 여기 넣으면 안 된다** — 그러면 누구나 우리 계정으로 API 를 부른다.
  위 `.env.prod` 의 `TOSS_SECRET_KEY` 와 **같은 세트의 키**여야 한다(다르면 `INVALID_API_KEY`).
- **환경변수(선택)**: `NEXT_PUBLIC_DEMO_PUBLIC_KEY` — 공개 `/demo` 화면이 대화할 봇의 publicKey.
  **미설정이면 `pk_local_dev`(V1 시드 봇)로 떨어진다.** 지금 운영이 그 상태이고, 그래서
  그 시드 행을 지우면 `/demo` 가 전부 fallback 이 된다(`docs/decisions.md` 2026-09-09).
  다른 봇으로 데모를 돌리려면 여기서 그 봇의 publicKey 를 명시할 것.
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

🔴 **⑦ 결제 수단 종단 1회 — V7(다중 카드, PR #74) 이후 배포에서 <등록 성공 경로>를 브라우저로 본 적이 없다.**
개발 중에는 토스 샌드박스 iframe 에 자동화 도구가 입력을 못 넣어 DB 에 행을 심고 봤다.
⚠️ 화면 주소가 **`/account`(마이페이지)** 로 바뀌었다 — `/billing` 은 308 리다이렉트만 남아 있다(쿼리스트링은 따라간다). 거기서:

1. **등록 2장** — 토스 테스트 카드로 두 번 등록 (`authKey` 발급 → `POST /api/billing/methods` 200 · 목록 반환).
   첫 장에만 "기본" 배지가 붙는지
2. **기본 변경** — 둘째 카드의 "기본으로" → `PUT /api/billing/methods/{id}/default` 200, 배지가 옮겨가는지
3. **삭제 거부** — 기본 카드의 삭제 버튼이 비활성인지(다른 카드가 남아 있을 때). 직접 호출하면 409
4. **삭제** — 기본이 아닌 카드 삭제 → `DELETE /api/billing/methods/{id}` 204, 목록에서 사라지는지.
   이어서 마지막 한 장(기본)도 삭제되는지
5. **재등록** — 삭제 직후 같은 카드로 다시 등록해 빌링키가 정상 발급되고 다시 "기본"인지

`TOSS_SECRET_KEY`·`NEXT_PUBLIC_TOSS_CLIENT_KEY` 가 빈 문자열이어도 컨테이너는 정상 `healthy` 로
뜬다(위 "결제 수단(토스) 환경변수" 절) — 이 ⑦번을 건너뛰면 그 사실을 배포 후에도 못 알아챈다.

## 9. 운영

### ✅ 백엔드도 자동 배포다 (2026-09-09부터). 그전까지 이 비대칭이 운영을 두 번 깨뜨렸다

| | 배포 방식 |
|---|---|
| 프론트 (Vercel) | `main` 에 푸시하면 **자동** |
| 백엔드 (EC2) | **자동.** `.github/workflows/deploy.yml` 이 아래 4단계를 대신 돌린다 |

**`main` 에 푸시하면**: `publish.yml`(GHCR 이미지 빌드) → **성공하면** `deploy.yml`(SSH 로 4단계 + 헬스체크).
Actions 탭의 `Deploy to EC2` 가 초록불이면 배포된 것이고, 빨간불이면 <배포가 안 된 것>이다.
Caddyfile·`docker-compose.prod.yml` 만 바뀐 푸시는 이미지 빌드 없이 `deploy.yml` 이 바로 돈다
(그 둘은 이미지 안이 아니라 서버 디스크의 파일이라, 이미지가 안 바뀌어도 배포가 필요하다).

**필요한 GitHub Secrets 4개** (Settings → Secrets and variables → Actions):
`EC2_HOST`(탄력적 IP 또는 도메인) · `EC2_USER`(`ubuntu`) · `EC2_SSH_KEY`(배포용 개인키 전문) ·
`EC2_SSH_KNOWN_HOSTS`(`ssh-keyscan -H <EC2_HOST>` 출력).
마지막 것을 Secrets 에 박는 이유: 워크플로 안에서 `ssh-keyscan` 을 돌리면 매 실행마다
"처음 보는 호스트를 그냥 믿는" 것이라 중간자 공격을 하나도 막지 못한다.

**여전히 손으로 해야 하는 것**: `.env.prod` 변경(서버에만 있다) · 롤백(`IMAGE_TAG` 를 이전 커밋
SHA 로 바꾸고 아래 4단계) · rate limit 종단 확인(아래 절).
그리고 **아래 4단계는 지우지 않는다**: 워크플로가 그대로 옮긴 원본이고, Actions 가 못 돌 때 손으로 돌릴 수단이다.

**API 컨트랙트가 바뀐 변경을 `main` 에 머지하면, 그 순간 운영이 깨진다.** 새 프론트가
옛 백엔드에 없는 경로를 부르기 때문이다. 2026-09-08 에 그대로 겪었다 — PR #74~#76 이
`/api/billing/method` 를 `/api/billing/methods` 로 바꾸고 `/api/plan` 을 추가했는데
EC2 를 갱신하지 않아, 배포된 `/account` 가 통째로 오류 화면이 됐다.

⚠️ **증상이 원인을 가린다.** 매핑 없는 경로는 `GlobalExceptionHandler` 의 catch-all
(`@ExceptionHandler(Exception.class)`)에 걸려 **500 `INTERNAL_ERROR`** 로 나간다 —
화면에는 *"일시적인 오류가 발생했습니다. 잠시 후 다시 시도해주세요"* 가 뜬다.
**재시도로는 절대 안 풀린다.** 404 였다면 "경로가 없다" 로 바로 읽혔을 텐데 500 이라
서버 장애처럼 보인다. (이 저장소가 세 번째로 만난 부류다 — 원인이 다른 것들이 한 문구로 뭉개진다:
`temperature=0` 인데 "잠시 후 재시도" · 빌링키 복호화 실패 · 그리고 이것)

**이제 머지하면 워크플로가 곧바로 돈다.** 머지와 배포 사이의 시간이 곧 운영이 깨져 있는 시간이라,
사람이 기억해서 4단계를 돌리는 구조로는 두 번 다 실패했다(문서에 적어둔 뒤에도 두 번째가 났다).

**빠르게 확인하는 법** — 배포된 백엔드의 스키마 버전을 보면 된다:
```bash
ssh -i <키> ubuntu@<탄력적IP> 'docker logs $(docker ps -qf name=alldap-api) 2>&1 | grep "Current version of schema" | tail -1'
```
저장소의 최신 마이그레이션 번호(`api/src/main/resources/db/migration/`)와 다르면 백엔드가 낡은 것이다.

---

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
문제이기 때문이다. 배포마다 직접 확인한다. `$API_DOMAIN` 은 실제 배포 도메인으로 바꿀 것.

```bash
# 🔴 분 경계 직후에 시작한다 (아래 ③ 참고). 25번이 2초면 끝난다.
S=$(date +%S); sleep $(( (60 - 10#$S) % 60 ))

KEY="pk_zzzzzzzzzzzzzzzzzzzzzz"   # 형식만 맞고 존재하지 않는 키 (아래 ② 참고)
for i in $(seq 1 25); do
  printf "%2d " "$i"
  curl -s -o /dev/null -w "%{http_code}\n" \
    -X POST "https://$API_DOMAIN/api/w/$KEY/chat" \
    -H "Content-Type: application/json" \
    -H "Forwarded: for=203.0.113.$i" \
    -d "{\"message\":\"probe\",\"sessionId\":\"probe-$i\"}"
done
```

**정상: 1~20 번이 `404`, 21~25 번이 `429`.** 위조 IP 25개가 전부 같은 버킷으로 셌다는 뜻이고,
그것이 `header_up -Forwarded` 가 실제로 도는지를 보는 유일한 신호다.

**25개가 전부 같은 코드(429 가 하나도 없음)면 4번(`--force-recreate caddy`)이 이번 배포에
적용되지 않은 것이다.** 컨테이너가 재생성됐는지(`docker compose ps` 의 `caddy` 생성 시각,
또는 `docker exec alldap-caddy-1 grep header_up /etc/caddy/Caddyfile`)부터 다시 확인할 것.

> 🔴 **이 명령은 2026-09-09 에 세 번 고쳤다. 세 가지가 전부 "돌아가는데 아무것도 검증하지
> 않는" 결과를 냈다.** 임의로 줄이지 말 것.
>
> **① 본문에 `sessionId` 가 반드시 있어야 한다.** 옛 명령은 `-d '{"message":"test"}'` 였는데
> `ChatRequest` 는 `sessionId` 도 `@NotBlank` 다. 검증(`@Valid`)이 컨트롤러 본문보다 먼저 돌아
> **`rateLimiter.check` 를 지나가지도 못하고 25번 전부 `400`** 이 된다. 그런데 옛 판정 기준이
> "전부 같은 코드면 실패"라, **이 점검은 언제나 실패를 보고했다.** 잡으려는 것을 원리적으로
> 못 잡는 검사였다(이 저장소가 안 도는 `redirect.check.ts` 로 이미 겪은 부류다).
>
> **② 진짜 `publicKey` 를 쓰지 않는다.** `WidgetController` 의 순서는
> `형식 검사 → rate limit → findByPublicKey` 다. 그래서 **형식만 맞고 존재하지 않는 키**
> (`pk_` + 아무 22자 = 25자)면 카운터는 그대로 세면서 `404` 로 끝난다:
> **LLM 호출 0건 · 대화 로그 0건.** 진짜 키를 쓰면 배포마다 LLM 을 20번 부르고
> 운영 대화 로그에 쓰레기 20건이 쌓인다.
>
> **③ 25번이 <같은 1분> 안에 끝나야 한다.** `RateLimiter` 는 고정 윈도우(`now / 60000`)라
> 도중에 분이 바뀌면 카운터가 둘로 갈려 **한도에 안 걸린다.** 실제로 이것 때문에 429 가 안 나와
> "방어가 뚫렸다"로 오독할 뻔했다. 그래서 맨 앞에 분 경계까지 기다리는 줄이 있다.

## 알려진 구멍 (배포 후 처리)

- **1GB 는 여유가 없다.** 문서 업로드 시 pymupdf 가 파일을 통째로 메모리에 올린다.
  ⚠️ **실측(2026-09-09, 유휴 상태)**: `Mem 911Mi 중 사용 607Mi · available 303Mi`,
  **`Swap 506Mi 사용 중`**. 컨테이너 합은 250MiB 뿐인데(api 222 · caddy 17 · ai-service 10)
  이미 스왑을 쓰고 있다 = 아무도 안 쓰는 상태에서도 여유가 넉넉하지 않다는 뜻이다.
  `.env.prod` 의 `UPLOAD_MAX_SIZE`/`UPLOAD_MAX_BYTES` 를 10MB 로 낮춰뒀지만,
  큰 PDF 가 몰리면 여전히 위험하다. `docker stats` 로 지켜볼 것.
- **rate limit 이 인메모리다.** 인스턴스를 늘리면 각자 세므로 실질 한도가 배가 된다.
  수평 확장 시작 시점이 Redis 교체 시점이다.
- **백그라운드 문서 처리가 FastAPI `BackgroundTasks` 다.** 컨테이너를 재시작하면
  처리 중이던 업로드가 `pending` 에 갇힌다.
- **테스트 질문 생성이 Gemini 무료 등급을 쓴다.** 약관상 입력을 학습에 쓴다 —
  실제 고객 문서를 받기 전에 정리할 것.
- **프리티어 12개월이 끝나면 월 $23 쯤 나간다.** 만료 전에 정리하거나 옮길 것.
- 🔴 **결제는 테스트 키로만 돈다.** 라이브 전환에 자동결제 추가 계약이 필요하다(위 §6 참고).
  그리고 실제 청구 로직 자체가 아직 없다 — 카드를 저장하는 데까지가 전부다.
- 🔴 **`BILLING_CRYPTO_KEY` 는 DB 백업과 함께 백업해야 하는 값이다.** 이것만 잃어도
  `billing_methods` 전체가 쓸모없어지고, 토스에 조회 API 가 없어 복구 수단이 없다.
