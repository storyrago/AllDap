# 데모 채팅 스크롤 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/demo` 오른쪽 채팅 패널이 대화가 쌓여도 세로로 자라지 않고, 고정 높이 안에서만 스크롤되게 한다.

**Architecture:** 메시지 목록 `div` 하나에 고정 높이(`h-[28rem]`)와 `overflow-y-auto` 를 주고, 새 말풍선이 생기면 `useEffect` 로 그 컨테이너의 `scrollTop` 을 바닥까지 민다. 파일 하나만 바뀐다. 위젯·대시보드 채팅은 각자 레이아웃에 맞는 자동 스크롤을 이미 갖고 있어 손대지 않는다.

**Tech Stack:** Next.js 16.2.12 (App Router) · React 19.2.4 · TypeScript · Tailwind CSS 4

**설계 문서:** [`docs/superpowers/specs/2026-09-01-demo-chat-scroll-design.md`](../specs/2026-09-01-demo-chat-scroll-design.md)

## Global Constraints

- **브랜치는 `feat/hero-door-sequence`.** `/demo` 페이지 자체가 이 브랜치에서 생겼고 main 에는 없다. `main` 에 직접 커밋하지 않는다.
- **새 의존성을 추가하지 않는다.** `web/` 에는 테스트 프레임워크가 없고(vitest·jest 모두 없음, 테스트 파일 0개), 이번 변경 때문에 들이지 않는다. CI 가 도는 것은 `npm run lint` 와 `npm run build` 둘뿐이다.
- **검증은 브라우저 실측이다.** 이 저장소가 `web/` 를 검증해 온 방식이다(AGENTS.md "브라우저 실측" 절).
- **주석과 사용자에게 보이는 문구는 한국어.**
- **TypeScript/React 코드에는 왜 그렇게 썼는지 설명 주석을 붙인다** (AGENTS.md 필수 항목: `useEffect` 의존성 배열에 왜 그 값이 들어갔는가).
- **모바일 대응은 하지 않는다** (AGENTS.md 작업 규칙 6 — 공개 페이지는 데스크톱만).
- **`web/app/(widget)/w/[publicKey]/page.tsx` 와 `web/app/(dashboard)/bot/[botId]/chat/page.tsx` 는 건드리지 않는다.**
- 고정 높이 **`28rem`**, 화면 방어 **`max-h-[calc(100vh-20rem)]`** — 스펙의 실측값이다. 임의로 바꾸지 않는다.

**서버가 떠 있어야 한다** (검증에 실제 답변이 필요하다):

```bash
docker compose up -d && (cd api && ./gradlew bootRun &) && (cd ai-service && .venv/bin/uvicorn app.main:app --port 8001 &) && (cd web && npm run dev &)
```

---

### Task 1: 메시지 영역을 고정 높이 + 내부 스크롤로 바꾼다

**Files:**
- Modify: `web/components/DemoConsole.tsx:17` (import)
- Modify: `web/components/DemoConsole.tsx:94` (ref + 자동 스크롤 effect 추가)
- Modify: `web/components/DemoConsole.tsx:191` (메시지 컨테이너 `div`)
- Modify: `web/components/DemoConsole.tsx:193` (빈 상태 안내문)
- Test: 없음 (브라우저 실측 — 아래 Step 1 의 스크립트가 검사 역할을 한다)

**Interfaces:**
- Consumes: 없음 (선행 태스크 없음)
- Produces: 없음 (외부에 노출되는 이름이 늘지 않는다. `logRef` 는 컴포넌트 내부 지역 변수다)

---

- [ ] **Step 1: 검사 스크립트를 준비하고, 지금 코드에서 <실패하는지> 먼저 확인한다**

브라우저를 `http://localhost:3000/demo` 로 연다. 콘솔(또는 브라우저 도구의 `javascript_tool`)에 아래를 그대로 붙여 실행한다.

```js
// /demo 채팅 스크롤 검사 — 4가지를 본다.
// 1) 로그 영역이 role="log" 로 표시돼 있고  2) 높이가 448px 를 넘지 않으며
// 3) 답변이 와도 창(window)이 스크롤되지 않고  4) 로그는 바닥에 붙어 있다.
async function checkDemoScroll() {
  const fails = [];
  const log = document.querySelector('aside [role="log"]');
  if (!log) return ['❌ aside 안에 role="log" 인 스크롤 영역이 없다'];

  if (log.tabIndex !== 0) fails.push(`❌ tabIndex 가 0 이 아니다 (${log.tabIndex}) — 키보드로 스크롤 못 함`);

  // 답변 3턴을 실제로 주고받는다. 제안 버튼을 순서대로 누른다.
  const btns = [...document.querySelectorAll('aside button')]
    .filter((b) => b.textContent.includes('?'))
    .slice(0, 3);
  if (btns.length < 3) return ['❌ 제안 질문 버튼을 3개 찾지 못했다'];

  window.scrollTo(0, 0);
  await new Promise((r) => setTimeout(r, 200));
  const winBefore = Math.round(window.scrollY);

  for (const b of btns) {
    b.click();
    // 답변이 올 때까지 기다린다(생성 모델 호출이라 몇 초 걸린다).
    for (let i = 0; i < 40 && b.disabled; i++) await new Promise((r) => setTimeout(r, 500));
    await new Promise((r) => setTimeout(r, 500));
  }

  const h = Math.round(log.getBoundingClientRect().height);
  const winAfter = Math.round(window.scrollY);
  const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight;

  if (h > 448) fails.push(`❌ 로그 높이가 ${h}px — 448px 를 넘었다 (고정 안 됨)`);
  if (log.scrollHeight <= log.clientHeight) fails.push(`❌ 내용이 넘치지 않아 스크롤 검사를 못 했다 (scrollHeight ${log.scrollHeight})`);
  if (winAfter !== winBefore) fails.push(`❌ 창이 스크롤됐다 ${winBefore} → ${winAfter} — scrollIntoView 를 쓰고 있지 않은지 확인`);
  if (atBottom > 4) fails.push(`❌ 로그가 바닥에 안 붙었다 (${atBottom}px 남음) — 자동 스크롤 안 됨`);

  return fails.length ? fails : [`✅ 통과 — 로그 높이 ${h}px · 창 스크롤 ${winBefore}→${winAfter} · 바닥까지 ${atBottom}px`];
}
await checkDemoScroll();
```

**Expected (변경 전): 첫 줄에서 바로 실패한다.**

```
["❌ aside 안에 role=\"log\" 인 스크롤 영역이 없다"]
```

지금 메시지 컨테이너는 `<div className="flex flex-col gap-3">` 뿐이라 `role="log"` 이 없다. 이게 "먼저 실패하는 검사"다.

---

- [ ] **Step 2: `useEffect` 를 import 에 추가한다**

`web/components/DemoConsole.tsx:17` 을 바꾼다.

변경 전:
```tsx
import { useMemo, useRef, useState } from "react";
```

변경 후:
```tsx
import { useEffect, useMemo, useRef, useState } from "react";
```

---

- [ ] **Step 3: 로그 컨테이너 ref 와 자동 스크롤 effect 를 넣는다**

`web/components/DemoConsole.tsx:94`, `const inputRef = useRef<HTMLInputElement>(null);` 바로 **아래**에 붙인다.

```tsx
  /*
   * 대화 로그 영역. 새 말풍선이 생기면 맨 아래로 내린다.
   * ref 는 "DOM 요소를 직접 가리키는 손잡이"다 — 스크롤 위치는 React 상태로 표현할 수 없는
   * 브라우저 동작이라 요소를 직접 만져야 한다.
   *
   * ⚠️ 이 화면에서는 sentinel + scrollIntoView 를 쓰면 안 된다.
   * 위젯(/w/[publicKey])과 대시보드 채팅은 그 방식을 쓰는데, 두 화면은 h-dvh 라
   * <페이지 자체가 스크롤되지 않아서> scrollIntoView 가 컨테이너만 움직인다.
   * /demo 는 왼쪽 문서 목록 때문에 페이지가 스크롤되고, scrollIntoView 는
   * <스크롤 가능한 조상을 전부> 움직인다 — 답변이 올 때마다 창이 통째로 아래로 튄다
   * (실측 664px, 설계 문서의 대조표 참고). 그래서 컨테이너만 직접 민다.
   */
  const logRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
    /*
     * 의존성이 둘인 이유.
     * msgs — 말풍선이 늘어날 때 내려야 한다.
     * pending — "문서를 찾아보는 중…" 줄이 생겼다 사라지며 로그 높이가 바뀐다.
     *           msgs 만 넣으면 그 로딩 문구가 스크롤 아래에 숨어, 보낸 직후 화면이
     *           아무 반응 없는 것처럼 보인다.
     */
  }, [msgs, pending]);
```

---

- [ ] **Step 4: 메시지 컨테이너에 고정 높이·스크롤·접근성 속성을 준다**

`web/components/DemoConsole.tsx:191`.

변경 전:
```tsx
          <div className="flex flex-col gap-3">
```

변경 후:
```tsx
          <div
            ref={logRef}
            /*
             * 대화가 쌓여도 패널이 세로로 자라지 않게 <고정 높이 + 안쪽 스크롤>.
             * 높이를 막지 않으면 패널이 화면보다 커지고, 그 순간 위 <aside> 의
             * lg:sticky 가 무력해진다 — sticky 는 붙은 요소가 화면보다 작을 때만 동작한다.
             *
             * 28rem(448px)은 눈대중이 아니라 브라우저에서 잰 값이다.
             * 질문 36px + 답변 177px + 질문 36px + 답변 132px + 간격 36px = 417px (2쌍).
             *
             * max-h 는 낮은 화면에서만 줄어드는 안전장치다. 이 패널에서 로그를 뺀 나머지
             * (제목·제안 버튼·입력창·안내문)가 285px 이고 top-8 이 32px 이라 20rem 을 뺀다.
             * 이게 없으면 세로가 짧은 화면에서 방금 고친 문제가 그대로 재현된다.
             */
            className="flex h-[28rem] max-h-[calc(100vh-20rem)] flex-col gap-3 overflow-y-auto"
            /*
             * 스크롤되는 영역은 포커스를 받을 수 없으면 키보드로 굴릴 방법이 아예 없다.
             * role="log" 은 새로 추가되는 답변을 스크린리더가 읽어주게 한다(암묵적 aria-live).
             */
            tabIndex={0}
            role="log"
          >
```

---

- [ ] **Step 5: 빈 상태 안내문을 세로 가운데로 보낸다**

`web/components/DemoConsole.tsx:193`. 448px 짜리 빈 상자에 안내문 한 줄만 위에 붙어 있으면 덜 만든 화면처럼 보인다.

변경 전:
```tsx
              <p className="text-sm leading-relaxed text-muted">
```

변경 후 (주석은 JSX 자식 자리라 `{/* */}` 형태여야 한다 — 이 파일의 다른 주석들과 같은 방식):
```tsx
            {/* m-auto: flex 컨테이너에서 margin:auto 는 남는 공간을 사방으로 나눠 가진다.
                자식이 이것 하나뿐인 빈 상태에서만 효과가 있고, 말풍선이 생기면 사라진다. */}
            {msgs.length === 0 && (
              <p className="m-auto text-sm leading-relaxed text-muted">
```

---

- [ ] **Step 6: 검사 스크립트를 다시 돌려 통과를 확인한다**

브라우저에서 `/demo` 를 **새로고침**한 뒤 Step 1 의 `checkDemoScroll()` 을 다시 실행한다.

Run: 브라우저 콘솔에 Step 1 스크립트 붙여넣기
Expected: PASS

```
["✅ 통과 — 로그 높이 448px · 창 스크롤 0→0 · 바닥까지 0px"]
```

⚠️ **높이가 448 이 아니라 더 작게 나올 수 있고, 그건 정상이다.** 브라우저 창 세로가 낮으면
`max-h-[calc(100vh-20rem)]` 이 먼저 걸린다(예: 창 720px → 400px). 검사는 "448 을 넘지 않는가"를
보므로 그대로 통과한다. 448 을 **넘으면** 고정이 안 된 것이다.

하나라도 `❌` 가 나오면 그 메시지가 어느 단계가 빠졌는지 알려준다. 넘어가지 말 것.

---

- [ ] **Step 7: 눈으로도 확인한다**

1. 문서를 하나 열어 왼쪽을 길게 만든 뒤 페이지를 스크롤한다 → 채팅 패널이 `lg:sticky` 로 따라온다.
2. 대화가 없는 상태에서 안내문이 상자 세로 가운데 있다.
3. `Tab` 키로 로그 영역에 포커스가 들어가고 방향키로 스크롤된다.

---

- [ ] **Step 8: 린트와 빌드를 돌린다**

CI 가 도는 것과 같은 두 가지다.

```bash
cd web && npm run lint && npm run build
```

Expected: 둘 다 오류 없이 끝난다 (`✓ Compiled successfully`).

---

- [ ] **Step 9: 커밋한다**

`widget/demo.html` 에 로컬 실험용 수정이 남아 있다(위젯 스크립트 경로와 publicKey). **같이 커밋하지 말 것** — 파일을 명시해서 담는다.

```bash
git add web/components/DemoConsole.tsx
git commit -m "$(cat <<'EOF'
fix: 데모 채팅이 세로로 자라지 않고 안에서 스크롤되게 했다

대화가 쌓일수록 오른쪽 패널이 그대로 길어져서, 패널이 화면보다 커지는
순간 aside 의 lg:sticky 가 무력해지고 채팅창이 위로 사라졌다.

고정 높이 28rem + overflow-y-auto 로 바꿨다. 448px 는 브라우저에서
질문·답변 2쌍을 실제로 주고받고 잰 값이다(417px).

자동 스크롤은 위젯·대시보드와 달리 scrollIntoView 를 쓰지 않는다.
/demo 는 페이지 자체가 스크롤되는 레이아웃이라 scrollIntoView 가 조상까지
움직여 창이 664px 딸려 내려가는 것을 실측으로 확인했다. 컨테이너의
scrollTop 만 직접 민다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

**1. 스펙 커버리지** — 스펙 "결정" 표의 6줄이 전부 태스크에 있다.

| 스펙 항목 | 어느 단계 |
|---|---|
| `h-[28rem]` | Step 4 |
| `max-h-[calc(100vh-20rem)]` | Step 4 |
| `overflow-y-auto` | Step 4 |
| `scrollTop = scrollHeight` 자동 스크롤 | Step 3 |
| 빈 상태 `m-auto` | Step 5 |
| `tabIndex={0}` · `role="log"` | Step 4 |
| 스펙 "검증" 4항목 | Step 6 (1·2·4번 자동) · Step 7 (3번 눈 확인) |
| 위젯·대시보드 손대지 않음 | Global Constraints · Step 9 의 `git add` 파일 지정 |

**2. 플레이스홀더** — 없다. 모든 단계에 실제 코드와 실제 명령이 있다.

**3. 이름 일관성** — `logRef` 가 Step 3(선언)과 Step 4(사용)에서 같다. `checkDemoScroll()` 이 Step 1 과 Step 6 에서 같다. 검사 스크립트가 찾는 `role="log"` · `tabIndex` 는 Step 4 가 실제로 넣는 속성과 일치한다.
