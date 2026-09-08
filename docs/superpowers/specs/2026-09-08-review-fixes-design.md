# 코드 리뷰 지적 24건 정리 (2026-09-08)

리뷰어 둘(인증·리다이렉트 담당 `A-`, UI·요금제 담당 `B-`)이 PR #78~#81 을 훑어 낸
지적 24건을 처리한다. 24건을 하나씩 고치지 않고 **뿌리 원인별로 네 묶음**으로 접는다.

## 왜 하나씩이 아닌가

1. **24건이 독립적이지 않다.** 뿌리가 겹쳐 네 덩어리로 접힌다.
2. **긴급도가 자릿수로 다르다.** 라이브 오픈 리다이렉트와 빈 줄 하나를 같은 무게로 다룰 수 없다.
3. **전부가 "오류"도 아니다.** B-6 은 사용자가 내린 결정이고, 일부 Minor 는 이번 작업 이전부터 있던 것이다.

---

## 묶음 ① PR `fix/redirect-open-redirect` (최우선, 운영 배포됨)

### 무엇이 뚫렸나

`web/lib/redirect.ts:45` 가 입력은 URL 파서에 맡겼는데 **출력을 검사하지 않는다.**
`url.pathname` 이 `//` 로 시작할 수 있고, 그러면 반환값이 프로토콜 상대 URL 이 되어
Next 라우터가 다시 해석할 때 외부로 나간다.

직접 재현했다 (origin `https://all-dap.vercel.app`):

```
"/..//evil.com"                        -> //evil.com            재해석 origin https://evil.com
"/./..//evil.com"                      -> //evil.com            재해석 origin https://evil.com
"/..//evil.com/login?x=1"              -> //evil.com/login?x=1  재해석 origin https://evil.com
"https://all-dap.vercel.app//evil.com" -> //evil.com            재해석 origin https://evil.com
"https://all-dap.vercel.app/\/evil.com"-> ///evil.com           재해석 origin https://evil.com
```

호출지는 `web/app/(site)/auth/page.tsx:98,136` 의 `router.replace(nextPath())`.
`?next=` 가 배포돼 있음은 확인했다 (`curl https://all-dap.vercel.app/faq` 에
`href="/auth?next=%2Ffaq"` 가 있다). 따라서 취약점도 라이브다.

공격자는 `https://all-dap.vercel.app/auth?next=/..//evil.com` 을 뿌리기만 하면 된다.
우리 도메인 문자열조차 필요 없다. 사용자는 **진짜 우리 도메인의 진짜 로그인 폼**에서
로그인한 뒤 공격자 사이트로 떨어진다. `redirect.ts` 머리 주석이 막겠다고 적어둔 바로 그 공격이다.

**측정하지 않은 것:** 함수가 `//evil.com` 을 반환하는 것은 실측했으나, 그 값으로
Next 라우터가 실제로 외부 도메인까지 항해하는지는 브라우저로 재보지 않았다.
출력이 프로토콜 상대 URL 인 것 자체가 결함이라 수정 근거는 충분하다.

### 왜 검사가 못 잡았나

`web/lib/redirect.check.ts` 는 존재하지만 **아무 데서도 돌지 않는다.**

- `grep -c '"tsx"' web/package.json` -> `0` (실행기가 의존성에 없다)
- CI 의 web 잡은 `npm ci`, `npm run lint`, `npm run build` 셋뿐이다

즉 이 사고의 구조적 원인은 "검사를 안 짠 것"이 아니라 **"짜둔 검사가 안 도는 것"** 이다.
그래서 수정과 CI 연결을 같은 PR 에 둔다. 나누면 "고쳤는데 안 도는 검사" 가 그대로 남는다.

### 어떻게 고치나 (TDD)

1. `redirect.check.ts` 에 실패 케이스를 **먼저** 넣고 돌려서 빨간불을 확인한다.
   - C-1 5종: 위 재현 목록 그대로
   - 하드닝 5종: `https://<origin>@evil.com`, `https://<origin>.evil.com`,
     `<origin>:8443/x`, `HTTPS://EVIL.COM`, `blob:https://evil.com/x`
2. `redirect.ts` 를 고쳐 초록불로 만든다.

```ts
const path = url.pathname + url.search + url.hash;
try {
  if (new URL(path, origin).origin !== origin) return DEFAULT_AFTER_AUTH;
} catch {
  return DEFAULT_AFTER_AUTH;
}
return path;
```

3. `redirect.check.ts:43` 의 손으로 적은 `"12가지"` 를 카운터로 바꾼다. 케이스를 늘리면 어긋난다.
4. `tsx` 를 devDependency 에 넣고 `"check:redirect": "tsx lib/redirect.check.ts"` 스크립트를
   추가한 뒤 CI web 잡의 lint 다음에 단계를 건다. `redirect.check.ts` 에 `process.exit(1)` 이
   이미 있어 실패하면 빨간불이 된다.
5. Minor 2건을 같이 처리한다.
   - `auth/page.tsx:161` 의 `"대시보드로 이동합니다…"` 는 `?next=` 가 있으면 거짓이다. `"이동합니다…"` 로.
   - `AuthLink.tsx:71` 에 `usePathname()` 이 쿼리와 해시를 버린다는 한계를 주석 한 줄로 남긴다.
     (`/pricing#plans` 에서 로그인하면 `/pricing` 으로 복귀한다. 지금 실해는 없다.)
6. `AGENTS.md` 의 `?next=` 서술을 갱신한다. 구현이 끝나 참이 됐고, "마케팅 헤더에서만 동작"
   이라는 한계가 빠져 있다.

수정안은 미리 검증했다: 기존 12케이스 + C-1 5종 + 하드닝 5종 = **22/22 통과**.
`https:/evil.com -> /evil.com` 처럼 통과가 정답인 케이스도 그대로다.

### 검토한 대안

- **`url.pathname.startsWith("//")` 한 줄.** 실제로 막힌다. 기각한 이유는 이 파일이 세운 원칙이
  *"직접 파싱하지 않고 파서에게 판정을 맡긴다"* 이고, **C-1 이 난 이유가 그 원칙을 출력에는
  적용하지 않은 것**이기 때문이다. 한 줄짜리는 원칙을 되레 어긴다. 왕복 검증은 판정을 다시 파서에게 맡긴다.
- **`tsx` 없이 Node 네이티브 타입 스트리핑**(22.18+). 기각한 이유는 import 에 `.ts` 확장자가
  필요해 tsconfig 를 건드려야 하고, Node 마이너 버전에 따라 켜졌다 꺼졌다 하기 때문이다.
  **보안 검사가 조용히 안 도는 것이 바로 이 사고**라 버전에 안 흔들리는 쪽을 택한다.

---

## 묶음 ② `main` 직행: 낡은 주석 5건

전부 한 줄이고, 바꾸기 전에 이유를 설명할 필요가 없으며, 틀려도 한 줄 되돌리면 끝난다.
`AGENTS.md` 의 "간단한 수정" 기준에 해당한다.

| 자리 | 무엇이 거짓인가 |
|---|---|
| `web/lib/plans.ts:11-13` | "2번 미구현" 이라 단언하나 PR #76 에서 끝났다 (B-1) |
| `web/app/(site)/pricing/page.tsx:10` | 머리 주석 첫 문장을 같은 주석 7줄 뒤가 부정한다 (B-2) |
| `web/app/(site)/layout.tsx:6-7` | 지워진 "소개" 링크를 설명한다. 지금은 로고가 그 일을 한다 |
| `web/app/(dashboard)/account/page.tsx:8` | 없는 파일을 가리킨다. 리다이렉트는 `next.config.ts` 에 있다 |
| `api/.../ErrorCode.java:124` | 요금제 버튼이 `/account` 에 있던 시절 안내다. 지금은 `/pricing` |

밀기 전 로컬 검사: `cd web && npx tsc --noEmit && npm run lint`,
`ErrorCode.java` 때문에 `cd api && ./gradlew test` 도 돌린다.

---

## 묶음 ③ PR `fix/account-card-states`: `/account` 화면 결함

- **B-3** `account/page.tsx:388,460,561`. 기본 카드가 없는데 카드는 있으면 **카드가 통째로 안 보인다.**
  V7 부분 유니크 인덱스는 "기본 1장 이하"만 보장하고 "1장 이상"은 앱 코드가 지키는데,
  `BillingService.register` 에 TOCTOU 경합이 있다. 그 상태가 되면 사용자는 자기 카드를 보지도
  지우지도 못하고 토스에는 빌링키가 남는다. `!billed` 분기의 `AddCardTile` 에 `full` 가드도 없다.
  (경합 자체는 미실측이다. 프론트 분기 결과는 코드로 확인된다.)
- **B-4** `components/PlanCards.tsx:59,78-81`. **"아직 안 불러옴"과 "못 불러옴"을 `null` 하나로 뭉갠다.**
  `GET /api/plan` 이 실패하면 바꾸기 버튼이 이유 없이 사라진다. `/account` 는 같은 상황을
  `loading` 으로 갈라 안내한다(`account/page.tsx:596-600`). 그 방식에 맞춘다.
- **B-5** `account/page.tsx:509`. `<details>` 에 `open` 이 없어 **2번째 카드부터 닫힌 서랍에 들어간다.**
  부작용으로 `justAddedId` + `alldap-card-in` 등장 애니메이션이 첫 카드에서만 동작한다
  (`globals.css:151-152` 가 설명하는 코드가 사실상 죽어 있다). `<details open={justAddedId !== null}>` 로 고친다.

접근성 3건을 같이 얹는다. 값이 싸고 실사용 영향이 있다.

- `account/page.tsx:750-759` 비활성 삭제 버튼의 이유가 `title` 에만 있어 키보드와 스크린리더가 못 읽는다
- `account/page.tsx:740-749` "기본으로" 버튼에 `aria-label` 이 없다. 서랍에 같은 카드사 카드가 최대 4장이라 구별이 안 된다
- `pricing/page.tsx:81` 앵커 도착지 `<section id="plans">` 에 접근 가능한 이름이 없다. `/account` 가 이 자리를 직접 겨냥한다

B-3 과 B-4 는 같은 부류다: **원인이 다른 두 사실을 한 값에 뭉갠 것.**
`AGENTS.md` 가 "낸 버그 5건" 으로 기록한 그 부류의 여섯 번째이자 일곱 번째다.

---

## 묶음 ④ 나머지 Minor: 판정만 하고 이유를 남긴다

고치지 않기로 한 것은 `docs/decisions.md` 에 이유를 적는다.

| 항목 | 판정 |
|---|---|
| `account/page.tsx:394` 의 `PLANS.find(...) ?? null` | 서버가 모르는 플랜 id 를 주면 "새로고침하세요" 라고 안내하는데 새로고침은 영원히 안 통한다. B-4 와 같은 부류라 묶음 ③ 에서 함께 고친다 |
| `/pricing:122`, `/faq:117`, `ReceptionHero:1022` 의 CTA | 도착지 가드는 옳다. 고칠 자리는 CTA 문구와 목적지인데, 그건 카피 결정이라 별도 슬라이스다. 안 고친다 |
| `pricing/page.tsx:43` metadata description | 숫자 3개를 `lib/plans.ts` 와 두 벌로 적고, 화면에서 뺀 "가정값" 을 계속 말한다. 문구 한 줄이라 묶음 ② 에 넣는다 |
| `DemoConsole.tsx:362` 빈 줄 | 안 고친다. 값어치가 없다 |
| `EvidenceKind` 유니온 3벌 중복 | `Evidence.tsx` 에서 export 하면 풀린다. 묶음 ③ 과 파일 계열이 달라 별도로 둔다 |
| `auth/page.tsx` 의 `nextPath()` 이중 호출 경합 | **실측으로 재현되지 않았다**(React 스케줄링이 막는다). 안 고친다. 이유를 주석으로 남긴다 |

---

## 고치지 않기로 한 것 (사용자 결정)

- **B-6** `/pricing` 의 *"결제는 아직 연결되지 않았습니다, 문의를 남겨주세요"* 는 되살리지 않는다.
  사용자가 명시적으로 제거를 지시했고, 리뷰어도 돈이 나갈 경로는 없다고 인정했다.
- **A-2** 대시보드 세션 만료 가드에 `?next=` 를 붙이지 않는다. 붙이면 봇 화면 북마크 복귀가
  되지만 **비로그인 상태의 주소창에 봇 UUID 가 남는다.** 한계 주석만 남긴다.
  (PR #81 본문에 이미 한계로 기록돼 있다.)

---

## 검증 계획

| 묶음 | 무엇으로 |
|---|---|
| ① | `npx tsx lib/redirect.check.ts` 가 수정 전 빨간불, 수정 후 초록불. 공격 5종이 전부 `/dashboard` 로 떨어지고 정상 4종이 그대로인지 확인. `npx tsc --noEmit`, `npm run lint` |
| ② | `npx tsc --noEmit`, `npm run lint`, `./gradlew test` |
| ③ | `npx tsc --noEmit`, `npm run lint`, 브라우저 실측: 카드 2장 등록 시 두 번째가 서랍 밖에 보이는가, `/api/plan` 을 죽였을 때 안내가 나오는가 |

이 저장소의 반복된 교훈은 *"진짜 상대와 붙여보기 전까지는 검증했다고 말하지 말 것"* 이다.
묶음 ③ 은 통합 테스트로는 안 잡히는 화면 분기라 브라우저 실측이 필요하다.

## 한계

- C-1 이 **브라우저에서 실제로 외부 도메인까지 항해하는지** 재보지 않았다. 함수 반환값까지만 실측했다.
- B-3 의 TOCTOU 경합 자체를 재현하지 않았다. 그 상태에 빠졌을 때 화면이 어떻게 되는지만 코드로 확인했다.
- 묶음 ④ 에서 안 고치기로 한 것들은 여전히 지적으로 유효하다. 값어치 판단으로 미룬 것이지 반증한 것이 아니다.
