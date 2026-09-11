/*!
 * AllDap 임베드 위젯 로더  (PRD F-04)
 * ---------------------------------------------------------------------------
 * 설치는 반드시 "한 줄"이어야 한다.
 *
 *   <script src="http://localhost:8080/widget/alldap-widget.js"
 *           data-public-key="pk_local_dev"></script>
 *
 * 왜 한 줄인가:
 *   페르소나 P1(김하늘, 27세 학과 조교)의 기술 숙련도 상한이 "복사 → 붙여넣기"다.
 *   npm install·빌드·번들러 설정을 요구하는 순간 이 사람은 설치를 포기한다.
 *   즉 설치 난이도 자체가 제품 요구사항이다.
 *
 * ===========================================================================
 * [설계 결정 1] 이 파일은 "채팅 UI"가 아니라 "로더"다
 * ===========================================================================
 * 채팅 화면 본체는 Next.js 페이지 `/w/[publicKey]` 이고(PRD §7 사이트맵),
 * 이 파일은 그 페이지를 iframe 으로 띄워주는 얇은 로더다. (CLAUDE.md 아키텍처 그림)
 *
 * 왜 이렇게 나눴나 — 만약 이 파일이 채팅 UI를 직접 그린다면:
 *   · 말풍선·출처 카드·👍/👎 UI가 Next.js 쪽과 위젯 쪽에 **두 벌** 생긴다.
 *     1인 개발에서 같은 화면을 두 번 만들고 두 번 고치는 건 감당이 안 된다.
 *   · 위젯 쪽만 순수 JS라 타입 검사도, 컴포넌트 재사용도 못 받는다.
 * 그래서 UI는 Next.js 한 곳에만 두고, 여기서는 그걸 "띄우는 일"만 한다.
 *
 * 이 파일의 책임은 딱 4가지다.
 *   ① data-public-key 읽기
 *   ② GET /api/w/{publicKey}/config 로 봇 이름 받아 플로팅 버튼 꾸미기
 *      (색은 config 가 아니라 설치 코드의 data-primary-color 에서 온다. 아래 [색상] 참고)
 *   ③ 버튼 클릭 시 채팅창(iframe) 열고 닫기 — 데스크톱은 창, 모바일은 전체화면
 *   ④ iframe 안의 페이지와 postMessage 로 신호 주고받기
 *
 * 채팅 전송(POST /api/w/{publicKey}/chat), 출처 카드, 👍/👎 는 여기가 아니라
 * iframe 안의 `/w/[publicKey]` 페이지가 담당한다.
 * 실제 파일은 `web/app/(widget)/w/[publicKey]/page.tsx` 다.
 * `(widget)` 은 라우트 그룹이라 **URL 에는 나타나지 않는다** (주소는 `/w/{publicKey}`).
 * 대시보드와 레이아웃을 나누려고 묶어둔 것이고, 경로를 찾을 때 이 괄호를 빼면 파일이 없다.
 *
 * ===========================================================================
 * [설계 결정 2] 왜 프레임워크를 쓰지 않았나
 * ===========================================================================
 * 이 파일은 "우리 사이트"가 아니라 "남의 사이트"에서 실행된다.
 *   · 남의 페이지가 React 17을 쓰는데 우리가 React 18을 끌고 들어가면 충돌하거나,
 *     최소한 수백 KB를 남의 페이지에 얹게 된다.
 *   · 위젯 하나 때문에 남의 사이트가 느려지면 관리자는 위젯을 뗀다.
 * 그래서 의존성 0, 빌드 0. 파일 하나를 그대로 서빙한다.
 *
 * 문법도 ES5로 맞춘다(var / function / 문자열 연결). 화살표 함수·템플릿 리터럴·class 를
 * 쓰지 않는 이유는 트랜스파일 단계를 아예 없애기 위해서다.
 * 단 fetch / Shadow DOM / postMessage 같은 "브라우저 API"는 쓴다. 이건 문법이 아니라
 * 런타임 기능이라 트랜스파일로 해결되는 대상이 아니고, IE11은 지원 범위 밖이다.
 *
 * ===========================================================================
 * [설계 결정 3] CSS 격리 — Shadow DOM(껍데기) + iframe(내용) 2단
 * ===========================================================================
 * 남의 페이지에는 이런 CSS가 흔하다.
 *     * { box-sizing: content-box; }
 *     button { background: red !important; font-size: 30px; }
 *     div { border: 1px dashed hotpink; }
 * 격리하지 않으면 우리 위젯이 이걸 그대로 뒤집어쓴다.
 *
 * 검토한 3가지:
 *   (A) 클래스 접두사(.alldap-btn)
 *       → 이름 충돌만 막는다. 위 예시의 `button { ... !important }` 한 줄에 그대로 뚫린다. 탈락.
 *   (B) 전부 iframe
 *       → 격리는 최강(문서가 통째로 분리됨)이지만, 플로팅 버튼까지 iframe에 넣으면
 *         버튼 크기·모서리 둥글기·그림자를 부모 페이지에서 제어할 수 없고
 *         투명 배경 처리와 크기 조절 때문에 postMessage 통신이 오히려 늘어난다.
 *   (C) 껍데기는 Shadow DOM, 내용은 iframe  ← 채택
 *       → 플로팅 버튼·패널 프레임처럼 "호스트 페이지 위에 떠야 하는 것"은 Shadow DOM으로
 *         감싸 바깥 CSS 선택자가 들어오지 못하게 하고,
 *         실제 채팅 화면은 어차피 별도 origin(Next.js)의 iframe이라 100% 분리된다.
 *         라이브러리 없이 네이티브 기능만 쓴다.
 *
 * Shadow DOM 의 유일한 구멍: **상속되는 속성**(font-family, color, line-height 등)은
 * 경계를 넘어 들어온다. 그래서 아래 CSS의 `:host` 에서 이 값들을 명시적으로 다시 잡는다.
 * "Shadow DOM 이니까 안전하다"가 아니라 "상속 속성만 직접 막는다"까지가 정확한 이해다.
 *
 * ===========================================================================
 * [현재 상태: 2026-08-02 실제 설치 실측 통과]
 * ===========================================================================
 * 이 주석 블록은 2026-07-31(W2 착수 전)에 쓰였고 한동안 낡은 채로 남아 있었다.
 * 아래가 현재 사실이다. 위 W2 TODO 4개는 **전부 구현됐다** (PR #11).
 *
 *   · GET /api/w/{publicKey}/config  → Spring 구현 완료. CORS 도 열려 있다
 *   · iframe 안의 /w/{publicKey}     → Next.js 페이지 구현 완료
 *   · allowed_origins 검증           → **켜져 있다.** 아래 경고를 볼 것
 *   · rate limit                     → 켜져 있다 (IP + publicKey 기준 분당 20건, 인메모리)
 *
 * 별도 origin 의 가짜 고객 사이트에 script 한 줄을 붙여 로더 → iframe → 인사말 →
 * 근거 붙은 답변 → channel=widget 로그까지 브라우저로 확인했다(2026-08-02).
 *
 * 🔴 **빈 `allowed_origins` 는 "전부 허용" 이 아니라 "전부 차단" 이다.**
 *    옛 주석이 정반대로("검증을 켜기 전까지는 public_key 만 알면 누구나 붙일 수 있다")
 *    적혀 있었다. publicKey 는 설치 코드에 그대로 노출되므로 비밀이 아니고,
 *    기본값을 "허용" 으로 두면 모든 신규 봇이 무방비로 태어난다. 그래서 반대로 잡았다.
 *    ⚠️ 대신 **설정 조회에만** 걸린다. 채팅은 iframe 안에서 나가 고객 Origin 이
 *    오지 않으므로 원리적으로 검증 대상이 아니고, 그쪽 방어선은 rate limit 이다.
 *
 * 실패해도 콘솔 에러로 죽지 않고, 패널 안에 한국어 안내 문구를 띄운다(그대로 유효하다).
 * ---------------------------------------------------------------------------
 */
(function () {
  'use strict';

  /* 같은 페이지에 스크립트가 두 번 붙는 사고는 실제로 흔하다
     (관리자가 header와 footer 양쪽에 붙이는 경우). 버튼이 2개 생기면 바로 티가 나므로 막는다. */
  if (window.__ALLDAP_WIDGET_LOADED__) { return; }
  window.__ALLDAP_WIDGET_LOADED__ = true;

  // ===========================================================================
  // 1. 설치 코드에서 설정 읽기
  // ===========================================================================

  /**
   * 자기 자신(<script> 태그)을 찾는다.
   * document.currentScript 는 "지금 실행 중인 script"를 가리키지만
   * async/defer 로 로드되면 null 이 될 수 있어 src 로 되찾는 폴백을 둔다.
   */
  function findSelfScript() {
    if (document.currentScript) { return document.currentScript; }
    var list = document.getElementsByTagName('script');
    for (var i = list.length - 1; i >= 0; i--) {
      if (list[i].src && list[i].src.indexOf('alldap-widget.js') !== -1) {
        return list[i];
      }
    }
    return null;
  }

  var selfScript = findSelfScript();

  // 남의 페이지에 alert 를 띄우면 안 된다. 설치자가 볼 수 있게 콘솔에만 남긴다.
  if (!selfScript) {
    console.error('[AllDap] 위젯 스크립트 태그를 찾지 못했습니다. 설치 코드를 다시 확인해주세요.');
    return;
  }

  var publicKey = selfScript.getAttribute('data-public-key');
  if (!publicKey) {
    console.error('[AllDap] data-public-key 가 없습니다. 봇의 [내보내기] 화면에서 설치 코드를 다시 복사해 붙여넣어주세요.');
    return;
  }

  /**
   * data-launcher="none" 이면 <우리 플로팅 버튼을 그리지 않는다.>
   *
   * 왜 필요한가 — "위젯이 우리 사이트 디자인과 안 맞는다" 에 대한 답이다.
   * 채팅창은 iframe 이라 우리 것일 수밖에 없지만(대화 내용이 고객사 사내 문서라
   * 남의 스크립트에서 읽히면 안 된다), <버튼은 페이지 위에 있으므로 고객이 만들 수 있다.>
   * 고객이 자기 HTML·CSS 로 버튼을 만들고 window.AllDap.open() 을 부르면
   * 사이트에 보이는 것은 100% 고객 디자인이 된다. (파일 맨 아래 공개 API 참고)
   *
   * 기본값은 'default' 다 — 개발자가 없는 고객은 한 줄만 붙이고 끝나야 한다.
   */
  var launcherMode = selfScript.getAttribute('data-launcher') === 'none' ? 'none' : 'default';

  function trimSlash(u) { return String(u).replace(/\/+$/, ''); }

  /**
   * API 주소(Spring :8080).
   * 위젯 JS 는 Spring 이 정적 파일로 서빙하므로 스크립트 src 의 origin 이 곧 API origin 이다.
   * 이렇게 해두면 로컬(localhost:8080) → 운영(https://api.example.com) 으로 옮길 때
   * 관리자가 붙여넣은 한 줄의 src 만 바뀌고 위젯 코드는 손댈 게 없다.
   */
  function resolveApiBase() {
    var override = selfScript.getAttribute('data-api-base');
    if (override) { return trimSlash(override); }
    try { return new URL(selfScript.src).origin; } catch (e) { return 'http://localhost:8080'; }
  }

  /**
   * 채팅 화면 주소(Next.js :3000).
   *
   * 여기가 로컬 개발에서 헷갈리는 지점이다. 위젯 JS 는 Spring(:8080)이 주고,
   * 정작 띄울 화면은 Next.js(:3000)에 있다. 즉 둘의 origin 이 다르다.
   * 그래서 로컬에서는 설치 코드에 data-app-base="http://localhost:3000" 을 붙여야 한다.
   *
   * 🔴 **이 속성은 임시방편이 아니라 영구히 필요하다.** 옛 주석은 "운영에서는
   * 필요 없게 만드는 게 목표" 라며 리버스 프록시로 한 도메인에 묶는 구성을 적어뒀는데,
   * 2026-09-07 배포에서 **반대로 갔다**: Caddy 는 Spring 만 프록시하고 프론트는
   * Vercel 이라 둘의 origin 이 영구히 다르다. 아래 폴백(스크립트 origin = Spring)은
   * 따라서 운영에서도 맞지 않는다.
   *
   * 관리자가 이 속성을 손으로 붙일 일은 없다. 대시보드 내보내기 화면이 스니펫에
   * **항상** 넣어준다(`web/app/(dashboard)/bot/[botId]/export/page.tsx`, 값은 그 화면이
   * 떠 있는 주소). 빠졌을 때의 증상과 근거는 그 파일 주석에 2026-08-05 로 남아 있다.
   */
  function resolveAppBase() {
    var override = selfScript.getAttribute('data-app-base');
    if (override) { return trimSlash(override); }
    return API_BASE;
  }

  var API_BASE = resolveApiBase();
  var APP_BASE = resolveAppBase();

  /* [색상] 버튼 색이 어디서 오는가: 지금은 config 가 아니다.

     ⚠️ 이 값의 <유일한> 출처는 설치 코드의 data-primary-color 속성(없으면 기본값)이다.
     GET /api/w/{publicKey}/config 는 색을 실어 보내지 않는다. bots 테이블에 색상 컬럼이
     없어서(`api/src/main/resources/db/migration/` 의 마이그레이션 V8 까지 확인했다.
     루트 `db/` 는 2026-07-31 Flyway 이관으로 없어진 경로다) Spring 의
     WidgetConfigResponse.from 이 색 자리에 null 을 박아 넣는다.

     PRD F-04 는 "브랜드 색상 1종 커스텀"을 요구하므로 언젠가 컬럼을 추가해야 한다.
     그때 <반드시> 같이 볼 것: 아래 applyConfig 는 data.primaryColor 를 읽는데
     Spring·프론트가 쓰는 이름은 themeColor 다(WidgetConfigResponse · web/lib/types.ts).
     지금은 서버가 어차피 null 이라 드러나지 않지만, 컬럼만 추가하고 이름을 안 맞추면
     **색이 조용히 무시된다.**
     ⚠️ 컬럼 이름 후보부터 두 갈래다: api/ 의 WidgetConfigResponse TODO 는 theme_color 를,
     여기 옛 주석과 demo.html 은 bots.primary_color 를 가리킨다. 어느 쪽으로 갈지는
     그 슬라이스에서 정할 일이라 이 파일에서는 고르지 않았다. "config 값이 우선한다" 고만 적혀 있던 옛 주석은
     그래서 사실이 아니었다. 이름이 다르면 우선할 기회조차 없다. */
  var settings = {
    botName: '문의 도우미',
    primaryColor: selfScript.getAttribute('data-primary-color') || '#2563eb'
  };

  // ===========================================================================
  // 2. 세션 ID
  // ===========================================================================

  /**
   * 대화를 하나로 묶는 값.
   * conversations.session_id 가 VARCHAR(64) 이고 Python ChatRequest.session_id 도
   * max_length=64 라서 64자를 넘기면 안 된다.
   *
   * 왜 iframe 안이 아니라 여기(로더)에서 만드나:
   *   iframe 안의 localStorage 는 "제3자 저장소"라 사파리·브레이브 등에서 자주 차단된다.
   *   반면 로더는 호스트 사이트와 같은 origin 에서 도니 제1자 저장소라 살아남는다.
   *   그래서 여기서 만들어 두고 handshake 때 iframe 으로 내려준다.
   */
  var SESSION_KEY = 'alldap_session_' + publicKey;

  function loadSessionId() {
    var made = 'w_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 10);
    try {
      var saved = window.localStorage.getItem(SESSION_KEY);
      if (saved) { return saved; }
      window.localStorage.setItem(SESSION_KEY, made);
    } catch (e) { /* 저장이 막혀도 이번 방문 동안은 동작해야 한다 */ }
    return made;
  }

  var sessionId = loadSessionId();

  // ===========================================================================
  // 3. 스타일 (Shadow DOM 안에서만 유효)
  // ===========================================================================

  /* ES5 라 템플릿 리터럴(백틱)을 못 쓴다. 배열 join 이 문자열 + 연결보다 읽기 쉽다. */
  function buildCss(color) {
    return [
      /* :host = 위젯을 담은 바깥 요소.
         상속 속성(font/color/line-height 등)은 Shadow DOM 경계를 넘어 들어오므로
         여기서 전부 되잡아야 남의 사이트 폰트·색에 오염되지 않는다. */
      ':host {',
      '  all: initial;',
      '  font-family: -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo",',
      '               "Malgun Gothic", "맑은 고딕", sans-serif;',
      '  font-size: 14px;',
      '  line-height: 1.6;',
      '  color: #111827;',
      '  text-align: left;',
      '  direction: ltr;',
      '}',
      /* Shadow DOM 안에서는 * 를 써도 바깥으로 새지 않는다. 마음 놓고 초기화한다. */
      '* { box-sizing: border-box; margin: 0; padding: 0; }',

      /* button·textarea 는 폰트를 상속받지 않는다. 브라우저 기본 스타일시트가
         `font: 13.333px Arial` 처럼 직접 지정해버리기 때문이다.
         :host 에서 폰트를 잡아둬도 여기서 명시하지 않으면 버튼 글씨만 Arial 로 튄다. */
      'button, textarea, input { font: inherit; color: inherit; }',

      /* ※ z-index 를 여기(Shadow DOM 안)에 적으면 안 된다. 이유는 아래 setHostStyle 참고. */

      /* ── 플로팅 버튼 ── */
      '.launcher {',
      '  position: fixed; right: 20px; bottom: 20px;',
      '  width: 56px; height: 56px; border-radius: 50%;',
      '  border: 0; cursor: pointer; padding: 0;',
      '  background: ' + color + '; color: #fff;',
      '  box-shadow: 0 4px 16px rgba(0,0,0,.24);',
      '  display: flex; align-items: center; justify-content: center;',
      '  transition: transform .15s ease;',
      '}',
      '.launcher:hover { transform: scale(1.06); }',
      '.launcher:focus-visible { outline: 3px solid #fff; outline-offset: 2px; }',
      '.launcher svg { width: 26px; height: 26px; fill: #fff; pointer-events: none; }',
      '.launcher .close-icon { display: none; }',
      '.launcher.is-open .open-icon { display: none; }',
      '.launcher.is-open .close-icon { display: block; }',

      /* 안 읽은 답변 표시. iframe 이 unread 신호를 보내면 켠다. */
      '.badge {',
      '  position: absolute; top: -2px; right: -2px;',
      '  min-width: 18px; height: 18px; border-radius: 9px;',
      '  background: #ef4444; color: #fff; font-size: 11px; font-weight: 700;',
      '  display: none; align-items: center; justify-content: center; padding: 0 5px;',
      '}',
      '.badge.is-on { display: flex; }',

      /* ── 패널(iframe 을 담는 틀) ── */
      '.panel {',
      '  position: fixed; right: 20px; bottom: 88px;',
      '  width: 380px; height: 600px; max-height: calc(100vh - 120px);',
      '  background: #fff; border-radius: 16px; overflow: hidden;',
      '  box-shadow: 0 12px 40px rgba(0,0,0,.22);',
      '  display: none; flex-direction: column;',
      '}',
      '.panel.is-open { display: flex; }',

      /* 헤더는 로더가 그린다. iframe 로드가 늦어도 "뭔가 열렸다"는 게 즉시 보여야 하고,
         모바일에서 닫기 버튼이 iframe 로드에 의존하면 사용자가 갇힌다. */
      '.header {',
      '  background: ' + color + '; color: #fff; flex-shrink: 0;',
      '  padding: 13px 14px; display: flex; align-items: center; gap: 8px;',
      '}',
      '.title { font-weight: 700; font-size: 15px; flex: 1; overflow: hidden;',
      '         text-overflow: ellipsis; white-space: nowrap; }',
      '.close {',
      '  background: transparent; border: 0; color: #fff; cursor: pointer;',
      '  font-size: 22px; line-height: 1; width: 30px; height: 30px; border-radius: 8px;',
      '}',
      '.close:hover { background: rgba(255,255,255,.2); }',

      '.stage { flex: 1; position: relative; background: #f9fafb; }',
      '.frame { width: 100%; height: 100%; border: 0; display: block; }',

      /* iframe 이 뜨기 전/실패했을 때 덮는 화면 */
      '.overlay {',
      '  position: absolute; inset: 0; display: flex; flex-direction: column;',
      '  align-items: center; justify-content: center; gap: 10px;',
      '  padding: 24px; text-align: center; background: #f9fafb;',
      '}',
      '.overlay.is-hidden { display: none; }',
      '.overlay-text { font-size: 13px; color: #4b5563; white-space: pre-line; }',
      '.spinner {',
      '  width: 22px; height: 22px; border-radius: 50%;',
      '  border: 3px solid #e5e7eb; border-top-color: ' + color + ';',
      '  animation: spin .8s linear infinite;',
      '}',
      '.spinner.is-hidden { display: none; }',
      '@keyframes spin { to { transform: rotate(360deg); } }',
      '.retry {',
      '  border: 1px solid #d1d5db; background: #fff; border-radius: 8px;',
      '  padding: 6px 12px; cursor: pointer; font: inherit; font-size: 13px;',
      '  display: none;',
      '}',
      '.retry.is-on { display: inline-block; }',

      /* ── 모바일 ──
         480px 이하에서는 떠 있는 창 대신 화면 전체를 덮는다.
         작은 화면에서 380px 짜리 창은 키보드가 올라오면 거의 쓸 수 없다. */
      '@media (max-width: 480px) {',
      '  .panel {',
      '    right: 0; left: 0; top: 0; bottom: 0;',
      '    width: 100%; height: 100%; max-height: 100%; border-radius: 0;',
      '  }',
      /* 전체화면일 때 플로팅 버튼이 채팅 위에 떠 있으면 입력창을 가린다. */
      '  .launcher.is-open { display: none; }',
      '}'
    ].join('\n');
  }

  // ===========================================================================
  // 4. DOM 만들기
  // ===========================================================================

  var host = document.createElement('div');
  host.setAttribute('data-alldap-widget', '');

  /**
   * 위젯을 담는 바깥 요소(host)의 스타일.
   *
   * ★ 왜 이건 Shadow DOM 안의 CSS 로 못 하나 (한 번 틀렸던 부분이라 적어둔다)
   *   Shadow DOM 안의 z-index 는 "그 안에서 누가 위인가"만 정한다.
   *   호스트 페이지의 헤더·모달과 우열을 겨루는 건 **light DOM 에 있는 host 요소**다.
   *   그래서 z-index 는 반드시 여기(host)에 걸어야 한다.
   *   안에만 적어두면 DOM 순서 덕분에 우연히 위에 뜨다가, 호스트 페이지에
   *   z-index 가 걸린 요소가 하나 생기는 순간 위젯이 그 아래로 깔린다.
   *
   * ★ 왜 인라인 스타일 + !important 인가
   *   `:host` 규칙은 호스트 페이지의 CSS 에게 진다(host 요소는 남의 문서에 있는 요소다).
   *   `div { position: static !important }` 같은 한 줄에 위젯이 통째로 깨지면 안 되므로,
   *   위치·쌓임 순서처럼 "양보하면 안 되는 값"만 인라인 !important 로 못 박는다.
   *   색·폰트 같은 나머지는 Shadow DOM 안에서 처리하므로 여기 적지 않는다.
   *
   * z-index 값: 남의 사이트 헤더·모달보다 위여야 한다. 32비트 정수 최대값 근처를 쓰되,
   * 우리보다 위에 떠야 할 것(쿠키 동의 배너·접근성 도구)을 위해 최대값에서 조금 뺀다.
   */
  function setHostStyle() {
    var s = host.style;
    s.setProperty('position', 'fixed', 'important');
    s.setProperty('top', '0', 'important');
    s.setProperty('left', '0', 'important');
    // 크기 0 — 실제로 보이는 건 안쪽의 버튼·패널(둘 다 position:fixed)이다.
    // host 가 화면을 덮으면 호스트 페이지의 클릭을 가로채게 되므로 반드시 0 이어야 한다.
    s.setProperty('width', '0', 'important');
    s.setProperty('height', '0', 'important');
    s.setProperty('z-index', '2147483000', 'important');
    s.setProperty('display', 'block', 'important');
  }
  setHostStyle();

  /* mode:'open' — 호스트 페이지 JS 가 shadowRoot 에 접근할 수 있다.
     'closed' 로 감춰도 보안이 되지는 않고(같은 페이지의 JS는 어차피 막을 수 없다)
     디버깅만 어려워지므로 open 을 쓴다. */
  var shadow = host.attachShadow({ mode: 'open' });

  var styleEl = document.createElement('style');
  styleEl.textContent = buildCss(settings.primaryColor);
  shadow.appendChild(styleEl);

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) { node.className = className; }
    /* textContent 만 쓴다. 서버에서 온 문자열을 innerHTML 로 넣으면
       거기 섞인 <script> 가 실행되어 "남의 사이트"에 XSS 를 심는 꼴이 된다.
       (아래 아이콘 SVG 만 예외 — 우리가 이 파일에 직접 적은 고정 문자열이다) */
    if (text !== undefined && text !== null) { node.textContent = String(text); }
    return node;
  }

  // 플로팅 버튼
  var launcher = el('button', 'launcher');
  launcher.setAttribute('type', 'button');
  launcher.setAttribute('aria-label', '문의 챗봇 열기');
  launcher.setAttribute('aria-expanded', 'false');
  launcher.innerHTML =
    '<svg class="open-icon" viewBox="0 0 24 24" aria-hidden="true">' +
    '<path d="M12 3C7.03 3 3 6.58 3 11c0 2.2 1.02 4.18 2.67 5.6L5 21l4.2-2.2c.88.2 1.82.3 2.8.3 4.97 0 9-3.58 9-8s-4.03-8-9-8z"/></svg>' +
    '<svg class="close-icon" viewBox="0 0 24 24" aria-hidden="true">' +
    '<path d="M18.3 5.71 12 12l6.3 6.29-1.41 1.42L10.6 13.4l-6.3 6.3-1.4-1.42L9.18 12 2.9 5.71 4.3 4.3l6.3 6.29 6.29-6.3z"/></svg>';

  var badge = el('span', 'badge');
  badge.setAttribute('aria-hidden', 'true');
  launcher.appendChild(badge);

  // 패널
  var panel = el('div', 'panel');
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-label', '문의 챗봇');
  panel.setAttribute('aria-modal', 'false');   // 호스트 페이지를 막지 않는다

  var header = el('div', 'header');
  var titleEl = el('div', 'title', settings.botName);
  var closeBtn = el('button', 'close', '×');   // ×
  closeBtn.setAttribute('type', 'button');
  closeBtn.setAttribute('aria-label', '채팅창 닫기');
  header.appendChild(titleEl);
  header.appendChild(closeBtn);

  var stage = el('div', 'stage');
  var overlay = el('div', 'overlay');
  var spinner = el('div', 'spinner');
  var overlayText = el('div', 'overlay-text', '채팅 화면을 불러오는 중입니다…');
  var retryBtn = el('button', 'retry', '다시 시도');
  retryBtn.setAttribute('type', 'button');
  overlay.appendChild(spinner);
  overlay.appendChild(overlayText);
  overlay.appendChild(retryBtn);
  stage.appendChild(overlay);

  panel.appendChild(header);
  panel.appendChild(stage);

  shadow.appendChild(panel);
  shadow.appendChild(launcher);

  /* 감출 때 <제거>하지 않고 인라인 style 로 숨기는 이유:
     아래 열고 닫기 코드가 launcher 의 className·aria 속성을 계속 만진다.
     지워버리면 그 코드가 전부 null 검사를 달아야 하는데, 얻는 게 없다.
     인라인 style 은 시트의 어떤 규칙보다 세서 미디어쿼리(.launcher.is-open)에도 안 진다. */
  if (launcherMode === 'none') { launcher.style.display = 'none'; }

  function mount() { document.body.appendChild(host); }
  if (document.body) {
    mount();
  } else {
    document.addEventListener('DOMContentLoaded', mount);
  }

  // ===========================================================================
  // 5. 봇 설정 불러오기
  // ===========================================================================

  var CONFIG_TIMEOUT_MS = 8000;

  /**
   * PRD §10.3 공통 에러 포맷:
   *   { "error": { "code": "...", "message": "한국어 설명" } }
   * 이 포맷을 못 지킨 응답(프록시가 뱉는 502 HTML 등)도 오므로 그때는 기본 문구로 대체한다.
   */
  function errorMessageOf(payload, status) {
    if (payload && payload.error && payload.error.message) { return payload.error.message; }
    if (status === 404) { return '챗봇을 찾을 수 없습니다.\n설치 코드의 public key 를 확인해주세요.'; }
    if (status === 429) { return '요청이 너무 많습니다. 잠시 후 다시 시도해주세요.'; }
    return '일시적인 오류가 발생했습니다. 잠시 후 다시 시도해주세요.';
  }

  /** fetch 에는 타임아웃 옵션이 없어 AbortController 로 직접 건다. */
  function getJson(path) {
    var controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
    var timer = controller ? setTimeout(function () { controller.abort(); }, CONFIG_TIMEOUT_MS) : null;

    var options = {
      method: 'GET',
      headers: { 'Accept': 'application/json' },
      // 위젯은 익명이라 쿠키가 필요 없다. 'omit' 이면 CORS 설정도 훨씬 단순해진다.
      credentials: 'omit'
    };
    if (controller) { options.signal = controller.signal; }

    return fetch(API_BASE + path, options).then(function (res) {
      if (timer) { clearTimeout(timer); }
      return res.text().then(function (raw) {
        var parsed = null;
        try { parsed = raw ? JSON.parse(raw) : null; } catch (e) { /* JSON 이 아닐 수 있다 */ }
        if (!res.ok) { throw new Error(errorMessageOf(parsed, res.status)); }
        return parsed;
      });
    }, function (netErr) {
      if (timer) { clearTimeout(timer); }
      // 여기로 오는 대표 사례: 서버가 안 떠 있음 / CORS 차단 / 타임아웃.
      // (Spring 이 구현되기 전까지 항상 이 경로를 탄다고 적혀 있었으나, 2026-08-02 부터는
      //  진짜 실패일 때만 온다. 로컬에서 Spring 을 안 띄웠을 때가 가장 흔하다)
      throw new Error('챗봇 서버에 연결하지 못했습니다.\n잠시 후 다시 시도해주세요.');
    });
  }

  var configLoaded = false;

  /* 받아온 설정을 들고 있는다. 채팅 페이지에도 <이 값을> 내려주기 때문이다 (아래 설명). */
  var botConfig = null;

  /* 설정을 못 받은 이유(한국어 문구). 채팅 화면을 덮는 오버레이에 그대로 띄운다. */
  var configError = null;

  function applyConfig(data) {
    if (!data) { return; }
    botConfig = data;
    /* 채팅 페이지가 이미 떠 있으면 지금 바로 전달한다.
       아직 안 떠 있으면 ready 신호를 받을 때 host-info 에 실어 보낸다. */
    postToFrame({ type: 'host-info', sessionId: sessionId, hostname: window.location.hostname, config: data });
    if (data.botName) {
      settings.botName = data.botName;
      titleEl.textContent = data.botName;
      launcher.setAttribute('aria-label', data.botName + ' 열기');
    }
    /* ⚠️ 이 분기는 지금 <한 번도 실행되지 않는다.> 서버는 색 필드를 themeColor 라는
       이름으로 내려보내고, 그나마도 항상 null 이다(위 [색상] 주석 참고).
       지우지 않고 두는 이유는 컬럼이 생겼을 때 붙일 자리가 여기라서고,
       그때 이름을 맞추는 것이 첫 할 일이다. */
    if (data.primaryColor) {
      settings.primaryColor = data.primaryColor;
      styleEl.textContent = buildCss(data.primaryColor);   // 색만 바꿔 CSS 를 다시 만든다
    }
    /* welcomeMessage 는 여기서 쓰지 않는다. 첫 인사말을 그리는 건 채팅 화면의 일이라
       iframe 안의 /w/[publicKey] 페이지가 <위에서 넘긴> config 로 처리한다.
       (로더가 인사말까지 그리면 같은 UI 를 두 곳에서 만들게 된다) */
  }

  /**
   * 설정은 "처음 열 때" 딱 한 번만 가져온다.
   * 페이지가 열리자마자 요청하면 채팅을 쓰지 않는 방문자에게도 네트워크 비용이 든다.
   * 남의 사이트에 얹히는 코드라 이런 비용에 인색해야 한다.
   * (버튼 색은 이 응답과 무관하다. 언제나 data-primary-color 또는 기본값이다)
   */
  function ensureConfig() {
    if (configLoaded) { return; }
    configLoaded = true;

    getJson('/api/w/' + encodeURIComponent(publicKey) + '/config')
      .then(applyConfig)
      ['catch'](function (err) {
        /* 이 요청은 <허용 도메인 검증을 통과한 유일한 요청>이다 (아래 host-info 주석 참고).
           그래서 실패를 조용히 넘기면 안 된다 — 대표 사례가
           "이 사이트가 허용 도메인에 없다" 이고, 그건 관리자가 설정 화면에서 고칠 수 있다.
           삼켜버리면 관리자는 위젯이 왜 멀쩡히 뜨는데 답이 이상한지 알 수 없다. */
        configError = err && err.message ? err.message : '봇 설정을 불러오지 못했습니다.';
        console.warn('[AllDap] ' + configError);
        showFatal(configError);
      });
  }

  // ===========================================================================
  // 6. iframe (채팅 화면 본체)
  // ===========================================================================

  var frame = null;
  var frameReady = false;
  var readyTimer = null;
  var FRAME_READY_TIMEOUT_MS = 10000;

  function chatUrl() {
    /* 쿼리로는 식별자만 넘긴다. 세션 ID·사용자 정보는 URL 에 담지 않는다.
       URL 은 리퍼러 헤더·브라우저 기록·서버 액세스 로그에 그대로 남기 때문이다.
       그런 값은 아래 handshake(postMessage)로 넘긴다. */
    return APP_BASE + '/w/' + encodeURIComponent(publicKey) + '?embed=1';
  }

  function showOverlay(text, canRetry) {
    overlayText.textContent = text;
    overlay.className = 'overlay';
    spinner.className = canRetry ? 'spinner is-hidden' : 'spinner';
    retryBtn.className = canRetry ? 'retry is-on' : 'retry';
  }

  function hideOverlay() {
    overlay.className = 'overlay is-hidden';
  }

  /*
   * 되돌릴 수 없는 오류(예: 허용 도메인이 아니다). 이유만 남기고 스피너도 재시도 버튼도 없앤다.
   * showOverlay 의 두 번째 인자는 "재시도 가능한가" 하나로 스피너까지 같이 정해서
   * 이 경우를 표현하지 못한다 — 스피너를 두면 "곧 될 것처럼" 보이고,
   * 재시도 버튼을 두면 눌러도 config 를 다시 부르지 않아 아무 일도 일어나지 않는다.
   */
  function showFatal(text) {
    showOverlay(text, false);
    spinner.className = 'spinner is-hidden';
  }

  function createFrame() {
    frameReady = false;
    showOverlay('채팅 화면을 불러오는 중입니다…', false);

    frame = document.createElement('iframe');
    frame.className = 'frame';
    frame.setAttribute('title', settings.botName + ' 채팅');
    /* 리퍼러를 origin 까지만 보낸다. 호스트 페이지의 전체 URL(쿼리 포함)이
       우리 서버 로그에 남지 않게 하려는 것. 도메인 검증에는 origin 이면 충분하다. */
    frame.setAttribute('referrerpolicy', 'strict-origin-when-cross-origin');
    frame.src = chatUrl();
    stage.appendChild(frame);

    /* 교차 출처 iframe 은 로드 실패를 onerror 로 알려주지 않는다.
       (브라우저가 남의 origin 의 상태를 페이지에 흘리지 않으려고 일부러 막는다)
       그래서 "정해진 시간 안에 iframe 이 ready 신호를 보내는가"로 판단한다. */
    readyTimer = setTimeout(function () {
      if (frameReady) { return; }
      showOverlay(
        '채팅 화면을 불러오지 못했습니다.\n' +
        '잠시 후 다시 시도하거나 사이트 관리자에게 알려주세요.',
        true
      );
      console.warn('[AllDap] 채팅 화면(' + chatUrl() + ')이 응답하지 않습니다. ' +
        'W2에서 web/app/w/[publicKey] 페이지를 구현하면 연결됩니다.');
    }, FRAME_READY_TIMEOUT_MS);
  }

  function destroyFrame() {
    if (readyTimer) { clearTimeout(readyTimer); readyTimer = null; }
    if (frame && frame.parentNode) { frame.parentNode.removeChild(frame); }
    frame = null;
    frameReady = false;
  }

  retryBtn.addEventListener('click', function () {
    destroyFrame();
    createFrame();
  });

  // ---------------------------------------------------------------------------
  // postMessage 규약 (로더 ↔ 채팅 페이지)
  //
  //   채팅 페이지 → 로더 : { source:'alldap-widget', type:'ready' | 'close' | 'unread' }
  //   로더 → 채팅 페이지 : { source:'alldap-widget-host', type:'host-info' | 'visibility' }
  //
  // 왜 origin 을 매번 검사하나:
  //   window.message 는 아무 사이트나 보낼 수 있다. origin 을 확인하지 않으면
  //   광고 iframe 하나가 우리 위젯에 가짜 신호를 보내 마음대로 열고 닫을 수 있다.
  //   보낼 때도 '*' 대신 APP_BASE 를 지정해, 우리가 보낸 sessionId 가
  //   엉뚱한 origin 으로 새지 않게 한다.
  // ---------------------------------------------------------------------------

  function appOrigin() {
    try { return new URL(APP_BASE, window.location.href).origin; } catch (e) { return null; }
  }

  function postToFrame(payload) {
    var target = appOrigin();
    if (!frame || !frame.contentWindow || !target) { return; }
    payload.source = 'alldap-widget-host';
    frame.contentWindow.postMessage(payload, target);
  }

  window.addEventListener('message', function (e) {
    var expected = appOrigin();
    if (!expected || e.origin !== expected) { return; }        // 출처 확인 — 필수
    var data = e.data;
    if (!data || data.source !== 'alldap-widget') { return; }  // 우리 규약인지 확인

    if (data.type === 'ready') {
      frameReady = true;
      if (readyTimer) { clearTimeout(readyTimer); readyTimer = null; }
      /* 설정을 못 받았으면 오버레이를 걷지 않는다. 채팅창은 떠 있는데
         "왜 안 되는지" 는 안 보이는 상태가 제일 나쁘다. */
      if (configError) { showFatal(configError); } else { hideOverlay(); }
      /* 채팅 페이지가 필요한 정보를 내려준다.
         hostname 만 보내는 이유: allowed_origins 검증에는 도메인이면 충분하고,
         전체 URL 에는 남의 사이트 쿼리 파라미터(개인정보일 수 있다)가 섞일 수 있다.

         ⚠️ config 를 <우리가> 실어 보내는 이유 (2026-08-02 실제 설치에서 잡은 버그).
         채팅 페이지가 스스로 /api/w/{publicKey}/config 를 부르면 <반드시 403 이 난다.>
         그 요청의 Origin 은 고객 사이트가 아니라 iframe 자신, 즉 우리 앱(:3000)이기 때문이다.
         고객이 허용 도메인에 우리 앱 주소를 넣어줄 리도 없고, 넣게 하는 것도 이상하다.
         "허용된 사이트에 설치됐는가" 를 판별할 수 있는 건 <고객 페이지에서 도는 이 로더>뿐이다.
         그래서 검증되는 요청은 로더가 한 번만 보내고, 결과를 아래로 넘긴다. */
      postToFrame({
        type: 'host-info',
        sessionId: sessionId,
        hostname: window.location.hostname,
        config: botConfig            // 아직 응답 전이면 null — 도착하면 applyConfig 가 다시 보낸다
      });
      return;
    }

    // 모바일 전체화면에서 채팅 페이지 안의 닫기 버튼을 눌렀을 때
    if (data.type === 'close') { closePanel(); return; }

    // 닫힌 상태에서 새 답변이 왔을 때 뱃지 표시
    if (data.type === 'unread') {
      var n = typeof data.count === 'number' ? data.count : 1;
      if (!isOpen && n > 0) {
        badge.textContent = n > 9 ? '9+' : String(n);
        badge.className = 'badge is-on';
      }
    }
  });

  // ===========================================================================
  // 7. 열고 닫기
  // ===========================================================================

  var isOpen = false;

  /* 열기 직전에 포커스가 어디 있었는지 기억한다.
     기본 런처를 쓸 때는 닫으면서 그 버튼으로 돌려주면 되지만, 고객이 자기 버튼을 쓰면
     우리 런처는 숨겨져 있어 focus() 가 아무 일도 안 한다 — 키보드 사용자가 페이지 맨 앞으로
     튕겨나간다. 그래서 <열기를 누른 그 요소>로 돌려준다. */
  var lastFocused = null;

  function openPanel() {
    if (isOpen) { return; }
    lastFocused = document.activeElement;
    isOpen = true;
    panel.className = 'panel is-open';
    launcher.className = 'launcher is-open';
    launcher.setAttribute('aria-expanded', 'true');
    launcher.setAttribute('aria-label', settings.botName + ' 닫기');
    badge.className = 'badge';

    ensureConfig();
    if (!frame) { createFrame(); }
    postToFrame({ type: 'visibility', visible: true });
  }

  function closePanel() {
    if (!isOpen) { return; }
    isOpen = false;
    panel.className = 'panel';
    launcher.className = 'launcher';
    launcher.setAttribute('aria-expanded', 'false');
    launcher.setAttribute('aria-label', settings.botName + ' 열기');
    postToFrame({ type: 'visibility', visible: false });

    /* iframe 은 지우지 않고 남겨둔다.
       지우면 다시 열 때마다 페이지가 새로 로드되어 대화 내용이 사라진다.
       (닫을 때마다 대화가 날아가면 사용자가 다시 묻지 않는다) */

    // 닫으면 포커스를 돌려준다. 키보드 사용자가 길을 잃지 않게.
    // 고객이 자기 버튼을 쓰는 경우엔 우리 런처가 숨겨져 있으므로 <열기를 누른 요소>로 보낸다.
    var back = launcherMode === 'none' ? lastFocused : launcher;
    if (back && typeof back.focus === 'function') { back.focus(); }
  }

  launcher.addEventListener('click', function () {
    if (isOpen) { closePanel(); } else { openPanel(); }
  });
  closeBtn.addEventListener('click', closePanel);

  // ESC 로 닫기. 남의 페이지 키 입력을 가로채면 안 되므로 열려 있을 때만 반응한다.
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && isOpen) { closePanel(); }
  });

  // ===========================================================================
  // 8. 공개 API — 고객 페이지가 위젯을 직접 여닫을 수 있게 한다
  // ===========================================================================
  /*
   * 왜 필요한가
   * ─────────────────────────────────────────────────────────────────────────
   * "위젯이 우리 사이트 디자인과 안 맞는다" 가 가장 흔한 반대다.
   * 채팅창 자체는 iframe 이라 우리 것일 수밖에 없다 — 대화 내용이 고객사 사내 문서라
   * 같은 문서에 두면 그 페이지의 서드파티 스크립트(광고·애널리틱스)가 읽을 수 있다.
   * 하지만 <버튼은 페이지 위에 있으니 고객이 만들 수 있다.>
   *
   *   <button class="내-사이트-버튼">문의하기</button>
   *   <script>
   *     document.querySelector('.내-사이트-버튼')
   *             .addEventListener('click', function () { AllDap.open(); });
   *   </script>
   *
   * 여기에 data-launcher="none" 을 더하면 <사이트에 보이는 것은 100% 고객 디자인>이 되고,
   * 우리 UI 는 눌렀을 때만 등장한다.
   *
   * 설계 메모
   * ─────────────────────────────────────────────────────────────────────────
   * · 내부 상태를 그대로 노출하지 않고 <함수만> 준다. isOpen 을 변수로 내보내면
   *   고객이 그 값을 바꿔 우리 상태와 화면이 어긋난다. 읽기 전용 함수로 준다.
   * · 이미 열려 있는데 open() 을 또 부르는 경우는 openPanel 앞에서 막았다.
   *   안 막으면 lastFocused 가 우리 iframe 으로 덮여, 닫을 때 포커스가 사라진 요소로 간다.
   * · 이 스크립트는 async/defer 없이 문서 순서대로 실행되므로, <이 태그보다 아래에 있는>
   *   고객 스크립트에서는 window.AllDap 이 항상 존재한다. 위에 두면 없다.
   *   (그 경우까지 받아주는 큐 스텁은 지금 필요하지 않다 — 필요해지면 그때 넣는다)
   */
  window.AllDap = {
    open: function () { openPanel(); },
    close: function () { closePanel(); },
    toggle: function () { if (isOpen) { closePanel(); } else { openPanel(); } },
    isOpen: function () { return isOpen; }
  };
})();
