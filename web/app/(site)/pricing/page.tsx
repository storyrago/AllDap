import type { Metadata } from "next";
import Link from "next/link";

import { Evidence, PageIntro } from "@/components/Evidence";
import { PlanCards } from "@/components/PlanCards";

/**
 * `/pricing` — 요금제.
 *
 * 🔴 <금액은 전부 가정값이다. 다만 그 사실을 화면에 적지는 않는다(아래 참고).>
 * PRD §13.1 은 <무엇에 값을 매길지>(과금축)를 2026-07-31 에 확정했고, <얼마를 받을지>는
 * "파일럿 4주 후" 로 미뤄뒀었다. 2026-09-07 에 그 결정을 뒤집어 금액을 정했다 —
 * 포트폴리오에서 결제 흐름을 끝까지 보여주려면 숫자가 필요하고, 파일럿은 현실적으로
 * 열리지 않기 때문이다(docs/decisions.md 2026-09-07). 숫자는 원가 실측에서 역산했고
 * 시장 기준점 둘을 참고했다.
 *
 * 🔴 <그 사실을 화면에 적던 "가정" 태그는 2026-09-08 에 뺐다.> 그때까지의 규칙은
 *    "이 숫자를 보여주는 자리에는 반드시 가정 태그를 붙인다" 였는데, 요금제 페이지에서
 *    자기 값을 스스로 "추측" 이라 부르는 것은 <읽는 사람에게 아무 선택지도 주지 않으면서>
 *    값만 못 믿게 만든다. 값이 가정이라는 사실은 그대로이고(lib/plans.ts), 파일럿 뒤에
 *    다시 정한다는 계획도 그대로다 — 방문자에게 말하지 않을 뿐이다.
 *    ⚠️ 같은 날 "미정"(결제 미연결) 태그도 뺐다. 그 경고가 정말 필요한 자리는 <돈이 움직이는
 *       모양의 버튼 옆>이고, 거기에는 그대로 남아 있다 — components/PlanCards.tsx 의
 *       "요금제를 바꿔도 청구는 일어나지 않습니다", /account 의 같은 경고와 카드 등록
 *       테스트 환경 경고. 이 페이지의 비로그인 방문자가 할 수 있는 일은 <문의>뿐이다.
 *    🔴 결제가 붙으면 저 세 경고를 함께 지울 것. 여기에는 지울 것이 남아 있지 않다.
 *
 * 이 사이트의 규칙(주장에는 근거의 <성격>까지 댄다)은 과금 기준에 그대로 살아 있다.
 *
 * 숫자의 원본은 lib/plans.ts 하나다. 이 파일에 숫자를 직접 적지 않는다.
 *
 * ⚠️ 요금제 카드는 `components/PlanCards.tsx` 로 나갔다(2026-09-08). 로그인한 사람에게는
 *    같은 카드가 <고르는> 카드가 되어야 하는데, 그러려면 토큰을 봐야 하고 그건 브라우저에만
 *    있기 때문이다. 이 페이지는 metadata 를 내보내는 서버 컴포넌트로 남는다.
 *    ⚠️ 마이페이지(`/account`)는 이제 요금제를 <그리지 않는다> — 확인만 하고 여기로 보낸다.
 *       같은 카드를 두 곳에 두면 한쪽만 고치는 사고가 난다.
 *
 * 호출하는 API: 없음 (PlanCards 가 로그인 상태에서만 /api/plan 을 부른다).
 */
export const metadata: Metadata = {
  title: "요금제 — AllDap",
  /* 숫자를 적지 않는다. 이 파일의 규칙이 그렇고(원본은 lib/plans.ts 하나),
     두 벌이 되면 요금이 바뀔 때 한쪽만 고치는 사고가 난다. */
  description: "봇이 답하지 못한 질문에는 요금을 받지 않습니다. 무료와 Pro 두 요금제가 있습니다.",
};

const AXES = [
  {
    axis: "답변 수",
    headline: "답하지 못한 질문은 세지 않습니다",
    body:
      "봇이 근거를 못 찾아 “담당자에게 문의해주세요” 로 넘긴 응답은 과금 대상이 아닙니다. 실제로 답을 만든 것만 셉니다.",
    evidenceKind: "설계" as const,
    evidence:
      "대화 로그의 is_fallback 값을 그대로 씁니다. 과금 로직을 위해 따로 만든 값이 아니라, 환각 억제를 위해 이미 있던 값입니다.",
  },
  {
    axis: "품질 평가 실행",
    headline: "첫 리포트는 무료입니다",
    body:
      "평가는 테스트 질문을 실제 파이프라인에 태우고 채점 모델을 부르므로 단건 비용이 가장 큽니다. 한 번은 무료로 보고, 설정을 바꿔가며 비교하는 반복 실행이 유료 구간입니다.",
    evidenceKind: "실측" as const,
    evidence:
      "16문항 1회 = 804 뉴런. 그중 채점 51% · 답변 생성 47% · 검색 개선(리랭커) 1.7%. 호출마다 응답에 실린 사용량을 그대로 합산한 값입니다.",
  },
];

export default function PricingPage() {
  return (
    <div className="mx-auto w-full max-w-5xl px-6 py-16">
      <PageIntro
        eyebrow="요금제"
        title="봇이 답하지 못한 질문에는 요금을 받지 않습니다."
      />

      {/* 🔴 금액을 <가장 먼저> 보여주고, 바로 아래에 "어디서 나온 숫자인지" 를 붙인다.
             숫자가 없던 때는 "없다" 를 먼저 말했다. 있는 지금은 근거의 성격을 먼저 말한다.
             어느 쪽이든 목적은 같다 — 읽는 사람이 속은 기분이 들지 않게.

             id="plans" — 마이페이지의 "요금제 바꾸기" 가 이 자리로 바로 내려꽂는다.
             페이지 맨 위로 보내면 마케팅 문구부터 다시 읽게 되는데, 그 사람은 이미 고르러 온 것이다. */}
      {/* aria-label 을 붙이는 이유: /account 의 "요금제 바꾸기" 가 이 자리로 바로 내려꽂는데,
          제목 없는 section 은 랜드마크 목록에서 이름 없는 칸으로만 보인다. */}
      <section id="plans" aria-label="요금제" className="mt-12 scroll-mt-8">
        <PlanCards />
        <p className="mt-3 text-xs text-muted">모든 금액은 부가세 별도입니다.</p>
      </section>

      {/*
        ── 왜 카드가 아니라 <목록>인가 (2026-09-08 배치 개편) ─────────────────
        전에는 이 두 축이 위 요금제 카드와 똑같은 상자였다(`rounded-lg border bg-surface p-6`).
        그래서 페이지가 "비슷한 상자 넷"으로 읽혔는데, 위 둘과 여기 둘은 성격이 아예 다르다 —
        위는 <고르는 상품>이고 여기는 <용어의 정의>다. 같은 모양이면 같은 무게로 읽힌다.

        대신 `/features` 가 이미 쓰는 리듬(왼쪽 라벨 · 오른쪽 주장+설명+근거)을 가져왔다.
        새 스타일을 만들지 않으므로 두 페이지가 같은 몸짓을 공유하고, 상자가 사라져
        위 요금표와 확실히 구별된다.

        ⚠️ 축 이름("답변 수" · "품질 평가 실행")은 위 요금 카드의 행 이름과 <짝이다.>
           한쪽 문구를 다듬으면 반대쪽도 함께 볼 것 — 어긋나면 정의가 무엇을 정의하는지 사라진다.
      */}
      <section className="mt-14">
        <h2 className="text-xs font-medium tracking-[0.22em] text-muted">과금 기준</h2>
        <ul className="mt-6 divide-y divide-subtle border-t border-subtle">
          {AXES.map((a) => (
            <li key={a.axis} className="grid gap-x-8 gap-y-2 py-7 sm:grid-cols-[9rem_1fr]">
              <p className="pt-1 text-xs font-medium tracking-[0.18em] text-muted">{a.axis}</p>
              <div className="min-w-0">
                <h3 className="text-lg font-bold leading-snug tracking-[-0.02em]">{a.headline}</h3>
                <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted">{a.body}</p>
                <Evidence kind={a.evidenceKind}>{a.evidence}</Evidence>
              </div>
            </li>
          ))}
        </ul>
      </section>

      {/* 🔴 여기 있던 "답변 수로 과금하면서 못 답한 것은 빼는 이유" 섹션을 지웠다 (2026-09-08).
             과금 기준이 제품 철학과 어떻게 이어지는지를 문단으로 설득하는 자리였는데, 바로 위
             "답하지 못한 질문은 세지 않습니다" 가 이미 <규칙>으로 같은 말을 한다. 규칙을 읽은
             사람에게 그 규칙의 정당성을 다시 설명하는 것은 읽는 사람이 아니라 만든 사람을 위한
             글이다. CTA 만 남겨 이 자리를 <다음 행동>으로 되돌린다. */}
      <div className="mt-14 border-t border-subtle pt-10">
        <Link
          href="/auth"
          className="inline-flex rounded-lg bg-foreground px-6 py-3 text-sm font-semibold text-surface"
        >
          도입 문의하기
        </Link>
      </div>
    </div>
  );
}
