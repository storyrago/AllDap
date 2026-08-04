# widget/ — 임베드 위젯 (PRD F-04)

고객(관리자)의 웹사이트에 **한 줄**만 붙이면 챗봇이 뜨게 하는 스크립트다.

```html
<script src="http://localhost:8080/widget/alldap-widget.js"
        data-public-key="pk_local_dev"></script>
```

> **왜 한 줄인가**
> 페르소나 P1(김하늘, 27세 학과 조교)의 기술 숙련도 상한이 "복사 → 붙여넣기"다.
> npm·빌드·설정 파일을 요구하는 순간 이 사람은 설치를 포기한다.
> 즉 **설치 난이도 자체가 제품 요구사항**이다.

---

## ⚠️ 현재 상태 (2026-07-31)

| 항목 | 상태 |
|---|---|
| 플로팅 버튼 · 채팅창 열기/닫기 · 모바일 전체화면 | ✅ 동작 |
| 호스트 페이지 CSS 로부터 격리 | ✅ 동작 (`demo.html` 로 확인 가능) |
| 봇 이름·색상 불러오기 (`GET /api/w/{publicKey}/config`) | ❌ **Spring(:8080) 미구현 → 실패함** |
| 실제 대화·출처 카드·👍/👎 | ❌ **Next.js `/w/[publicKey]` 미구현 → 안 뜸** |

**지금 `demo.html` 을 열면 채팅창 안에 "채팅 화면을 불러오지 못했습니다" 가 뜨는 것이 정상이다.**
서버가 없으니 당연한 결과이고, 그때 위젯이 콘솔 에러로 죽지 않고 안내 문구를 보여주는지가
지금 단계에서 확인할 수 있는 전부다.

---

## 구조 — 이 스크립트는 "채팅 UI"가 아니라 "로더"다

```
고객 사이트 (남의 도메인)
└─ <script src=".../alldap-widget.js">      ← 이 폴더. 순수 JS, 의존성 0
   └─ Shadow DOM
      ├─ 플로팅 버튼
      └─ 패널(틀) ─ <iframe src="{Next.js}/w/{publicKey}?embed=1">
                                └─ 채팅 화면 본체 (말풍선·출처 카드·👍/👎)
                                   ※ web/ 에서 만든다. 아직 없음 (W2)
```

### 왜 UI를 여기서 직접 그리지 않나

PRD §7 사이트맵에 `/w/[publicKey]` (엔드유저 위젯, 공개) 페이지가 이미 있다.
로더가 채팅 UI를 직접 그리면 **같은 화면을 Next.js 쪽과 위젯 쪽에 두 벌** 만들게 된다.
1인 개발에서 같은 화면을 두 번 만들고 두 번 고치는 건 감당이 안 된다.
그래서 UI는 Next.js 한 곳에만 두고, 이 파일은 그걸 **띄우는 일**만 한다.

### 이 파일의 책임 (딱 4가지)

1. `data-public-key` 읽기
2. `GET /api/w/{publicKey}/config` 로 봇 이름·색상 받아 버튼 꾸미기
3. 채팅창 열고 닫기 (데스크톱은 떠 있는 창, 480px 이하는 전체화면)
4. iframe 안 페이지와 `postMessage` 로 신호 주고받기

채팅 전송(`POST /api/w/{publicKey}/chat`)·출처 카드·피드백은 **여기 없다.** iframe 안의 일이다.

---

## 설계 결정

### 1. 프레임워크를 쓰지 않았다

이 코드는 "우리 사이트"가 아니라 **"남의 사이트"에서 실행된다.**

- 남의 페이지가 React 17을 쓰는데 우리가 React 18을 들고 들어가면 충돌하거나,
  최소한 수백 KB를 남의 페이지에 얹게 된다.
- 위젯 하나 때문에 남의 사이트가 느려지면 관리자는 위젯을 뗀다.

그래서 **의존성 0, 빌드 0**. 파일 하나를 그대로 서빙한다.
문법도 ES5(`var`/`function`/문자열 연결)로 맞춰 트랜스파일 단계를 아예 없앴다.
단 `fetch`·Shadow DOM·`postMessage` 같은 **브라우저 API** 는 쓴다.
이건 문법이 아니라 런타임 기능이라 트랜스파일로 해결되는 대상이 아니고, IE11은 지원 범위 밖이다.

### 2. CSS 격리 — Shadow DOM(껍데기) + iframe(내용)

남의 페이지에는 이런 CSS가 흔하다.

```css
* { box-sizing: content-box; }
button { background: red !important; font-size: 30px; }
body { font-family: "Comic Sans MS"; line-height: 3; }
```

| 방법 | 판정 | 이유 |
|---|---|---|
| (A) 클래스 접두사 `.alldap-btn` | ❌ 탈락 | 이름 충돌만 막는다. 위의 `button { ... !important }` 한 줄에 그대로 뚫린다 |
| (B) 전부 iframe | △ | 격리는 최강이지만 플로팅 버튼까지 iframe에 넣으면 크기·모서리·그림자 제어와 투명 배경 처리 때문에 통신이 오히려 늘어난다 |
| **(C) 껍데기 Shadow DOM + 내용 iframe** | ✅ **채택** | 떠 있어야 하는 껍데기는 Shadow DOM이 막아주고, 채팅 화면은 어차피 다른 origin의 iframe이라 100% 분리된다. 라이브러리도 필요 없다 |

**Shadow DOM의 유일한 구멍**: `font-family`·`color`·`line-height` 처럼 **상속되는 속성**은
경계를 넘어 들어온다. 그래서 `alldap-widget.js` 의 `:host` 블록에서 이 값들을 명시적으로 다시 잡는다.
"Shadow DOM 이니까 안전하다"가 아니라 **"상속 속성만 직접 막는다"** 까지가 정확한 이해다.
→ `demo.html` 이 이걸 실제로 검증하는 장치다(일부러 고약한 CSS를 깔아뒀다).

### 3. 안전 규칙

- 서버에서 온 문자열은 **`textContent` 로만** 넣는다. `innerHTML` 을 쓰면 응답에 섞인
  `<script>` 가 실행되어 **남의 사이트에 XSS를 심는 꼴**이 된다. 위젯에서 가장 조심할 지점.
- `postMessage` 는 **보낼 때도 받을 때도 origin 을 확인**한다. 확인하지 않으면 그 페이지의
  광고 iframe 하나가 가짜 신호를 보내 위젯을 마음대로 열고 닫을 수 있다.
- 호스트 페이지 정보는 **`hostname` 만** 넘긴다. 전체 URL에는 남의 사이트 쿼리 파라미터
  (개인정보일 수 있다)가 섞일 수 있다.
- 세션 ID는 **로더 쪽 `localStorage`** 에 둔다. iframe 안은 제3자 저장소라
  사파리 등에서 차단되는 경우가 많다.

---

## 서빙 위치

위젯 JS는 **Spring이 정적 파일로** 서빙한다.

```
api/src/main/resources/static/widget/alldap-widget.js
   → http://localhost:8080/widget/alldap-widget.js
```

(Spring Boot는 `src/main/resources/static/` 아래를 그대로 `/` 경로에 매핑한다)

**왜 Next.js가 아니라 Spring인가**

- 설치 한 줄에 들어가는 도메인이 **API 도메인과 같아진다.** 관리자가 복사할 게 하나뿐이다.
- 위젯 JS는 `public_key` 검증·CORS 정책과 수명주기를 같이 한다. API와 함께 배포되는 게 자연스럽다.
- 정적 파일 한 개라 Next.js 빌드에 얹을 이유가 없다.

> ⚠️ **아직 아무것도 연결돼 있지 않다.** `api/` 는 지금 Spring Initializr로 생성 중이라 비어 있다.
> TODO(W2): 아래 중 하나를 정할 것.
> 1. 이 파일을 `api/src/main/resources/static/widget/` 로 **복사** (가장 단순, 두 곳에 파일이 생김)
> 2. Gradle `processResources` 에서 `widget/` → `static/widget/` **복사 태스크** 추가 (원본 한 곳 유지)
> 3. `WebMvcConfigurer` 로 저장소의 `widget/` 디렉터리를 **리소스 핸들러에 매핑** (로컬 개발 편함)
>
> 결정하면 `docs/decisions.md` 에 한 줄 남길 것.

---

## 설치 코드 속성

| 속성 | 필수 | 설명 |
|---|---|---|
| `data-public-key` | ✅ | 봇 식별자. `bots.public_key`. 없으면 위젯이 콘솔 에러만 남기고 조용히 종료한다 |
| `data-api-base` | — | Spring API 주소. 기본값은 **스크립트를 내려받은 origin** |
| `data-app-base` | — | 채팅 페이지(Next.js) 주소. 기본값은 `data-api-base` 와 동일 |
| `data-primary-color` | — | 버튼·헤더 색. config 응답에 색이 있으면 그쪽이 이긴다 |
| `data-launcher` | `default` | `none` 이면 **기본 플로팅 버튼을 그리지 않는다.** 아래 "커스텀 런처" 참고 |

### 커스텀 런처 — "위젯이 우리 사이트랑 안 어울려요" 에 대한 답

가장 흔한 반대다. 채팅창 자체는 **iframe 이라 우리 것일 수밖에 없다** — 대화 내용이
고객사 사내 문서 기반이라, 고객 페이지와 같은 문서에 두면 그 페이지에 박힌
서드파티 스크립트(광고·애널리틱스·태그매니저)가 대화를 읽을 수 있다.
Shadow DOM 은 CSS 만 격리하고 JS 접근은 막지 않는다. iframe 은 브라우저가 원천 차단한다.

**하지만 버튼은 페이지 위에 있으므로 고객이 만들 수 있다.**

```html
<!-- 고객이 자기 디자인으로 만든 버튼 -->
<button id="help" class="내-사이트-버튼">문의하기</button>

<script src="https://.../widget/alldap-widget.js"
        data-public-key="pk_xxx"
        data-launcher="none"></script>

<!-- ⚠️ 위젯 스크립트보다 <아래에> 둘 것. 위에 두면 window.AllDap 이 아직 없다. -->
<script>
  document.getElementById('help').addEventListener('click', function () {
    AllDap.open();
  });
</script>
```

이러면 **사이트에 보이는 것은 100% 고객 디자인**이고, 우리 UI 는 눌렀을 때만 등장한다.

#### 공개 API (`window.AllDap`)

| 함수 | 설명 |
|---|---|
| `AllDap.open()` | 채팅창을 연다. 이미 열려 있으면 아무 일도 안 한다 |
| `AllDap.close()` | 닫는다 |
| `AllDap.toggle()` | 열려 있으면 닫고, 닫혀 있으면 연다 |
| `AllDap.isOpen()` | 열려 있는지 `true`/`false` |

- **상태를 값이 아니라 함수로 준다.** `isOpen` 을 변수로 노출하면 고객이 그걸 바꿔
  우리 내부 상태와 화면이 어긋난다.
- **닫으면 포커스를 "열기를 누른 요소" 로 돌려준다.** 기본 런처를 감춘 상태에서
  우리 버튼에 focus() 를 하면 아무 일도 안 일어나 키보드 사용자가 페이지 맨 앞으로 튕긴다.
- 로더는 `async`/`defer` 없이 문서 순서대로 실행되므로, **이 스크립트 태그보다 아래에 있는**
  고객 코드에서는 `window.AllDap` 이 항상 존재한다. 위에 두면 `ReferenceError` 다.
  (그 경우까지 받아주는 큐 스텁은 아직 넣지 않았다 — 필요해지면 그때)

### `data-app-base` 가 왜 필요한가 (로컬 개발에서 헷갈리는 지점)

위젯 JS는 **Spring(:8080)** 이 주는데, 정작 띄울 화면은 **Next.js(:3000)** 에 있다.
origin이 다르니 스크립트 주소만으로는 채팅 페이지 위치를 알 수 없다.
그래서 **로컬에서는** 설치 코드에 `data-app-base="http://localhost:3000"` 을 붙여야 한다.

> ✅ **2026-08-05: 관리자가 손으로 붙일 일은 없어졌다.**
> 대시보드의 **내보내기** 화면이 스니펫에 `data-app-base` 를 **항상** 넣어준다
> (값은 그 화면이 떠 있는 주소 = 채팅 페이지를 서빙하는 앱의 origin).
> 로컬이든 운영이든 자동으로 맞으므로, 아래 프록시 구성이 정해지기 전에도 설치가 깨지지 않는다.
>
> ⚠️ 이걸 안 넣었을 때의 증상을 적어둔다 — PoC 에서 실제로 겪었고 원인 찾기가 고약하다.
> **버튼도 뜨고 봇 이름·인사말까지 정상인데** 채팅창이 "채팅 화면을 불러오는 중입니다…" 에서 멎는다.
> config 는 Spring 이 맞게 주기 때문에 앞부분이 멀쩡한 것이다.
> 네트워크 탭에 `GET :8080/w/{publicKey}?embed=1 → 401` 이 보이면 이 문제다.

운영에서는 이 속성이 필요 없게 만드는 게 목표다.
리버스 프록시로 한 도메인에 둘을 묶으면(`/api/*`·`/widget/*` → Spring, 나머지 → Next.js)
origin이 같아져 기본값이 그대로 맞는다.
→ **TODO(W2): 이 프록시 구성을 정하고, 정해지면 README와 코드 주석을 갱신할 것.**

---

## postMessage 규약 (W2에서 Next.js가 지켜야 할 계약)

`/w/[publicKey]` 페이지는 아래 규약을 구현해야 로더와 붙는다.

**채팅 페이지 → 로더**

| type | 언제 | 비고 |
|---|---|---|
| `ready` | 페이지가 그려진 직후 | **필수.** 이게 안 오면 10초 뒤 로더가 "불러오지 못했습니다" 를 띄운다 |
| `close` | 페이지 안의 닫기 버튼을 눌렀을 때 | 모바일 전체화면에서 필요 |
| `unread` | 창이 닫힌 상태에서 새 답변이 왔을 때 | `{ count: number }` → 버튼에 빨간 뱃지 |

**로더 → 채팅 페이지**

| type | 내용 |
|---|---|
| `host-info` | `{ sessionId, hostname }` — `ready` 를 받은 직후 보낸다 |
| `visibility` | `{ visible: boolean }` — 창이 열리고 닫힐 때 |

모든 메시지는 `source` 필드로 구분한다
(페이지 → 로더는 `'alldap-widget'`, 로더 → 페이지는 `'alldap-widget-host'`).

**교차 출처 iframe은 로드 실패를 `onerror` 로 알려주지 않는다.**
브라우저가 남의 origin 상태를 페이지에 흘리지 않으려고 일부러 막기 때문이다.
그래서 로더는 "정해진 시간 안에 `ready` 가 오는가"로 성공/실패를 판단한다.

---

## W2 할 일

- [ ] Spring `GET /api/w/{publicKey}/config` — 응답 `{ botName, welcomeMessage, primaryColor }` (camelCase)
- [ ] Spring `POST /api/w/{publicKey}/chat` — 위젯 채팅 (rate limit 필수)
- [ ] Spring `POST /api/messages/{messageId}/feedback` — 👍/👎
- [ ] **CORS 허용** — 남의 도메인에서 호출되므로 CORS 없이는 무조건 막힌다
- [ ] Next.js `web/app/w/[publicKey]/page.tsx` — 채팅 UI + 위 postMessage 규약
- [ ] 위젯 JS를 Spring static 으로 서빙하는 방법 확정 (위 3안 중 택1)
- [ ] `demo.html` 로 최종 검수 (아래 AC)

**F-04 완료 조건(AC)**: 외부 정적 사이트(`demo.html`)에 한 줄로 설치 → 정상 대화 성공.
문서에 있는 질문에는 답변 + 출처가 뜨고, 문서에 없는 질문에는 **지어내지 않고 거절 문구**가 떠야 한다.

---

## 아직 정해지지 않은 것 · 알려진 갭

숨기지 않고 적어둔다. 나중에 "된다고 써놨는데 안 되네"가 제일 나쁘다.

### 1. 허용 도메인(`allowed_origins`) 검증 — **미정** (PRD 부록A #3)

`bots.allowed_origins TEXT[]` 컬럼은 이미 있지만 **검증 로직은 없다.**
PRD의 현재 기울기는 *"필드만 만들고 검증은 이후"*, 결정 시점은 W2다.

검증을 켜기 전까지는 **`public_key` 만 알면 누구나 남의 봇을 자기 사이트에 붙일 수 있다.**
`public_key` 는 설치 코드에 그대로 노출되므로 비밀이 아니다. 즉 이건 "언젠가 할 일"이 아니라
**"안 하면 뚫려 있는 구멍"** 이다. 최소한 이건 정해야 한다.

- 검증 위치: Spring의 `/api/w/*` 에서 `Origin` 헤더를 `allowed_origins` 와 대조
- 비어 있으면 전체 허용인가, 전체 차단인가 (편의 ↔ 안전)
- 로컬 개발용 `localhost` 예외를 둘 것인가

### 2. `bots` 에 색상 컬럼이 없다

PRD F-04는 "브랜드 색상 1종 커스텀"을 요구하는데 `api/src/main/resources/db/migration/V1__init.sql` 의 `bots` 에는
색상 컬럼이 없다. 지금은 `data-primary-color` 속성으로 우회한다.
→ W2에서 `bots.primary_color` 를 추가하고 config 응답에 실으면 이 속성은 불필요해진다.
(스키마 변경은 `api/src/main/resources/db/migration/` 의 Flyway 마이그레이션이 단일 진실 공급원.
Spring `ddl-auto` 로 컬럼을 만들면 안 된다. `V2__add_bot_primary_color.sql` 같은 새 파일로 추가할 것)

### 3. 피드백에 필요한 `messageId` 를 Python은 주지 않는다

Python `ChatResponse` = `{answer, sources[], is_fallback, latency_ms}` 에 **id가 없다.**
👍/👎(`POST /api/messages/{messageId}/feedback`)를 붙이려면 그 id가 있어야 한다.
`messages` 테이블은 Spring이 쓰므로, **Spring이 로그를 저장하면서 만든 id** 를 응답에 넣어야 한다.
→ W2에서 Spring 채팅 응답에 `messageId` 를 반드시 포함시킬 것. 없으면 피드백 UI를 못 붙인다.

### 4. 봇별 `system_prompt` 는 아직 반영되지 않는다

Python `POST /internal/chat` 은 `bot_id`·`message`·`session_id` 만 받는다.
`fallback_message` 는 Spring이 `is_fallback == true` 를 보고 봇 문구로 치환해 우회할 수 있지만,
`system_prompt` 는 **Python을 고치기 전까지 반영 불가**다.
위젯에서 "봇마다 말투가 다르다"고 설명하면 안 된다. 자세한 내용은 `api/README.md` 참고.

### 5. 그 밖에

- rate limit 없음 → 익명 공개 엔드포인트라 그대로 두면 LLM 비용이 샌다 (W2)
- 다크 모드 미대응 (라이트 기준 한 벌)
- 답변 스트리밍(SSE) 여부 미정 — PRD 부록A #1, 결정 시점 W2

---

## 파일

| 파일 | 설명 |
|---|---|
| `alldap-widget.js` | 위젯 로더. 이 폴더의 전부다 |
| `demo.html` | 위젯을 설치한 **가짜 외부 사이트**. F-04 AC 검수용 |

### 검수 방법

```bash
cd widget
python3 -m http.server 5500
# → http://localhost:5500/demo.html
```

`file://` 로 바로 열면 origin이 없어 통신 검사가 정확하지 않으므로 정적 서버로 여는 걸 권장한다.
