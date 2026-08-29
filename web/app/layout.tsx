import type { Metadata } from "next";
import localFont from "next/font/local";
import { ViewTransition } from "react";
import "./globals.css";

/**
 * Pretendard Variable — 직접 호스팅하는 한글 가변 폰트.
 *
 * ⚠️ `next/font/google` 을 피한 기존 이유(빌드 시점에 구글 서버로 요청 → 오프라인·
 *    사내망 빌드가 깨진다)는 여기 해당하지 않는다. `next/font/local` 은 저장소 안의
 *    파일만 읽는다. 그래서 빌드에도 런타임에도 외부 요청이 0 이다.
 *
 * 왜 OS 기본 폰트로 안 되나: 윈도우는 한글이 맑은 고딕으로 잡히는데 굵기가
 * 400·700 둘뿐이다. 랜딩 H1 이 800 이라 <가짜 굵게>가 나온다.
 * Pretendard 는 100~900 가변이라 이 문제가 사라진다.
 * (2,350자만 담은 근거와 재생성 방법은 globals.css 상단 주석 참고)
 */
const pretendard = localFont({
  src: "./fonts/Pretendard-KSX1001.woff2",
  // 가변 폰트라 <범위>로 준다. 이래야 브라우저가 800 을 진짜 굵기로 만든다.
  weight: "100 900",
  display: "swap", // 폰트를 기다리며 글자가 안 보이는 구간을 만들지 않는다
  variable: "--font-pretendard",
  // 폰트가 오기 전과, KS X 1001 밖 글자를 받는 스택. 여기 적어두면 next 가
  // 이 폴백의 메트릭을 원본에 맞춰 조정해 교체 순간의 레이아웃 밀림을 줄인다.
  fallback: [
    "-apple-system",
    "BlinkMacSystemFont",
    "Apple SD Gothic Neo",
    "Malgun Gothic",
    "Noto Sans KR",
    "system-ui",
    "sans-serif",
  ],
});

export const metadata: Metadata = {
  /*
   * og:image 같은 상대 경로를 절대 URL 로 바꿀 때 기준이 되는 주소.
   * 안 정하면 빌드가 경고를 내고 localhost 로 박혀서, 배포 후 카카오톡·슬랙에
   * 링크를 붙여도 미리보기 이미지가 안 뜬다(외부에서 localhost 를 못 받으므로).
   * TODO(배포): 실제 도메인이 정해지면 NEXT_PUBLIC_SITE_URL 로 주입할 것.
   */
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000"),
  title: "AllDap",
  description:
    "문서를 올리면 출처가 표시되는 한국어 RAG 챗봇을 만들고, 답변 품질을 자동 평가해주는 서비스",
};

/**
 * 루트 레이아웃.
 *
 * 여기에는 <html>/<body> 와 전역 스타일만 둔다. 헤더·네비게이션을 두지 않는 이유:
 *   /w/[publicKey] 임베드 위젯은 고객사 사이트 안에서 뜨는 "공개 화면"이라
 *   관리자용 헤더·좌측 네비를 절대 물려받으면 안 된다.
 * 그래서 공통 크롬(헤더/네비)은 라우트 그룹별 layout.tsx 로 내렸다.
 *
 *   app/page.tsx               → 랜딩 (크롬 없음 — 히어로가 자기 헤더를 갖는다)
 *   app/(site)/layout.tsx      → 인증 (가벼운 공개 헤더)
 *   app/(dashboard)/layout.tsx → 대시보드 (관리자 헤더 + 봇 좌측 네비)
 *   app/(widget)/layout.tsx    → 위젯 (크롬 없음)
 *
 * 라우트 그룹 `(이름)` 폴더는 URL 에 나타나지 않는다. 레이아웃만 갈라준다.
 */
export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko" className={`h-full antialiased ${pretendard.variable}`}>
      {/*
        ── 페이지 전환 경계는 (site) 가 아니라 여기(루트)에 둔다 ─────────────────
        랜딩(`app/page.tsx`)은 위 주석대로 (site) 그룹 <밖>에 있다. 이전에는
        이 경계가 (site)/layout.tsx 안에만 있어서, "/" → "/auth" 같은 이동은
        도착 쪽에만 경계가 있고 출발 쪽(랜딩)에는 없었다 — React 가 두 스냅샷을
        비교해 view transition 을 시작하려면 경계가 <양쪽 다>에 있어야 하는데,
        랜딩 쪽이 빠져 있어 전환이 아예 시작되지 않았다(startViewTransition 0회 실측).
        루트는 "/" 를 포함한 모든 라우트에 걸쳐 살아있으므로 여기 두면 항상 양쪽에 존재한다.
      */}
      <body className="flex min-h-full flex-col">
        <ViewTransition
          enter={{ door: "door", default: "fade" }}
          exit={{ door: "none", default: "fade" }}
        >
          {children}
        </ViewTransition>
      </body>
    </html>
  );
}
