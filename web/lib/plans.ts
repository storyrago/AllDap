/**
 * 요금제 정의 — 2026-09-07 결정 (docs/decisions.md · PRD §13.1).
 *
 * 🔴 <전부 가정값이다.> 원가 실측(답변 1건 ≈ 25뉴런 · 평가 1회 804뉴런)에서 역산하고
 *    시장 기준점 둘(Chatbase Hobby · 채널톡 ALF)을 참고했을 뿐, 실사용 데이터가 없다.
 *    그래서 이 숫자를 보여주는 자리에는 반드시 "가정" 태그를 붙인다(components/Evidence.tsx).
 *
 * ⚠️ 지금은 <화면에만> 있다. Spring 에 플랜 테이블·한도 검사·청구는 없다
 *    (요금제 연동 4조각 중 2·4번 미구현). 2번을 만들어 Spring 이 이 값을 갖게 되면
 *    프론트는 여기가 아니라 API 에서 받아야 한다 — 같은 숫자가 두 벌이면 반드시 어긋난다.
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
