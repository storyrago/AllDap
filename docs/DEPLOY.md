# 배포 (비용 0원 구성)

프론트는 **Vercel**, 나머지 셋(Spring · Python · Postgres)은 **VM 한 대에 docker compose** 로 올린다.

```
[Vercel]  web  ──HTTPS──┐
                         ▼
[VM]  Caddy :80/:443  ← Let's Encrypt 자동 발급
        │
        ├── api (Spring)   ← 바깥에 노출되는 유일한 서비스
        ├── ai-service     ← 포트를 아예 안 연다
        └── db (pgvector)  ← 포트를 아예 안 연다
             compose 내부 네트워크
```

## 왜 이 구조인가

**🔴 Python 을 인터넷에서 보이지 않게 하는 것이 배포의 1순위 제약이다.**
`/internal/*` 에는 인증이 **전혀** 없다. 포트가 하나라도 열리면 publicKey 도 JWT 도 없이
누구나 남의 봇 문서와 청크를 읽는다.

`docker-compose.prod.yml` 에서 `ports:` 를 여는 서비스는 **caddy 하나뿐**이다.
방화벽 규칙으로 "막는" 게 아니라 **애초에 호스트에 뜨지 않게** 한다 — 규칙은 잊거나 실수로
지울 수 있지만, 안 열린 포트는 실수할 여지가 없다.

**HTTPS 는 선택이 아니다.** 관리자 화면이 Vercel(HTTPS)에 있어서, HTTP API 를 부르면
브라우저가 mixed content 로 차단한다. 로컬에서는 둘 다 http 라 안 겪는 문제다.

---

## 1. 준비물

| | 비용 | 비고 |
|---|---|---|
| Oracle Cloud 계정 | 0원 | Always Free ARM 인스턴스용 |
| DuckDNS 서브도메인 | 0원 | Let's Encrypt 발급에 도메인이 필요하다 |
| Vercel 계정 | 0원 | 프론트 |
| Cloudflare · Google AI API 키 | 0원 | 이미 로컬에서 쓰던 것 그대로 |

## 2. VM 만들기 (Oracle Always Free)

- **Shape**: `VM.Standard.A1.Flex` (ARM Ampere). 2026 년에 Always Free 할당이
  4 OCPU/24GB → **2 OCPU/12GB** 로 줄었다. 우리 스택엔 충분하다.
- **리전**: 서울·US East 는 `Out of host capacity` 가 잦다. **싱가포르·프랑크푸르트**가
  비교적 잘 잡힌다. 한국 사용자 지연을 생각하면 싱가포르.
- **이미지**: Ubuntu 22.04 이상 (ARM)
- ⚠️ **유휴 회수**: CPU 가 오래 0 에 가까우면 Oracle 이 인스턴스를 회수한다.
  면접 사이에 놀고 있는 데모가 조용히 사라진다.
  → **카드를 등록해 Pay-As-You-Go 로 올려두면 Always Free 리소스는 계속 $0 이면서
  회수 대상에서 빠진다.** 포트폴리오 데모라면 이 편이 안전하다.

### ⚠️ 방화벽이 두 겹이다 — 여기서 대부분 막힌다

Oracle 은 **클라우드 쪽 Security List** 와 **VM 안의 iptables** 를 둘 다 통과해야 한다.
Ubuntu 이미지는 iptables 가 기본으로 막혀 있어서, 클라우드 쪽만 열고
"왜 안 되지" 하는 경우가 대부분이다. **둘 다** 80·443 을 열어야 한다.

```bash
# ① 클라우드: VCN → Security List → Ingress Rules 에 0.0.0.0/0 TCP 80, 443 추가 (웹 콘솔)

# ② VM 안
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

### 도커 설치

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER   # 다시 로그인해야 적용된다
```

## 3. DuckDNS

1. https://www.duckdns.org 에서 서브도메인 생성 (예: `alldap`)
2. VM 의 **공인 IP** 를 등록 → `alldap.duckdns.org` 가 그 IP 를 가리킨다
3. 확인: `dig +short alldap.duckdns.org` 가 VM IP 를 뱉어야 한다.
   **이게 맞아야 Let's Encrypt 인증서가 나온다** — 발급 과정에서 그 주소로 실제 접속해 확인한다.

## 4. 배포

```bash
git clone https://github.com/storyrago/AllDap.git && cd AllDap
cp .env.prod.example .env.prod
vi .env.prod          # 아래 값 채우기

docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```

`.env.prod` 에서 반드시 바꿀 것:

```bash
API_DOMAIN=alldap.duckdns.org
CORS_ALLOWED_ORIGINS=https://<Vercel 배포 주소>
DB_PASSWORD=$(openssl rand -base64 24)     # 로컬의 alldap/alldap 을 쓰지 말 것
JWT_SECRET=$(openssl rand -base64 48)      # 새면 아무나 남의 계정 토큰을 만든다
CF_ACCOUNT_ID= / CF_API_TOKEN= / GOOGLE_API_KEY=
```

> 값이 하나라도 비면 **기동이 실패한다.** 의도된 동작이다 —
> `application-prod.yaml` 과 `ai-service/app/config.py` 의 `_check_prod` 가
> 둘 다 fail-closed 로 짜여 있다. 조용히 잘못된 상태로 뜨는 것보다 낫다.

**기동 순서는 compose 가 강제한다**: `db(healthy) → api(healthy) → ai-service`.
스키마는 Spring 이 뜨면서 Flyway 로 만들기 때문에 **Python 이 먼저 뜨면 안 된다.**

첫 빌드는 Gradle 의존성 내려받느라 몇 분 걸린다. ARM VM 이면 더 걸릴 수 있다.

## 5. Vercel (프론트)

- **Root Directory**: `web`
- **환경변수**: `NEXT_PUBLIC_API_BASE_URL=https://alldap.duckdns.org`
- 배포 후 그 주소를 **VM 의 `CORS_ALLOWED_ORIGINS` 에 넣고** api 를 재시작한다.
  (`docker compose -f docker-compose.prod.yml --env-file .env.prod up -d api`)

> ⚠️ Vercel 은 브랜치마다 **프리뷰 도메인**을 만든다. 프리뷰에서도 API 를 쓰려면
> 그 도메인도 `CORS_ALLOWED_ORIGINS` 에 넣어야 한다(쉼표 구분).

## 6. 배포 후 확인 — 순서대로

```bash
# ① Spring 이 밖에서 보이는가
curl -s https://alldap.duckdns.org/actuator/health        # {"status":"UP"}

# ② 위젯 JS 가 나오는가 (설치 코드가 이 주소를 가리킨다)
curl -sI https://alldap.duckdns.org/widget/alldap-widget.js | head -1

# 🔴 ③ Python 이 <안 보이는가> — 가장 중요한 확인
curl -s -m 5 http://<VM공인IP>:8001/health                # 연결 실패해야 정상
curl -s -m 5 http://<VM공인IP>:5432                       # 연결 실패해야 정상

# ④ 내부에서는 되는가
docker compose -f docker-compose.prod.yml exec api curl -s http://ai-service:8001/health
```

그다음 **브라우저로**: 가입 → 봇 생성 → 문서 업로드(`ready` 까지) → 테스트 채팅 →
내보내기에서 스니펫 복사 → 아무 정적 사이트에 붙여 실제 대화.

⚠️ **내보내기 스니펫의 도메인이 배포 주소인지 반드시 눈으로 확인할 것.**
`src` 는 `NEXT_PUBLIC_API_BASE_URL`, `data-app-base` 는 Vercel 주소가 나와야 한다.

## 7. 운영

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod logs -f api
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build   # 갱신 배포

# DB 백업 (볼륨이 날아가면 문서·대화·평가가 전부 사라진다)
docker compose -f docker-compose.prod.yml exec -T db pg_dump -U alldap alldap | gzip > backup-$(date +%F).sql.gz
```

## 알려진 구멍 (배포 후 처리)

- **`X-Forwarded-For` 를 Spring 이 신뢰하지 않는다.** 위젯 채팅 rate limit 이 IP 기준인데,
  프록시를 거치면 **모든 요청이 Caddy 의 IP** 로 보여 전 세계가 한 바구니에서 한도를 나눠 쓴다.
  → `application-prod.yaml` 에 `server.forward-headers-strategy: framework` 추가 필요.
- **rate limit 이 인메모리다.** 인스턴스를 늘리면 각자 세므로 실질 한도가 배가 된다.
  수평 확장 시작 시점이 Redis 교체 시점이다.
- **백그라운드 문서 처리가 FastAPI `BackgroundTasks` 다.** 컨테이너를 재시작하면
  처리 중이던 업로드가 `pending` 에 갇힌다.
- **재시도·서킷브레이커가 없다.** Python 이 죽으면 <고객 사이트에 박힌> 챗봇이 죽는다.
- **답변 생성이 Gemini 무료 등급을 쓴다**(테스트 질문 생성). 약관상 입력을 학습에 쓴다 —
  실제 고객 문서를 받기 전에 정리할 것.
