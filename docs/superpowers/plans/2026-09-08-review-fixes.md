# 코드 리뷰 지적 24건 정리 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 운영에 배포된 오픈 리다이렉트를 닫고, 그것이 통과한 원인(짜둔 검사가 안 돌던 것)을 CI 로 막고, `/account` 화면 결함 세 건과 낡은 주석을 정리한다.

**Architecture:** 설계(`docs/superpowers/specs/2026-09-08-review-fixes-design.md`)의 네 묶음을 그대로 따른다. 묶음 ①은 브랜치 `fix/redirect-open-redirect` 에서 Task 1~3, 묶음 ②는 `main` 직행으로 Task 4, 묶음 ③·④는 브랜치 `fix/account-card-states` 에서 Task 5~8.

**Tech Stack:** Next.js 16.2.12 / React 19.2.4 / TypeScript 5 (`web/`), Spring Boot 4 / Java 21 (`api/`), GitHub Actions (`.github/workflows/ci.yml`)

## Global Constraints

- **em dash 문자를 쓰지 않는다.** 코드, 주석, 커밋 메시지, PR 본문, 문서 전부. 쉼표나 콜론, 괄호, 마침표로 대체한다. 이미 파일에 있던 것은 건드리지 않는다.
- 코드 주석과 사용자에게 보이는 에러 메시지는 **한국어**로 쓴다. 에러는 "무엇을 어떻게 하면 되는지"까지 담는다.
- 커밋 메시지 형식: `<타입>: <한국어 요약>` (feat / fix / refactor / test / docs / chore / review). 본문 끝에 `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- PR 본문은 `.github/PULL_REQUEST_TEMPLATE.md` 를 채운다. "한계 & 트레이드오프" 와 "검토한 대안" 두 칸이 핵심이다. 끝에 `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
- 프론트 로컬 검사: `cd web && npx tsc --noEmit && npm run lint && npm run check`
  (`check` 는 Task 2 가 만든다. 그 전에는 마지막 명령을 뺀다)
- 백엔드 로컬 검사: `cd api && ./gradlew test`
- **`main` 푸시는 Vercel 자동 배포다.** Task 4 는 밀기 전에 반드시 로컬 검사를 통과시킨다.
- **PR 은 올리기만 하고 CI 결과를 기다리지 않는다.** `gh pr create` 까지가 범위다.
- 설계 결정은 `docs/decisions.md` 에 `날짜 | 무엇을 | 왜 그렇게 | 검토한 대안` 한 줄로 남긴다.
- 프론트 코드를 쓰기 전 필요하면 `web/node_modules/next/dist/docs/` 를 읽는다. 기억에 의존해 구버전 문법을 쓰지 않는다.

---

## 파일 구조

| 파일 | 책임 | 어느 Task |
|---|---|---|
| `web/lib/redirect.ts` | `?next=` 값을 같은 사이트 경로로만 좁히는 순수 함수 | 1 |
| `web/lib/redirect.check.ts` | 위 함수의 자체 점검. 실패하면 `process.exit(1)` | 1, 2 |
| `web/package.json` | `tsx` devDependency 와 `check` 스크립트 | 2, 5, 7 |
| `.github/workflows/ci.yml` | web 잡에 로직 검사 단계 | 2 |
| `web/app/(site)/auth/page.tsx` | 로그인 화면. 이동 중 문구 | 3 |
| `web/components/AuthLink.tsx` | 공개 헤더의 로그인/대시보드 버튼. `?next=` 를 붙이는 유일한 곳 | 3 |
| `AGENTS.md` | `?next=` 항목의 사실과 한계 | 3 |
| `web/lib/plans.ts` | 요금제 정의(숫자의 유일한 원본)와 `resolvePlan` | 4, 7 |
| `web/lib/plans.check.ts` | `resolvePlan` 의 세 갈래가 안 뭉개지는지 | 7 |
| `web/lib/wallet.ts` | 카드 상태에서 <무엇을 그릴지> 판단만. 마크업 없음 | 5 |
| `web/lib/wallet.check.ts` | 위 판단의 자체 점검 | 5 |
| `web/app/(site)/pricing/page.tsx` | 요금제 페이지. 머리 주석(4), metadata·앵커 섹션(7) | 4, 7 |
| `web/app/(site)/layout.tsx` | 공개 화면 공통 레이아웃 | 4 |
| `api/src/main/java/com/alldap/api/global/exception/ErrorCode.java` | 에러 코드와 안내 문구 | 4 |
| `web/app/(dashboard)/account/page.tsx` | 마이페이지. 카드 지갑과 요금제 확인 | 4, 5, 7 |
| `web/components/PlanCards.tsx` | `/pricing` 의 요금제 카드. 로그인 시 고르기 | 6 |
| `docs/decisions.md` | 결정 로그 | 3, 8 |

---

## Task 1: 오픈 리다이렉트를 닫는다 (TDD)

**Files:**
- Modify: `web/lib/redirect.check.ts` (실패 케이스를 먼저 추가)
- Modify: `web/lib/redirect.ts:45`

**Interfaces:**
- Consumes: 없음 (첫 Task)
- Produces: `safeRedirectPath(raw: string | null, origin: string): string` 의 동작이 바뀐다. 반환값은 항상 `origin` 기준으로 다시 해석해도 `origin` 을 벗어나지 않는 경로다. Task 2 가 이 파일을 CI 에 연결한다.

**배경:** `redirect.ts` 는 입력을 URL 파서에 맡겨 판정하는데, **출력을 검사하지 않는다.** `url.pathname` 이 `//` 로 시작할 수 있어(`/..//evil.com` 이 그렇다) 반환값이 프로토콜 상대 URL 이 되고, 라우터가 다시 해석하면 외부 도메인으로 나간다. 이 취약점은 지금 `https://all-dap.vercel.app` 에 배포돼 있다.

🔴 **브라우저로 실제 항해까지 확인했다 (2026-09-08).** 함수 반환값만 보고 "취약점" 이라 부르지 않기 위해 dev 서버에서 끝까지 눌러봤다.

```
localStorage.setItem('alldap.token', 'fake.jwt.token')
  → http://localhost:3000/auth?next=/..//example.com
  → location.href === "https://example.com/"     (탭 제목 "Example Domain")

대조군: /auth?next=/faq  →  http://localhost:3000/faq   (정상)
```

`/auth` 의 로그인 가드는 토큰이 <있기만> 하면 `router.replace(nextPath())` 를 부르므로 가짜 토큰으로 재현된다. **Next 라우터가 `//example.com` 을 프로토콜 상대 URL 로 해석해 외부 도메인까지 실제로 나간다.**

- [ ] **Step 1: 브랜치를 딴다**

인증·리다이렉트는 `AGENTS.md` 가 "반드시 브랜치 + PR" 로 못박은 영역이다.

```bash
cd /Users/cheonjamin/projects/AllDap
git switch -c fix/redirect-open-redirect
```

- [ ] **Step 2: 실패하는 검사를 먼저 추가한다**

`web/lib/redirect.check.ts` 의 `check("로그인 화면 자기 자신", "/auth", DEFAULT_AFTER_AUTH);` 줄 **바로 아래**에 붙인다.

```ts

// ── 🔴 2026-09-08 코드 리뷰에서 나온 구멍 ──────────────────────────────
// 입력은 파서에게 맡겨놓고 <출력>을 검사하지 않아서, url.pathname 이 "//" 로 시작하면
// 반환값이 프로토콜 상대 URL 이 됐다. 라우터가 그걸 다시 해석하면 외부로 나간다.
// 이 케이스들이 없어서 구멍이 배포까지 갔다. 이 파일이 먼저 빨간불이 되어야 한다.
check("경로 탈출 뒤 프로토콜 상대", "/..//evil.com", DEFAULT_AFTER_AUTH);
check("점 세그먼트를 섞은 변형", "/./..//evil.com", DEFAULT_AFTER_AUTH);
check("탈출 + 경로 + 쿼리", "/..//evil.com/login?x=1", DEFAULT_AFTER_AUTH);
check("우리 origin 뒤에 슬래시 둘", `${ORIGIN}//evil.com`, DEFAULT_AFTER_AUTH);
check("우리 origin 뒤에 역슬래시", `${ORIGIN}/\\/evil.com`, DEFAULT_AFTER_AUTH);

// ── 지금도 통과하지만 회귀하면 안 되는 것 ──────────────────────────────
// 전부 "우리 도메인처럼 보이는 남의 호스트" 다. 파서가 이미 갈라주고 있다는 것을
// 검사로 굳혀둔다. 나중에 판정을 손볼 때 이 줄들이 안전망이 된다.
check("userinfo 로 위장한 호스트", "https://alldap.example@evil.com", DEFAULT_AFTER_AUTH);
check("접미사로 위장한 호스트", "https://alldap.example.evil.com", DEFAULT_AFTER_AUTH);
check("같은 호스트 다른 포트", `${ORIGIN}:8443/x`, DEFAULT_AFTER_AUTH);
check("대문자 스킴", "HTTPS://EVIL.COM", DEFAULT_AFTER_AUTH);
check("blob: 스킴", "blob:https://evil.com/x", DEFAULT_AFTER_AUTH);
```

⚠️ `ORIGIN` 은 이 파일 상단에 `"https://alldap.example"` 로 정의돼 있다. userinfo 케이스는 템플릿 문자열로 조립하면 읽기 어려워져 값을 그대로 적었다.

- [ ] **Step 3: 검사를 돌려 빨간불을 확인한다**

Run: `cd web && npx tsx lib/redirect.check.ts`

Expected: 종료코드 1. 다음 5줄이 `❌` 로 찍힌다.

```
  ❌ 경로 탈출 뒤 프로토콜 상대
       "/..//evil.com" → //evil.com  (기대: /dashboard)
  ❌ 점 세그먼트를 섞은 변형
  ❌ 탈출 + 경로 + 쿼리
  ❌ 우리 origin 뒤에 슬래시 둘
  ❌ 우리 origin 뒤에 역슬래시
🔴 5건 실패
```

🔴 **5건이 아니라 0건 실패가 나오면 멈춘다.** 그 경우 취약점 재현이 안 된 것이므로 `ORIGIN` 값과 케이스 문자열을 다시 확인한다.

- [ ] **Step 4: `redirect.ts` 를 고친다**

`web/lib/redirect.ts` 의 마지막 두 줄

```ts
  // pathname 부터 다시 조립한다. 원본 문자열을 그대로 쓰면 위에서 정규화한 것이 무의미해진다.
  return url.pathname + url.search + url.hash;
```

을 아래로 바꾼다.

```ts
  // pathname 부터 다시 조립한다. 원본 문자열을 그대로 쓰면 위에서 정규화한 것이 무의미해진다.
  const path = url.pathname + url.search + url.hash;

  // 🔴 조립한 <결과>를 한 번 더 파서에게 물어본다 (2026-09-08 코드 리뷰).
  //    위 판정을 통과해도 url.pathname 이 "//" 로 시작할 수 있다. "/..//evil.com" 이 그렇다:
  //    파서가 ".." 로 한 단계 올라가면서 남은 "//evil.com" 이 통째로 경로가 된다.
  //    그 값을 라우터가 다시 해석하면 프로토콜 상대 URL 이라 https://evil.com 으로 나간다.
  //    입력에 쓴 원칙("모양을 우리가 판정하지 않고 파서에게 맡긴다")을 출력에도 그대로 적용한다.
  //    startsWith("//") 한 줄로도 막히지만, 그건 이 파일이 명시적으로 기각한 방식이다.
  try {
    if (new URL(path, origin).origin !== origin) return DEFAULT_AFTER_AUTH;
  } catch {
    return DEFAULT_AFTER_AUTH;
  }

  return path;
```

- [ ] **Step 5: 검사를 돌려 초록불을 확인한다**

Run: `cd web && npx tsx lib/redirect.check.ts`

Expected: 종료코드 0. 22줄 전부 `✅`. 특히 아래 두 줄이 **그대로 통과**해야 한다. 통과가 정답인 케이스라 함께 막히면 과잉 차단이다.

```
  ✅ 슬래시 하나짜리 변형 — 내부 경로로 정규화된다
       "https:/evil.com" → /evil.com
  ✅ 쿼리·해시 유지
       "/features?tab=a#b" → /features?tab=a#b
```

- [ ] **Step 6: 타입과 린트를 통과시킨다**

Run: `cd web && npx tsc --noEmit && npm run lint`
Expected: 둘 다 출력 없이 종료코드 0.

- [ ] **Step 7: 커밋**

```bash
cd /Users/cheonjamin/projects/AllDap
git add web/lib/redirect.ts web/lib/redirect.check.ts
git commit -m "fix: 오픈 리다이렉트를 막는다. 반환값도 파서에게 다시 물어본다

safeRedirectPath 는 입력을 URL 파서에 맡겨 판정했는데 출력을 검사하지 않았다.
url.pathname 이 // 로 시작할 수 있어서(\"/..//evil.com\" 이 그렇다) 반환값이
프로토콜 상대 URL 이 되고, 라우터가 다시 해석하면 외부 도메인으로 나갔다.

이 파일이 세운 원칙은 \"모양을 우리가 판정하지 않고 파서에게 맡긴다\" 인데
그 원칙을 입력에만 적용하고 출력에는 적용하지 않은 것이 원인이다.
조립한 경로를 origin 기준으로 한 번 더 해석해 origin 이 바뀌면 기본값으로 돌린다.

검사를 먼저 빨간불로 만든 뒤 고쳤다. 케이스 12가지에서 22가지로 늘렸다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 2: 그 검사를 CI 에 연결한다

**Files:**
- Modify: `web/package.json`
- Modify: `web/package-lock.json` (npm 이 자동으로 고친다)
- Modify: `web/lib/redirect.check.ts:43` 부근 (손으로 적은 개수를 카운터로)
- Modify: `.github/workflows/ci.yml` (web 잡)

**Interfaces:**
- Consumes: Task 1 이 고친 `redirect.check.ts`
- Produces: `npm run check` 스크립트. CI 의 web 잡이 이걸 돌린다.

**배경:** `redirect.check.ts` 는 있었지만 **아무 데서도 돌지 않았다.** `tsx` 가 의존성에 없고 CI web 잡은 `npm ci` / `npm run lint` / `npm run build` 셋뿐이었다. 이 사고의 구조적 원인은 검사를 안 짠 것이 아니라 짜둔 검사가 안 돈 것이므로, 수정과 같은 PR 에 둔다. 나누면 "고쳤는데 안 도는 검사" 가 남는다.

- [ ] **Step 1: `tsx` 를 devDependency 로 설치한다**

```bash
cd /Users/cheonjamin/projects/AllDap/web
npm install --save-dev tsx
```

Expected: `package.json` 의 `devDependencies` 에 `"tsx": "^4.x.x"` 가 생기고 `package-lock.json` 이 갱신된다.

- [ ] **Step 2: `check` 스크립트를 추가한다**

`web/package.json` 의 `scripts` 를 아래로 바꾼다.

```json
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "lint": "eslint",
    "check": "tsx lib/redirect.check.ts"
  },
```

- [ ] **Step 3: 스크립트가 도는지 확인한다**

Run: `cd web && npm run check`
Expected: 22줄 전부 `✅`, 종료코드 0.

- [ ] **Step 4: 손으로 적은 개수를 카운터로 바꾼다**

`web/lib/redirect.check.ts` 에서 아래 세 자리를 고친다.

먼저 `let failed = 0;` 아래에 한 줄 추가:

```ts
let failed = 0;
/* 통과 개수를 손으로 적어두면 케이스를 늘릴 때마다 어긋난다. 실제로 "12가지" 로 굳어 있었다. */
let total = 0;
```

`check` 함수 안 맨 앞에 한 줄 추가:

```ts
function check(label: string, raw: string | null, expected: string) {
  total++;
  const got = safeRedirectPath(raw, ORIGIN);
```

마지막 줄을 바꾼다:

```ts
console.log(failed === 0 ? `\nOK: ${total}가지 통과` : `\n🔴 ${failed}건 실패`);
```

- [ ] **Step 5: CI 에 단계를 건다**

`.github/workflows/ci.yml` 의 web 잡에서 아래 부분을

```yaml
      # web/package.json 의 scripts.lint 는 "eslint" 이고
      # web/eslint.config.mjs (flat config) 가 있는 걸 확인했다.
      - name: 린트
        run: npm run lint
```

아래로 바꾼다.

```yaml
      # web/package.json 의 scripts.lint 는 "eslint" 이고
      # web/eslint.config.mjs (flat config) 가 있는 걸 확인했다.
      - name: 린트
        run: npm run lint

      # 🔴 이 단계가 없어서 2026-09-08 까지 오픈 리다이렉트가 살아 있었다.
      # lib/redirect.check.ts 는 그전부터 있었지만 아무 데서도 돌지 않았다.
      # 검사를 짜두는 것과 검사가 도는 것은 다른 일이다.
      # 실패하면 그 파일이 process.exit(1) 을 하므로 잡이 빨간불이 된다.
      - name: 로직 안전성 검사
        run: npm run check
```

- [ ] **Step 6: 로컬 검사를 통과시킨다**

Run: `cd web && npx tsc --noEmit && npm run lint && npm run check`
Expected: 셋 다 종료코드 0.

- [ ] **Step 7: 커밋**

```bash
cd /Users/cheonjamin/projects/AllDap
git add web/package.json web/package-lock.json web/lib/redirect.check.ts .github/workflows/ci.yml
git commit -m "chore: 리다이렉트 자체 점검을 CI 에서 돌린다

lib/redirect.check.ts 는 있었지만 실행기(tsx)가 의존성에 없었고
CI 의 web 잡은 npm ci / lint / build 셋뿐이었다. 그래서 이 검사는
저장소에 존재하기만 하고 한 번도 돌지 않았다.

앞 커밋이 막은 구멍이 배포까지 간 원인이 이것이다.
tsx 를 devDependency 로 넣고 check 스크립트를 만들어
CI 의 lint 다음에 걸었다.

통과 개수를 손으로 적어둔 것(\"12가지\")도 카운터로 바꿨다.
케이스를 늘릴 때마다 어긋나는 값이다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 3: 리다이렉트 주변 Minor 2건, 문서 갱신, PR 올리기

**Files:**
- Modify: `web/app/(site)/auth/page.tsx:161`
- Modify: `web/components/AuthLink.tsx` (주석 한 줄 추가)
- Modify: `AGENTS.md:359`
- Modify: `docs/decisions.md` (끝에 한 줄)

**Interfaces:**
- Consumes: Task 1, 2 의 커밋
- Produces: PR 번호 하나. Task 4 는 이 PR 과 무관하게 `main` 에서 진행한다.

- [ ] **Step 1: 이동 중 문구가 거짓말하지 않게 고친다**

`web/app/(site)/auth/page.tsx:161` 의

```tsx
  if (token) return <p className="px-6 py-16 text-sm text-muted">대시보드로 이동합니다…</p>;
```

를 아래로 바꾼다. `?next=` 가 있으면 대시보드로 가지 않으므로 목적지를 말하지 않는다.

```tsx
  /* 목적지를 적지 않는다. `?next=` 가 있으면 대시보드가 아니라 있던 자리로 간다. */
  if (token) return <p className="px-6 py-16 text-sm text-muted">이동합니다…</p>;
```

- [ ] **Step 2: `AuthLink` 의 한계를 주석으로 남긴다**

`web/components/AuthLink.tsx` 에서

```tsx
  const href =
    pathname && pathname !== "/auth" ? `/auth?next=${encodeURIComponent(pathname)}` : "/auth";
```

바로 위에 아래 주석을 붙인다.

```tsx
  /*
   * ⚠️ 알고 남긴 한계: `usePathname()` 은 쿼리스트링과 해시를 버린다(Next 16 문서).
   *    그래서 `/pricing#plans` 에서 로그인하면 `/pricing` 으로 돌아온다. 해시가 사라진다.
   *    지금은 실해가 없어서 두었다. 해시로 특정 자리를 겨냥하는 링크가 늘면
   *    `window.location` 을 읽어야 하는데, 그러면 이 컴포넌트가 서버에서 그려질 때
   *    쓸 값이 없어져 하이드레이션을 다시 따져야 한다. 값어치가 생기면 그때 한다.
   */
```

- [ ] **Step 3: `AGENTS.md` 의 `?next=` 서술을 갱신한다**

지금은 기능이 있다고만 적혀 있고, 어디에만 붙는지와 이번 사고가 빠져 있다.

```bash
cd /Users/cheonjamin/projects/AllDap
python3 - <<'PY'
p = "AGENTS.md"
s = open(p).read()
old = "**로그인·가입 뒤 있던 페이지로 복귀**(`?next=`, 오픈 리다이렉트 검증은 `web/lib/redirect.ts`)"
new = (
    "**로그인·가입 뒤 있던 페이지로 복귀**(`?next=`, 오픈 리다이렉트 검증은 `web/lib/redirect.ts`. "
    "자체 점검 `web/lib/redirect.check.ts` 는 2026-09-08 부터 CI 에서 돈다). "
    "🔴 **`?next=` 를 붙이는 곳은 공개 헤더(`AuthLink`) 하나뿐이다.** 대시보드 세션 만료 가드"
    "(`app/(dashboard)/layout.tsx`)는 안 붙인다 (붙이면 비로그인 상태의 주소창에 봇 UUID 가 남는다). "
    "🔴 **2026-09-08 에 이 자리에서 오픈 리다이렉트가 뚫린 채 배포됐다:** `url.pathname` 이 `//` 로 "
    "시작하면 반환값이 프로토콜 상대 URL 이 되어 라우터가 외부로 나갔다. 원인은 검사를 안 짠 것이 "
    "아니라 **짜둔 검사가 아무 데서도 안 돈 것**이다"
)
assert old in s, "AGENTS.md 의 대상 문장을 찾지 못했다. 손으로 확인할 것"
open(p, "w").write(s.replace(old, new))
print("ok")
PY
```

Expected: `ok` 출력.

- [ ] **Step 4: `docs/decisions.md` 에 결정을 남긴다**

파일 끝에 빈 줄 하나를 두고 아래 한 줄을 추가한다.

```
2026-09-08 | 오픈 리다이렉트를 `startsWith("//")` 한 줄이 아니라 <반환값을 파서에게 다시 물어보는> 왕복 검증으로 막았고, 수정과 CI 연결을 같은 PR 에 넣었다 | `safeRedirectPath` 는 입력을 URL 파서에 맡겨 판정하면서 출력은 검사하지 않았다. `url.pathname` 이 `//` 로 시작할 수 있어서(`/..//evil.com`) 반환값이 프로토콜 상대 URL 이 되고, 라우터가 다시 해석하면 외부로 나간다. 실제로 배포된 상태였다. 한 줄짜리 문자열 검사로도 막히지만 이 파일이 세운 원칙이 "모양을 우리가 판정하지 않고 파서에게 맡긴다" 이고, **구멍이 난 이유가 그 원칙을 출력에는 적용하지 않은 것**이라 원칙을 어기는 방식으로 메우면 같은 자리가 또 뚫린다. 🔴 CI 연결을 같은 PR 에 넣은 이유가 더 중요하다: `redirect.check.ts` 는 그전에도 있었는데 `tsx` 가 의존성에 없고 CI 단계도 없어 **한 번도 돈 적이 없었다.** 검사를 짜두는 것과 검사가 도는 것은 다른 일이고, 나누면 "고쳤는데 안 도는 검사" 가 그대로 남는다 | ① `url.pathname.startsWith("//")` 한 줄: 실제로 막히지만 위 이유로 기각 ② 절대 URL(`url.href`)을 반환하고 라우터에 맡기기: 반환 타입이 바뀌어 `AuthLink` 등 호출부가 전부 영향을 받고, 개발과 운영에서 origin 이 달라 새 경우의 수가 생긴다 ③ `tsx` 없이 Node 네이티브 타입 스트리핑(22.18+)으로 검사 실행: import 에 `.ts` 확장자가 필요해 tsconfig 를 건드려야 하고 Node 마이너 버전에 따라 켜졌다 꺼졌다 한다. **보안 검사가 조용히 안 도는 것이 바로 이 사고**라 버전에 안 흔들리는 쪽을 택했다
```

- [ ] **Step 5: 로컬 검사를 통과시킨다**

Run: `cd web && npx tsc --noEmit && npm run lint && npm run check`
Expected: 셋 다 종료코드 0.

- [ ] **Step 6: 커밋하고 밀기**

```bash
cd /Users/cheonjamin/projects/AllDap
git add "web/app/(site)/auth/page.tsx" web/components/AuthLink.tsx AGENTS.md docs/decisions.md
git commit -m "docs: 이동 중 문구와 ?next= 서술을 사실에 맞춘다

\"대시보드로 이동합니다…\" 는 ?next= 가 있으면 거짓이다. 목적지를 뺐다.
usePathname 이 쿼리와 해시를 버리는 한계를 AuthLink 주석에 남겼다.
AGENTS.md 의 ?next= 항목에 어디에만 붙는지와 이번 사고를 적었다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git push -u origin fix/redirect-open-redirect
```

- [ ] **Step 7: PR 을 올린다**

`.github/PULL_REQUEST_TEMPLATE.md` 를 먼저 읽고 그 칸을 채운다. "한계 & 트레이드오프" 에는 아래를 반드시 적는다.

- 함수가 `//evil.com` 을 반환하는 것은 실측했으나, **그 값으로 Next 라우터가 실제로 외부 도메인까지 항해하는지는 브라우저로 재보지 않았다.** 출력이 프로토콜 상대 URL 인 것 자체가 결함이라 수정은 정당하지만, "실제로 피싱이 성립했다" 고까지는 말할 수 없다.
- 대시보드 세션 만료 가드(A-2)에는 `?next=` 를 붙이지 않았다. 붙이면 비로그인 주소창에 봇 UUID 가 남는다.
- 검사는 순수 함수만 본다. 라우터가 그 값을 어떻게 쓰는지는 검사 범위 밖이다.

본문을 스크래치패드 파일에 먼저 쓰고 `--body-file` 로 넘긴다. 본문이 길어 셸에 직접 넣으면 따옴표가 깨진다.

```bash
cat > /tmp/pr1-body.md <<'BODY'
## 해결하려는 문제가 무엇인가요?

`https://all-dap.vercel.app/auth?next=/..//evil.com` 링크를 뿌리면, 사용자가 **진짜 우리 도메인의 진짜 로그인 폼**에서 로그인한 뒤 공격자 사이트로 떨어진다. 공격자는 우리 도메인 문자열조차 필요 없다.

`web/lib/redirect.ts` 는 입력을 URL 파서에 맡겨 판정하면서 **출력을 검사하지 않았다.** `url.pathname` 이 `//` 로 시작할 수 있고, 그러면 반환값이 프로토콜 상대 URL 이 되어 라우터가 다시 해석할 때 외부로 나간다. 직접 재현했다 (origin `https://all-dap.vercel.app`):

```
"/..//evil.com"                        -> //evil.com            재해석 origin https://evil.com
"/./..//evil.com"                      -> //evil.com            재해석 origin https://evil.com
"/..//evil.com/login?x=1"              -> //evil.com/login?x=1  재해석 origin https://evil.com
"https://all-dap.vercel.app//evil.com" -> //evil.com            재해석 origin https://evil.com
"https://all-dap.vercel.app/\/evil.com"-> ///evil.com           재해석 origin https://evil.com
```

이 파일 머리 주석이 *"주소창이 우리 도메인이었으므로 사용자는 그 사이트를 우리 것으로 믿는다"* 고 적어둔 바로 그 공격이다. **막으려던 것을 막지 못했다.**

🔴 **함수 반환값에서 멈추지 않고 브라우저로 끝까지 눌러봤다.** 이 저장소의 반복된 교훈이 *"진짜 상대와 붙여보기 전까지는 검증했다고 말하지 말 것"* 이라, 라우터가 실제로 나가는지를 확인해야 "결함" 과 "취약점" 을 가를 수 있다.

```
localStorage.setItem('alldap.token', 'fake.jwt.token')
  → http://localhost:3000/auth?next=/..//example.com
  → location.href === "https://example.com/"     (탭 제목 "Example Domain")

대조군: /auth?next=/faq  →  http://localhost:3000/faq   (정상)
```

**나간다.** 결함이 아니라 취약점이다.

🔴 **운영에 배포돼 있다.**

```
$ curl -s https://all-dap.vercel.app/faq | grep -o 'href="/auth[^"]*"'
href="/auth?next=%2Ffaq"
```

그리고 더 중요한 사실이 하나 있다. 자체 점검 `web/lib/redirect.check.ts` 는 **그전부터 있었는데 한 번도 돈 적이 없다.**

```
$ grep -c '"tsx"' web/package.json
0
```

CI 의 web 잡은 `npm ci` / `npm run lint` / `npm run build` 셋뿐이었다. 검사를 짜두는 것과 검사가 도는 것은 다른 일이고, 이 사고의 구조적 원인은 후자다.

## 왜 해야 하나요?

안 하면 우리 로그인 폼이 피싱 발판이 된다. 사용자가 우리를 믿는 그 순간을 정확히 노리는 공격이라 피해가 크다. 라이브라서 나중이 없다.

CI 연결을 같이 하는 이유: 안 하면 **"고쳤는데 안 도는 검사"** 가 그대로 남는다. 같은 자리가 또 뚫려도 아무도 모른다.

## 어떻게 해결했나요?

- [ ] `api/` (Spring Boot)
- [x] `web/` (Next.js)
- [ ] `ai-service/` (Python)
- [ ] `widget/` (임베드 위젯)
- [ ] `db/` · 마이그레이션
- [x] 문서 · 설정 · CI

**① 검사를 먼저 빨간불로 만들었다.** `redirect.check.ts` 에 위 5종을 넣고 돌려 5건 실패를 확인한 뒤 코드를 고쳤다. 그 검사가 이 케이스를 못 갖고 있던 것이 원인이므로 순서가 중요하다.

**② 조립한 경로를 파서에게 다시 물어본다.**

```ts
const path = url.pathname + url.search + url.hash;
try {
  if (new URL(path, origin).origin !== origin) return DEFAULT_AFTER_AUTH;
} catch {
  return DEFAULT_AFTER_AUTH;
}
return path;
```

이 파일이 세운 원칙이 *"직접 파싱하지 않고 브라우저의 URL 파서에게 판정을 맡긴다"* 인데, 그 원칙을 **입력에만 적용하고 출력에는 적용하지 않은 것**이 구멍의 정체다. 그래서 같은 원칙으로 메웠다.

**③ 검사를 CI 에 연결했다.** `tsx` 를 devDependency 에 넣고 `check` 스크립트를 만들어 web 잡의 lint 다음에 걸었다. `redirect.check.ts` 에 `process.exit(1)` 이 이미 있어 실패하면 빨간불이 된다.

**④ 통과 개수를 카운터로 바꿨다.** `"12가지"` 라고 손으로 적혀 있어서 케이스를 늘리면 어긋난다.

### 검증

```
$ cd web && npx tsx lib/redirect.check.ts   # 수정 전
  ❌ 경로 탈출 뒤 프로토콜 상대
       "/..//evil.com" → //evil.com  (기대: /dashboard)
  ... (5건)
🔴 5건 실패                                  # 종료코드 1

$ cd web && npm run check          # 수정 후
  ✅ ... (22줄)
OK: 22가지 통과                               # 종료코드 0
```

통과가 정답인 케이스도 그대로다: `"https:/evil.com" → /evil.com`, `"/features?tab=a#b" → /features?tab=a#b`.

`npx tsc --noEmit` 과 `npm run lint` 도 통과했다.

## 이 PR의 한계 & 트레이드오프

- **실측은 로컬 dev 서버에서 했다.** 운영(Vercel)에서 직접 눌러보지는 않았다. 같은 코드가 같은 라우터로 도는 것이 근거이고, 운영에서 시도하면 실제 사용자 계정과 로그가 얽힌다. `?next=` 가 운영에 배포된 것은 `curl` 로 따로 확인했다.
- **가짜 토큰으로 재현했다.** `/auth` 의 로그인 가드가 토큰의 유효성을 보지 않고 존재만 보기 때문에 성립한다. 진짜 로그인 직후 경로(`router.replace` 호출지 둘 중 나머지 하나)는 같은 `nextPath()` 를 쓰므로 같은 결과지만, 그쪽은 따로 누르지 않았다.
- **검사는 순수 함수만 본다.** 라우터가 그 반환값을 어떻게 쓰는지는 검사 범위 밖이다. 호출부가 늘면 같은 부류의 구멍이 다시 생길 수 있다.
- **A-2 는 안 고쳤다.** 대시보드 세션 만료 가드(`app/(dashboard)/layout.tsx`)는 `?next=` 를 안 붙인다. 붙이면 봇 화면 북마크 복귀가 되지만 **비로그인 상태의 주소창에 봇 UUID 가 남는다.** 한계로만 적었다.
- **`AuthLink` 의 `usePathname()` 은 쿼리와 해시를 버린다.** `/pricing#plans` 에서 로그인하면 `/pricing` 으로 온다. 지금 실해가 없어 주석만 남겼다.
- **`tsx` 의존성 하나가 늘었다.** Node 22.18+ 의 네이티브 타입 스트리핑으로 없앨 수 있지만 tsconfig 를 건드려야 하고 Node 마이너 버전에 따라 켜졌다 꺼졌다 한다. **보안 검사가 조용히 안 도는 것이 바로 이 사고**라 버전에 안 흔들리는 쪽을 택했다.

## 기존 기능에 미치는 영향

- **환각 억제(fallback)**: 해당 없음. 로그인 이후 이동 경로만 건드린다.
- **봇 간 격리**: 해당 없음. `bot_id` 를 다루지 않는다.
- **테이블 소유권 · Flyway**: 해당 없음. 마이그레이션이 없다.
- **에러 포맷 · camelCase**: 해당 없음. API 응답을 바꾸지 않는다.
- **시크릿**: 없음.
- **비용**: LLM 호출이 없다. CI 에 단계 하나(수백 ms)가 늘었다.
- **동작 변화**: `?next=` 로 프로토콜 상대 경로가 오면 이제 `/dashboard` 로 간다. 정상 경로(`/faq`, `/features?tab=a#b`, 같은 origin 의 절대 URL, `https:/evil.com`)는 그대로다.
- **배포**: 코드 외 할 일 없음. `main` 머지 시 Vercel 자동 배포.

## Edge Case & 실패 시나리오

- **`?next=` 가 파싱조차 안 되는 값**: `new URL` 이 던지고 `/dashboard` 로 간다. 왕복 검증에도 같은 `try/catch` 를 뒀다.
- **`?next=` 가 없음 / 빈 문자열 / `null`**: 전부 `/dashboard`. 검사에 있다.
- **`/auth` 자기 자신**: `/dashboard`. 무한 왕복처럼 보이는 것을 막는다.
- **"없어서 0" 과 "못 재서 0"**: 이 함수는 실패 시 항상 `DEFAULT_AFTER_AUTH` 하나로 떨어진다. 뭉개는 것이 맞다. 사용자가 알아야 할 차이가 없고("어디로 갈지 모르겠으면 대시보드"), 이유를 노출하면 공격자에게 판정 힌트를 준다.
- **사용자에게 보이는 안내**: `"대시보드로 이동합니다…"` 가 `?next=` 가 있으면 거짓이라 `"이동합니다…"` 로 바꿨다.
- **CI 가 이 검사에서 빨간불일 때**: 그 파일이 실패한 케이스를 이름과 함께 찍으므로 로그만 보고 원인을 안다.

## 검토한 대안과 선택 이유

- **`url.pathname.startsWith("//")` 한 줄** → 기각. 실제로 막힌다(역슬래시 변형도 파서가 `/` 로 정규화해 잡힌다). 그런데 이 파일이 명시적으로 기각해둔 방식이고, **구멍이 난 이유가 "파서에게 맡긴다" 는 원칙을 출력에는 안 지킨 것**이라, 원칙을 어기는 방식으로 메우면 같은 자리가 또 뚫린다.
- **절대 URL(`url.href`)을 반환하고 라우터에 맡기기** → 기각. 반환 타입이 바뀌어 호출부가 전부 영향을 받고, 개발과 운영에서 origin 이 달라 새 경우의 수가 생긴다.
- **`tsx` 없이 Node 네이티브 타입 스트리핑** → 기각. 위 "한계" 참고.
- **수정과 CI 연결을 별도 PR 로** → 기각. 나누면 "고쳤는데 안 도는 검사" 가 남는다. 그게 정확히 이 사고의 원인이다.

## 리뷰 포인트 (파일/영역별 Risk)

| Risk | 파일 / 영역 | 봐야 할 것 |
|---|---|---|
| 🔴 | `web/lib/redirect.ts` | 왕복 검증이 정상 경로를 과잉 차단하지 않는가. 특히 `https:/evil.com → /evil.com` 이 그대로 통과하는가 |
| 🔴 | `.github/workflows/ci.yml` | 검사 단계가 web 잡 안에 있고 `working-directory: web` 기본값을 받는가 |
| 🟡 | `web/lib/redirect.check.ts` | 새로 넣은 10개 케이스의 기대값이 맞는가. 특히 "통과가 정답" 인 케이스를 실수로 차단 기대로 적지 않았는가 |
| 🟡 | `AGENTS.md` | `?next=` 서술이 이제 사실과 맞는가 |
| 🟢 | `web/app/(site)/auth/page.tsx`, `web/components/AuthLink.tsx` | 문구와 주석 |

🤖 Generated with [Claude Code](https://claude.com/claude-code)

BODY

gh pr create --base main --head fix/redirect-open-redirect \
  --title "fix: 오픈 리다이렉트를 닫고, 그것이 통과한 원인(안 도는 검사)을 CI 로 막는다" \
  --body-file /tmp/pr1-body.md
```

🔴 **CI 결과를 기다리지 않는다.** `gh pr create` 가 URL 을 출력하면 이 Task 는 끝이다.

- [ ] **Step 8: `main` 으로 돌아온다**

```bash
cd /Users/cheonjamin/projects/AllDap
git switch main
```

---

## Task 4: 낡은 주석 5건을 `main` 에 직접 고친다

**Files:**
- Modify: `web/lib/plans.ts:11-13`
- Modify: `web/app/(site)/pricing/page.tsx:10` 부근
- Modify: `web/app/(site)/layout.tsx:6-7`
- Modify: `web/app/(dashboard)/account/page.tsx:8`
- Modify: `api/src/main/java/com/alldap/api/global/exception/ErrorCode.java:124`

**Interfaces:**
- Consumes: 없음. 앞 Task 들과 독립적이다.
- Produces: 없음. 주석과 문구만 바뀐다.

**왜 `main` 직행인가:** 전부 한 줄이고, 바꾸기 전에 이유를 설명할 필요가 없으며, 틀려도 한 줄 되돌리면 끝난다. `AGENTS.md` 의 "간단한 수정" 기준 그대로다.

🔴 **`pricing` 의 metadata 는 여기서 뺐다 (2026-09-08 자기검토).** 처음에는 "문구 한 줄" 이라고 여기 넣었는데, 그것을 왜 바꾸는지 설명하는 데 세 줄이 들었다(숫자가 두 벌 · 화면에서 뺀 주장이 남아 있음 · 이 파일이 스스로 금지한 규칙). **설명이 필요하면 PR 이라는 것이 이 저장소의 기준**이고, 그 기준이 프로젝트 1순위 목적(무엇을 왜 바꿨는지가 PR 단위로 읽힌다)과 직결된다. Task 7 로 옮겼다.

🔴 **`main` 푸시는 Vercel 자동 배포다.** Step 5 의 로컬 검사를 반드시 통과시킨 뒤 민다.

- [ ] **Step 1: `plans.ts` 의 거짓 단언을 고친다**

`web/lib/plans.ts` 의 아래 문단

```ts
 * ⚠️ 지금은 <화면에만> 있다. Spring 에 플랜 테이블·한도 검사·청구는 없다
 *    (요금제 연동 4조각 중 2·4번 미구현). 2번을 만들어 Spring 이 이 값을 갖게 되면
 *    프론트는 여기가 아니라 API 에서 받아야 한다 — 같은 숫자가 두 벌이면 반드시 어긋난다.
```

를 아래로 바꾼다.

```ts
 * ⚠️ 2번 조각(요금제 선택)은 PR #76 에서 끝났다. `users.plan` 이 생겼고 `GET`·`PUT /api/plan`
 *    이 있다. 그런데 <숫자는 여전히 여기에만 있다>. 서버의 `Plan` enum 은 이름과 `isPaid()`
 *    뿐이고 금액도 한도도 모른다(api 의 `plan/Plan.java` 주석 참고). 서버가 그 숫자로 하는 일이
 *    아직 없어서다. 한도 검사와 청구(4번 조각)가 붙어 서버가 금액을 갖게 되면 그때 API 에서
 *    받아야 한다. 같은 숫자가 두 벌이면 반드시 어긋난다.
```

- [ ] **Step 2: `pricing` 머리 주석의 자기모순을 고친다**

`web/app/(site)/pricing/page.tsx` 의

```
 * 🔴 <금액은 전부 가정값이다. 그리고 그 사실을 화면에 그대로 적는다.>
```

를 아래로 바꾼다. 같은 주석 7줄 뒤가 "그 태그는 뺐다" 고 말하므로 첫 문장이 자기 자신을 부정하고 있었다.

```
 * 🔴 <금액은 전부 가정값이다. 다만 그 사실을 화면에 적지는 않는다(아래 참고).>
```

- [ ] **Step 3: 지워진 링크를 설명하는 주석 두 개를 고친다**

`web/app/(site)/layout.tsx` 의

```
 * 관리자 네비게이션은 넣지 않는다. 다만 로그인한 사람도 이 화면에 온다(대시보드 헤더의
 * "소개" → 랜딩 → 기능 페이지). 그래서 오른쪽 끝 버튼만 로그인 여부를 안다(`AuthLink`).
```

를 아래로 바꾼다. 대시보드 헤더의 "소개" 는 2026-09-08 에 "봇 목록" 으로 바뀌었고 랜딩으로 가는 일은 로고가 맡는다.

```
 * 관리자 네비게이션은 넣지 않는다. 다만 로그인한 사람도 이 화면에 온다(대시보드 헤더의
 * 로고가 랜딩으로 가고, 거기서 기능 페이지로 들어온다). 그래서 오른쪽 끝 버튼만
 * 로그인 여부를 안다(`AuthLink`).
```

`web/app/(dashboard)/account/page.tsx:8` 의

```
 * 사용자가 그 사이를 오가야 한다. 옛 주소는 이 화면으로 넘긴다(`app/(dashboard)/billing/page.tsx`).
```

를 아래로 바꾼다. 그 파일은 없다. 리다이렉트는 `next.config.ts` 의 308 이다.

```
 * 사용자가 그 사이를 오가야 한다. 옛 주소(`/billing`)는 `next.config.ts` 의 308 리다이렉트로
 * 이 화면에 넘긴다. 쿼리스트링이 따라가므로 옛 주소로 온 `authKey` 도 안 샌다.
```

- [ ] **Step 4: `ErrorCode` 의 안내가 가리키는 자리를 고친다**

`api/src/main/java/com/alldap/api/global/exception/ErrorCode.java` 의

```java
    BILLING_METHOD_REQUIRED_BY_PLAN(HttpStatus.CONFLICT, "BILLING_METHOD_REQUIRED_BY_PLAN",
            "유료 요금제를 쓰는 동안에는 마지막 카드를 삭제할 수 없습니다. 다른 카드를 먼저 등록하거나, 요금제를 무료로 바꾼 뒤 삭제해주세요."),
```

를 아래로 바꾼다. 요금제를 바꾸는 자리는 2026-09-08 에 `/account` 에서 `/pricing` 으로 옮겼다.

```java
    BILLING_METHOD_REQUIRED_BY_PLAN(HttpStatus.CONFLICT, "BILLING_METHOD_REQUIRED_BY_PLAN",
            "유료 요금제를 쓰는 동안에는 마지막 카드를 삭제할 수 없습니다. 다른 카드를 먼저 등록하거나, 요금제 페이지에서 무료로 바꾼 뒤 삭제해주세요."),
```

- [ ] **Step 5: 로컬 검사를 통과시킨다**

Run: `cd web && npx tsc --noEmit && npm run lint`
Expected: 종료코드 0.

Run: `cd api && ./gradlew test`
Expected: `BUILD SUCCESSFUL`, 164건 통과.

🔴 **`ErrorCode` 문구를 검증하는 테스트가 있으면 여기서 빨간불이 난다.** 그러면 테스트의 기대 문자열도 함께 고친다.

- [ ] **Step 6: 커밋하고 민다**

```bash
cd /Users/cheonjamin/projects/AllDap
git add web/lib/plans.ts "web/app/(site)/pricing/page.tsx" "web/app/(site)/layout.tsx" "web/app/(dashboard)/account/page.tsx" api/src/main/java/com/alldap/api/global/exception/ErrorCode.java
git commit -m "docs: 사실과 어긋난 주석 다섯 곳을 고친다

plans.ts: \"2번 조각 미구현\" 은 PR #76 에서 끝나 거짓이 됐다.
  다만 숫자가 여기에만 있는 것은 그대로라, 그 이유를 대신 적었다.
pricing: 머리 주석 첫 문장을 같은 주석 일곱 줄 뒤가 부정하고 있었다.
(site)/layout: 대시보드 헤더의 \"소개\" 는 \"봇 목록\" 으로 바뀌었다.
account: 없는 파일을 가리켰다. 리다이렉트는 next.config.ts 에 있다.
ErrorCode: 요금제를 바꾸는 자리가 /account 에서 /pricing 으로 옮겨졌다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git push origin main
```

---

## Task 5: 카드 지갑의 분기를 순수 함수로 뽑고 TDD 로 고친다 (B-3, B-5)

**Files:**
- Create: `web/lib/wallet.ts`
- Create: `web/lib/wallet.check.ts`
- Modify: `web/app/(dashboard)/account/page.tsx:60-64`(`MAX_METHODS` 이사), `:385-390`, `:461-568` 부근
- Modify: `web/package.json` (`check` 스크립트에 붙인다)

**Interfaces:**
- Consumes: Task 2 가 만든 `npm run check` 스크립트와 `tsx` devDependency
- Produces:
  ```ts
  // web/lib/wallet.ts
  export const MAX_METHODS = 5;
  export interface WalletView {
    billed: BillingCard | undefined;
    others: BillingCard[];
    warnNoDefault: boolean;
    showDrawer: boolean;
    drawerOpen: boolean;
    full: boolean;
  }
  export function walletView(methods: BillingCard[], justAddedId: string | null): WalletView;
  ```
  Task 7 이 같은 파일(`account/page.tsx`)의 `CardItem` 을 고친다.

🔴 **선행 조건: PR① 이 `main` 에 머지돼 있어야 한다.** Task 2 가 `tsx` 와 `check` 스크립트를 `web/package.json` 에 넣었고 이 Task 가 거기에 한 줄을 더한다. 머지 전에 브랜치를 따면 **같은 파일 같은 줄에서 충돌한다.** `AGENTS.md` 가 2026-09-08 에 겪은 스택 브랜치 함정이 그것이다. 머지가 안 됐으면 먼저 머지하고 시작한다.

**왜 순수 함수로 뽑는가.** 원래 계획은 JSX 를 재배치하고 브라우저로 눈으로 보는 것이었다. 그러면 **CI 가 아무것도 지키지 않는다.** 다음에 누가 그 블록을 건드리면 조용히 다시 깨진다. 이 PR 묶음의 핵심 교훈이 *"짜둔 검사가 안 돌고 있었다"* 인데, 같은 묶음에서 검사 없는 수정을 하는 것은 앞뒤가 안 맞는다.
뽑아낼 값어치가 있는 이유는 **깨진 것이 정확히 <분기 판단>이기 때문**이다. 마크업이 아니라 "어떤 상태에서 무엇을 그릴지" 가 틀렸다. 그 판단은 렌더러 없이 잴 수 있다.
이 저장소에 이미 같은 방식이 여섯 개 있다: `redirect.check.ts` · `retriever_check.py` · `evaluator_check.py` · `answerable_check.py` · `bot_prompt_check.py` · `fallback_e2e_check.py`. 새 관례가 아니다.

**B-3 배경:** `billed = data.methods.find((m) => m.isDefault)` 다. 카드는 있는데 기본이 하나도 없으면 `billed` 가 `undefined` 라 **`else` 분기로 떨어져 카드 등록 타일만 그린다.** 사용자는 자기 카드를 보지도 지우지도 못하고 토스에는 빌링키가 남는다. V7 부분 유니크 인덱스는 "기본 1장 이하" 만 보장하고 "1장 이상" 은 앱 코드가 지키는데 `BillingService.register` 에 TOCTOU 경합이 있다. 같은 분기의 `AddCardTile` 에는 `full` 가드도 없다.
⚠️ 경합 자체는 재현하지 않았다. **프론트가 그 상태에서 어떻게 그려지는지만 코드로 확인했다.**

**B-5 배경:** 첫 카드만 `isDefault=true` 라 2번째부터는 전부 `others` 행인데 `<details>` 에 `open` 이 없다. **등록 직후 닫힌 서랍 안으로 사라진다.** 등록에 성공해도 화면에 변화가 없어 실패한 것처럼 보인다. 부작용으로 `justAddedId` + `alldap-card-in` 등장 애니메이션이 첫 카드에서만 동작한다(`globals.css:151-152` 가 설명하는 코드가 사실상 죽어 있다).

**두 버그를 한 Task 로 묶는 이유:** 둘 다 같은 `<details>` 줄을 고친다. 나누면 한 PR 안에서 같은 줄을 두 번 바꾸는 커밋이 남고, 리뷰어는 첫 번째 버전을 읽을 이유가 없다.

- [ ] **Step 1: 브랜치를 딴다**

```bash
cd /Users/cheonjamin/projects/AllDap
git switch main && git pull
grep -q '"check"' web/package.json && echo "PR1 머지됨, 진행" || echo "🔴 멈출 것: PR1 을 먼저 머지한다"
git switch -c fix/account-card-states
```

Expected: `PR1 머지됨, 진행`. 아니면 멈춘다.

- [ ] **Step 2: 검사를 먼저 쓴다**

`web/lib/wallet.check.ts` 를 새로 만든다. **아직 `wallet.ts` 가 없으므로 이 파일은 지금 돌지 않는다.** 그게 맞다.

```ts
/**
 * walletView 의 자체 점검. `npm run check` 가 돌린다.
 *
 * 왜 이 파일이 있나: 2026-09-08 코드 리뷰에서 나온 두 버그가 전부 <분기 판단>이었다.
 * 기본 카드가 없으면 카드가 통째로 안 보였고, 2번째 카드는 닫힌 서랍에 숨었다.
 * 마크업이 아니라 "어떤 상태에서 무엇을 그릴지" 가 틀린 것이라 렌더러 없이 잴 수 있다.
 * 🔴 브라우저로만 확인하면 CI 가 아무것도 지키지 않는다. 이 저장소는 이미
 *    "짜둔 검사가 안 돌아서" 오픈 리다이렉트를 배포까지 보냈다.
 */
import type { BillingCard } from "./types";
import { MAX_METHODS, walletView } from "./wallet";

let failed = 0;
let total = 0;

function card(id: string, isDefault: boolean): BillingCard {
  return {
    id,
    issuerCode: "61",
    issuerName: "현대",
    cardNumberMasked: "43301234****123*",
    registeredAt: "2026-09-08T00:00:00Z",
    isDefault,
  };
}

function check(label: string, got: unknown, expected: unknown) {
  total++;
  const ok = JSON.stringify(got) === JSON.stringify(expected);
  if (!ok) failed++;
  console.log(`  ${ok ? "✅" : "❌"} ${label}${ok ? "" : `\n       받음: ${JSON.stringify(got)}  기대: ${JSON.stringify(expected)}`}`);
}

console.log("walletView: 카드 상태별로 무엇을 그리는가\n");

// ── 정상 상태 ───────────────────────────────────────────────────────
{
  const v = walletView([], null);
  check("0장: 서랍을 안 그린다", v.showDrawer, false);
  check("0장: 청구 카드가 없다", v.billed, undefined);
  check("0장: 경고하지 않는다", v.warnNoDefault, false);
  check("0장: 상한이 아니다", v.full, false);
}
{
  const a = card("a", true);
  const v = walletView([a], null);
  check("1장: 그 카드가 청구 카드다", v.billed?.id, "a");
  check("1장: 서랍은 비어 있다", v.others, []);
  check("1장: 서랍은 닫혀 있다", v.drawerOpen, false);
}
{
  const [a, b] = [card("a", true), card("b", false)];
  const v = walletView([a, b], null);
  check("2장: 청구 카드는 서랍에 없다", v.others.map((c) => c.id), ["b"]);
  check("2장: 서랍은 닫혀 있다", v.drawerOpen, false);
}
{
  const v = walletView([card("a", true), card("b", false), card("c", false), card("d", false), card("e", false)], null);
  check(`${MAX_METHODS}장: 상한에 닿았다`, v.full, true);
}

// ── 🔴 리뷰에서 나온 버그 두 개 ─────────────────────────────────────
// B-3: 기본 카드가 없는데 카드는 있는 상태. 서버 불변식이 깨진 것이고
//      (V7 인덱스는 "기본 1장 이하" 만 보장한다) 전에는 이때 목록이
//      통째로 안 그려져 사용자가 자기 카드를 보지도 지우지도 못했다.
{
  const [a, b] = [card("a", false), card("b", false)];
  const v = walletView([a, b], null);
  check("기본 없음: 서랍을 그린다", v.showDrawer, true);
  check("기본 없음: 두 장 다 서랍에 있다", v.others.map((c) => c.id), ["a", "b"]);
  check("기본 없음: 경고한다", v.warnNoDefault, true);
  check("기본 없음: 서랍을 열어둔다", v.drawerOpen, true);
  check("기본 없음: 청구 카드가 없다", v.billed, undefined);
}
{
  const v = walletView([card("a", false), card("b", false), card("c", false), card("d", false), card("e", false)], null);
  check("기본 없음 + 상한: full 가드가 살아 있다", v.full, true);
}

// B-5: 방금 추가한 카드는 첫 장이 아니면 전부 서랍 행이라,
//      서랍이 닫혀 있으면 등록에 성공해도 화면에 아무 변화가 없다.
{
  const v = walletView([card("a", true), card("b", false)], "b");
  check("방금 추가: 서랍을 열어둔다", v.drawerOpen, true);
}
{
  const v = walletView([card("a", true)], "a");
  check("방금 추가한 것이 청구 카드면 서랍을 억지로 열지 않는다", v.drawerOpen, false);
}

console.log(failed === 0 ? `\nOK: ${total}가지 통과` : `\n🔴 ${failed}건 실패`);
if (failed) process.exit(1);
```

- [ ] **Step 3: 지금 화면이 하는 일 그대로를 `wallet.ts` 에 옮긴다**

🔴 **일부러 <고치지 않고> 옮긴다.** 검사가 실제 버그를 잡는지 먼저 봐야 한다. 아래는 `account/page.tsx:385-390` 과 `:509` 의 현재 동작을 그대로 옮긴 것이다.

`web/lib/wallet.ts` 를 새로 만든다.

```ts
import type { BillingCard } from "./types";

/**
 * 계정당 카드 상한. 서버(`BillingService.MAX_METHODS`)와 같은 값이다.
 * 화면(`app/(dashboard)/account/page.tsx`)에서 여기로 옮겼다. 판단이 이 파일로 왔기 때문이다.
 */
export const MAX_METHODS = 5;

/** 카드 상태에서 화면이 무엇을 그릴지. 마크업이 아니라 <판단>만 담는다. */
export interface WalletView {
  /** 청구에 쓰이는 카드. 없을 수 있다 */
  billed: BillingCard | undefined;
  /** 서랍에 들어갈 카드. 청구 카드는 빠진다 (두 번 그리면 혼동이 돌아온다) */
  others: BillingCard[];
  /** 카드는 있는데 기본이 없다. 서버 불변식이 깨진 상태다 */
  warnNoDefault: boolean;
  /** 서랍을 그리는가. 아니면 등록 자리만 그린다 */
  showDrawer: boolean;
  /** 서랍을 열어둘 것인가 */
  drawerOpen: boolean;
  /** 상한에 닿았는가 */
  full: boolean;
}

export function walletView(methods: BillingCard[], justAddedId: string | null): WalletView {
  const billed = methods.find((m) => m.isDefault);
  const others = methods.filter((m) => m.id !== billed?.id);
  return {
    billed,
    others,
    warnNoDefault: false,
    showDrawer: billed !== undefined,
    drawerOpen: false,
    full: methods.length >= MAX_METHODS,
  };
}
```

- [ ] **Step 4: 검사를 돌려 빨간불을 확인한다**

`web/package.json` 의 `check` 스크립트에 먼저 붙인다.

```json
    "check": "tsx lib/redirect.check.ts && tsx lib/wallet.check.ts"
```

Run: `cd web && npm run check`

Expected: 종료코드 1. `redirect.check.ts` 는 22가지 통과하고, `wallet.check.ts` 는 **18가지 중 4건**이 `❌` 다. **이 숫자는 실측했다** (같은 로직을 스크래치패드에서 돌려 확인).

```
  ❌ 기본 없음: 서랍을 그린다
       받음: false  기대: true
  ❌ 기본 없음: 경고한다
  ❌ 기본 없음: 서랍을 열어둔다
  ❌ 방금 추가: 서랍을 열어둔다
🔴 4건 실패
```

⚠️ **통과할 것 같은데 통과하는 케이스 둘을 미리 적어둔다.** 처음에 이 둘도 빨간불일 것이라 예측했다가 돌려보고 틀린 것을 알았다.

- `"기본 없음: 두 장 다 서랍에 있다"` → **지금도 통과한다.** `others` 는 `m.id !== billed?.id` 로 거르는데 `billed` 가 `undefined` 면 `undefined?.id` 도 `undefined` 라 아무것도 안 걸러진다. 값은 이미 맞았고, **그 값을 쓰는 분기에 도달하지 못한 것**이 버그였다.
- `"기본 없음 + 상한: full 가드가 살아 있다"` → **지금도 통과한다.** 같은 이유다. `full` 계산은 맞았고 `full` 을 읽는 JSX 가 그려지지 않았다.

두 케이스를 지우지 않고 남기는 이유: `showDrawer` 를 고친 뒤에야 <의미>가 생기는 검사다. 회귀가 나면 여기서 잡힌다.

🔴 **4건이 아니면 멈춘다.** 하나도 실패하지 않으면 검사가 버그를 재현하지 못한 것이고, 더 많이 실패하면 기대값을 잘못 적은 것이다. 둘 다 Step 2 를 다시 봐야 한다.

- [ ] **Step 5: `walletView` 를 고친다**

`web/lib/wallet.ts` 의 함수 본문을 아래로 바꾼다.

```ts
export function walletView(methods: BillingCard[], justAddedId: string | null): WalletView {
  const billed = methods.find((m) => m.isDefault);
  /* 청구 카드는 서랍에 <다시> 넣지 않는다. 두 번 그리면 "왜 같은 카드가 두 개지" 가 되고,
     지갑 구조가 없애려던 혼동이 그대로 돌아온다. */
  const others = methods.filter((m) => m.id !== billed?.id);
  /* 🔴 카드는 있는데 기본이 없는 상태. V7 부분 유니크 인덱스는 "기본 1장 이하" 만 보장하고
     "1장 이상" 은 앱 코드가 지킨다(BillingService.register 에 TOCTOU 경합이 있다).
     전에는 이때 목록을 통째로 안 그려서, 사용자가 자기 카드를 보지도 지우지도 못하는데
     토스에는 빌링키가 남았다. 어느 카드로 청구되는지는 우리도 모른다. 그렇게 말하고
     지정할 수 있게 열어준다. 아무 카드나 청구 카드로 그리는 것은 모르는 것을 아는 척하는 것이다. */
  const warnNoDefault = billed === undefined && methods.length > 0;
  return {
    billed,
    others,
    warnNoDefault,
    /* 서랍의 조건은 <카드가 있는가> 다. billed 가 아니다. 이 한 줄이 B-3 의 전부다. */
    showDrawer: methods.length > 0,
    /* 방금 추가했으면 연다(안 열면 2번째부터 등록한 카드가 닫힌 서랍 안으로 사라진다).
       기본이 없을 때도 연다(거기서 지정해야 한다). */
    drawerOpen: (justAddedId !== null && others.some((c) => c.id === justAddedId)) || warnNoDefault,
    full: methods.length >= MAX_METHODS,
  };
}
```

- [ ] **Step 6: 검사를 돌려 초록불을 확인한다**

Run: `cd web && npm run check`
Expected: 종료코드 0. `redirect.check.ts` 22가지 + `wallet.check.ts` 18가지 전부 `✅`.

- [ ] **Step 7: 화면이 `walletView` 를 쓰게 한다**

`web/app/(dashboard)/account/page.tsx` 의 상수 정의

```tsx
const MAX_METHODS = 5;
```

를 지우고(주석 포함) 파일 상단 import 에 붙인다.

```tsx
import { MAX_METHODS, walletView } from "@/lib/wallet";
```

그 다음 아래 블록

```tsx
  const full = data.methods.length >= MAX_METHODS;
  /* 청구에 쓰이는 카드 = 기본 카드. 서버가 "카드가 있으면 기본이 정확히 하나" 를 보장하므로
     (V7 의 부분 유니크 인덱스) 여기서 여러 장을 걱정할 필요가 없다. */
  const billed = data.methods.find((m) => m.isDefault);
  /* 서랍에 들어갈 카드 = 청구 카드를 뺀 나머지. 청구 카드를 여기 다시 넣으면 같은 카드가
     화면에 두 번 그려져, 이번 개편이 없애려던 혼동이 그대로 돌아온다. */
  const others = data.methods.filter((m) => m.id !== billed?.id);
```

를 아래로 바꾼다.

```tsx
  /* 무엇을 그릴지에 대한 판단은 전부 lib/wallet.ts 에 있다. 여기는 그리기만 한다.
     판단을 화면에서 빼낸 이유: 2026-09-08 리뷰에서 나온 두 버그가 전부 분기 판단이었고,
     화면 안에 있으면 브라우저로 눈으로 보는 것 말고는 잴 방법이 없다(lib/wallet.check.ts). */
  const { billed, others, warnNoDefault, showDrawer, drawerOpen, full } = walletView(
    data.methods,
    justAddedId,
  );
```

- [ ] **Step 8: JSX 를 그 판단에 맞춰 재배치한다**

아래 줄

```tsx
        {billed ? (
          <>
            <div className="mt-5 rounded-xl border border-subtle bg-surface p-5">
```

를 바꾼다.

```tsx
        {billed && (
          <div className="mt-5 rounded-xl border border-subtle bg-surface p-5">
```

청구 카드 블록이 닫히고 서랍이 시작하는 자리, 즉

```tsx
              </div>
            </div>

            {/*
              ── 왜 <details> 인가 (직접 만든 토글이 아니라) ──────────────────────
```

를 바꾼다.

```tsx
              </div>
          </div>
        )}

        {warnNoDefault && (
          <p role="alert" className="mt-5 text-sm text-danger">
            청구에 쓸 카드가 지정돼 있지 않습니다. 아래 목록에서 카드 하나를 “기본으로” 지정해주세요.
          </p>
        )}

        {showDrawer ? (
          <>
            {/*
              ── 왜 <details> 인가 (직접 만든 토글이 아니라) ──────────────────────
```

서랍 여는 줄

```tsx
            <details className="group mt-4 rounded-xl border border-subtle bg-surface">
```

를 바꾼다.

```tsx
            {/* open 은 제어 컴포넌트가 아니다. React 는 이 prop 이 <바뀔 때만> DOM 을
                건드리므로 사용자가 손으로 닫으면 그대로 닫혀 있다. */}
            <details open={drawerOpen} className="group mt-4 rounded-xl border border-subtle bg-surface">
```

요약 문구

```tsx
                  {others.length > 0 ? `다른 카드 ${others.length}장` : "다른 카드 없음"}
```

를 바꾼다. 청구 카드가 없으면 "다른" 이라 부를 기준이 없다.

```tsx
                  {others.length > 0
                    ? `${billed ? "다른 카드" : "카드"} ${others.length}장`
                    : "다른 카드 없음"}
```

마지막으로 0장 분기

```tsx
            </details>
          </>
        ) : (
          /* 카드 0장. 서랍을 만들지 않는다 — 열어봐야 빈 칸뿐인 서랍은 클릭을 한 번 더
             요구할 뿐이다. 등록 자리 하나만 카드 크기로 보여준다. */
          <div className="mt-5 max-w-[260px]">
            <AddCardTile opening={opening} onClick={handleOpenBillingWindow} />
          </div>
        )}
```

는 **그대로 둔다.** 바깥 조건이 `showDrawer` 로 바뀌었으므로 `else` 는 이제 진짜 "카드 0장" 이고, 그때는 `full` 이 참일 수 없어 가드가 필요 없다.

- [ ] **Step 9: 로컬 검사를 전부 통과시킨다**

Run: `cd web && npx tsc --noEmit && npm run lint && npm run check`
Expected: 셋 다 종료코드 0.

🔴 JSX 닫는 태그 오류가 나면 Step 8 의 들여쓰기와 괄호를 다시 맞춘다. 조각을 옮기는 작업이라 `tsc` 가 유일한 안전망이다.

- [ ] **Step 10: 브라우저로 확인한다**

`preview_start` 로 `web` 을 띄운다. **Bash 로 dev 서버를 띄우지 않는다.**

검사가 판단을 지키므로 여기서 볼 것은 **판단이 마크업으로 옳게 이어졌는가** 하나다.

1. 카드 0장: 등록 타일 하나만 보인다.
2. 카드 1장: 청구 카드 블록이 펼쳐져 있고 서랍은 "다른 카드 없음 · 카드 추가".
3. 카드 2장: 두 번째 카드가 **닫히지 않은 서랍 안에** 보인다.

기본 카드가 없는 상태는 정상 경로로 만들 수 없다. DB 로 직접 만든다.

```bash
docker exec -i $(docker ps -qf name=postgres) psql -U alldap -d alldap -c "UPDATE billing_methods SET is_default = false WHERE user_id = (SELECT id FROM users WHERE email = '<테스트계정>');"
```

Expected: 빨간 경고 한 줄과 **펼쳐진 서랍 안의 카드 목록.** 각 카드에 "기본으로" 버튼이 있다.

되돌린다.

```bash
docker exec -i $(docker ps -qf name=postgres) psql -U alldap -d alldap -c "UPDATE billing_methods SET is_default = true WHERE id = (SELECT id FROM billing_methods WHERE user_id = (SELECT id FROM users WHERE email = '<테스트계정>') LIMIT 1);"
```

⚠️ 테스트 계정은 끝나고 지운다: `DELETE FROM users WHERE email LIKE '<패턴>'`.

- [ ] **Step 11: 커밋**

```bash
cd /Users/cheonjamin/projects/AllDap
git add web/lib/wallet.ts web/lib/wallet.check.ts web/package.json "web/app/(dashboard)/account/page.tsx"
git commit -m "fix: 카드 지갑의 분기를 순수 함수로 뽑고 두 버그를 고친다

깨진 것이 마크업이 아니라 분기 판단이었다. 판단을 lib/wallet.ts 로 빼고
lib/wallet.check.ts 를 먼저 빨간불로 만든 뒤 고쳤다.

B-3: billed 는 is_default 인 카드를 찾는데, 카드는 있고 기본이 없으면 undefined 라
  \"카드 0장\" 분기로 떨어졌다. 그 상태의 사용자는 자기 카드를 보지도 지우지도 못하고
  토스에는 빌링키가 남는다. 서랍의 조건을 methods.length > 0 으로 바꿨다.
  덕분에 그 분기에 없던 full 가드도 따라온다. 어느 카드로 청구되는지는 모르므로
  아무 카드나 청구 카드라고 그리지 않고, 모른다고 말한 뒤 지정할 수 있게 열어둔다.
B-5: <details> 에 open 이 없어 2번째부터 등록한 카드가 닫힌 서랍에 숨었다.
  등록에 성공해도 화면에 변화가 없어 실패한 것처럼 보인다.

브라우저로만 확인하면 CI 가 아무것도 지키지 않는다. 이 저장소는 이미
짜둔 검사가 안 돌아서 오픈 리다이렉트를 배포까지 보냈다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 6: 요금제를 "못 불러옴" 과 "아직 안 불러옴" 으로 가른다 (B-4)

**Files:**
- Modify: `web/components/PlanCards.tsx:57-88` 부근, `:110-125` 부근

**Interfaces:**
- Consumes: 없음
- Produces: 없음

🔴 **이 Task 에는 자동 검사를 안 붙인다. 사용자 승인을 받은 예외다.** 판단이 `signedIn && planFailed` 한 줄이라 순수 함수로 뽑아도 조건 하나짜리 껍데기가 되고, 실제로 재려면 렌더러(testing-library 등)가 필요한데 이 저장소에는 프론트 테스트 러너가 없다. 러너 도입은 이 PR 의 범위를 넘는다.
**대가**: 이 수정은 Step 5 의 브라우저 확인으로만 지켜진다. 나중에 누가 `planFailed` 분기를 지워도 CI 는 모른다. Task 5·7 처럼 판단이 <여러 갈래>로 늘어나면 그때 뽑아낸다.

**배경:** `plan` 이 `PlanId | null` 하나라 **"아직 안 불러옴" 과 "못 불러옴" 이 같은 값**이다. `GET /api/plan` 이 실패하면 바꾸기 버튼이 **이유 없이 사라진다.** `/account` 에서 "요금제 바꾸기" 로 온 사람이 정확히 이 화면을 만난다. `/account` 는 같은 상황을 `loading` 으로 갈라 안내한다(`account/page.tsx:596-600`).

이 저장소가 반복해 내는 부류다. `AGENTS.md` 의 "낸 버그 5건" 이 전부 **원인이 다른 두 사실을 같은 값으로 뭉갠 것**이다.

- [ ] **Step 1: 실패 상태를 따로 갖는다**

`web/components/PlanCards.tsx` 의

```tsx
  /*
   * 지금 요금제. `null` 은 <아직 못 불러왔거나 실패했다>는 뜻이고, 그때는 배지도 버튼도
   * 그리지 않는다. 모르는 채로 "사용 중" 을 아무 카드에나 붙이면 그게 거짓말이다.
   */
  const [plan, setPlan] = useState<PlanId | null>(null);
```

를 아래로 바꾼다.

```tsx
  /*
   * 지금 요금제. `null` 은 <모른다>는 뜻이고, 그때는 배지도 버튼도 그리지 않는다.
   * 모르는 채로 "사용 중" 을 아무 카드에나 붙이면 그게 거짓말이다.
   *
   * 🔴 "아직 안 불러왔다" 와 "불러오려다 실패했다" 를 <가른다> (2026-09-08 코드 리뷰).
   *    전에는 둘 다 null 이라, 요청이 실패하면 바꾸기 버튼이 <이유 없이> 사라졌다.
   *    /account 의 "요금제 바꾸기" 로 온 사람이 정확히 이 화면을 만난다.
   *    이 저장소가 반복해 낸 부류다 (AGENTS.md "낸 버그 5건" 은 전부 이 모양이다).
   */
  const [plan, setPlan] = useState<PlanId | null>(null);
  const [planFailed, setPlanFailed] = useState(false);
```

- [ ] **Step 2: effect 에서 실패를 기록한다**

같은 파일의

```tsx
      try {
        setPlan((await api.plan.getPlan()).plan);
      } catch {
        /* 못 불러와도 마케팅 본문은 그대로 보여야 한다. 요금제 표시만 조용히 접는다. */
        setPlan(null);
      }
```

를 아래로 바꾼다.

```tsx
      try {
        setPlan((await api.plan.getPlan()).plan);
        setPlanFailed(false);
      } catch {
        /* 못 불러와도 마케팅 본문은 그대로 보여야 한다. 요금제 표시만 접되,
           <조용히> 접지는 않는다. 버튼이 사라진 이유를 아래에서 말한다. */
        setPlan(null);
        setPlanFailed(true);
      }
```

- [ ] **Step 3: 이유를 화면에 적는다**

같은 파일에서 `notice` 블록

```tsx
      {notice && (
        <p role="status" className="mb-4 text-sm text-success">
          {notice}
        </p>
      )}
```

바로 **아래**에 붙인다.

```tsx
      {/* 🔴 버튼이 사라진 이유를 말한다. 안 말하면 사용자는 <기능이 없는 화면>이라고 읽는다.
             role="alert" 은 쓰지 않는다: 급한 오류가 아니고 마케팅 본문은 그대로 읽을 수 있다. */}
      {signedIn && planFailed && (
        <p role="status" className="mb-4 text-sm text-danger">
          지금 쓰는 요금제를 불러오지 못했습니다. 화면을 새로고침하면 다시 시도합니다. 아래 내용은
          그대로 보실 수 있습니다.
        </p>
      )}
```

- [ ] **Step 4: 로컬 검사를 통과시킨다**

Run: `cd web && npx tsc --noEmit && npm run lint`
Expected: 종료코드 0.

- [ ] **Step 5: 브라우저로 실패 경로를 확인한다**

`preview_start` 로 `web` 을 띄우고 로그인한 뒤 `/pricing` 을 연다. Spring(`:8080`)을 잠시 내리거나, `javascript_tool` 로 `window.fetch` 를 실패시켜 `GET /api/plan` 을 죽인다.

Expected: 카드 위에 붉은 안내 한 줄이 뜨고, 바꾸기 버튼은 없으며, 요금제 내용(금액·포함량)은 그대로 읽힌다.

- [ ] **Step 6: 커밋**

```bash
cd /Users/cheonjamin/projects/AllDap
git add web/components/PlanCards.tsx
git commit -m "fix: 요금제를 못 불러왔을 때 이유 없이 버튼만 사라지던 것을 고친다

plan 이 PlanId | null 하나라 \"아직 안 불러옴\" 과 \"못 불러옴\" 이 같은 값이었다.
GET /api/plan 이 실패하면 바꾸기 버튼이 조용히 사라져서, /account 의
\"요금제 바꾸기\" 로 온 사람은 기능이 없는 화면이라고 읽게 된다.

planFailed 를 따로 두고 그때 이유를 화면에 적는다.
/account 가 같은 상황을 loading 으로 가르는 방식과 맞췄다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 7: 모르는 요금제 id(TDD), 접근성 세 곳, 요금제 metadata

**Files:**
- Create: `web/lib/plans.check.ts`
- Modify: `web/lib/plans.ts` (`resolvePlan` 추가)
- Modify: `web/package.json` (`check` 스크립트에 붙인다)
- Modify: `web/app/(dashboard)/account/page.tsx:394` 부근, `:598` 부근, `:733-760` 부근
- Modify: `web/app/(site)/pricing/page.tsx:43` 부근, `:81` 부근

**Interfaces:**
- Consumes: Task 5 가 재배치한 JSX (같은 파일이지만 다른 블록이다), Task 5 가 늘린 `check` 스크립트
- Produces: `resolvePlan(plan: string | null): Plan | null | undefined`

🔴 **TDD 로 하는 것과 안 하는 것을 갈라 적는다.** Step 1~6(`resolvePlan`)은 검사를 먼저 빨간불로 만든다. Step 7~9(접근성 속성, metadata 문자열)에는 **자동 검사를 안 붙인다.** 렌더러가 필요하고 이 저장소에 프론트 테스트 러너가 없다. 사용자 승인을 받은 예외이며, 그 대가는 브라우저와 눈으로만 지켜진다는 것이다.

- [ ] **Step 1: 검사를 먼저 쓴다**

`web/lib/plans.check.ts` 를 새로 만든다. 아직 `resolvePlan` 이 없으므로 지금은 돌지 않는다. 그게 맞다.

```ts
/**
 * resolvePlan 의 자체 점검. `npm run check` 가 돌린다.
 *
 * 재는 것은 하나다: <세 갈래가 뭉개지지 않는가.>
 *   null       서버 응답을 못 받았다 (새로고침하면 될 수도 있다)
 *   undefined  서버는 답했는데 우리가 모르는 요금제 id 다 (새로고침해도 그대로다)
 *   Plan       알아냈다
 * 🔴 이 저장소가 낸 버그가 전부 <원인이 다른 사실을 한 값으로 뭉갠 것>이다
 *    (AGENTS.md "낸 버그 5건"). 그 규칙을 적어둔 파일 안에서 다섯 번째가 났다.
 *    그래서 규칙을 글로 적는 대신 검사로 못박는다.
 */
import { PLANS, resolvePlan } from "./plans";

let failed = 0;
let total = 0;

function check(label: string, got: unknown, expected: unknown) {
  total++;
  const ok = JSON.stringify(got) === JSON.stringify(expected);
  if (!ok) failed++;
  console.log(`  ${ok ? "✅" : "❌"} ${label}${ok ? "" : `\n       받음: ${JSON.stringify(got)}  기대: ${JSON.stringify(expected)}`}`);
}

console.log("resolvePlan: 세 갈래가 뭉개지지 않는가\n");

check("못 불러옴은 null 이다", resolvePlan(null), null);
check("아는 요금제는 그 정의를 준다", resolvePlan(PLANS[0].id)?.id, PLANS[0].id);
check("모르는 id 는 undefined 다", resolvePlan("enterprise"), undefined);
// 위 둘을 각각 통과해도 <서로 같은 값>이면 화면은 구별하지 못한다. 그것까지 못박는다.
check("모르는 id 와 못 불러옴이 같은 값이 아니다", resolvePlan("enterprise") === resolvePlan(null), false);

console.log(failed === 0 ? `\nOK: ${total}가지 통과` : `\n🔴 ${failed}건 실패`);
if (failed) process.exit(1);
```

- [ ] **Step 2: 지금 화면이 하는 일 그대로를 `plans.ts` 에 옮긴다**

🔴 **일부러 고치지 않고 옮긴다.** `account/page.tsx:394` 의 현재 식(`?? null`)을 그대로 쓴다. 검사가 실제 버그를 잡는지 먼저 봐야 한다.

`web/lib/plans.ts` 끝에 붙인다.

```ts
/**
 * 요금제 id 를 그 정의로 바꾼다.
 *
 * ⚠️ 인자가 `PlanId` 가 아니라 `string | null` 이다. 값이 <네트워크에서> 오기 때문이다.
 *    서버가 우리보다 새 버전이면 우리가 모르는 id 를 준다. 타입에 `PlanId` 라고 적는 것과
 *    런타임이 그 약속을 지키는 것은 다른 일이다.
 */
export function resolvePlan(plan: string | null): Plan | null | undefined {
  return plan === null ? null : (PLANS.find((p) => p.id === plan) ?? null);
}
```

`web/package.json` 의 `check` 스크립트에 붙인다.

```json
    "check": "tsx lib/redirect.check.ts && tsx lib/wallet.check.ts && tsx lib/plans.check.ts"
```

- [ ] **Step 3: 검사를 돌려 빨간불을 확인한다**

Run: `cd web && npm run check`

Expected: 종료코드 1. 앞의 두 검사는 통과하고 `plans.check.ts` 는 **4가지 중 2건**이 `❌` 다. **이 숫자는 실측했다.**

```
  ❌ 모르는 id 는 undefined 다
       받음: null  기대: undefined
  ❌ 모르는 id 와 못 불러옴이 같은 값이 아니다
       받음: true  기대: false
🔴 2건 실패
```

🔴 **2건이 아니면 멈춘다.** Step 1 의 기대값이나 Step 2 의 옮겨 적기를 다시 본다.

- [ ] **Step 4: `resolvePlan` 을 고친다**

`?? null` 한 조각을 걷어낸다. 그게 뭉개던 자리다.

```ts
export function resolvePlan(plan: string | null): Plan | null | undefined {
  /* 🔴 `?? null` 을 쓰지 않는다. 그러면 "모르는 id" 가 "못 불러옴" 으로 둔갑하고,
     화면이 그 사람에게 <영원히 안 통하는> "새로고침하세요" 를 안내하게 된다.
     `find` 가 주는 undefined 를 그대로 흘려보내는 것이 세 번째 갈래다. */
  return plan === null ? null : PLANS.find((p) => p.id === plan);
}
```

- [ ] **Step 5: 검사를 돌려 초록불을 확인한다**

Run: `cd web && npm run check`
Expected: 종료코드 0. `redirect` 22가지 + `wallet` 18가지 + `plans` 4가지 전부 `✅`.

- [ ] **Step 6: 화면이 `resolvePlan` 을 쓰게 한다**

`web/app/(dashboard)/account/page.tsx` 의

```tsx
  /* 지금 요금제의 정의(이름·금액·포함량). plan 이 null 이면 <모른다>는 뜻이라 null 로 둔다 —
     `?? PLANS[0]` 같은 기본값을 쓰면 못 불러온 것을 "무료 요금제" 라고 <거짓말>하게 된다. */
  const current = plan === null ? null : (PLANS.find((p) => p.id === plan) ?? null);
```

를 아래로 바꾼다.

```tsx
  /* 지금 요금제의 정의(이름·금액·포함량). 세 갈래를 <가른다>: null 은 못 불러온 것,
     undefined 는 서버가 우리가 모르는 id 를 준 것, 나머지는 알아낸 것.
     `?? PLANS[0]` 같은 기본값을 쓰면 못 불러온 것을 "무료 요금제" 라고 <거짓말>하게 된다.
     판단은 lib/plans.ts 에 있고 lib/plans.check.ts 가 지킨다. */
  const current = resolvePlan(plan);
```

import 를 맞춘다. `PLANS` 를 이 파일에서 더 쓰지 않으면 함께 정리한다(`tsc` 가 알려준다).

```tsx
import { resolvePlan } from "@/lib/plans";
```

- [ ] **Step 7: 비활성 삭제 버튼의 이유를 보이는 문장으로 바꾼다**

`web/app/(dashboard)/account/page.tsx` 의 `CardItem` 안

```tsx
          {!card.isDefault && (
            <button
              type="button"
              onClick={onSetDefault}
              disabled={busy}
              className="text-xs text-muted underline hover:text-foreground disabled:opacity-50"
            >
              기본으로
            </button>
          )}
          <button
            type="button"
            onClick={onArm}
            disabled={busy || !deletable}
            aria-label={`${label} 삭제`}
            title={deletable ? undefined : "다른 카드를 기본으로 지정한 뒤 삭제할 수 있습니다."}
            className="ml-auto text-xs text-danger underline disabled:opacity-40 disabled:no-underline"
          >
            삭제
          </button>
```

를 아래로 바꾼다.

```tsx
          {!card.isDefault && (
            <button
              type="button"
              onClick={onSetDefault}
              disabled={busy}
              /* 서랍에는 같은 카드사 카드가 최대 4장까지 들어간다. "기본으로" 라는 글자만으로는
                 스크린리더 사용자가 어느 카드의 버튼인지 알 수 없다. 삭제 버튼과 같은 label 을 쓴다. */
              aria-label={`${label} 기본으로 지정`}
              className="text-xs text-muted underline hover:text-foreground disabled:opacity-50"
            >
              기본으로
            </button>
          )}
          {!deletable && (
            /* 왜 title 이 아니라 <보이는 문장>인가: 비활성 버튼은 초점을 받지 못해
               키보드·스크린리더 사용자가 title 에 도달할 방법이 아예 없다. 눈으로 보는
               사람도 마우스를 올려야만 읽을 수 있었다. 이유는 늘 보이는 편이 낫다. */
            <span className="text-xs text-muted">
              다른 카드를 기본으로 지정한 뒤 삭제할 수 있습니다.
            </span>
          )}
          <button
            type="button"
            onClick={onArm}
            disabled={busy || !deletable}
            aria-label={`${label} 삭제`}
            className="ml-auto text-xs text-danger underline disabled:opacity-40 disabled:no-underline"
          >
            삭제
          </button>
```

⚠️ `!card.isDefault` 와 `!deletable` 는 동시에 참이 되지 않는다. `deletable` 이 거짓인 경우는 "기본 카드인데 다른 카드가 남아 있을 때" 하나뿐이다.

- [ ] **Step 8: 앵커 도착지에 이름을 준다**

`web/app/(site)/pricing/page.tsx` 의

```tsx
      <section id="plans" className="mt-12 scroll-mt-8">
```

를 아래로 바꾼다. `/account` 가 이 자리를 직접 겨냥하므로, 건너뛰어 온 사람에게 여기가 어디인지 알려줄 이름이 필요하다.

```tsx
      {/* aria-label 을 붙이는 이유: /account 의 "요금제 바꾸기" 가 이 자리로 바로 내려꽂는데,
          제목 없는 section 은 랜드마크 목록에서 이름 없는 칸으로만 보인다. */}
      <section id="plans" aria-label="요금제" className="mt-12 scroll-mt-8">
```

🔴 **이 단계는 원래 Task 4(`main` 직행)에 있었다.** 바꾸는 이유를 설명하는 데 세 줄이 드는 것을 보고 옮겼다. 설명이 필요하면 PR 이라는 것이 이 저장소의 기준이다.

- [ ] **Step 9: `pricing` 의 metadata 에서 숫자와 낡은 주장을 뺀다**

`web/app/(site)/pricing/page.tsx` 의

```ts
export const metadata: Metadata = {
  title: "요금제 — AllDap",
  description:
    "봇이 답하지 못한 질문에는 요금을 받지 않습니다. 무료(월 200건)와 Pro(월 29,000원 · 3,000건) 두 플랜이며, 금액은 파일럿 전 가정값입니다.",
};
```

를 아래로 바꾼다. 이 파일은 스스로 "숫자의 원본은 lib/plans.ts 하나다. 이 파일에 숫자를 직접 적지 않는다" 고 적어놓고 metadata 에서만 어기고 있었다. 그리고 "가정값입니다" 는 화면에서 뺀 주장이라 검색 결과에만 남아 있었다.

```ts
export const metadata: Metadata = {
  title: "요금제 — AllDap",
  /* 숫자를 적지 않는다. 이 파일의 규칙이 그렇고(원본은 lib/plans.ts 하나),
     두 벌이 되면 요금이 바뀔 때 한쪽만 고치는 사고가 난다. */
  description: "봇이 답하지 못한 질문에는 요금을 받지 않습니다. 무료와 Pro 두 요금제가 있습니다.",
};
```

⚠️ `title` 의 문자는 원래 있던 것이라 건드리지 않는다.

- [ ] **Step 10: 그 세 번째 갈래를 화면에 그린다**

같은 파일의

```tsx
        {current === null ? (
          <p className="mt-4 text-sm text-muted">
            요금제를 불러오지 못했습니다. 화면을 새로고침해주세요. (카드 관리는 위에서 계속 쓸 수
            있습니다)
          </p>
        ) : (
```

를 아래로 바꾼다.

```tsx
        {current === null ? (
          <p className="mt-4 text-sm text-muted">
            요금제를 불러오지 못했습니다. 화면을 새로고침해주세요. (카드 관리는 위에서 계속 쓸 수
            있습니다)
          </p>
        ) : current === undefined ? (
          /* 서버는 답했는데 우리가 모르는 요금제 id 다. 새로고침해도 그대로다.
             할 수 있는 일이 문의뿐이라 그렇게 안내한다. */
          <p role="alert" className="mt-4 text-sm text-danger">
            알 수 없는 요금제입니다 ({plan}). 새로고침해도 달라지지 않으니 문의해주세요.
          </p>
        ) : (
```

- [ ] **Step 11: 로컬 검사를 통과시킨다**

Run: `cd web && npx tsc --noEmit && npm run lint && npm run check`
Expected: 셋 다 종료코드 0.

🔴 `current` 의 타입이 `Plan | null | undefined` 가 되므로 아래쪽에서 `current.name` 등을 쓰는 자리가 좁혀지는지 `tsc` 가 확인해준다. 빨간불이 나면 삼항 순서(`null` 먼저, `undefined` 다음)를 다시 본다.

- [ ] **Step 12: 커밋**

```bash
cd /Users/cheonjamin/projects/AllDap
git add web/lib/plans.ts web/lib/plans.check.ts web/package.json "web/app/(dashboard)/account/page.tsx" "web/app/(site)/pricing/page.tsx"
git commit -m "fix: 모르는 요금제 id 를 가르고, 카드 버튼 접근성 셋을 고친다

비활성 삭제 버튼의 이유가 title 에만 있었다. 비활성 버튼은 초점을 못 받아
키보드와 스크린리더가 도달할 방법이 없다. 늘 보이는 문장으로 바꿨다.
\"기본으로\" 버튼에는 aria-label 이 없어 같은 카드사 카드가 여럿일 때 구별되지 않았다.
/pricing 의 앵커 도착지 section 에 이름을 줬다. /account 가 이 자리를 직접 겨냥한다.

/pricing 의 metadata description 도 고쳤다. 이 파일이 스스로 \"숫자를 직접 적지 않는다\"
고 적어놓고 metadata 에서만 어기고 있었고, 화면에서 뺀 \"가정값\" 주장이 검색 결과에만
남아 있었다.

PLANS.find 의 결과를 ?? null 로 뭉개던 것을 lib/plans.ts 의 resolvePlan 으로
옮기고 세 갈래를 갈랐다. 서버가 우리가 모르는 요금제 id 를 주면
\"새로고침하세요\" 가 나가는데 그건 영원히 안 통한다.
lib/plans.check.ts 를 먼저 빨간불(2건)로 만든 뒤 고쳤다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 8: 결정을 기록하고 PR② 를 올린다

**Files:**
- Modify: `docs/decisions.md`

**Interfaces:**
- Consumes: Task 5~7 의 커밋
- Produces: PR 번호 하나. 이 계획의 마지막이다.

- [ ] **Step 1: `docs/decisions.md` 에 두 줄을 추가한다**

파일 끝에 빈 줄 하나를 두고 아래를 추가한다.

```
2026-09-08 | 기본 카드가 없을 때 카드 목록을 새로 그리지 않고 `<details>` 블록을 `billed` 분기 <밖으로> 꺼냈다 | 카드는 있고 기본이 없으면 `billed` 가 undefined 라 "카드 0장" 분기로 떨어져 **목록이 통째로 안 그려졌다.** 그 상태의 사용자는 자기 카드를 보지도 지우지도 못하는데 토스에는 빌링키가 남는다. 경고 문구와 카드 목록을 그 분기 안에 새로 쓰면 마크업이 두 벌이 되고, 이 저장소는 이미 "같은 것을 두 곳에 두면 한쪽만 고치는 사고가 난다" 를 여러 번 적어놨다(`AddCardTile` 을 따로 뺀 이유가 그것이다). 조건만 `methods.length > 0` 으로 바꾸면 마크업은 한 벌 그대로고, 그 분기에 없던 `full` 가드도 저절로 따라온다. 어느 카드로 청구되는지는 <우리도 모르므로> 아무 카드나 청구 카드로 그리지 않고 모른다고 말한다 | ① `billed` 에 `?? methods[0]` 기본값 주기: 모르는 것을 아는 척하게 된다. 이 저장소가 반복해 낸 버그의 정확한 모양이다 ② 그 분기에 목록을 따로 그리기: 마크업 두 벌 ③ 프론트에서 자동으로 첫 카드를 기본 지정해 고치기: 사용자 동의 없이 청구 카드를 정하는 것이라 더 나쁘다. 뿌리인 `BillingService.register` 의 경합은 별도 슬라이스다

2026-09-08 | `PlanCards` 의 요금제 상태를 `planFailed` 로 갈랐고, `/account` 의 `PLANS.find` 결과도 `?? null` 을 걷어내 세 갈래로 갈랐다 | 둘 다 <원인이 다른 사실을 한 값으로 뭉갠> 것이다. `PlanCards` 는 "아직 안 불러옴" 과 "못 불러옴" 이 같은 `null` 이라 요청이 실패하면 바꾸기 버튼이 이유 없이 사라졌고, `/account` 는 "못 불러옴" 과 "서버가 우리가 모르는 id 를 줌" 이 같은 `null` 이라 후자에게 **영원히 안 통하는 "새로고침하세요"** 를 안내했다. `AGENTS.md` 가 기록한 "낸 버그 5건" 이 전부 이 모양이고, 다섯 번째는 그 규칙을 적어둔 파일 안에서 났다. 여섯 번째와 일곱 번째다 | ① `PlanCards` 에도 `/account` 처럼 `loading` 불리언을 두기: 실패와 로딩을 또 다른 조합으로 나눠야 해서 상태가 하나 더 는다. 필요한 구분은 "실패했는가" 하나다 ② 모르는 요금제 id 에 `PLANS[0]` 을 쓰기: 같은 뭉개기다 ③ 서버 응답 타입을 좁혀 애초에 모르는 id 가 못 오게 하기: 옳지만 `api/` 를 건드리는 별도 슬라이스이고, 그래도 프론트는 방어해야 한다
```

- [ ] **Step 2: 전체 검사를 다시 돌린다**

Run: `cd web && npx tsc --noEmit && npm run lint && npm run check`
Expected: 셋 다 종료코드 0.

🔴 `npm run check` 는 이제 셋을 돌린다: `redirect.check.ts`(22) · `wallet.check.ts`(18) · `plans.check.ts`(4). Task 5 와 7 이 차례로 붙였다.

- [ ] **Step 3: 커밋하고 민다**

```bash
cd /Users/cheonjamin/projects/AllDap
git add docs/decisions.md
git commit -m "docs: 카드 목록 재배치와 상태 가르기의 근거를 남긴다

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git push -u origin fix/account-card-states
```

- [ ] **Step 4: PR 을 올린다**

`.github/PULL_REQUEST_TEMPLATE.md` 를 채운다. "한계 & 트레이드오프" 에 아래를 반드시 적는다.

- **B-3 의 뿌리인 `BillingService.register` 의 TOCTOU 경합은 안 고쳤다.** 프론트가 그 상태를 견디게만 했다. 경합 자체는 재현하지 않았고, 서버 수정은 별도 슬라이스다.
- `<details open={...}>` 는 제어 컴포넌트가 아니다. 사용자가 손으로 닫으면 그대로 닫혀 있고, 우리는 `justAddedId` 나 `billed` 가 **바뀔 때만** 연다. 의도한 동작이지만 "왜 안 열리지" 로 읽힐 여지가 있다.
- 접근성 수정은 스크린리더로 실제 검증하지 않았다. 코드 수준의 개선이다.
- 묶음 ④ 의 나머지(CTA 문구·목적지, `EvidenceKind` 3벌 중복, `DemoConsole` 빈 줄, `nextPath()` 이중 호출)는 **판정만 하고 안 고쳤다.** 값어치 판단으로 미룬 것이지 반증한 것이 아니다.

```bash
cat > /tmp/pr2-body.md <<'BODY'
## 해결하려는 문제가 무엇인가요?

`/account` 의 카드 지갑에 세 가지가 있었다.

**① 기본 카드가 없으면 카드가 통째로 안 보인다.** `billed = data.methods.find((m) => m.isDefault)` 인데, 카드는 있고 기본이 하나도 없으면 `undefined` 라 **"카드 0장" 분기로 떨어져 등록 타일만 그린다.** 그 상태의 사용자는 자기 카드를 보지도 지우지도 못하는데 토스에는 빌링키가 남는다. V7 의 부분 유니크 인덱스는 "기본 1장 이하" 만 보장하고 "1장 이상" 은 앱 코드가 지키는데, `BillingService.register` 에 TOCTOU 경합이 있다. 같은 분기의 `AddCardTile` 에는 `full` 가드도 없었다.

**② 두 번째부터 등록한 카드가 닫힌 서랍에 숨는다.** 첫 카드만 `isDefault` 라 나머지는 전부 `others` 행인데 `<details>` 에 `open` 이 없었다. 등록에 성공해도 화면에 아무 변화가 없어 실패한 것처럼 보인다. 부작용으로 `justAddedId` + `alldap-card-in` 등장 애니메이션이 **첫 카드에서만** 동작했다. `globals.css:151-152` 가 설명하는 코드가 사실상 죽어 있었다.

**③ 요금제를 못 불러오면 버튼이 이유 없이 사라진다.** `PlanCards` 의 `plan` 이 `PlanId | null` 하나라 **"아직 안 불러옴" 과 "못 불러옴" 이 같은 값**이다. `GET /api/plan` 이 실패하면 바꾸기 버튼이 조용히 사라져서, `/account` 의 "요금제 바꾸기" 로 온 사람은 **기능이 없는 화면**이라고 읽는다. `/account` 는 같은 상황을 `loading` 으로 갈라 안내하고 있었다.

거기에 접근성 셋과 뭉갠 값 하나를 함께 고쳤다.

## 왜 해야 하나요?

①은 사용자가 **자기 결제 수단을 잃어버린 것처럼 보이는** 상태다. 돈이 걸린 화면에서 가장 나쁜 종류의 화면이다.

③은 이 저장소가 반복해 내는 부류다. `AGENTS.md` 의 "낸 버그 5건" 이 전부 **원인이 다른 두 사실을 같은 값으로 뭉갠 것**이고, 다섯 번째는 그 규칙을 적어둔 파일 안에서 났다. 여섯 번째와 일곱 번째를 여기서 닫는다.

## 어떻게 해결했나요?

- [ ] `api/` (Spring Boot)
- [x] `web/` (Next.js)
- [ ] `ai-service/` (Python)
- [ ] `widget/` (임베드 위젯)
- [ ] `db/` · 마이그레이션
- [x] 문서 · 설정 · CI

**①** 카드 목록(`<details>`)을 `billed` 분기 **밖으로** 꺼내 조건을 `data.methods.length > 0` 으로 바꿨다. 경고와 목록을 그 분기 안에 새로 쓰면 마크업이 두 벌이 되는데, 이 저장소는 이미 그 이유로 `AddCardTile` 을 따로 뺐다. 조건만 바꾸면 마크업은 한 벌 그대로고 **그 분기에 없던 `full` 가드도 저절로 따라온다.**
어느 카드로 청구되는지는 우리도 모르므로 **아무 카드나 청구 카드로 그리지 않는다.** 모른다고 말하고 서랍을 열어 기본을 지정할 수 있게 한다.

**②** `<details open={justAddedId !== null || !billed}>`. ①과 **같은 줄**이라 한 커밋으로 묶었다. 나누면 한 PR 안에서 같은 줄을 두 번 바꾸는 커밋이 남고, 리뷰어는 첫 번째 버전을 읽을 이유가 없다.
제어 컴포넌트가 아니다. React 는 이 prop 이 바뀔 때만 DOM 을 건드리므로 사용자가 손으로 닫으면 그대로 닫혀 있다.

**③** `planFailed` 를 따로 두고, 실패했을 때 버튼이 사라진 이유를 화면에 적는다.

**접근성 셋**: 비활성 삭제 버튼의 이유를 `title` 에서 **보이는 문장**으로 옮겼다(비활성 버튼은 초점을 못 받아 키보드·스크린리더가 `title` 에 도달할 방법이 아예 없다). "기본으로" 버튼에 `aria-label` 을 붙였다(서랍에 같은 카드사 카드가 최대 4장이라 구별이 안 됐다). `/pricing` 의 앵커 도착지 `<section id="plans">` 에 이름을 줬다.

**뭉갠 값 하나**: `PLANS.find(...) ?? null` 을 걷어냈다. 서버가 우리가 모르는 요금제 id 를 주면 "새로고침하세요" 가 나갔는데 그건 영원히 안 통한다.

**`/pricing` 의 metadata description**: 이 파일이 스스로 *"숫자의 원본은 lib/plans.ts 하나다. 이 파일에 숫자를 직접 적지 않는다"* 고 적어놓고 metadata 에서만 어기고 있었다. 그리고 화면에서 뺀 "가정값" 주장이 검색 결과에만 남아 있었다. 숫자를 뺐다.
⚠️ **처음에는 이걸 `main` 직행으로 분류했다가 옮겼다.** 바꾸는 이유를 설명하는 데 세 줄이 드는 것을 보고 기준을 다시 봤다. 설명이 필요하면 PR 이라는 것이 이 저장소의 기준이고, 그 기준이 프로젝트 1순위 목적과 직결된다.

### 검증

**①과 ②는 TDD 로 했다.** 깨진 것이 마크업이 아니라 <분기 판단>이라 렌더러 없이 잴 수 있다. 판단을 `lib/wallet.ts` 로 빼고 `lib/wallet.check.ts` 를 **먼저 빨간불로** 만든 뒤 고쳤다.

```
$ cd web && npm run check      # 수정 전
  ❌ 기본 없음: 서랍을 그린다        받음: false  기대: true
  ❌ 기본 없음: 경고한다
  ❌ 기본 없음: 서랍을 열어둔다
  ❌ 방금 추가: 서랍을 열어둔다
🔴 4건 실패                       # 종료코드 1

$ cd web && npm run check      # 수정 후
OK: 18가지 통과                   # 종료코드 0
```

🔴 **예측이 두 군데 틀렸다는 것이 이 방식의 값어치다.** 처음에는 6건이 빨간불일 것이라 봤는데 실제로는 4건이었다. `"기본 없음: 두 장 다 서랍에 있다"` 와 `full` 가드는 **지금 코드에서도 통과한다** (`others` 는 `m.id !== billed?.id` 로 거르는데 `billed` 가 `undefined` 면 아무것도 안 걸러진다). **값은 이미 맞았고, 그 값을 쓰는 분기에 도달하지 못한 것**이 버그였다. 짐작만 했으면 엉뚱한 곳을 고쳤을 것이다.

`resolvePlan` 도 같은 방식이다: `plans.check.ts` 4가지 중 2건 빨간불 → 고침 → 4가지 통과.

`npx tsc --noEmit` · `npm run lint` 통과.

브라우저 실측 (`preview_start` 로 띄운 dev 서버):

- 카드 0장: 등록 타일만 보인다
- 카드 1장: 청구 카드가 펼쳐져 있고 서랍은 "다른 카드 없음 · 카드 추가"
- 카드 2장: **두 번째 카드가 열린 서랍 안에 보인다** (전에는 닫힌 서랍에 숨었다)
- 기본 카드 없음(DB 에서 `is_default = false` 로 만들어 재현): **경고 한 줄 + 펼쳐진 카드 목록.** 각 카드에 "기본으로" 버튼이 있다. 전에는 이 상태에서 카드가 하나도 안 보였다
- `GET /api/plan` 실패: 붉은 안내 한 줄이 뜨고 요금제 내용은 그대로 읽힌다

## 이 PR의 한계 & 트레이드오프

- 🔴 **①의 뿌리인 `BillingService.register` 의 TOCTOU 경합은 안 고쳤다.** 프론트가 그 상태를 견디게만 했다. **경합 자체는 재현하지 않았고**, 코드를 읽어 가능하다고 판단한 것이다. 서버 수정은 별도 슬라이스다.
- **`<details open={...}>` 는 제어 컴포넌트가 아니다.** 사용자가 손으로 닫으면 그대로 닫혀 있고, 우리는 `justAddedId` 나 `billed` 가 **바뀔 때만** 연다. 의도한 동작이지만 "왜 다시 안 열리지" 로 읽힐 여지가 있다.
- 🔴 **③(`planFailed`)과 접근성·metadata 에는 자동 검사가 없다.** 판단이 렌더 가드라 순수 함수로 뽑아도 조건 하나짜리 껍데기가 되고, 실제로 재려면 렌더러가 필요한데 이 저장소에 프론트 테스트 러너가 없다. 러너 도입은 별도 슬라이스다. **대가는 그 셋이 브라우저와 눈으로만 지켜진다는 것**이고, 나중에 누가 지워도 CI 는 모른다.
- **접근성 수정을 스크린리더로 실제 검증하지 않았다.** 코드 수준의 개선이고, `title` 을 보이는 문장으로 바꾼 것은 눈으로 확인했다.
- **리뷰 Minor 중 넷은 판정만 하고 안 고쳤다**: `/pricing`·`/faq`·`ReceptionHero` 의 CTA 문구와 목적지(카피 결정이라 별도), `EvidenceKind` 유니온 3벌 중복(파일 계열이 다르다), `DemoConsole.tsx:362` 빈 줄(값어치 없음), `auth/page.tsx` 의 `nextPath()` 이중 호출 경합(**실측으로 재현되지 않았다**). 값어치 판단으로 미룬 것이지 반증한 것이 아니다.
- **B-6 은 고치지 않기로 결정했다.** `/pricing` 의 "결제 미연결" 문구를 되살리자는 제안인데, 사용자가 명시적으로 제거를 지시한 결정이고 돈이 나갈 경로도 없다.

## 기존 기능에 미치는 영향

- **환각 억제(fallback)**: 해당 없음.
- **봇 간 격리**: 해당 없음. 이 화면은 `bot_id` 를 다루지 않는다.
- **테이블 소유권 · Flyway**: 해당 없음. 마이그레이션이 없고 서버 코드를 안 건드린다.
- **에러 포맷 · camelCase**: 해당 없음. API 를 바꾸지 않는다.
- **시크릿**: 없음.
- **비용**: LLM 호출 없음. 요청 수도 그대로다.
- **동작 변화**: 정상 상태(기본 카드가 정확히 한 장)의 화면은 서랍이 열려 있는지 말고는 같다. 달라지는 것은 전부 **전에 화면이 잘못 그려지던 상태**다.
- **배포**: 코드 외 할 일 없음.

## Edge Case & 실패 시나리오

- **카드 0장**: 등록 타일만. `full` 이 참일 수 없어 가드가 필요 없다.
- **카드 5장(상한)**: 서랍 안 `!full` 가드가 등록 타일을 숨기고 안내 문구가 뜬다. **기본이 없는 상태에서도 이제 이 가드를 지난다.** 전에는 그 분기에 가드가 아예 없었다.
- **기본이 없는데 카드가 5장**: 경고 + 목록 + 상한 안내. 전에는 화면이 비어 있었다.
- **`GET /api/plan` 실패**: 이유를 적고 마케팅 본문은 그대로 보여준다.
- **서버가 모르는 요금제 id 를 줌**: "새로고침" 이 아니라 "문의해주세요" 로 안내한다. 새로고침은 영원히 안 통하기 때문이다.
- **"없어서 0" 과 "못 재서 0"**: 이 PR 이 고치는 것이 정확히 그 구분이다. `planFailed` 와 `current === undefined` 둘 다 뭉개져 있던 사실을 갈랐다.
- **카드 삭제 중 연타**: `busyId` 로 버튼이 잠긴다. 기존 동작이고 이 PR 이 안 건드렸다.

## 검토한 대안과 선택 이유

- **`billed` 에 `?? methods[0]` 기본값** → 기각. 모르는 것을 아는 척하게 된다. 이 저장소가 반복해 낸 버그의 정확한 모양이고, `/account` 가 `?? PLANS[0]` 을 안 쓴 이유와 같다.
- **기본 없음 분기에 목록을 따로 그리기** → 기각. 마크업이 두 벌이 된다.
- **프론트가 자동으로 첫 카드를 기본 지정** → 기각. 사용자 동의 없이 청구 카드를 정하는 것이라 더 나쁘다.
- **`PlanCards` 에도 `/account` 처럼 `loading` 불리언** → 기각. 실패와 로딩을 또 다른 조합으로 나눠야 해서 상태가 하나 더 는다. 필요한 구분은 "실패했는가" 하나다.
- **비활성 버튼에 `aria-disabled` + `aria-describedby`** → 기각. 보이는 문장 한 줄이 더 짧고 **눈으로 보는 사람에게도 도움이 된다.** aria 배관은 마우스 사용자에게 아무것도 주지 않는다.

## 리뷰 포인트 (파일/영역별 Risk)

| Risk | 파일 / 영역 | 봐야 할 것 |
|---|---|---|
| 🔴 | `web/lib/wallet.ts` | 판단이 여기로 다 왔는가. 화면에 남은 조건문이 없는가 |
| 🔴 | `web/app/(dashboard)/account/page.tsx` 카드 목록 블록 | JSX 를 옮긴 작업이다. 세 상태(0장 / 정상 / 기본 없음)가 전부 맞게 그려지는가. 청구 카드가 서랍에 **두 번** 그려지지 않는가 |
| 🟡 | `web/components/PlanCards.tsx` | `planFailed` 가 토큰이 바뀔 때 초기화되는가. 실패 안내가 마케팅 본문을 가리지 않는가 |
| 🟡 | `account/page.tsx` 의 `current` 삼항 | `null`(못 불러옴)과 `undefined`(모르는 id)의 순서. 뒤집으면 안내가 서로 바뀐다 |
| 🟢 | 접근성 세 곳, `/pricing` 의 `aria-label` 과 metadata | 문구와 속성 |

🤖 Generated with [Claude Code](https://claude.com/claude-code)

BODY

gh pr create --base main --head fix/account-card-states \
  --title "fix: /account 의 카드 화면 결함 셋과 접근성 셋" \
  --body-file /tmp/pr2-body.md
```

🔴 **CI 결과를 기다리지 않는다.**

---

## 이 계획이 다루지 않는 것 (알고 남긴다)

| 항목 | 왜 안 하나 |
|---|---|
| B-6 `/pricing` 의 "미정" 근거 되살리기 | 사용자가 명시적으로 제거를 지시한 결정이다. 리뷰어도 돈이 나갈 경로는 없다고 인정했다 |
| A-2 대시보드 가드에 `?next=` | 붙이면 비로그인 상태의 주소창에 봇 UUID 가 남는다. Task 3 에서 한계로만 적는다 |
| `/pricing`·`/faq`·`ReceptionHero` 의 CTA 문구·목적지 | 도착지 가드는 옳다. 고칠 자리는 카피이고 별도 슬라이스다 |
| `EvidenceKind` 유니온 3벌 중복 | `Evidence.tsx` 에서 export 하면 풀리지만 이 PR 들과 파일 계열이 다르다 |
| `DemoConsole.tsx:362` 빈 줄 | 값어치가 없다 |
| `auth/page.tsx` 의 `nextPath()` 이중 호출 경합 | 실측으로 재현되지 않았다(React 스케줄링이 막는다) |
| `BillingService.register` 의 TOCTOU 경합 | B-3 의 뿌리이지만 서버 수정이고 재현도 안 했다. 별도 슬라이스 |
