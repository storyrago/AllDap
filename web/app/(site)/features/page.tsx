import type { Metadata } from "next";
import Link from "next/link";

import { Evidence, Framed, PageIntro } from "@/components/Evidence";

/**
 * `/features` — 기능 소개. 히어로 헤더의 "기능" 메뉴가 여기로 온다.
 *
 * ── 왜 별도 페이지인가 (랜딩 아래 섹션이 아니라) ──────────────────────────
 * 랜딩(`/`)의 `ReceptionHero` 는 `wheel` 을 `preventDefault` 로 가로채 자기 줌 연출에 쓰고
 * `overflow: hidden` 이다. 아래에 섹션을 붙이면 그 스크롤 로직과 충돌한다.
 * 그 로직은 "입력량 비례 방식은 구경이 아니라 작업이 됐다" 같은 실험 기록이 주석에 남은
 * 튜닝된 코드라 건드리지 않았다. 그리고 `(site)` 레이아웃이 이미 헤더·푸터를 갖고 있어
 * 페이지를 얹기만 하면 된다 — URL 이 생겨 공유·SEO 도 된다.
 *
 * ── 이 파일이 서버 컴포넌트인 이유 ───────────────────────────────────────
 * `export const metadata` 는 서버 컴포넌트에서만 쓸 수 있고, 이 페이지는 상태도 이벤트도
 * 없는 정적 문서다. 클라이언트 번들에 들어갈 이유가 없다.
 *
 * 호출하는 API: 없음.
 */
export const metadata: Metadata = {
  title: "기능 — AllDap",
  description:
    "PDF·DOCX·HWPX 를 올리면 출처가 표시되는 챗봇이 됩니다. 근거가 없으면 답을 지어내지 않고, 답변 품질을 자동 평가해 리포트로 보여줍니다.",
};

/**
 * 🔴 여기 적힌 수치는 전부 <실측치>다. `AGENTS.md` 의 측정 절이 출처다.
 *    마케팅 문구를 지어내지 않는 것이 이 페이지의 규칙이고, 그게 제품 주장과 일관된다.
 */
const FEATURES = [
  {
    id: "F-01",
    title: "한글 문서를 그대로 올립니다",
    body:
      "PDF · DOCX · HWPX · TXT · MD 를 지원합니다. 국내 규정과 안내문 상당수가 한글 문서인데, 비개발자용 챗봇 빌더 상당수가 이를 다루지 못합니다.",
    evidence: {
      kind: "설계" as const,
      text: "구버전 .hwp 는 바이너리 포맷이라 미지원 — 업로드하면 “.hwpx 로 저장 후 올려주세요” 로 안내합니다. 파일당 20MB.",
    },
  },
  {
    id: "F-03",
    title: "답변마다 어느 문서의 어느 대목인지 붙습니다",
    body:
      "질문과 가까운 문서 조각을 찾아 그것만 근거로 답합니다. 답변 아래에 출처가 표시되므로 관리자가 맞는지 바로 확인할 수 있습니다.",
    evidence: {
      kind: "실측" as const,
      text: "문서 50개 · 청크 306개 기준. 답변당 근거 5건, 응답 1.6초.",
    },
  },
  {
    id: "F-03",
    title: "문서에 없으면 답하지 않습니다",
    body:
      "근거를 못 찾으면 지어내는 대신 담당자에게 문의하라고 안내합니다. 검색 단계와 생성 단계에 방어선을 두 겹으로 두었습니다.",
    evidence: {
      kind: "실측" as const,
      text: "문서에 없는 질문 10개 → 10개 모두 거절(기준 8개). 근거가 있는 대조군 3개는 정상 답변 — 전부 거절하는 봇이 만점받는 것을 막기 위해 함께 잽니다.",
    },
  },
  {
    id: "F-05",
    title: "답변 품질을 숫자로 증명합니다",
    body:
      "문서에서 테스트 질문을 자동 생성하고, 답변을 다른 계열의 모델이 채점합니다. 검색 설정을 바꿔가며 같은 질문으로 재실행해 before/after 를 비교할 수 있습니다.",
    evidence: {
      kind: "실측" as const,
      text: "리랭커+하이브리드 검색 도입: 전체 충실성 0.781 → 0.875, 회당 오답 1.75건 → 0건 (16문항 · 설정당 3회 이상 · 같은 테스트셋).",
    },
  },
  {
    id: "F-04",
    title: "설치는 스크립트 한 줄입니다",
    body:
      "고객 사이트에 한 줄을 붙여넣으면 우측 하단에 상담 버튼이 생깁니다. 허용한 도메인 밖에서는 열리지 않습니다.",
    evidence: {
      kind: "실측" as const,
      text: "다른 origin 의 사이트에 실제 설치 확인. 허용하지 않은 도메인은 안내 문구로 차단됩니다.",
    },
  },
] satisfies ReadonlyArray<{
  id: string;
  title: string;
  body: string;
  evidence: { kind: "실측" | "설계" | "미정"; text: string };
}>;

export default function FeaturesPage() {
  return (
    <div className="mx-auto w-full max-w-5xl px-6 py-16">
      <PageIntro
        eyebrow="기능"
        title="문서를 읽고, 출처를 대고, 모르면 모른다고 합니다."
      />

      {/*
        🔴 이 페이지의 규칙: 주장 하나에 근거 하나.
           근거를 못 대는 주장은 <아예 쓰지 않는다.> 제품이 하는 일과 같다.
      */}
      <ul className="mt-12 space-y-10">
        {FEATURES.map((f, i) => (
          // key 로 index 를 쓴다 — id(F-03)가 두 항목에서 겹치기 때문이다.
          // 같은 기능 명세 안의 서로 다른 성질을 나눠 설명한 것이라 겹치는 게 맞다.
          <li key={i} className="grid gap-x-8 gap-y-3 sm:grid-cols-[7rem_1fr]">
            <p className="pt-1 text-xs font-medium tracking-[0.18em] text-muted">{f.id}</p>
            <div className="min-w-0">
              <h2 className="text-xl font-bold tracking-[-0.02em] sm:text-2xl">{f.title}</h2>
              <p className="mt-2 max-w-2xl leading-relaxed text-muted">{f.body}</p>
              <Evidence kind={f.evidence.kind}>{f.evidence.text}</Evidence>
            </div>
          </li>
        ))}
      </ul>

      {/* 품질 대시보드가 이 제품의 존재 이유라 별도로 한 번 더 세운다 */}
      <section className="mt-16">
        <Framed>
          <div className="bg-surface p-6 sm:p-8">
            <h2 className="text-lg font-bold tracking-[-0.02em]">
              같은 질문으로 다시 재서, 좋아졌는지 확인합니다
            </h2>
            {/* 🔴 제목과 표 사이에 있던 "아래는 이 제품을 만들면서 실제로 나온 비교표입니다"
                   한 문단을 지웠다 (2026-09-08). 표의 머리글(검색 방식 / 전체 충실성 / 회당 오답)이
                   이미 무엇을 보는 표인지 말하고, 출처는 아래 근거 태그가 댄다. 표를 앞에서
                   말로 한 번 더 소개하는 것은 표를 못 믿는다는 뜻이 된다.

                   표가 좁은 화면에서 페이지를 밀지 않도록 자기 안에서 스크롤한다 */}
            <div className="mt-6 overflow-x-auto">
              <table className="w-full min-w-[30rem] text-left text-sm">
                <thead className="text-xs text-muted">
                  <tr className="border-b border-subtle">
                    <th className="py-2 pr-4 font-medium">검색 방식</th>
                    <th className="py-2 pr-4 font-medium">전체 충실성</th>
                    <th className="py-2 font-medium">회당 오답</th>
                  </tr>
                </thead>
                <tbody>
                  <tr className="border-b border-subtle">
                    <td className="py-2.5 pr-4">벡터 검색만</td>
                    <td className="py-2.5 pr-4 tabular-nums">0.781</td>
                    <td className="py-2.5 tabular-nums">1.75건</td>
                  </tr>
                  <tr>
                    <td className="py-2.5 pr-4 font-semibold">리랭커 + 하이브리드</td>
                    <td className="py-2.5 pr-4 font-semibold tabular-nums">0.875</td>
                    <td className="py-2.5 font-semibold tabular-nums">0건</td>
                  </tr>
                </tbody>
              </table>
            </div>

            {/* 🔴 뒤에 붙어 있던 "답을 못 하는 것은 안전한 실패지만 틀린 답은 사용자가 그것을
                   믿게 됩니다" 를 지웠다 (2026-09-08). 표에 <회당 오답 1.75건 → 0건> 이 이미
                   찍혀 있고, 그게 왜 중요한지는 이 표를 보러 온 사람이 판단할 몫이다.
                   근거 태그는 <수치의 출처>를 대는 자리이지 그 수치의 의미를 설득하는 자리가 아니다. */}
            <Evidence>
              16문항 · 설정당 3회 이상 · 같은 테스트셋. 측정 편차가 0.032 라서 +0.094 는 그 3배입니다.
            </Evidence>
          </div>
        </Framed>
      </section>

      {/* 공개 페이지 넷 중 여기만 <다음으로 갈 곳>이 없었다. /pricing 과 /faq 는 /auth 로
          잇는데, 이 페이지는 "출처가 붙는다 · 모르면 답하지 않는다"를 주장하는 자리라
          그걸 그대로 실연하는 /demo 로 보내는 편이 맞다. 세 페이지가 서로 다른 다음 행동을 준다.
          className 은 /pricing 의 CTA 와 같은 것을 쓴다 — 새 스타일을 만들지 않는다. */}
      <Link
        href="/demo"
        className="mt-8 inline-flex rounded-lg bg-foreground px-6 py-3 text-sm font-semibold text-surface"
      >
        데모 열어보기
      </Link>
    </div>
  );
}
