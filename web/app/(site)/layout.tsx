import Link from "next/link";

/**
 * 공개 화면(랜딩 `/`, 인증 `/auth`) 공통 레이아웃.
 * 로그인 전 사용자가 보는 화면이므로 관리자 네비게이션을 넣지 않는다.
 */
export default function SiteLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-dvh flex-col">
      <header className="border-b border-subtle">
        <div className="mx-auto flex w-full max-w-5xl items-center justify-between px-6 py-4">
          <Link href="/" className="text-base font-semibold">
            AllDap
          </Link>
          <Link href="/auth" className="text-sm text-muted hover:underline">
            로그인
          </Link>
        </div>
      </header>

      <main className="flex-1">{children}</main>

      <footer className="border-t border-subtle">
        <div className="mx-auto w-full max-w-5xl px-6 py-6 text-xs text-muted">
          AllDap — 문서 기반 FAQ 챗봇 빌더 (포트폴리오 프로젝트)
        </div>
      </footer>
    </div>
  );
}
