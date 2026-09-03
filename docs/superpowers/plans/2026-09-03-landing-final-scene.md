# 랜딩 마지막 장면 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 랜딩에서 고용하기가 뜬 뒤 스크롤이 또 먹는 것을 없애고, `/demo` 에서 돌아오면 로봇 화면으로 오게 하고, 마지막 장면 우상단에 기능·요금제·FAQ 를 띄운다.

**Architecture:** 세 변경 모두 `web/components/ReceptionHero.tsx` 한 파일이다. 진행도 `p`(0~1)를 매 프레임 rAF 루프가 읽어 문·카메라·UI 를 그리는 구조는 그대로 두고, **언제 무엇이 일어나는가**만 바꾼다. 각 장면의 모양과 곡선은 건드리지 않는다.

**Tech Stack:** Next.js 16.2.12 (App Router) · React 19.2.4 · TypeScript · Tailwind CSS 4

**설계 문서:** [`docs/superpowers/specs/2026-09-03-landing-final-scene-design.md`](../specs/2026-09-03-landing-final-scene-design.md)

## Global Constraints

- **브랜치는 `feat/landing-final-scene`.** `main` 에 직접 커밋하지 않는다.
- **파일 하나만 바꾼다: `web/components/ReceptionHero.tsx`.** `(site)` 헤더·`app/page.tsx`·`globals.css` 를 건드리지 않는다.
- **새 의존성을 추가하지 않는다.** `web/` 에는 테스트 프레임워크가 없다(vitest·jest 모두 없음, 테스트 파일 0건). CI 는 `npm run lint` 와 `npm run build` 둘뿐이다.
- **검증은 브라우저 실측이다.** 이 저장소가 `web/` 를 검증해 온 방식이다.
- **주석은 한국어.** TypeScript/React 코드에는 왜 그렇게 썼는지 설명을 붙인다 — 이 저장소의 1순위 목적이 "설명할 수 있는 코드"다.
- **`STEPS` · `REVEAL` · `DOOR_COUNT` 의 정의를 바꾸지 않는다.** 문 열림 구간·CTA 페이드·로봇 클릭 조건이 전부 거기서 계산된다. 문 개수를 3→1 로 줄였다가 **CTA 가 영영 안 뜨는 버그**를 이미 낸 적이 있고 그 경고가 `REVEAL` 선언부 주석에 있다.
- **숨어 있는 링크는 `opacity` 만 끄지 않는다.** `visibility` 를 함께 토글한다. 안 그러면 Tab 키가 안 보이는 링크를 찾아가 Enter 로 이동한다 — 이 저장소가 CTA·로봇·레버에서 세 번 겪었다(`a5db59c`).
- **모바일 대응은 하지 않는다** (AGENTS.md 작업 규칙 6 — 공개 페이지는 데스크톱만).

**서버가 떠 있어야 한다:**

```bash
docker compose up -d && (cd api && ./gradlew bootRun &) && (cd web && npm run dev &)
```

> 🔴 **검증 전에 미리보기 패인을 반드시 앞에 둘 것.** 패인이 가려지면 브라우저가
> `requestAnimationFrame` 을 멈춰서 문이 아예 안 열린다. 설계 단계에서 실제로 겪었다 —
> 씬의 transform 이 4초 넘게 한 숫자도 안 변했다. 진행이 안 되면 코드가 아니라
> **이것부터** 의심할 것. 합성 `WheelEvent`·`KeyboardEvent` 로는 진행되지 않는 것도 확인했다.
> 진행에는 **실제 키 입력**(`computer` 도구의 `key` 액션, 패인이 앞에 있을 때)을 쓴다.
>
> 🔴 **키 이름은 `ArrowDown` / `ArrowUp` 이다.** `Down` / `Up` 으로 보내면 이벤트는 도착하지만
> `e.key` 가 달라 `onKey` 핸들러의 조건에 안 걸린다(Task 1 에서 실제로 겪었다).
> 그리고 **새로고침한 뒤에는 화면을 한 번 클릭해 포커스를 준 다음** 키를 보내야 한다.
> 키가 가끔 한 번 누락되기도 하므로, 눌렀으면 `heroState()` 로 <실제로 진행됐는지 확인>하고
> 안 됐으면 다시 누를 것. 횟수를 세지 말고 상태를 볼 것.

---

## 공통 검사 스크립트

세 태스크가 같은 것을 읽는다. 브라우저 콘솔(또는 `javascript_tool`)에 붙여 쓴다.

```js
// 랜딩 상태 읽기 — 씬 배율, CTA, 우상단 메뉴.
function heroState() {
  const scene = document.querySelector('[style*="transform-origin"]');
  const m = scene && new DOMMatrix(getComputedStyle(scene).transform);
  const cta = document.querySelector('a[href="/auth"]');
  const nav = document.querySelector('header nav');
  const navLink = nav && nav.querySelector('a[href="/pricing"]');
  return {
    // 씬 배율. 문이 다 열리고 카메라가 로봇 앞까지 들어가면 크게 뛴다.
    scale: m ? Math.round(Math.hypot(m.a, m.b) * 1000) / 1000 : null,
    ctaOpacity: cta ? getComputedStyle(cta.closest('div[style*="opacity"]')).opacity : null,
    ctaVisibility: cta ? getComputedStyle(cta.closest('div[style*="visibility"]')).visibility : null,
    navExists: !!nav,
    navVisibility: nav ? getComputedStyle(nav).visibility : null,
    // 안 보이는 링크가 Tab 순서에 남아 있으면 접근성 결함이다.
    navFocusable: navLink ? (navLink.focus(), document.activeElement === navLink) : null,
  };
}
heroState();
```

---

### Task 1: 마지막 걸음을 스크롤에서 떼어낸다

**Files:**
- Modify: `web/components/ReceptionHero.tsx:170` (anim 초기값에 `transMs` 추가)
- Modify: `web/components/ReceptionHero.tsx:188-207` (`stepBy`)
- Modify: `web/components/ReceptionHero.tsx:291` (전환 재생이 `transMs` 를 쓰게)

**Interfaces:**
- Consumes: 없음 (첫 태스크)
- Produces: **진행도의 마지막 상태가 `p === 1`**, 사용자가 밟는 단계는 `0 … DOOR_COUNT`. Task 2 가 이 두 값을 복원에 그대로 쓴다.

---

- [ ] **Step 1: 지금 동작을 먼저 확인한다 (변경 전이라 실패해야 한다)**

미리보기 패인을 앞에 두고 `http://localhost:3000` 을 연 뒤, **아래로 두 번** 스크롤한다(실제 키 입력 `ArrowDown` 두 번, 사이에 3초씩 기다린다). 그리고 위 `heroState()` 를 실행한다.

Expected (변경 전): 문은 다 열렸지만 카메라가 아직 멀리 있다.

```
{ scale: 0.64 언저리, ctaOpacity: "1", ctaVisibility: "visible", navExists: false, ... }
```

`scale` 이 1 보다 한참 작으면 아직 다가가지 않은 것이다. 여기서 한 번 더 `Down` 을 누르면 `scale` 이 **2 배 이상으로 뛴다** — 이것이 없애려는 동작이다. 그 값도 적어 둔다.

---

- [ ] **Step 2: 전환 길이를 담을 자리를 만든다**

`web/components/ReceptionHero.tsx:170` 근처, `anim` 초기값의 `transStart` 줄 **다음**에 한 줄 추가한다.

변경 전:
```tsx
    transFrom: 0,  // 이번 전환의 출발 진행도
    transStart: 0, // 전환 시작 시각(ms). 0 이면 전환 중이 아니다
```

변경 후:
```tsx
    transFrom: 0,  // 이번 전환의 출발 진행도
    transStart: 0, // 전환 시작 시각(ms). 0 이면 전환 중이 아니다
    /* 이번 전환의 길이(ms). 전환마다 <이동 거리가 다르므로> 고정값을 쓸 수 없다.
       마지막 전환은 다른 단계의 2배를 움직이는데, 길이를 고정하면 그 구간만 2배 빨라져
       문이 열리자마자 카메라가 튀어 들어간다. */
    transMs: STEP_DURATION_MS,
```

---

- [ ] **Step 3: `stepBy` 의 상한과 목적지를 바꾼다**

`web/components/ReceptionHero.tsx:188-207`.

변경 전:
```tsx
    const next = Math.min(STEPS, Math.max(0, a.step + dir));
    if (next === a.step) return; // 양 끝에서는 더 가지 않는다
    a.step = next;
    /* 화면이 움직이면 팔은 걷는다. 안 그러면 문이 닫히거나 로봇에게 다가가는
       동안에도 팔이 천장에 매달린 채 따라다닌다. */
    setArmsOpen(false);
    // <현재 위치>에서 출발한다. 전환 도중에 방향을 바꿔도 튀지 않는다.
    a.transFrom = a.p;
    a.target = next / STEPS;
    a.transStart = performance.now();
```

변경 후:
```tsx
    /* 사용자가 밟는 단계는 <문 개수>까지다. 예전에는 STEPS(= 문 + 1)까지 밟을 수 있어서,
       고용하기가 뜬 뒤에도 스크롤이 한 번 더 먹으며 카메라만 로봇 앞으로 다가갔다.
       그 마지막 걸음은 사라진 게 아니라 아래 target 계산에서 <마지막 문 열기와 한
       전환으로 합쳐졌다>. */
    const next = Math.min(DOOR_COUNT, Math.max(0, a.step + dir));
    if (next === a.step) return; // 양 끝에서는 더 가지 않는다
    a.step = next;
    /* 화면이 움직이면 팔은 걷는다. 안 그러면 문이 닫히거나 로봇에게 다가가는
       동안에도 팔이 천장에 매달린 채 따라다닌다. */
    setArmsOpen(false);
    // <현재 위치>에서 출발한다. 전환 도중에 방향을 바꿔도 튀지 않는다.
    a.transFrom = a.p;
    /* 마지막 단계의 목적지는 문이 다 열리는 지점(REVEAL)이 아니라 <끝>(1)이다.
       그래야 한 번의 전환 안에서 앞부분은 마지막 문이 열리고(→REVEAL),
       뒷부분은 카메라가 로봇 앞으로 들어간다(REVEAL→1).
       ⚠️ STEPS 나 REVEAL 을 바꾸지 않는다 — 문 열림 구간·CTA 페이드·로봇 클릭 조건이
          전부 그 둘에서 계산되므로 한꺼번에 흔들린다(REVEAL 선언부 주석 참고). */
    a.target = next === DOOR_COUNT ? 1 : next / STEPS;
    /* 길이는 이동 거리에 비례시킨다. 한 단계(1/STEPS)를 움직이면 STEP_DURATION_MS 그대로고,
       마지막 전환은 그 2배를 움직이므로 2배 길어진다 — 눈에 보이는 속도가 같아진다. */
    a.transMs = STEP_DURATION_MS * Math.abs(a.target - a.transFrom) * STEPS;
    a.transStart = performance.now();
```

---

- [ ] **Step 4: 전환 재생이 그 길이를 쓰게 한다**

`web/components/ReceptionHero.tsx:291`.

변경 전:
```tsx
          const k = Math.min(1, (now - a.transStart) / STEP_DURATION_MS);
```

변경 후:
```tsx
          const k = Math.min(1, (now - a.transStart) / a.transMs);
```

---

- [ ] **Step 5: 브라우저에서 확인한다**

패인을 앞에 두고 `http://localhost:3000` 을 **새로고침**한 뒤, `ArrowDown` 두 번(사이 3초, 마지막 전환은 2.3초 걸린다 — 넉넉히 4초 기다릴 것). 그리고 `heroState()`.

Expected: **두 번 만에** 카메라가 로봇 앞까지 들어와 있다.

```
{ scale: 2 이상, ctaOpacity: "1", ctaVisibility: "visible", ... }
```

이어서 `ArrowDown` 을 한 번 더 누르고 3초 뒤 다시 `heroState()`.

Expected: `scale` 이 **거의 그대로**다(호흡·손떨림 때문에 ±1% 안쪽으로만 흔들린다). 2배로 뛰면 실패다.

그리고 `ArrowUp` 을 한 번 눌러 되돌아가는 것도 본다 — 카메라가 물러나며 문이 닫혀야 하고, 중간에 멈춰 갇히면 안 된다.

---

- [ ] **Step 6: 린트·빌드**

```bash
cd web && npm run lint && npm run build
```

Expected: 둘 다 오류 없이 끝난다.

---

- [ ] **Step 7: 커밋**

```bash
git add web/components/ReceptionHero.tsx
git commit -m "$(cat <<'EOF'
fix: 고용하기가 뜬 뒤 스크롤이 또 먹지 않게 했다

문이 다 열리고 고용하기가 뜬 뒤에도 스크롤이 한 번 더 먹으며 카메라만
로봇 앞으로 다가갔다. 도착한 줄 알았는데 화면이 또 움직인다.

그 마지막 걸음을 스크롤에서 떼어내 마지막 문 열기와 한 전환으로 합쳤다.
사용자가 밟는 단계를 문 개수까지로 낮추고, 그 마지막 단계의 목적지를
REVEAL 이 아니라 1 로 준다. 한 전환 안에서 앞부분은 문이 열리고 뒷부분은
카메라가 들어가므로 연출의 순서와 모양은 그대로다.

STEPS 와 REVEAL 은 건드리지 않았다. 문 열림 구간·CTA 페이드·로봇 클릭
조건이 전부 거기서 계산되고, 문 개수를 줄였다가 CTA 가 영영 안 뜨는
버그를 이미 낸 적이 있다.

전환 길이는 이동 거리에 비례하게 바꿨다. 마지막 전환만 2배를 움직이는데
1150ms 고정이면 그 구간만 2배 빨라진다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: 탭이 기억한다

**Files:**
- Modify: `web/components/ReceptionHero.tsx` (파일 상단 상수 — `STEP_DURATION_MS` 선언 근처)
- Modify: `web/components/ReceptionHero.tsx:137` 근처 (ref 하나 추가)
- Modify: `web/components/ReceptionHero.tsx:212` 근처 (마운트 effect 안, `anim.current.shake = …` 다음)
- Modify: `web/components/ReceptionHero.tsx:296` 근처 (rAF 루프에서 `const p = a.p;` 다음)

**Interfaces:**
- Consumes: Task 1 이 정한 **마지막 상태 = `step === DOOR_COUNT` 이고 `p === 1`**. 복원할 때 이 두 값을 그대로 넣는다.
- Produces: 없음.

---

- [ ] **Step 1: 지금 동작을 먼저 확인한다 (실패해야 한다)**

브라우저 콘솔에서:

```js
sessionStorage.setItem("alldap:hero-seen", "1");
location.reload();
```

새로고침이 끝나면 `heroState()`.

Expected (변경 전): 표시를 넣어도 **아무 일도 일어나지 않는다.** 문이 닫힌 채 시작한다.

```
{ scale: 1 미만, ctaOpacity: "0", ctaVisibility: "hidden", ... }
```

---

- [ ] **Step 2: 키 이름을 상수로 둔다**

`web/components/ReceptionHero.tsx` 의 `const STEP_DURATION_MS = 1150;` **바로 아래**에 넣는다.

```tsx
/**
 * 이 탭에서 이미 문을 다 열어봤는가. 값은 쓰지 않고 <있느냐>만 본다.
 *
 * sessionStorage 라 탭을 닫으면 사라진다 — 처음 온 사람은 언제나 연출을 전부 보고,
 * 이미 본 사람만 건너뛴다. localStorage 로 두면 몇 달 뒤에 다시 온 사람도
 * 이 랜딩의 유일한 볼거리를 영영 못 보게 된다.
 */
const SEEN_KEY = "alldap:hero-seen";
```

---

- [ ] **Step 3: 한 번만 저장하기 위한 ref 를 둔다**

`web/components/ReceptionHero.tsx:142` 의 `const scrollRef = useRef<HTMLDivElement>(null);` **바로 위**에 넣는다.

```tsx
  /* 끝까지 봤다는 사실을 이미 저장했는가. sessionStorage 쓰기는 동기 I/O 라
     매 프레임 부르면 애니메이션 프레임을 갉아먹는다. 한 번만 쓰려고 둔다. */
  const seenSavedRef = useRef(false);
```

---

- [ ] **Step 4: 마운트할 때 복원한다**

마운트 effect 안, `anim.current.shake = window.matchMedia(...)` 줄 **다음**에 넣는다.

```tsx
    /* 이 탭에서 이미 끝까지 본 적이 있으면 연출을 재생하지 않고 <마지막 상태로 놓는다>.
       /demo 에 갔다가 뒤로가기나 로고로 돌아오면 문부터 다시 열어야 했던 것이 이 화면의
       불편이었다. 전환(transStart)을 걸지 않으므로 애니메이션 없이 그 자리에서 시작한다.

       ⚠️ 읽기를 이 effect <안>에서 하는 이유: 서버에는 sessionStorage 가 없다.
          초기 렌더에서 읽으면 서버가 그린 HTML 과 브라우저의 첫 렌더가 어긋난다
          (이 저장소가 로그인 유지에서 같은 부류의 버그를 이미 한 번 냈다). */
    try {
      if (sessionStorage.getItem(SEEN_KEY)) {
        const a = anim.current;
        a.step = DOOR_COUNT;
        a.p = 1;
        a.target = 1;
        a.transStart = 0; // 전환 중이 아니라 <이미 도착한> 상태다
        seenSavedRef.current = true; // 이미 저장돼 있으니 다시 쓸 필요가 없다
      }
    } catch {
      /* 사파리 사생활 보호 모드 등에서는 sessionStorage 접근 <자체>가 예외를 던진다.
         기억을 못 하는 것은 불편일 뿐이라, 연출을 처음부터 보여주고 넘어간다. */
    }
```

---

- [ ] **Step 5: 끝까지 오면 저장한다**

rAF 루프 안, `const p = a.p;` **다음** 줄에 넣는다.

```tsx
      /* 끝까지 왔다는 사실을 이 탭에 남긴다. 다음에 이 랜딩을 열면 문을 건너뛴다.
         0.999 로 재는 이유: p 는 보간으로 다가가므로 정확히 1 이 되는 프레임을
         기다리면 놓칠 수 있다. */
      if (!seenSavedRef.current && p >= 0.999) {
        seenSavedRef.current = true;
        try {
          sessionStorage.setItem(SEEN_KEY, "1");
        } catch {
          /* 저장 못 해도 이번 방문의 연출에는 영향이 없다. 다음에 다시 문부터 볼 뿐이다. */
        }
      }
```

---

- [ ] **Step 6: 브라우저에서 확인한다**

1. 콘솔에서 `sessionStorage.clear()` 후 새로고침 → **문부터** 시작한다(`ctaVisibility: "hidden"`).
2. `ArrowDown` 두 번으로 끝까지 간 뒤 `sessionStorage.getItem("alldap:hero-seen")` → `"1"`.
3. 그 상태에서 **새로고침** → `heroState()` 가 곧바로 `scale` 2 이상, `ctaVisibility: "visible"`.
4. 로봇을 눌러 `/demo` 로 간 뒤 **뒤로가기** → 문이 아니라 로봇 화면.
5. 🔴 **첫 프레임에 문이 스치는지 눈으로 본다.** 스펙이 "1프레임 미만일 것으로 보지만 추정"
   이라고 적어둔 항목이다. 새로고침을 여러 번 하며 관찰할 것. 실제로 깜빡이면
   무대에 초기 `opacity: 0` 을 걸고 첫 프레임에 푸는 방식으로 막고, 그 사실을 보고서에 적는다.
   깜빡이지 않으면 "관찰했고 안 보였다"를 적는다.

---

- [ ] **Step 7: 린트·빌드**

```bash
cd web && npm run lint && npm run build
```

Expected: 둘 다 오류 없이 끝난다.

---

- [ ] **Step 8: 커밋**

```bash
git add web/components/ReceptionHero.tsx
git commit -m "$(cat <<'EOF'
feat: 랜딩을 한 번 다 본 탭은 로봇 화면에서 시작한다

/demo 에 갔다가 뒤로가기나 왼쪽 위 로고로 돌아오면 첫 문부터 다시
열어야 했다. 로봇을 보러 갔다 온 사람이 로봇에게 돌아가는 데 문을
두 번 여는 셈이었다.

끝까지 도달하면 sessionStorage 에 표시를 남기고, 랜딩이 열릴 때 그 표시가
있으면 애니메이션 없이 마지막 상태에서 시작한다. 탭을 닫으면 사라지므로
처음 온 사람은 언제나 연출을 전부 본다.

읽기는 effect 안에서만 한다. 서버에는 sessionStorage 가 없어서 초기
렌더에서 읽으면 하이드레이션이 어긋난다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: 마지막 장면 우상단 메뉴

**Files:**
- Modify: `web/components/ReceptionHero.tsx` (파일 상단 상수 — `SEEN_KEY` 아래)
- Modify: `web/components/ReceptionHero.tsx:157` 근처 (`ctaRef` 선언 옆에 `navRef`)
- Modify: `web/components/ReceptionHero.tsx:376-390` (CTA 페이드 값을 밖으로 꺼내고 메뉴에도 적용)
- Modify: `web/components/ReceptionHero.tsx:830` 근처 (`<header>` 안에 `<nav>` 추가)

**Interfaces:**
- Consumes: 없음 (Task 1·2 와 독립이다. 진행도 `p` 만 읽는다)
- Produces: 없음.

---

- [ ] **Step 1: 지금 상태를 확인한다 (실패해야 한다)**

`http://localhost:3000` 에서 `heroState()`.

Expected (변경 전): 메뉴가 아예 없다.

```
{ navExists: false, navVisibility: null, navFocusable: null, ... }
```

---

- [ ] **Step 2: 메뉴 항목을 상수로 둔다**

`const SEEN_KEY = "alldap:hero-seen";` **바로 아래**에 넣는다.

```tsx
/**
 * 마지막 장면 우상단 메뉴. `(site)` 헤더(web/app/(site)/layout.tsx)와 <같은 항목>이라
 * 두 화면에서 같은 곳으로 간다.
 *
 * ⚠️ 고용하기(/auth)는 넣지 않는다. 가운데 CTA 가 이미 그 자리이고, 같은 목적지를
 *    한 화면에 두 번 두면 "어느 쪽을 눌러야 하나"가 된다.
 * ⚠️ 문이 열리는 동안에는 이 메뉴가 보이지 않는다. 구석 메뉴를 걷어낸 결정(f66eff0,
 *    "기능은 레버가 대신한다")은 그 구간에서 그대로 유지된다.
 */
const SCENE_NAV = [
  { label: "기능", href: "/features" },
  { label: "요금제", href: "/pricing" },
  { label: "FAQ", href: "/faq" },
] as const;
```

---

- [ ] **Step 3: ref 를 하나 둔다**

`web/components/ReceptionHero.tsx:157` 의 `const ctaRef = useRef<HTMLDivElement>(null);` **바로 아래**에 넣는다.

```tsx
  /* 우상단 메뉴. CTA 와 <같은 값>으로 함께 나타난다. */
  const navRef = useRef<HTMLElement>(null);
```

---

- [ ] **Step 4: CTA 페이드 값을 블록 밖으로 꺼낸다**

`web/components/ReceptionHero.tsx:376-390`.

변경 전:
```tsx
      const cta = ctaRef.current;
      if (cta) {
        /* 마지막 문이 열려 로봇이 드러나는 순간(p ≈ 0.75)에 이미 떠 있어야 한다.
           그전까지 화면을 진행시키던 힌트는 첫 문에서 사라졌으므로, 여기서
           CTA 마저 늦게 뜨면 <누를 것도 없고 다음으로 갈 안내도 없는> 정지 화면이 된다. */
        const f = smoothstep(REVEAL - 0.12, REVEAL + 0.01, p);
        cta.style.opacity = String(f);
        cta.style.pointerEvents = f > 0.6 ? "auto" : "none";
```

변경 후:
```tsx
      /* 마지막 문이 열려 로봇이 드러나는 순간에 이미 떠 있어야 한다. 그전까지 화면을
         진행시키던 힌트는 첫 문에서 사라졌으므로, 여기서 CTA 마저 늦게 뜨면
         <누를 것도 없고 다음으로 갈 안내도 없는> 정지 화면이 된다.
         ⚠️ 블록 밖에 둔 이유: 아래 우상단 메뉴가 <같은 값>을 써야 한다.
            따로 계산하면 둘이 어긋나고, 한쪽만 고쳤을 때 조용히 벌어진다. */
      const ctaIn = smoothstep(REVEAL - 0.12, REVEAL + 0.01, p);

      const cta = ctaRef.current;
      if (cta) {
        cta.style.opacity = String(ctaIn);
        cta.style.pointerEvents = ctaIn > 0.6 ? "auto" : "none";
```

그리고 같은 블록에 남아 있는 `f` 두 곳도 `ctaIn` 으로 바꾼다.

변경 전:
```tsx
        cta.style.visibility = f > 0.01 ? "visible" : "hidden";
        cta.style.transform = `translateX(-50%) translateY(${26 - f * 26}px)`;
      }
```

변경 후:
```tsx
        cta.style.visibility = ctaIn > 0.01 ? "visible" : "hidden";
        cta.style.transform = `translateX(-50%) translateY(${26 - ctaIn * 26}px)`;
      }

      /* 우상단 메뉴는 CTA 와 <같은 값>으로 나타난다. */
      const nav = navRef.current;
      if (nav) {
        nav.style.opacity = String(ctaIn);
        nav.style.pointerEvents = ctaIn > 0.6 ? "auto" : "none";
        /* 🔴 opacity 만 끄면 안 된다. 안 보이는 상태에서도 Tab 키는 이 링크들을 찾아가
           포커스를 주고 Enter 로 이동시킨다 — 방문자에게는 아무것도 안 보이는 상태에서
           일어나는 이동이다. CTA·로봇 링크·레버에서 세 번 겪은 함정이라 함께 토글한다. */
        nav.style.visibility = ctaIn > 0.01 ? "visible" : "hidden";
      }
```

---

- [ ] **Step 5: 헤더에 메뉴를 넣는다**

`web/components/ReceptionHero.tsx:830` 근처. `<header>` 는 이미 `justifyContent: "space-between"` 이라, 두 번째 자식을 넣으면 오른쪽에 붙는다.

변경 전:
```tsx
              <span style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: 26, height: 22, border: "1.6px solid #171514", borderRadius: 4, fontSize: 11, fontWeight: 700, letterSpacing: "0.02em" }}>AI</span>
            </div>
          </header>
```

변경 후:
```tsx
              <span style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: 26, height: 22, border: "1.6px solid #171514", borderRadius: 4, fontSize: 11, fontWeight: 700, letterSpacing: "0.02em" }}>AI</span>
            </div>

            {/* 문을 다 열고 로봇을 만난 뒤에야 나타나는 메뉴. 초기값이 숨김인 것은
                rAF 루프가 첫 프레임을 그리기 전에도 안 보여야 하기 때문이다 —
                CTA 가 같은 이유로 같은 초기값을 갖고 있다. */}
            <nav
              ref={navRef}
              style={{ display: "flex", alignItems: "center", gap: 4, opacity: 0, pointerEvents: "none", visibility: "hidden" }}
            >
              {SCENE_NAV.map(({ label, href }) => (
                <Link
                  key={href}
                  href={href}
                  /* 랜딩에서 나가는 링크는 전부 문 열림 전환을 쓴다(로봇·고용하기와 같다). */
                  transitionTypes={["door"]}
                  style={{ padding: "8px 14px", borderRadius: 8, color: "#171514", fontSize: 15, fontWeight: 500, textDecoration: "none" }}
                >
                  {label}
                </Link>
              ))}
            </nav>
          </header>
```

---

- [ ] **Step 6: 브라우저에서 확인한다**

1. `sessionStorage.clear()` 후 새로고침 → `heroState()` 로 **`navExists: true`, `navVisibility: "hidden"`, `navFocusable: false`** 를 확인한다.
   🔴 `navFocusable` 이 `true` 면 안 보이는 링크가 Tab 순서에 남아 있다는 뜻이다 — 실패다.
2. `ArrowDown` 두 번으로 끝까지 간 뒤 `heroState()` → `navVisibility: "visible"`, `navFocusable: true`.
3. 화면에서 우상단에 **기능 · 요금제 · FAQ** 세 개가 CTA 와 함께 떠 있는지 스크린샷으로 확인한다.
4. **요금제**를 눌러 `/pricing` 으로 이동하는지 확인한다.

---

- [ ] **Step 7: 린트·빌드**

```bash
cd web && npm run lint && npm run build
```

Expected: 둘 다 오류 없이 끝난다.

---

- [ ] **Step 8: 커밋**

```bash
git add web/components/ReceptionHero.tsx
git commit -m "$(cat <<'EOF'
feat: 마지막 장면 우상단에 기능·요금제·FAQ 를 띄운다

랜딩은 자기 헤더를 갖고 화면 전체를 쓰는 무대라 (site) 헤더가 없다.
그래서 문을 다 열고 나면 갈 수 있는 곳이 고용하기와 로봇 둘뿐이었다.

(site) 헤더와 같은 세 항목을 CTA 와 같은 값으로 함께 띄운다. 고용하기는
가운데 CTA 가 이미 그 자리라 넣지 않았다. 문이 열리는 동안에는 여전히
메뉴가 없다 — 구석 메뉴를 걷어낸 결정은 그 구간에서 유지된다.

opacity 만 끄면 안 보이는 링크에 Tab 이 닿아 Enter 로 이동한다.
CTA·로봇·레버에서 세 번 겪은 함정이라 visibility 를 함께 토글한다.

CTA 의 페이드 값을 블록 밖으로 꺼내 둘이 같은 값을 쓰게 했다.
따로 계산하면 한쪽만 고쳤을 때 조용히 어긋난다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

**1. 스펙 커버리지**

| 스펙 항목 | 어느 태스크 |
|---|---|
| 마지막 걸음을 스크롤에서 떼어낸다 (상한 `DOOR_COUNT`, 목표 `1`) | Task 1 Step 3 |
| 전환 길이를 이동량에 비례 | Task 1 Step 2·4 |
| `STEPS`·`REVEAL` 을 건드리지 않는다 | Global Constraints · Task 1 Step 3 주석 |
| 되돌아갈 때 갇히지 않는다 | Task 1 Step 5 |
| `sessionStorage` 표시로 탭이 기억 | Task 2 Step 4·5 |
| 읽기는 effect 안에서만 | Task 2 Step 4 |
| 첫 프레임 깜빡임 관찰 (스펙이 "추정"이라 적은 항목) | Task 2 Step 6-5 |
| 우상단 기능·요금제·FAQ, 고용하기 제외 | Task 3 Step 2·5 |
| CTA 와 같은 값으로 노출 | Task 3 Step 4 |
| `visibility` 함께 토글 | Task 3 Step 4 · 검증 Step 6-1 |
| 스펙 검증 1~7번 | Task 1 Step 5·6 · Task 2 Step 6·7 · Task 3 Step 6·7 |

**2. 플레이스홀더** — 없다. 모든 단계에 실제 코드와 실제 명령이 있다.

**3. 이름 일관성** — `transMs`(Task 1 Step 2 선언 → Step 3 대입 → Step 4 사용), `SEEN_KEY`(Task 2 Step 2 선언 → Step 4·5 사용), `seenSavedRef`(Step 3 선언 → Step 4·5 사용), `navRef`(Task 3 Step 3 선언 → Step 4·5 사용), `SCENE_NAV`(Step 2 선언 → Step 5 사용), `ctaIn`(Step 4 안에서 선언·사용, 기존 `f` 를 전부 대체). 검사 스크립트 `heroState()` 가 읽는 `header nav` 와 `a[href="/pricing"]` 는 Task 3 Step 5 가 실제로 만드는 것과 일치한다.

**4. 태스크 경계** — 셋 다 따로 승인·거절할 수 있다. Task 2 는 Task 1 이 정한 마지막 상태(`p === 1`)에 의존하므로 **순서대로** 실행한다. Task 3 은 독립이지만 같은 파일이라 순서대로 두었다.
