import Link from "next/link";
import { AuthLink } from "@/components/AuthLink";

/**
 * 공개 화면(`/auth`, `/features`, `/pricing`, `/faq`) 공통 레이아웃.
 * 관리자 네비게이션은 넣지 않는다. 다만 로그인한 사람도 이 화면에 온다(대시보드 헤더의
 * 로고가 랜딩으로 가고, 거기서 기능 페이지로 들어온다). 그래서 오른쪽 끝 버튼만
 * 로그인 여부를 안다(`AuthLink`).
 *
 * ⚠️ 랜딩(`/`)은 이 그룹에 <없다>. 히어로가 자기 헤더를 갖고 화면 전체를 쓰는
 *    스크롤 무대라 이 크롬을 씌우면 헤더가 두 개가 된다(app/page.tsx 주석 참고).
 *    히어로 쪽 헤더는 문이 열리는 동안에는 로고뿐이지만, <마지막 장면>에서는
 *    우상단에 같은 메뉴가 뜬다(ReceptionHero 의 `SCENE_NAV`).
 * 🔴 그래서 아래 `NAV` 는 이 파일에만 있는 것이 아니다. 두 곳을 함께 고쳐야 한다 —
 *    한쪽만 고치면 랜딩 마지막 장면의 메뉴만 조용히 어긋난다.
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
            <AuthLink />
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
