import Link from "next/link";
import { ViewTransition } from "react";

/**
 * 공개 화면(`/auth`, `/features`, `/pricing`, `/faq`) 공통 레이아웃.
 * 로그인 전 사용자가 보는 화면이므로 관리자 네비게이션을 넣지 않는다.
 *
 * ⚠️ 랜딩(`/`)은 이 그룹에 <없다>. 히어로가 자기 헤더를 갖고 화면 전체를 쓰는
 *    스크롤 무대라 이 크롬을 씌우면 헤더가 두 개가 된다(app/page.tsx 주석 참고).
 *    그래서 헤더 메뉴가 두 곳에 있다 — 여기와 ReceptionHero. 항목을 바꿀 때는 둘 다 본다.
 */

/** 공개 페이지 메뉴. ReceptionHero 의 NAV 와 항목을 맞춘다. */
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

      {/*
        ── 페이지 전환 ────────────────────────────────────────────────────────
        `<Link>` 가 붙인 이름표(transitionTypes)를 <CSS 클래스로 바꿔주는> 것이 이 래퍼다.
        래퍼 없이 이름표만 주면 아무 일도 일어나지 않는다.
        `default: "fade"` 는 이름표가 없는 이동(= 대부분의 이동) 몫이다.
        ⚠️ 공식 예제는 여기에 "none" 을 써서 첫 로드에 아무것도 안 걸리게 한다.
           우리는 페이지끼리의 이동에 페이드가 필요해서 "fade" 로 둔다 —
           대신 첫 로드에도 걸릴 수 있어서 Step 6 에서 그걸 눈으로 확인한다.
      */}
      <main className="flex-1">
        <ViewTransition enter={{ default: "fade" }} exit={{ default: "fade" }}>
          {children}
        </ViewTransition>
      </main>

      <footer className="border-t border-subtle">
        <div className="mx-auto w-full max-w-5xl px-6 py-6 text-xs text-muted">
          AllDap — 문서 기반 FAQ 챗봇 빌더 (포트폴리오 프로젝트)
        </div>
      </footer>
    </div>
  );
}
