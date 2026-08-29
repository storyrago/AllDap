# 페이지 전환 연출 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 랜딩에서 나가는 링크 두 개(`고용하기` → `/auth`, 로봇 → `/demo`)는 도착 페이지가 가운데서 양옆으로 열리며 드러나게 하고, `(site)` 그룹 안의 나머지 이동은 은은한 페이드로 통일한다.

**Architecture:** 브라우저 View Transitions API 를 React 의 `<ViewTransition>` 으로 쓴다. `<Link transitionTypes={['door']}>` 가 이동에 이름표를 붙이고, `(site)` 레이아웃의 `<ViewTransition>` 래퍼가 그 이름표를 CSS 클래스로 바꾸며, `globals.css` 가 그 클래스에 애니메이션을 건다. 문짝 DOM 을 만들지 않고 **도착 페이지 스냅샷의 `clip-path`** 를 벌려 문이 열리는 그림을 만든다.

**Tech Stack:** Next.js 16.2.12 (App Router) · React 19.2.4 · TypeScript · Tailwind v4 + `globals.css`

## Global Constraints

- **의존성을 추가하지 않는다.** 애니메이션 라이브러리 없이 CSS 로만 한다(스펙의 기각 목록).
- **주석·문구는 한국어.** 설계 결정은 왜 그런지까지 적는다(`AGENTS.md`).
- **`prefers-reduced-motion: reduce` 면 전환 애니메이션을 전부 끈다.** 이동 자체는 정상 동작해야 한다.
- **View Transitions 미지원 브라우저에서 이동이 깨지면 안 된다.** 애니메이션만 빠진다.
- **대시보드(`(dashboard)` 그룹)는 범위 밖.** 건드리지 않는다.
- 전환 길이: 문 **0.4초**, 페이드 **0.22초**.
- 검증은 `npx tsc --noEmit` + `npx eslint` + **실제 브라우저 클릭**. 이 저장소의 `web/` 에는 테스트 러너가 없고, 이번 변경을 위해 도입하지 않는다(YAGNI).

### 사전 확인된 사실 (재조사 불필요)

이 계획을 쓰기 전에 설치된 패키지에서 직접 확인했다:

| 사실 | 근거 |
|---|---|
| `experimental.viewTransition` 설정이 존재 | `node_modules/next/dist/docs/01-app/03-api-reference/05-config/01-next-config-js/viewTransition.md` |
| `Link` 에 `transitionTypes?: string[]` 가 타입에 있음 | `node_modules/next/dist/client/link.d.ts:102` |
| React 가 `ViewTransition` 을 그대로 export (`unstable_` 아님) | `node_modules/next/dist/compiled/react/cjs/react.development.js` 의 `exports.ViewTransition` |
| **타입은 `@types/react/canary.d.ts` 에만 있다** | `node_modules/@types/react/canary.d.ts` — `index.d.ts` 에는 없다. 참조를 추가하지 않으면 타입 에러가 난다 |
| `ViewTransitionProps` 의 `enter`/`exit`/`default` 는 `Record<"default" \| string, "none" \| "auto" \| string>` 를 받음 | 같은 파일 46~64행 |

---

### Task 1: 기본 페이드 (설정 · 타입 · 래퍼)

문 연출이 얹힐 토대다. 이 태스크만 끝나도 **`(site)` 안의 이동이 부드러워지는** 것이 눈으로 보인다.

**Files:**
- Modify: `web/next.config.ts`
- Create: `web/types/react-canary.d.ts`
- Modify: `web/app/(site)/layout.tsx`
- Modify: `web/app/globals.css`

**Interfaces:**
- Consumes: 없음(첫 태스크)
- Produces: `(site)` 레이아웃의 `<ViewTransition>` 래퍼. Task 2 가 이 래퍼의 `enter` 매핑에 `door` 항목을 <추가>한다. CSS 클래스 이름 `fade` 를 정의하고, Task 2 는 같은 방식으로 `door` 를 정의한다.

- [ ] **Step 1: View Transitions 설정을 켠다**

`web/next.config.ts` 전체를 아래로 교체:

```ts
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  experimental: {
    /**
     * 라우트 이동에 View Transitions 를 쓴다(페이지 전환 연출).
     * ⚠️ experimental 이다 — Next 를 올릴 때 이름이 바뀌거나 빠질 수 있다.
     *    그래도 안전한 이유: 이 값이 사라지면 애니메이션만 없어지고 이동은 그대로 된다.
     */
    viewTransition: true,
  },
};

export default nextConfig;
```

- [ ] **Step 2: `ViewTransition` 의 타입을 켠다**

`web/types/react-canary.d.ts` 를 새로 만든다:

```ts
/// <reference types="react/canary" />

/*
 * `ViewTransition` 은 React 가 실제로 export 하는데(Next 이 품은 react 에서 확인),
 * 타입은 `@types/react/index.d.ts` 가 아니라 `canary.d.ts` 에 들어 있다.
 * 이 한 줄이 없으면 `import { ViewTransition } from "react"` 가 타입 에러가 난다.
 * tsconfig 의 include 가 `**/*.ts` 라 이 파일은 자동으로 잡힌다.
 */
export {};
```

- [ ] **Step 3: 타입이 실제로 잡히는지 확인**

Run: `cd web && npx tsc --noEmit`
Expected: 에러 없이 종료(출력 없음). 여기서 실패하면 다음 단계로 가지 말 것 — 래퍼를 넣어도 같은 이유로 막힌다.

- [ ] **Step 4: `(site)` 레이아웃의 children 을 래퍼로 감싼다**

`web/app/(site)/layout.tsx` 의 import 줄 바로 아래에 추가:

```tsx
import { ViewTransition } from "react";
```

그리고 `<main className="flex-1">{children}</main>` 을 아래로 교체:

```tsx
      {/*
        ── 페이지 전환 ────────────────────────────────────────────────────────
        `<Link>` 가 붙인 이름표(transitionTypes)를 <CSS 클래스로 바꿔주는> 것이 이 래퍼다.
        래퍼 없이 이름표만 주면 아무 일도 일어나지 않는다.
        `default: "fade"` 는 이름표가 없는 이동(= 대부분의 이동) 몫이다.
        ⚠️ 공식 예제는 여기에 "none" 을 써서 첫 로드에 아무것도 안 걸리게 한다.
           우리는 페이지끼리의 이동에 페이드가 필요해서 "fade" 로 둔다 —
           대신 첫 로드에도 걸릴 수 있어서 Step 6 에서 그걸 눈으로 확인한다.
      */}
      <main className="flex-1">
        <ViewTransition enter={{ default: "fade" }} exit={{ default: "fade" }}>
          {children}
        </ViewTransition>
      </main>
```

- [ ] **Step 5: 페이드 CSS 를 넣는다**

`web/app/globals.css` 의 맨 끝에 추가:

```css
/* ── 페이지 전환 ────────────────────────────────────────────────────────────
   `(site)/layout.tsx` 의 <ViewTransition> 이 이름표를 이 클래스로 바꿔준다.
   ⚠️ 선택자가 `.fade` 인 것은 <클래스>라는 뜻이다(요소 이름이 아니라).
      view-transition-class 규칙이라 점을 빼면 매칭되지 않는다. */
::view-transition-old(.fade) {
  animation: adPageFade 0.22s ease both reverse;
}
::view-transition-new(.fade) {
  animation: adPageFade 0.22s ease both;
}
@keyframes adPageFade {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}
```

그리고 기존 `@media (prefers-reduced-motion: reduce) { ... }` 블록 안, `.alldap-arm { transition: none; }` 바로 뒤에 추가:

```css
  /* 화면 전체가 움직이는 연출이라 이 설정을 켠 사용자가 가장 피하고 싶은 것이다.
     이동 자체는 그대로 되고 <애니메이션만> 사라진다. */
  ::view-transition-old(.fade),
  ::view-transition-new(.fade) {
    animation: none;
  }
```

- [ ] **Step 6: 브라우저에서 실제로 확인**

`web` 개발 서버가 떠 있어야 한다. 확인 순서:

1. `http://localhost:3000/features` 를 연다.
2. 헤더의 `FAQ` 를 **클릭**한다 → 내용이 페이드로 바뀌는지 본다(툭 끊기지 않아야 한다).
3. `http://localhost:3000/demo` 를 **새로고침**한다 → 첫 로드가 굼떠 보이는지 본다.
   - 굼떠 보이면: Step 4 의 `enter`/`exit` 를 `{ default: "none" }` 으로 바꾸고 페이드를 포기한다.
     스펙에 적힌 결정이다 — 첫인상이 느린 것이 페이드가 없는 것보다 나쁘다.

⚠️ **CSS 를 강제로 주입해 "보이는지" 만 확인하지 말 것.** 같은 저장소에서 로봇 말풍선을
그렇게 검증했다가 틀렸다 — CSS 가 맞는 것과 실제로 동작하는 것은 다른 사실이다.

- [ ] **Step 7: 타입·lint 확인**

Run: `cd web && npx tsc --noEmit && npx eslint "app/(site)/layout.tsx"`
Expected: 둘 다 출력 없이 통과.

- [ ] **Step 8: 커밋**

```bash
git add web/next.config.ts web/types/react-canary.d.ts "web/app/(site)/layout.tsx" web/app/globals.css
git commit -m "feat: 페이지 전환에 은은한 페이드를 넣었다"
```

---

### Task 2: 문 열림 전환

랜딩에서 나가는 **두 링크에만** 걸리는 연출. Task 1 의 래퍼와 CSS 규칙 위에 얹는다.

**Files:**
- Modify: `web/app/(site)/layout.tsx` (Task 1 이 만든 `<ViewTransition>` 의 `enter` 매핑에 `door` 추가)
- Modify: `web/app/globals.css`
- Modify: `web/components/ReceptionHero.tsx` (링크 2개)

**Interfaces:**
- Consumes: Task 1 의 `<ViewTransition enter={{ default: "fade" }} exit={{ default: "fade" }}>` 래퍼와 `::view-transition-*(.fade)` 규칙.
- Produces: 전환 타입 이름 `"door"`. 앞으로 문 연출이 필요한 링크는 `transitionTypes={["door"]}` 만 붙이면 된다.

- [ ] **Step 1: 래퍼에 `door` 매핑을 추가한다**

`web/app/(site)/layout.tsx` 의 `<ViewTransition ...>` 여는 태그를 아래로 교체:

```tsx
        <ViewTransition
          enter={{ door: "door", default: "fade" }}
          exit={{ door: "none", default: "fade" }}
        >
```

⚠️ **`exit` 의 `door` 가 `"none"` 인 것이 중요하다.** 문 연출은 <도착 페이지가 열리는 것>만
재생한다(스펙의 결정). 떠나는 쪽에도 애니메이션을 걸면 이동 하나가 두 배로 길어진다.

- [ ] **Step 2: 문 열림 CSS 를 넣는다**

`web/app/globals.css` 의 `@keyframes adPageFade { ... }` 바로 뒤에 추가:

```css
/* 문 열림 — 랜딩에서 나가는 링크에만 걸린다(transitionTypes={["door"]}).
   문짝 DOM 을 만들지 않는다. 도착 페이지 스냅샷을 가운데 틈만 남기고 가렸다가
   양옆으로 벌리면, 그게 곧 문이 열리는 그림이다. */
::view-transition-new(.door) {
  animation: adDoorOpen 0.4s cubic-bezier(0.4, 0, 0.2, 1) both;
}
@keyframes adDoorOpen {
  from {
    clip-path: inset(0 50% 0 50%);
  }
  to {
    clip-path: inset(0 0 0 0);
  }
}
```

그리고 `@media (prefers-reduced-motion: reduce)` 블록 안의 `.fade` 규칙 바로 뒤에 추가:

```css
  ::view-transition-new(.door) {
    animation: none;
  }
```

- [ ] **Step 3: 랜딩의 두 링크에 이름표를 붙인다**

`web/components/ReceptionHero.tsx` 에서 두 군데를 고친다.

**① 로봇 링크** — `<Link` 로 시작해 `ref={robotHitRef}` 를 가진 곳. `href="/demo"` 줄 <아래>에 두 줄을 넣는다:

```tsx
            <Link
              ref={robotHitRef}
              href="/demo"
              /* 이 화면은 문을 열고 들어온 곳이다. 나갈 때도 문이 열리며 도착해야
                 앞뒤가 이어진다. 이름표만 붙이고 <모양은 globals.css 가> 정한다. */
              transitionTypes={["door"]}
              aria-label="데모 페이지에서 직접 테스트해보기 — 이 봇이 학습한 문서를 전부 볼 수 있습니다"
              className="alldap-robot-hit"
```

**② CTA 링크** — `className="alldap-cta"` 를 가진 곳. 여는 태그를 아래로 교체한다
(원래 한 줄짜리라 여러 줄로 편다):

```tsx
              <Link
                href="/auth"
                /* 위 로봇 링크와 같은 이유다. 랜딩에서 나가는 링크는 둘뿐이고 둘 다 문이다. */
                transitionTypes={["door"]}
                className="alldap-cta"
                style={{ display: "flex", alignItems: "center", gap: 14, cursor: "pointer", padding: "26px 48px", borderRadius: 14, background: "#171514", color: "#FFFFFF", fontSize: 21, fontWeight: 600, letterSpacing: "-0.015em", textDecoration: "none", boxShadow: "0 22px 54px rgba(74,50,46,.32)" }}
              >
```

⚠️ **`style` 의 값을 바꾸지 말 것.** 위 코드는 지금 파일에 있는 값을 그대로 옮긴 것이다
(줄만 폈다). 값이 다르면 잘못 옮긴 것이니 파일 쪽을 믿는다.

- [ ] **Step 4: 타입·lint 확인**

Run: `cd web && npx tsc --noEmit && npx eslint components/ReceptionHero.tsx "app/(site)/layout.tsx"`
Expected: 둘 다 출력 없이 통과.

- [ ] **Step 5: 브라우저에서 실제로 확인**

1. `http://localhost:3000` 을 연다.
2. 스크롤(휠)을 **세 번** 해서 문 2개를 지나 로봇이 나올 때까지 간다.
   - 한 번에 한 단계씩 움직인다. 전환 중(약 1.15초)에는 입력이 무시된다.
3. **`고용하기` 를 클릭** → `/auth` 가 가운데서 양옆으로 열리며 드러나는지 본다.
4. 뒤로 가기로 랜딩에 돌아와 다시 로봇까지 간 뒤, **로봇을 클릭** → `/demo` 도 같은지 본다.
5. `/features` → `FAQ` 로 이동해 **페이드는 그대로인지** 확인한다(문이 아니어야 한다).

- [ ] **Step 6: 떠나는 화면이 이중으로 움직이지 않는지 본다**

Step 5 에서 문이 열리는 동안 **뒤쪽(떠나는 랜딩)이 같이 크로스페이드로 흐려지면**,
루트 스냅샷의 기본 애니메이션이 함께 도는 것이다. 그러면 `globals.css` 에 아래를 추가한다:

```css
/* 문 연출 중에는 루트(화면 전체) 기본 크로스페이드를 끈다.
   문이 열리는 것과 배경이 흐려지는 것이 겹치면 무엇이 움직이는지 읽히지 않는다. */
html:active-view-transition-type(door)::view-transition-old(root),
html:active-view-transition-type(door)::view-transition-new(root) {
  animation: none;
}
```

겹쳐 보이지 않으면 **추가하지 않는다.** 안 겪은 문제를 위해 규칙을 늘리지 않는다.

- [ ] **Step 7: 흔들림 최소화 설정에서 확인**

macOS: 시스템 설정 → 손쉬운 사용 → 디스플레이 → **동작 줄이기** 를 켜고 브라우저를 새로고침한다.
`고용하기` 와 `FAQ` 를 각각 눌러 **애니메이션 없이 즉시 이동**하는지 본다(이동은 정상이어야 한다).
확인 후 설정을 되돌린다.

- [ ] **Step 8: 커밋**

```bash
git add "web/app/(site)/layout.tsx" web/app/globals.css web/components/ReceptionHero.tsx
git commit -m "feat: 랜딩에서 나가는 링크에 문 열림 전환을 붙였다"
```

---

## 완료 조건

- [ ] `고용하기` · 로봇 클릭 시 도착 페이지가 가운데서 열린다(0.4초).
- [ ] `(site)` 안의 다른 이동은 페이드다(0.22초).
- [ ] `prefers-reduced-motion` 에서 둘 다 즉시 이동한다.
- [ ] `npx tsc --noEmit` · `npx eslint` 통과.
- [ ] 대시보드는 손대지 않았다.
