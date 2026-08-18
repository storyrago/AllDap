import type { Metadata } from "next";
import Link from "next/link";

import { Evidence, Framed, PageIntro } from "@/components/Evidence";

/**
 * `/pricing` — 요금제.
 *
 * 🔴 <이 페이지에 금액이 없다. 그게 의도다.>
 * PRD §13.1 은 <무엇에 값을 매길지>(과금축)를 확정했고 <얼마를 받을지>(금액)는
 * "파일럿 4주 후" 로 미뤄뒀다. 실사용 데이터 없이 정하면 근거 없는 숫자가 되기 때문이다.
 *
 * 그래서 지어낸 가격표를 세우지 않고, <정한 것과 안 정한 것을 구분해서> 적는다.
 * 이 사이트의 규칙(주장에는 근거를 댄다)을 가격에도 그대로 적용한 것이다 —
 * "미정" 태그가 붙은 항목이 그 표시다.
 *
 * 호출하는 API: 없음.
 */
export const metadata: Metadata = {
  title: "요금제 — AllDap",
  description:
    "봇이 답하지 못한 질문에는 요금을 받지 않습니다. 과금 기준은 답변 수와 품질 평가 실행 횟수이며, 금액은 파일럿 이후 공개합니다.",
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
        lead="억지로 답하게 만들 이유가 회사 쪽에 생기지 않도록 과금 기준을 정했습니다. 제품이 지키려는 것과 매출이 같은 방향을 봅니다."
      />

      {/* 🔴 이 페이지에서 가장 먼저 말해야 하는 것은 "금액이 아직 없다" 는 사실이다.
             아래에 축을 설명하고 나서 밝히면 읽는 사람이 속은 기분이 든다. */}
      <section className="mt-12">
        <Framed>
          <div className="bg-surface p-6 sm:p-8">
            <p className="text-xs font-medium tracking-[0.18em] text-warning">아직 정하지 않았습니다</p>
            <h2 className="mt-3 text-xl font-bold tracking-[-0.02em] sm:text-2xl">
              무엇에 값을 매길지는 정했고, 얼마일지는 정하지 않았습니다
            </h2>
            <p className="mt-3 max-w-2xl leading-relaxed text-muted">
              실사용 데이터 없이 금액을 정하면 근거 없는 숫자가 됩니다. 파일럿에서 봇당 월 답변 수와
              평가 실행 빈도를 재고, 원가를 확인한 다음 공개합니다.
            </p>
            <Evidence kind="미정">
              현재 AllDap 은 포트폴리오·학습 목적으로 만들고 있으며 결제 기능이 없습니다.
              도입을 검토하신다면 문의를 남겨주세요 — 파일럿 대상에게 먼저 알립니다.
            </Evidence>
          </div>
        </Framed>
      </section>

      <section className="mt-14">
        <h2 className="text-xs font-medium tracking-[0.22em] text-muted">과금 기준</h2>
        <div className="mt-6 grid gap-6 sm:grid-cols-2">
          {AXES.map((a) => (
            <article key={a.axis} className="rounded-lg border border-subtle bg-surface p-6">
              <p className="text-xs font-medium tracking-[0.18em] text-muted">{a.axis}</p>
              <h3 className="mt-3 text-lg font-bold leading-snug tracking-[-0.02em]">{a.headline}</h3>
              <p className="mt-3 text-sm leading-relaxed text-muted">{a.body}</p>
              <Evidence kind={a.evidenceKind}>{a.evidence}</Evidence>
            </article>
          ))}
        </div>
      </section>

      {/* 과금 기준이 제품 철학과 어떻게 이어지는지 — 이게 이 페이지의 논지다 */}
      <section className="mt-14 border-t border-subtle pt-10">
        <h2 className="max-w-3xl text-xl font-bold leading-snug tracking-[-0.025em] sm:text-2xl">
          답변 수로 과금하면서 “못 답한 것은 빼는” 이유
        </h2>
        <p className="mt-4 max-w-2xl leading-relaxed text-muted">
          답변 수만 세면, 봇이 근거 없이도 뭐라도 답하게 만드는 편이 회사에 이득이 됩니다. 그러면
          이 제품이 팔려는 것(근거 없으면 답하지 않는다)과 매출이 서로 반대 방향을 봅니다. 못 답한
          것을 과금에서 빼면 그 충돌이 사라집니다.
        </p>
        <Evidence kind="설계">
          거절 여부는 대화 로그에 이미 기록됩니다. 관리자 화면에서 “답하지 못한 질문” 을 모아 보여주므로,
          요금이 줄어드는 지점이 곧 <strong className="font-semibold text-foreground">문서를 보강할 지점</strong>이 됩니다.
        </Evidence>

        <Link
          href="/auth"
          className="mt-8 inline-flex rounded-lg bg-foreground px-6 py-3 text-sm font-semibold text-surface"
        >
          도입 문의하기
        </Link>
      </section>
    </div>
  );
}
