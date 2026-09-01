# 데모 채팅 스크롤 설계 (2026-09-01)

## 문제

`/demo` 오른쪽 채팅 패널(`DemoConsole.tsx`)은 대화가 쌓일수록 **패널 자체가 세로로 길어진다.**
메시지 목록 `div` 에 높이 제한이 없어서 말풍선이 늘어난 만큼 그대로 자란다.

부작용이 둘이다.

1. 왼쪽 문서 목록과 높이가 어긋나 페이지가 계속 길어진다.
2. `<aside>` 에 걸린 `lg:sticky lg:top-8` 이 **무력해진다.** sticky 는 붙은 요소가 화면보다
   작을 때만 동작한다. 몇 턴 주고받으면 패널이 화면보다 커져서, 문서를 읽으려고 스크롤하면
   채팅창이 그대로 위로 사라진다.

저장소의 다른 채팅 화면 둘은 이미 `overflow-y-auto` 로 되어 있다
(`(widget)/w/[publicKey]/page.tsx:172`, `(dashboard)/bot/[botId]/chat/page.tsx:132`).
`/demo` 만 빠져 있었다. 새 방식을 들이는 게 아니라 **빠진 곳을 맞추는 것**이다.

## 결정

**메시지 영역을 고정 높이 + 내부 스크롤로 바꾼다.**

| 무엇 | 값 | 근거 |
|---|---|---|
| 고정 높이 | `h-[28rem]` (448px) | 실측 2쌍 = 417px. 여유 31px |
| 낮은 화면 방어 | `max-h-[calc(100vh-20rem)]` | 채팅 영역 외 나머지 UI 실측 285px + `top-8` 32px ≈ 20rem |
| 스크롤 | `overflow-y-auto` | 기존 두 화면과 같은 방식 |
| 자동 스크롤 | `el.scrollTop = el.scrollHeight` | `scrollIntoView` 아님 — 아래 참조 |
| 빈 상태 | 안내문에 `m-auto` | 448px 빈 상자에 한 줄만 위에 붙으면 허전하다 |
| 접근성 | `tabIndex={0}` · `role="log"` | 스크롤 영역은 포커스가 없으면 키보드로 못 굴린다 |

### 높이 숫자는 브라우저에서 쟀다

눈대중이 아니라 실제로 2쌍을 주고받고 `getBoundingClientRect()` 로 쟀다.

| 요소 | 실측 |
|---|---|
| 질문 말풍선 | 36px |
| 답변(출처 4개 · 2줄) | 177px |
| 답변(출처 3개 · 1줄) | 132px |
| 간격 3개 (`gap-3`) | 36px |
| **2쌍 합계** | **417px** |
| 채팅 영역을 뺀 나머지 UI 전부 | 285px |

답변이 이보다 길면 2쌍이 다 안 들어온다. 그건 받아들인다 — 더 키우면 왼쪽 문서 목록 옆에서
채팅이 주인공이 되어버린다. 자동 스크롤이 항상 최신 답변을 아래에 붙여주므로,
"방금 물어본 것"은 어떤 경우에도 보인다.

### 🔴 `scrollIntoView` 를 쓰면 안 된다 — 기존 두 화면과 다르다

위젯·대시보드는 sentinel `<div ref={bottomRef} />` 에 `scrollIntoView({behavior:"smooth"})` 를 쓴다.
**`/demo` 에서 같은 방식을 쓰면 페이지 전체가 딸려 내려간다.**

실제로 `/demo` 위에서 재현해 확인했다.

| 방식 | `window.scrollY` | 컨테이너 `scrollTop` |
|---|---|---|
| `scrollIntoView` | **0 → 664** ❌ | 626 ✓ |
| `scrollTop = scrollHeight` | 0 (그대로) ✓ | 626 ✓ |

이유는 레이아웃 차이다. 위젯·대시보드는 `h-dvh flex` 라 **페이지 자체가 스크롤되지 않는다** —
`scrollIntoView` 가 움직일 조상이 컨테이너뿐이다. `/demo` 는 왼쪽 문서 때문에 페이지가 스크롤되고,
`scrollIntoView` 는 스크롤 가능한 **조상을 전부** 움직인다. 답변이 올 때마다 화면이 아래로 튄다.

→ 컨테이너에 직접 `scrollTop` 을 준다. 조상을 건드리지 않는다.

### 공용 훅으로 묶지 않는다

세 화면을 `useScrollToBottom` 하나로 묶는 안을 검토했고 **기각했다.**

- 훅이 두 전략(sentinel 방식 / 컨테이너 방식)을 다 품어야 한다. 인자로 분기를 받는 순간
  3줄짜리를 세 번 적는 것보다 **더** 복잡해진다.
- 위젯·대시보드는 각자 레이아웃에 맞는 올바른 방식을 이미 쓰고 있다. 고칠 것이 없다.
- 두 곳의 기존 주석(왜 ref 를 쓰는지, 왜 의존성이 `bubbles` 인지)은 이 저장소가 지키려는
  "설명할 수 있는 코드"의 일부다. 훅으로 옮기면 호출처에서 그 설명이 사라진다.

**이 판단은 정정에서 나왔다.** 처음에는 "위젯·대시보드에 자동 스크롤이 아예 없다"고 보고
묶자고 제안했는데, `scrollTop|scrollTo` 만 grep 해서 `scrollIntoView` 를 놓친 것이었다.
둘 다 이미 있었다. 근거가 틀렸으므로 결론도 뒤집었다.

## 구현

`web/components/DemoConsole.tsx` **한 파일.**

| 위치 | 변경 |
|---|---|
| import | `useEffect` 추가 |
| 상태 근처 | `logRef` 추가 + 자동 스크롤 `useEffect` |
| 190~244행 메시지 `div` | `h-[28rem] max-h-[calc(100vh-20rem)] overflow-y-auto` · `ref` · `tabIndex={0}` · `role="log"` |
| 192행 빈 상태 안내문 | `m-auto` |

```tsx
const logRef = useRef<HTMLDivElement>(null);
useEffect(() => {
  const el = logRef.current;
  if (el) el.scrollTop = el.scrollHeight;
}, [msgs, pending]);
```

**의존성이 둘인 이유**: `msgs` 는 말풍선이 늘 때, `pending` 은 "문서를 찾아보는 중…" 줄이
생겼다 사라지며 높이가 바뀔 때. `msgs` 만 넣으면 로딩 문구가 스크롤 아래에 숨는다.

## 범위 밖

- 위젯(`/w/[publicKey]`)·대시보드 채팅 — 이미 올바르게 동작한다. 손대지 않는다.
- 모바일 대응 — `AGENTS.md` 작업 규칙 6에 따라 공개 페이지는 데스크톱만 맞춘다.
  좁은 폭에서는 grid 가 1열로 접히고 고정 높이는 그대로 유효하다.
- `scrollIntoView({behavior:"smooth"})` 가 `prefers-reduced-motion` 을 무시하는 문제
  (기존 두 화면). 이번 변경과 무관한 기존 사안이라 건드리지 않는다.

## 검증

1. `/demo` 에서 질문 3개 이상 주고받기 → 패널 높이가 448px 에서 고정되고 안쪽에서만 스크롤된다.
2. 답변이 도착할 때마다 최신 말풍선이 아래에 보인다. **창 스크롤 위치는 변하지 않는다**
   (`window.scrollY` 로 확인 — 이게 `scrollIntoView` 와 갈리는 지점이다).
3. 문서 목록을 길게 스크롤해도 채팅 패널이 `lg:sticky` 로 따라온다.
4. Tab 으로 스크롤 영역에 포커스가 들어가고 방향키로 굴러간다.
