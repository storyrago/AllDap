import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
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
 *   app/(site)/layout.tsx      → 랜딩 · 인증 (가벼운 공개 헤더)
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
    <html lang="ko" className="h-full antialiased">
      <body className="flex min-h-full flex-col">{children}</body>
    </html>
  );
}
