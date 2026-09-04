import type { Metadata } from "next";
import Link from "next/link";

import { Evidence, PageIntro } from "@/components/Evidence";

/**
 * `/faq` — 자주 묻는 질문.
 *
 * ── 왜 `<details>` 인가 (직접 만든 아코디언이 아니라) ──────────────────────
 * 브라우저 기본 요소가 이미 필요한 것을 전부 한다: 펼침 상태 관리, 키보드 조작(Enter·Space),
 * 스크린리더에 "펼쳐짐/접힘" 전달, 그리고 <자바스크립트 없이> 동작. 직접 만들면
 * `aria-expanded` 와 포커스 처리를 손으로 맞춰야 하고 대개 한 군데를 빠뜨린다.
 * 이 페이지는 상태도 이벤트도 없어 서버 컴포넌트로 남을 수 있는데, 아코디언을 직접 만들면
 * "use client" 가 되어 번들이 늘어난다.
 *
 * ⚠️ 답변은 <실제 동작>만 적는다. 계획을 현재형으로 쓰면 그게 거짓이 된다.
 *
 * 호출하는 API: 없음.
 */
export const metadata: Metadata = {
  title: "자주 묻는 질문 — AllDap",
  description:
    "지원하는 문서 형식, 오답을 막는 방식, 설치 방법, 문서 보안에 대한 답변입니다.",
};

const QA = [
  {
    q: "어떤 문서를 올릴 수 있나요?",
    a: "PDF · DOCX · HWPX · TXT · MD 를 지원합니다. 파일당 20MB 입니다.",
    evidence: {
      kind: "설계" as const,
      text: "구버전 .hwp 는 지원하지 않습니다 — 바이너리 포맷이라 별도 라이브러리가 필요합니다. 업로드하면 “.hwpx 로 저장 후 올려주세요” 로 안내합니다. 암호가 걸린 PDF 도 열 수 없어 같은 방식으로 안내합니다.",
    },
  },
  {
    q: "챗봇이 엉뚱한 답을 하면 어떻게 되나요?",
    a: "근거를 못 찾으면 답을 만들지 않고 담당자에게 문의하라고 안내합니다. 검색 단계에서 관련 없는 문서 조각을 걸러내고, 답변 단계에서 모델이 “문서에 없다” 고 판단하면 그대로 거절합니다.",
    evidence: {
      kind: "실측" as const,
      text: "문서에 없는 질문 10개 → 10개 모두 거절(기준 8개). 근거가 있는 대조군 3개는 정상 답변합니다 — 전부 거절하는 봇도 만점을 받으므로 양쪽을 함께 잽니다.",
    },
  },
  {
    q: "답이 맞는지 어떻게 확인하나요?",
    a: "답변마다 어느 문서를 근거로 삼았는지 표시됩니다. 그리고 품질 리포트가 테스트 질문을 자동으로 만들어 채점하므로, 관리자가 문항별로 어디서 틀렸는지 볼 수 있습니다.",
    evidence: {
      kind: "설계" as const,
      text: "채점 모델은 답변 생성 모델과 계열을 다르게 두었습니다. 같은 모델이면 자기 답을 자기가 채점하게 됩니다.",
    },
  },
  {
    q: "우리 사이트에 붙이기 어렵나요?",
    a: "스크립트 한 줄을 붙여넣으면 됩니다. 우측 하단에 상담 버튼이 생기고, 누르면 대화창이 열립니다.",
    evidence: {
      kind: "실측" as const,
      text: "다른 도메인의 사이트에 실제로 설치해 확인했습니다. 허용 목록에 없는 도메인에서는 열리지 않습니다 — 새 봇은 아무 도메인도 허용되지 않은 상태로 시작하므로 직접 등록해야 합니다.",
    },
  },
  {
    q: "올린 문서가 외부로 나가나요?",
    a: "문서 본문은 답변을 만들 때 AI 제공자에게 전달됩니다. 임베딩은 고객 데이터를 모델 학습에 쓰지 않는다고 명시한 제공자(Cloudflare Workers AI)를 씁니다.",
    evidence: {
      kind: "미정" as const,
      text: "답변 생성 쪽은 현재 무료 등급을 쓰고 있어 약관상 입력이 학습에 쓰일 수 있습니다. 실제 고객 문서를 받는 시점(파일럿) 전에 결제 계정 연결 또는 제공자 교체가 필요합니다 — 지금은 테스트 문서만 다룹니다.",
    },
  },
  {
    q: "문서를 고치면 챗봇도 바뀌나요?",
    a: "새 문서를 올리면 몇 분 안에 반영됩니다. 처리 중에는 목록에서 상태를 볼 수 있고, 준비가 끝나면 그때부터 답변에 쓰입니다.",
    evidence: {
      kind: "설계" as const,
      text: "업로드 응답과 처리를 분리했습니다 — 문서를 읽고 나누고 색인하는 데 수십 초가 걸릴 수 있어, 기다리게 하는 대신 상태로 보여줍니다.",
    },
  },
] satisfies ReadonlyArray<{
  q: string;
  a: string;
  evidence: { kind: "실측" | "설계" | "미정"; text: string };
}>;

export default function FaqPage() {
  return (
    <div className="mx-auto w-full max-w-5xl px-6 py-16">
      <PageIntro
        eyebrow="자주 묻는 질문"
        title="아직 안 되는 것도 함께 적었습니다."
        lead="지금 동작하는 것만 현재형으로 썼습니다. 계획이거나 정해지지 않은 것은 그렇다고 표시했습니다."
      />

      {/* 질문 목록이므로 ul/li 다. div 나열이면 스크린리더가 "6개 중 3번째" 를 못 읽어준다.
          클래스는 그대로 옮겼고 details 는 li 안으로만 들어간다 — group-open/py-5 가
          details 에 남아야 펼침 회전과 divide-y 간격이 유지된다. */}
      <ul className="mt-10 divide-y divide-subtle border-b border-subtle">
        {QA.map((item) => (
          <li key={item.q}>
          <details className="group py-5">
            <summary className="flex cursor-pointer list-none items-start justify-between gap-4 text-base font-semibold leading-snug marker:content-none sm:text-lg">
              {item.q}
              {/* 펼침 표시. group-open 으로 회전시킨다 — 아이콘 두 개를 번갈아 숨기는 것보다 단순하다 */}
              <span
                aria-hidden
                className="mt-1 shrink-0 text-muted group-hover:text-foreground transition-transform group-open:rotate-45 motion-reduce:transition-none"
              >
                +
              </span>
            </summary>
            <div className="mt-3 max-w-2xl">
              <p className="leading-relaxed text-muted">{item.a}</p>
              <Evidence kind={item.evidence.kind}>{item.evidence.text}</Evidence>
            </div>
          </details>
          </li>
        ))}
      </ul>

      <p className="mt-10 text-sm text-muted">
        찾는 답이 없으면{" "}
        <Link href="/auth" className="font-medium text-foreground underline">
          문의를 남겨주세요
        </Link>
        .
      </p>
    </div>
  );
}
