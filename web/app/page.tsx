import type { Metadata } from "next";
import { ReceptionHero } from "@/components/ReceptionHero";

/**
 * `/` 랜딩 페이지 — PRD §8 "가치 제안, 데모, CTA / SEO, 반응형"
 *
 * ── 왜 (site) 그룹 밖(app/page.tsx)에 있나 ──────────────────────────────────
 * 원래 app/(site)/page.tsx 였는데 옮겼다. (site) 레이아웃은 헤더·푸터·max-w-5xl
 * 컨테이너를 씌우는데, 히어로는 <자기 헤더를 갖고 화면 전체를 쓰는 스크롤 무대>다.
 * 그 안에 넣으면 헤더가 두 개가 되고 무대가 컨테이너 폭에 짓눌린다.
 * `/auth` 는 그 크롬이 여전히 필요하므로 (site) 그룹에 그대로 남겨뒀다.
 *
 * ── 왜 이 파일은 "use client" 가 아닌가 ────────────────────────────────────
 * `export const metadata` 는 서버 컴포넌트에서만 쓸 수 있다. 랜딩은 SEO 가
 * 필요한 유일한 화면이라 이 파일은 서버 컴포넌트로 남기고, 브라우저가 필요한
 * 부분(<ReceptionHero />)만 클라이언트 컴포넌트로 분리했다.
 *
 * 호출하는 API: 없음. 로그인 없이 보는 화면이다.
 * (히어로 안의 데모 챗봇은 현재 목업이다 — ReceptionHero 의 TODO 참고)
 */
export const metadata: Metadata = {
  title: "AllDap — 문서를 읽고 출처까지 알려주는 한국어 AI 안내 데스크",
  description:
    "사내 문서를 올리면 출처가 표시되는 챗봇이 됩니다. 근거가 없으면 답을 지어내지 않고, 답변 품질을 자동으로 평가해 리포트로 보여줍니다.",
  openGraph: {
    title: "AllDap — 문서를 읽고 출처까지 알려주는 한국어 AI 안내 데스크",
    description:
      "사내 문서를 올리면 출처가 표시되는 챗봇이 됩니다. 근거가 없으면 답을 지어내지 않습니다.",
    type: "website",
    locale: "ko_KR",
    // 안내 데스크 장면을 구워둔 스틸. 3D 를 걷어내며 남은 유일한 이미지 산출물이다.
    images: [{ url: "/hero/hero-100.png", width: 2560, height: 1440 }],
  },
};

export default function LandingPage() {
  return <ReceptionHero />;
}
