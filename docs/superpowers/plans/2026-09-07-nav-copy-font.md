# 대시보드 소소한 수정 3건(문구·헤더·글꼴) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 대시보드 설명 문구 3개를 지우고, 로그인 뒤에도 랜딩·기능 페이지로 오갈 수 있게 양쪽 헤더를 잇고, 루트 글자 크기를 18px 로 키운다.

**Architecture:** `web/` 만 고친다. 문구는 `PageHeader` 의 `description` 인자만 뺀다. 헤더는 대시보드 쪽에 링크 하나를 더하고, 마케팅 쪽 "로그인" 버튼을 토큰을 아는 클라이언트 컴포넌트(`AuthLink`)로 바꾼다. 글꼴은 `globals.css` 에 `html { font-size }` 한 줄이다.

**Tech Stack:** Next.js 16.2.12 (App Router) · React 19.2.4 · Tailwind v4 · TypeScript

## Global Constraints

- 설계: `docs/superpowers/specs/2026-09-07-nav-copy-font-design.md`
- 브랜치 `fix/nav-copy-font` (이미 `origin/main` 에서 땄고 설계 커밋이 하나 있다). `main` 직접 커밋 금지.
- 커밋 메시지는 `<타입>: <한국어 요약>` 형식 + `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Spring(`api/`)·Python(`ai-service/`)·위젯 스크립트(`widget/`)는 한 줄도 안 고친다.
- 새 의존성 금지. 새 코드에는 한국어 주석으로 "왜"를 남긴다 (AGENTS.md — TypeScript/React 는 설명 필수).
- 검증 명령은 항상 `npx tsc --noEmit && npm run lint`. 자동 테스트는 없다(이 저장소의 `web/` 은 tsc·lint 까지다).
- 모바일 대응은 범위 밖(관리자 화면·마케팅 페이지). 위젯만 좁은 폭을 확인한다.

---

### Task 1: 설명 문구 3개 삭제

**Files:**
- Modify: `web/app/(dashboard)/dashboard/page.tsx:145-148`
- Modify: `web/app/(dashboard)/bot/[botId]/documents/page.tsx:157-160`
- Modify: `web/app/(dashboard)/bot/[botId]/settings/page.tsx:152`

**Interfaces:**
- Consumes: `PageHeader({ title, description?, actions? })` — `web/components/PageHeader.tsx`. `description` 이 이미 선택값이라 컴포넌트는 안 고친다.
- Produces: 없음.

- [ ] **Step 1: 내 봇 화면**

`web/app/(dashboard)/dashboard/page.tsx` 145–148행을

```tsx
      <PageHeader
        title="내 봇"
        description="봇 단위로 문서와 대화가 완전히 격리됩니다. 다른 봇의 문서는 절대 검색되지 않습니다."
      />
```

→ 다음으로 바꾼다.

```tsx
      <PageHeader title="내 봇" />
```

- [ ] **Step 2: 문서 관리 화면**

`web/app/(dashboard)/bot/[botId]/documents/page.tsx` 157–160행을

```tsx
      <PageHeader
        title="문서 관리"
        description="올린 문서만 답변의 근거가 됩니다. 문서에 없는 내용은 지어내지 않고 거절합니다."
      />
```

→

```tsx
      <PageHeader title="문서 관리" />
```

- [ ] **Step 3: 봇 설정 화면**

`web/app/(dashboard)/bot/[botId]/settings/page.tsx` 152행을

```tsx
      <PageHeader title="봇 설정" description="봇 이름과 사용자에게 보이는 문구를 관리합니다." />
```

→

```tsx
      <PageHeader title="봇 설정" />
```

- [ ] **Step 4: 지운 문구를 참조하는 주석이 없는지 확인**

Run:
```bash
cd /Users/cheonjamin/projects/AllDap/web && grep -rn '격리됩니다\|지어내지 않고 거절\|보이는 문구를 관리' app components
```
Expected: 출력 없음. (있으면 그 주석을 지우거나 고친다.)

- [ ] **Step 5: 검증**

Run: `cd /Users/cheonjamin/projects/AllDap/web && npx tsc --noEmit && npm run lint`
Expected: 둘 다 오류 없이 종료.

- [ ] **Step 6: 커밋**

```bash
cd /Users/cheonjamin/projects/AllDap && git add 'web/app/(dashboard)/dashboard/page.tsx' 'web/app/(dashboard)/bot/[botId]/documents/page.tsx' 'web/app/(dashboard)/bot/[botId]/settings/page.tsx' && git commit -m "fix: 대시보드에서 내부 동작을 설명하는 문구 3개를 뺀다

읽어도 사용자가 할 일이 없는 문구(격리·근거 정책·제목 반복)만 지운다.
행동을 바꾸는 안내(테스트 채팅 제외·내보내기 준비 조건)는 남긴다.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: 헤더 잇기 — 대시보드 "소개" 링크 + 마케팅 헤더 `AuthLink`

**Files:**
- Create: `web/components/AuthLink.tsx`
- Modify: `web/app/(site)/layout.tsx:1-5, 43-45`
- Modify: `web/app/(dashboard)/layout.tsx:95-107`

**Interfaces:**
- Consumes: `web/lib/api.ts` 의 `subscribeAccessToken(onChange): () => void` · `getAccessToken(): string | null` · `getAccessTokenServerSnapshot(): string | null | undefined` (대시보드 레이아웃이 같은 셋을 쓴다).
- Produces: `AuthLink()` — 인자 없음. 토큰이 있으면 `/dashboard` "대시보드", 없으면 `/auth` "로그인" 링크를 그린다.

- [ ] **Step 1: `AuthLink` 컴포넌트 생성**

`web/components/AuthLink.tsx`:

```tsx
"use client";

/**
 * 마케팅 헤더 오른쪽 끝의 버튼 — 로그인 전에는 "로그인", 로그인 뒤에는 "대시보드".
 *
 * ── 왜 이것만 클라이언트 컴포넌트인가 ──────────────────────────────────────
 * 감싸는 레이아웃(`app/(site)/layout.tsx`)은 서버 컴포넌트다. 그런데 "로그인했는가"를
 * 알려면 JWT 를 봐야 하고, 그 토큰은 localStorage 에 있다 — 즉 <브라우저에만 있다>.
 * 서버는 요청을 보낸 사람이 누구인지 자체를 모르므로 대신 판단해 줄 수가 없다.
 * (`BotName` 이 봇 이름을 클라이언트에서 가져오는 것과 같은 이유다)
 *
 * 그래서 <이 버튼만> 클라이언트로 내렸다. 레이아웃 전체를 클라이언트로 바꾸면
 * 공개 페이지 전부가 클라이언트 번들에 들어간다.
 *
 * ── 첫 렌더는 항상 "로그인" 이다 ───────────────────────────────────────────
 * useSyncExternalStore 의 세 번째 인자(서버 스냅샷)는 undefined 를 준다 — "아직 모름".
 * 서버 HTML 도, 하이드레이션 첫 렌더도 이 값을 쓰므로 둘이 "로그인" 으로 일치하고
 * (불일치면 React 가 경고하고 화면이 깨진다), 하이드레이션이 끝난 뒤 실제 토큰을 읽어
 * "대시보드" 로 바뀐다. 로그인한 사람에게만 한 프레임 깜빡임이 있다 — 하이드레이션
 * 불일치를 내지 않는 유일한 방법이라 받아들인다.
 * undefined(아직 모름)와 null(확실히 없음)을 여기서는 <같이> "로그인" 으로 그린다.
 * 대시보드 가드는 둘을 갈라야 했지만(null 만 튕김) 이 버튼은 어느 쪽이든 보여줄 글자가 같다.
 */

import Link from "next/link";
import { useSyncExternalStore } from "react";
import {
  getAccessToken,
  getAccessTokenServerSnapshot,
  subscribeAccessToken,
} from "@/lib/api";

const CLASS_NAME = "ml-2 rounded-lg bg-foreground px-4 py-2 font-medium text-surface";

export function AuthLink() {
  const token = useSyncExternalStore(
    subscribeAccessToken,
    getAccessToken,
    getAccessTokenServerSnapshot,
  );

  return token ? (
    <Link href="/dashboard" className={CLASS_NAME}>
      대시보드
    </Link>
  ) : (
    <Link href="/auth" className={CLASS_NAME}>
      로그인
    </Link>
  );
}
```

- [ ] **Step 2: 마케팅 헤더에서 고정 "로그인" 링크를 `AuthLink` 로 교체**

`web/app/(site)/layout.tsx` 1행 아래에 import 를 추가한다:

```tsx
import Link from "next/link";
import { AuthLink } from "@/components/AuthLink";
```

5행의 주석

```
 * 로그인 전 사용자가 보는 화면이므로 관리자 네비게이션을 넣지 않는다.
```

→

```
 * 관리자 네비게이션은 넣지 않는다. 다만 로그인한 사람도 이 화면에 온다(대시보드 헤더의
 * "소개" → 랜딩 → 기능 페이지). 그래서 오른쪽 끝 버튼만 로그인 여부를 안다(`AuthLink`).
```

43–45행의

```tsx
            <Link href="/auth" className="ml-2 rounded-lg bg-foreground px-4 py-2 font-medium text-surface">
              로그인
            </Link>
```

→

```tsx
            <AuthLink />
```

- [ ] **Step 3: 대시보드 헤더에 "소개" 링크 추가**

`web/app/(dashboard)/layout.tsx` 95–107행의

```tsx
          {/* 사용자 이름을 띄우려면 GET /api/auth/me 가 필요한데 아직 없다.
              지금은 계정 메뉴 자리에 결제 수단과 로그아웃 둘만 둔다.

              결제 수단이 <봇 화면이 아니라 헤더>에 있는 이유: 청구 대상이 계정이라
              봇을 여러 개 만들어도 카드는 한 장이다. 봇 하위에 두면 "봇마다 카드가
              따로인가?" 라는 잘못된 인상을 준다. 사용량 카드가 /dashboard 에 있는 것과 같은 판단이다. */}
          <div className="flex items-center gap-4">
            <Link
              href="/billing"
              className="text-xs text-muted hover:text-foreground"
            >
              결제 수단
            </Link>
```

→

```tsx
          {/* 사용자 이름을 띄우려면 GET /api/auth/me 가 필요한데 아직 없다.
              지금은 계정 메뉴 자리에 소개·결제 수단·로그아웃 셋만 둔다.

              "소개"(→ 랜딩)가 있는 이유: 로그인하면 랜딩·기능 페이지로 돌아갈 길이 없었다
              (2026-09-07 테스트에서 발견). 랜딩에 "기능" 메뉴가 있고 기능 페이지 상단에서
              요금제·FAQ 로 이어지므로 링크 하나면 공개 페이지 전부에 닿는다.
              반대 방향(마케팅 헤더 → 대시보드)은 components/AuthLink.tsx 가 맡는다.

              결제 수단이 <봇 화면이 아니라 헤더>에 있는 이유: 청구 대상이 계정이라
              봇을 여러 개 만들어도 카드는 한 장이다. 봇 하위에 두면 "봇마다 카드가
              따로인가?" 라는 잘못된 인상을 준다. 사용량 카드가 /dashboard 에 있는 것과 같은 판단이다. */}
          <div className="flex items-center gap-4">
            <Link href="/" className="text-xs text-muted hover:text-foreground">
              소개
            </Link>
            <Link
              href="/billing"
              className="text-xs text-muted hover:text-foreground"
            >
              결제 수단
            </Link>
```

- [ ] **Step 4: 검증**

Run: `cd /Users/cheonjamin/projects/AllDap/web && npx tsc --noEmit && npm run lint`
Expected: 둘 다 오류 없이 종료. (`Link` import 가 `(site)/layout.tsx` 에서 여전히 NAV 링크에 쓰이므로 unused 경고는 없다.)

- [ ] **Step 5: 커밋**

```bash
cd /Users/cheonjamin/projects/AllDap && git add web/components/AuthLink.tsx 'web/app/(site)/layout.tsx' 'web/app/(dashboard)/layout.tsx' && git commit -m "fix: 로그인 뒤에도 랜딩·기능 페이지와 대시보드를 오갈 수 있게 양쪽 헤더를 잇는다

대시보드 헤더에 \"소개\"(→ 랜딩) 링크를 더하고, 마케팅 헤더의 고정 \"로그인\" 버튼을
토큰을 아는 클라이언트 컴포넌트(AuthLink)로 바꿔 로그인 상태면 \"대시보드\" 로 그린다.
토큰이 localStorage 에만 있어 서버 컴포넌트인 레이아웃은 못 읽으므로 버튼만 떼어냈다.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: 루트 글자 크기 18px

**Files:**
- Modify: `web/app/globals.css:58` (`:root {` 바로 앞)

**Interfaces:** 없음.

- [ ] **Step 1: `html` 규칙 추가**

`web/app/globals.css` 58행 `:root {` 바로 앞에 넣는다:

```css
/* ─────────────────────────────────────────────────────────────────────────────
   루트 글자 크기 18px (2026-09-07)
   ─────────────────────────────────────────────────────────────────────────────
   본문 대부분이 text-sm(14px), 보조 글자가 text-xs(12px)였다 — 한국어 UI 로 작다.
   Tailwind 는 크기를 전부 루트 글자 크기 배율(rem)로 계산하므로 이 한 줄이면
   237곳의 클래스를 안 건드리고 전체가 12.5% 비례 확대된다(14 → 15.75 · 12 → 13.5).
   여백·카드 폭도 같이 커져 "확대"한 것처럼 균형이 유지된다.

   ⚠️ 반응형 경계(sm: = 40rem)도 rem 이라 640 → 720px 로 함께 옮겨간다.
      관리자 화면은 데스크톱 전용이라 무관하고, 위젯(/w/[publicKey])은 브라우저로 확인했다.
   ⚠️ 랜딩 히어로 장면은 px 고정값이라 이 값의 영향을 받지 않는다. */
html {
  font-size: 18px;
}
```

- [ ] **Step 2: 검증**

Run: `cd /Users/cheonjamin/projects/AllDap/web && npx tsc --noEmit && npm run lint`
Expected: 오류 없음 (CSS 만 바뀌었으니 통과가 당연하지만 습관으로 돌린다).

- [ ] **Step 3: 커밋**

```bash
cd /Users/cheonjamin/projects/AllDap && git add web/app/globals.css && git commit -m "fix: 루트 글자 크기를 18px 로 올려 전체 UI 를 12.5% 키운다

본문 14px·보조 12px 가 한국어 UI 로 작았다. Tailwind 가 rem 배율이라 한 줄로
237곳이 비례 확대되고 여백도 함께 늘어 균형이 유지된다.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: 브라우저 검증

**Files:** 없음 (검증만). 문제가 나오면 해당 Task 로 돌아가 고친다.

- [ ] **Step 1: 백엔드·프론트 띄우기**

로그인·봇 목록을 보려면 Spring 이 떠 있어야 한다:

```bash
cd /Users/cheonjamin/projects/AllDap && docker compose up -d && (cd api && set -a && . ./.env && set +a && ./gradlew bootRun -q > /tmp/api.log 2>&1 &)
```

프론트는 Browser 도구의 `preview_start` 로 `.claude/launch.json` 의 `web` 설정(포트 3000)을 띄운다. Bash 로 `npm run dev` 를 띄우지 않는다.

- [ ] **Step 2: 로그아웃 상태 — 마케팅 헤더**

`http://localhost:3000/features` 를 열고 `read_page` 로 헤더 오른쪽 버튼이 **"로그인"** 인지 확인. 콘솔에 hydration 경고가 없어야 한다(`read_console_messages`).

- [ ] **Step 3: 로그인 → 대시보드 헤더 → 소개 → 기능 → 대시보드**

`/auth` 에서 로그인한 뒤:
1. `/dashboard` 헤더에 **소개 · 결제 수단 · 로그아웃** 셋이 보이고, "내 봇" 제목 아래 설명 문구가 **없어야** 한다. 스크린샷.
2. "소개" 클릭 → `/` 랜딩 도달.
3. `/features` 로 이동 → 헤더 오른쪽 버튼이 **"대시보드"** 여야 한다. 스크린샷. 콘솔 hydration 경고 없음.
4. "대시보드" 클릭 → `/dashboard` 복귀.

- [ ] **Step 4: 문서 관리·봇 설정 화면**

봇 하나를 골라 `/bot/{id}/documents` · `/bot/{id}/settings` 를 열고 제목 아래 설명 문구가 없는지 `read_page` 로 확인. `/bot/{id}/chat` 은 "이 대화는 품질 지표에서 제외됩니다" 가 **남아 있어야** 한다.

- [ ] **Step 5: 글자 크기**

`javascript_tool` 로 `getComputedStyle(document.documentElement).fontSize` → `"18px"`, 본문 `text-sm` 요소 하나의 `fontSize` → `"15.75px"` 확인. 대시보드 스크린샷 1장.

- [ ] **Step 6: 위젯 폭**

`resize_window` 로 `width: 400, height: 700` 으로 줄인 뒤 `http://localhost:3000/w/pk_local_dev` 를 연다(로더 없이 열면 입력창만 보이는 것이 정상 — AGENTS.md "아직 안 고친 것"). 입력창·글자가 잘리거나 가로 스크롤이 생기지 않는지 스크린샷으로 확인. 끝나면 `resize_window preset: desktop` 으로 되돌린다.
너무 크면 사용자에게 보고하고 위젯 레이아웃에서만 되돌리는 방법을 제안한다(이 계획에는 없다 — 사용자 결정).

- [ ] **Step 7: 결과 보고**

스크린샷과 함께 확인한 항목·확인 못 한 항목을 그대로 보고한다. PR 은 사용자 확인 뒤 연다(PR 본문은 `.github/PULL_REQUEST_TEMPLATE.md` 를 채운다).
