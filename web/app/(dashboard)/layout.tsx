import Link from "next/link";

/**
 * 관리자 대시보드 공통 레이아웃 (`/dashboard`, `/bot/[botId]/*`).
 *
 * 이 그룹의 화면은 전부 로그인이 필요하다.
 * TODO(W2): 인증 가드를 붙일 것. 방법은 두 가지 중 하나로 확정한다.
 *   (a) middleware.ts 에서 쿠키를 확인하고 /auth 로 리다이렉트 — 쿠키 방식일 때 적합
 *   (b) 클라이언트에서 getAccessToken() 확인 후 리다이렉트 — localStorage 방식일 때
 *   지금은 토큰 보관 방식 자체가 미정이라(lib/api.ts 참고) 가드를 넣지 않았다.
 *   즉 현재는 로그인 없이도 이 화면들이 열린다. 뼈대라서 그렇다.
 */
export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-dvh flex-col">
      <header className="border-b border-subtle bg-surface">
        <div className="mx-auto flex w-full max-w-6xl items-center justify-between px-6 py-3">
          <Link href="/dashboard" className="text-base font-semibold">
            AllDap
          </Link>
          {/* TODO(W2): 로그인한 사용자 이름·로그아웃 메뉴. GET /api/auth/me 가 필요하다면
              PRD §10.1 표에 없으므로 Spring 설계 시 추가 여부를 정할 것. */}
          <span className="text-xs text-muted">계정 메뉴 (미구현)</span>
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-8">
        {children}
      </main>
    </div>
  );
}
