<div align="center">

# AllDap

**문서를 올리면 출처가 표시되는 한국어 RAG 챗봇**을 만들어주고,
그 챗봇이 얼마나 정확한지 **자동 평가 리포트로 증명**하는 서비스.

site: **https://all-dap.vercel.app**

<br/>

![Next.js](https://img.shields.io/badge/Next.js%2016-000000?style=flat-square&logo=nextdotjs&logoColor=white)
![Spring Boot](https://img.shields.io/badge/Spring%20Boot%204-6DB33F?style=flat-square&logo=springboot&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL%2016%20+%20pgvector-4169E1?style=flat-square&logo=postgresql&logoColor=white)
![AWS](https://img.shields.io/badge/AWS%20EC2%20·%20RDS-232F3E?style=flat-square&logo=amazonwebservices&logoColor=white)

</div>

---

## Table of Contents

- [Demo](#demo)
- [핵심 지표](#핵심-지표)
- [System Architecture](#system-architecture)
- [ERD](#erd)
- [API](#api)
- [Tech Stack](#tech-stack)
- [Monitoring](#monitoring)
- [Documentation](#documentation)

---

## Demo

### 1. 문서 업로드

PDF · DOCX · HWPX 를 올리면 파싱 → 청킹 → 임베딩이 백그라운드로 돌고,
`pending → processing → ready` 로 상태가 바뀝니다.
임베딩은 수십 초가 걸릴 수 있어 업로드 응답(202)과 처리를 분리했습니다.

<img width="960" height="482" alt="파일업로드" src="https://github.com/user-attachments/assets/62ae38bd-8b68-4b9b-800c-525d671c88e6" />

### 2. 출처가 붙은 답변

답변마다 **어느 문서의 어느 대목에서 나왔는지**를 함께 내려줍니다.

<img width="960" height="482" alt="출처가 붙은 답변" src="https://github.com/user-attachments/assets/135625af-607d-4383-8eec-c0c967574d5e" />

### 3. 근거가 없으면 답하지 않는다

이 제품이 존재하는 이유입니다. 문서에 근거가 없으면 지어내지 않고 fallback 합니다.
방어선이 두 겹입니다.

| 겹 | 무엇 | 어디서 막히나 |
|---|---|---|
| 1차 | 검색 단계 판정 (`answerable_max_distance`) | **LLM 을 아예 호출하지 않는다** |
| 2차 | 생성 단계 (`NO_ANSWER`) | LLM 이 근거를 읽고 "없다" 고 답한다 |

문서에 없는 질문 10개로 재면 **10/10 fallback**, 대조군(문서에 답이 있는 질문) 3/3 정상 답변입니다.
그중 **8건은 1차에서 잘려 LLM 을 부르지도 않습니다.**

<img width="960" height="482" alt="근거가 없으면 답하지 않음" src="https://github.com/user-attachments/assets/09e8e065-e903-4946-be6e-8fb74cdcf644" />

### 4. 품질 대시보드

**이 프로젝트의 심장입니다.** 청크에서 테스트 질문을 자동 생성하고,
답변 생성과 **계열이 다른** 모델로 채점합니다(자기 채점 방지).

<img width="960" height="482" alt="품질 대시보드" src="https://github.com/user-attachments/assets/80b7a484-bb2d-4544-a257-adcb86d93c6d" />

### 5. 한 줄 설치 위젯

고객 사이트에 `<script>` 한 줄을 넣으면 로더가 iframe 으로 채팅 화면을 띄웁니다.
허용하지 않은 도메인은 차단됩니다(빈 허용 목록은 "전부 허용" 이 아니라 **"전부 차단"** 입니다).

```html
<script src="https://alldap.duckdns.org/widget/alldap-widget.js"
        data-public-key="pk_xxxxxxxx"
        data-app-base="https://all-dap.vercel.app"></script>
```

> `data-app-base` 는 **영구히 필요합니다.** 위젯 JS 는 Spring 이 주는데 채팅 화면은 Vercel 에 있어
> 두 origin 이 다릅니다. 빠지면 iframe 이 Spring 을 가리켜 `X-Frame-Options` 로 막힙니다.
> 봇의 [내보내기] 화면이 이 값을 항상 넣어주므로, 그 화면에서 복사하면 신경 쓸 일이 없습니다.

<img width="960" height="482" alt="한 줄 설치 위젯" src="https://github.com/user-attachments/assets/465338d3-e174-40e1-8632-0bb785466d19" />

---

## 핵심 지표

검색 품질을 개선하고 **같은 평가셋으로 before/after 를 쟀습니다.**
같은 16문항 · 50문서 · 306청크 · 같은 모델 · `temperature=0` · 설정당 3회 이상.

| 설정 | 전체 충실성 | 회당 오답 | 회당 완전오답 | 채팅 지연 |
|---|---|---|---|---|
| 벡터 검색만 (before) | 0.781 | 1.75 | 1.00 | 0.67초 |
| **리랭커 + 하이브리드 (after, 현재 기본값)** | **0.875** | **0.00** | **0.00** | 1.56초 |

🔴 **결정적 근거는 평균이 아니라 오답입니다.** fallback 개수는 네 설정 모두 2로 같습니다.
즉 켠다고 "못 답하는 질문" 이 느는 게 아니라, fallback 의 **내용물**이 바뀌면서
**자신 있게 틀린 답이 사라집니다.** fallback 은 안전한 실패("담당자에게 문의하세요")지만
오답은 사용자가 잘못된 정보를 신뢰하게 만듭니다.

---

## System Architecture

<div align='center'>
        <img width="643" height="662" alt="image" src="https://github.com/user-attachments/assets/654038ff-6b68-434c-8677-6fd93291d725" />
</div>

| 경계 | 무엇이 도나 | 어떻게 배포되나 |
|---|---|---|
| **Vercel** | Next.js 16 | `main` 머지 시 자동 |
| **AWS EC2** t3.micro · 1GB | Caddy · Spring Boot · FastAPI | CI 가 GHCR 에 올린 이미지를 `docker pull` |
| └ **docker compose 네트워크** | **컨테이너 3개: `caddy` · `api` · `ai-service`** | 한 덩어리가 아니라 **따로 도는 셋**이고, 같은 브리지 네트워크라 서로를 이름으로 부른다 |
| **AWS RDS** | PostgreSQL 16 + pgvector | 관리형. 같은 VPC 라 인터넷을 거치지 않는다 |
| **외부 API** | Cloudflare · Gemini · Toss | 우리가 배포하지 않는다 |
| **CI/CD** | GitHub Actions · GHCR | 1GB 서버에서는 Gradle 컴파일이 OOM 이라 빌드를 CI 로 뺐다 |
| **계측 · 부하테스트** | Prometheus · Grafana · k6 | **운영 스택에 없다.** 로컬과 부하테스트에서만 띄운다 |


1. **외부 트래픽은 Spring 만 받습니다.** 브라우저에서 오는 길은 Caddy → Spring 하나뿐이고,
   나머지 경로로는 밖에서 들어올 수 없습니다.
2. **외부 LLM API 키는 Python 서비스만 가집니다.** Spring 도 Next.js 도 키를 갖지 않습니다.
3. **Next.js 는 API 게이트웨이가 아닙니다.** 브라우저는 Python 을 직접 부르지 않고,
   인증·권한·`bot_id` 격리는 전부 Spring 이 책임집니다.

**왜 두 언어로 나눴나.** AI 파이프라인(문서 파싱·임베딩·평가)은 Python 생태계가 사실상 필수고,
인증·트랜잭션·권한은 Spring 이 강합니다. 국내에서도 카카오페이(모델은 Python, 서빙은 Kotlin+Spring),
쏘카가 같은 구조를 씁니다.

---

## ERD

<img width="3260" height="1552" alt="AllDap" src="https://github.com/user-attachments/assets/eb4a7f73-fb46-4099-9701-149befa26dd6" />

---

## API

외부에 열린 API 는 **Spring Boot 하나뿐**입니다. Python AI 서비스의 `/internal/*` 는 호스트에 포트가 뜨지 않아 밖에서 부를 수 없습니다.

| SPRING | FastAPI |
|---|---|
| <img width="1471" height="2644" alt="localhost-swagger-ui-index html" src="https://github.com/user-attachments/assets/e92a5824-ca23-467a-8bb0-e8366dbf3f60" />|<img width="1474" height="1267" alt="localhost-docs" src="https://github.com/user-attachments/assets/c62f72ea-a668-4a1b-8d25-075edbf52df7" />|

---
## Tech Stack

| Field | Stack |
|---|---|
| **Frontend** | ![Next.js](https://img.shields.io/badge/Next.js%2016.2-000000?style=flat-square&logo=nextdotjs&logoColor=white) ![React](https://img.shields.io/badge/React%2019.2-61DAFB?style=flat-square&logo=react&logoColor=black) ![TypeScript](https://img.shields.io/badge/TypeScript%205-3178C6?style=flat-square&logo=typescript&logoColor=white) ![Tailwind CSS](https://img.shields.io/badge/Tailwind%20CSS%204-06B6D4?style=flat-square&logo=tailwindcss&logoColor=white) |
| **Backend** | ![Java](https://img.shields.io/badge/Java%2021-ED8B00?style=flat-square&logo=openjdk&logoColor=white) ![Spring Boot](https://img.shields.io/badge/Spring%20Boot%204.0.7-6DB33F?style=flat-square&logo=springboot&logoColor=white) ![Spring Security](https://img.shields.io/badge/Spring%20Security%20·%20JWT-6DB33F?style=flat-square&logo=springsecurity&logoColor=white) ![Hibernate](https://img.shields.io/badge/JPA%20·%20Hibernate-59666C?style=flat-square&logo=hibernate&logoColor=white) ![Flyway](https://img.shields.io/badge/Flyway-CC0200?style=flat-square&logo=flyway&logoColor=white) ![Gradle](https://img.shields.io/badge/Gradle%209.5-02303A?style=flat-square&logo=gradle&logoColor=white) |
| **AI Service** | ![Python](https://img.shields.io/badge/Python%203.11-3776AB?style=flat-square&logo=python&logoColor=white) ![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white) ![Pydantic](https://img.shields.io/badge/Pydantic%20v2-E92063?style=flat-square&logo=pydantic&logoColor=white) ![PyMuPDF](https://img.shields.io/badge/PyMuPDF%20·%20python--docx-FF6F00?style=flat-square) |
| **LLM / Embedding** | ![Cloudflare](https://img.shields.io/badge/Cloudflare%20Workers%20AI-F38020?style=flat-square&logo=cloudflare&logoColor=white) ![Google Gemini](https://img.shields.io/badge/Google%20Gemini-8E75B2?style=flat-square&logo=googlegemini&logoColor=white) |
| **Database** | ![PostgreSQL](https://img.shields.io/badge/PostgreSQL%2016-4169E1?style=flat-square&logo=postgresql&logoColor=white) ![pgvector](https://img.shields.io/badge/pgvector%20·%20HNSW-4169E1?style=flat-square) |
| **Infra** | ![AWS EC2](https://img.shields.io/badge/AWS%20EC2-FF9900?style=flat-square&logo=amazonec2&logoColor=white) ![AWS RDS](https://img.shields.io/badge/AWS%20RDS-527FFF?style=flat-square&logo=amazonrds&logoColor=white) ![Vercel](https://img.shields.io/badge/Vercel-000000?style=flat-square&logo=vercel&logoColor=white) ![Docker](https://img.shields.io/badge/Docker%20Compose-2496ED?style=flat-square&logo=docker&logoColor=white) ![Caddy](https://img.shields.io/badge/Caddy-1F88C0?style=flat-square&logo=caddy&logoColor=white) |
| **CI/CD** | ![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-2088FF?style=flat-square&logo=githubactions&logoColor=white) ![GHCR](https://img.shields.io/badge/GHCR-181717?style=flat-square&logo=github&logoColor=white) |
| **Monitoring** | ![Prometheus](https://img.shields.io/badge/Prometheus-E6522C?style=flat-square&logo=prometheus&logoColor=white) ![Grafana](https://img.shields.io/badge/Grafana-F46800?style=flat-square&logo=grafana&logoColor=white) ![k6](https://img.shields.io/badge/k6-7D64FF?style=flat-square&logo=k6&logoColor=white) |
| **Payment** | ![Toss Payments](https://img.shields.io/badge/Toss%20Payments%20(빌링키)-0064FF?style=flat-square&logo=tossbank&logoColor=white) |

**API 문서**는 springdoc(Spring) 과 FastAPI 자동 생성 문서(Python) 양쪽에 있고,
**운영에서는 두 겹으로 막아 열리지 않습니다**(경로 차단 + 생성 차단).
두 겹이 각각 동작하는 것을 CI 가 확인합니다.

---

## Monitoring

Prometheus + Grafana 로 계측하고 k6 로 부하를 걸어 **처리량 천장이 어디인지, 그 벽의 정체가
무엇인지**를 찾았습니다.

<img width="1242" height="310" alt="image" src="https://github.com/user-attachments/assets/2f9a8fcc-baf1-4110-9c56-3039681feaa0" />

**동시 사용자를 늘릴수록 처리량이 계단처럼 오르다가, 약 47 req/s 에서 멈춥니다.**
19:30 이후 두 계단(80 VU, 160 VU)의 높이가 같습니다. 사용자를 두 배로 늘려도 더 처리하지 못한다는 뜻입니다.
그 순간 오른쪽 지연 그래프가 뜁니다. 160 VU 에서 p50 이 1.7초에서 3.4초로 두 배가 됐습니다.
처리하지 못한 요청이 어딘가에서 줄을 서기 시작한 것입니다.

| Python anyio 스레드풀 | Spring Tomcat 스레드 |
|---|---|
| <img width="616" height="300" alt="image" src="https://github.com/user-attachments/assets/1a26dbc2-d3c6-40e1-a81a-9cbcc4d02322" /> | <img width="616" height="300" alt="image" src="https://github.com/user-attachments/assets/592bf242-85a6-4891-8a1f-fdedda7e5cad" /> |

**그 줄이 어디에 서 있는지를 두 그래프가 보여줍니다.**

| | 왼쪽: Python anyio 스레드풀 | 오른쪽: Spring Tomcat 스레드 |
|---|---|---|
| 보이는 것 | 파란 선이 계단처럼 오르다 **노란 상한 80 에 붙어 평평해진다** | 초록 `busy` 는 같은 시각에도 **160 까지 계속 오른다** (상한 200) |
| 뜻 | **벽이 여기다** | Spring 은 아직 여유가 있다 |

Spring 은 요청 160건을 받았는데 Python 은 80건만 동시에 처리합니다. **나머지 80건이 Python 앞에서 기다린 시간이 위 지연 그래프의 점프입니다.**

> 오른쪽에서 노란 `current` 가 200 에 닿는 것은 "꽉 찼다" 가 아닙니다. 미리 만들어둔 스레드 수이고, 실제로 일하는 스레드는 초록 `busy` 입니다.

---

## Documentation

| 문서 | 내용 |
|---|---|
| [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) | 로컬 실행 (db → api → ai-service → web 순서) |
| [`docs/INTERNAL-API.md`](docs/INTERNAL-API.md) | Spring 이 호출하는 Python `/internal` 컨트랙트 |
| [`docs/VERIFICATION.md`](docs/VERIFICATION.md) | 무엇이 어디까지 검증됐나. **"안 나빠졌다" 와 "재보지 않았다" 의 구분** |
| [`docs/DEPLOY.md`](docs/DEPLOY.md) | 배포 절차와 그 과정에서 밟은 함정 |
| [`docs/부하테스트-리포트.md`](docs/부하테스트-리포트.md) | 부하테스트 시리즈 종합 |
| [`docs/PRD_v0.4.md`](docs/PRD_v0.4.md) | 제품 요구사항 정의서 |
| [`docs/decisions.md`](docs/decisions.md) | 설계 결정 로그 (날짜 \| 무엇을 \| 왜 \| 검토한 대안) |
| [`docs/W1-이해노트.md`](docs/W1-이해노트.md) | RAG 파이프라인을 왜 그렇게 짰는가 |
| [`AGENTS.md`](AGENTS.md) | AI 코딩 에이전트용 저장소 컨텍스트 (원본) |

## Project Structure

```
AllDap/
├── web/           Next.js (App Router): 관리자 대시보드 · 공개 페이지 · 위젯 페이지
├── api/           Spring Boot API (:8080)
│   └── src/main/resources/db/migration/   V1 ~ V8 · 스키마 단일 진실 공급원
├── ai-service/    Python FastAPI AI 서비스 (:8001)
│   └── testdata/  파서 fixture · 평가 코퍼스 50문서
├── widget/        임베드용 위젯 스크립트 (한 줄 설치)
├── observability/ Prometheus · Grafana 설정
├── scripts/       부하테스트 · 배포 검증
└── docs/          위 표 참고
```
