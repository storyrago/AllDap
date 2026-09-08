/**
 * 요금제 정의 — 2026-09-07 결정 (docs/decisions.md · PRD §13.1).
 *
 * 🔴 <전부 가정값이다.> 원가 실측(답변 1건 ≈ 25뉴런 · 평가 1회 804뉴런)에서 역산하고
 *    시장 기준점 둘(Chatbase Hobby · 채널톡 ALF)을 참고했을 뿐, 실사용 데이터가 없다.
 *    ⚠️ 2026-09-08 <전까지>는 "이 숫자를 보여주는 자리에는 반드시 가정 태그를 붙인다" 가
 *       규칙이었다. 그 태그는 뺐다(`app/(site)/pricing/page.tsx` 주석 참고).
 *       <값이 가정이라는 사실은 바뀌지 않았다> — 화면에 그렇게 적지 않을 뿐이다.
 *       파일럿 뒤 실사용 데이터로 다시 정할 것.
 *
 * ⚠️ 2번 조각(요금제 선택)은 PR #76 에서 끝났다. `users.plan` 이 생겼고 `GET`·`PUT /api/plan`
 *    이 있다. 그런데 <숫자는 여전히 여기에만 있다>. 서버의 `Plan` enum 은 이름과 `isPaid()`
 *    뿐이고 금액도 한도도 모른다(api 의 `plan/Plan.java` 주석 참고). 서버가 그 숫자로 하는 일이
 *    아직 없어서다. 한도 검사와 청구(4번 조각)가 붙어 서버가 금액을 갖게 되면 그때 API 에서
 *    받아야 한다. 같은 숫자가 두 벌이면 반드시 어긋난다.
 *
 * ── 왜 interface 인가 ──────────────────────────────────────────────────────
 * 객체의 <모양>을 적는 자리라 lib/types.ts 의 응답 타입들과 같은 관례를 따른다.
 * `type` 으로 써도 동작은 같지만, 이 저장소에서 "객체 모양 = interface" 로 통일해 두면
 * 나중에 Spring 응답(PlanResponse)과 1:1 로 맞출 때 같은 자리에 같은 모양으로 놓인다.
 */
export interface Plan {
  id: "free" | "pro";
  name: string;
  /** 월 정액, 원. 부가세 별도. 0 이면 무료 플랜이다 */
  monthlyPriceKrw: number;
  /** 포함 답변 수(월). fallback 은 세지 않는다 — usage_events 가 이미 그렇게 센다 */
  includedAnswers: number;
  /** 포함 품질 평가 실행 횟수(월) */
  includedEvalRuns: number;
  /**
   * 포함량 초과 답변 1건의 값, 원. `null` 은 "초과가 불가능하다(한도에서 멈춘다)" 다.
   * 🔴 0 이 아니라 null 인 이유: "0원에 무제한" 과 "한도에서 멈춤" 은 다른 사실이다.
   *    이 저장소가 반복해 낸 버그가 정확히 그 부류다(AGENTS.md "낸 버그 5건").
   */
  overageAnswerKrw: number | null;
  /** 추가 평가 실행 1회의 값, 원. `null` 은 "추가 실행 불가" 다 (위와 같은 이유로 0 이 아니다) */
  extraEvalRunKrw: number | null;
}

export const PLANS: readonly Plan[] = [
  {
    id: "free",
    name: "무료",
    monthlyPriceKrw: 0,
    includedAnswers: 200,
    includedEvalRuns: 1,
    overageAnswerKrw: null,
    extraEvalRunKrw: null,
  },
  {
    id: "pro",
    name: "Pro",
    monthlyPriceKrw: 29_000,
    includedAnswers: 3_000,
    includedEvalRuns: 10,
    overageAnswerKrw: 15,
    extraEvalRunKrw: 2_000,
  },
];

/**
 * 요금제 id 를 그 정의로 바꾼다.
 *
 * ⚠️ 인자가 `PlanId` 가 아니라 `string | null` 이다. 값이 <네트워크에서> 오기 때문이다.
 *    서버가 우리보다 새 버전이면 우리가 모르는 id 를 준다. 타입에 `PlanId` 라고 적는 것과
 *    런타임이 그 약속을 지키는 것은 다른 일이다.
 */
export function resolvePlan(plan: string | null): Plan | null | undefined {
  /* 🔴 `?? null` 을 쓰지 않는다. 그러면 "모르는 id" 가 "못 불러옴" 으로 둔갑하고,
     화면이 그 사람에게 <영원히 안 통하는> "새로고침하세요" 를 안내하게 된다.
     `find` 가 주는 undefined 를 그대로 흘려보내는 것이 세 번째 갈래다. */
  return plan === null ? null : PLANS.find((p) => p.id === plan);
}
