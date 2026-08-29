import Link from "next/link";

/**
 * 공개 화면(`/auth`, `/features`, `/pricing`, `/faq`) 공통 레이아웃.
 * 로그인 전 사용자가 보는 화면이므로 관리자 네비게이션을 넣지 않는다.
 *
 * ⚠️ 랜딩(`/`)은 이 그룹에 <없다>. 히어로가 자기 헤더를 갖고 화면 전체를 쓰는
 *    스크롤 무대라 이 크롬을 씌우면 헤더가 두 개가 된다(app/page.tsx 주석 참고).
 *    히어로 쪽 헤더는 이제 로고뿐이다(구석 메뉴 3개는 문으로 있다가 요금제·FAQ 를
 *    빼며 함께 사라졌다 — ReceptionHero 상단 주석 참고). 그래서 메뉴 항목은 이제
 *    이 파일에만 있고, ReceptionHero 와 맞출 것이 없다.
 *
 * ⚠️ 페이지 전환(`<ViewTransition>`) 래퍼는 여기 없다 — 루트(`app/layout.tsx`)로
 *    옮겼다. 랜딩이 이 그룹 밖이라, 경계를 여기에만 두면 "/" 로 오가는 이동은
 *    한쪽(도착 쪽)에만 경계가 있어 전환이 시작되지 않는다. 다시 여기로 내리지 말 것.
 */

/** 공개 페이지 메뉴. */
const NAV = [
  { label: "기능", href: "/features" },
  { label: "요금제", href: "/pricing" },
  { label: "FAQ", href: "/faq" },
] as const;
export default function SiteLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-dvh flex-col">
      <header className="border-b border-subtle">
        <div className="mx-auto flex w-full max-w-5xl items-center justify-between px-6 py-4">
          <Link href="/" className="text-base font-semibold tracking-[0.14em]">
            ALLDAP
          </Link>
          <nav className="flex items-center gap-1 text-sm">
            {NAV.map(({ label, href }) => (
              <Link key={href} href={href} className="rounded px-3 py-2 text-muted hover:text-foreground">
                {label}
              </Link>
            ))}
            <Link href="/auth" className="ml-2 rounded-lg bg-foreground px-4 py-2 font-medium text-surface">
              로그인
            </Link>
          </nav>
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
