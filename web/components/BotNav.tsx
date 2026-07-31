"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * 봇 상세 화면(/bot/[botId]/*)의 좌측 네비게이션.
 *
 * "use client" 를 붙인 이유:
 *   현재 어느 탭인지 표시하려면 usePathname() 으로 브라우저의 현재 경로를 읽어야 하는데,
 *   이 훅은 클라이언트 컴포넌트에서만 쓸 수 있다.
 *   (Next.js App Router 는 기본이 서버 컴포넌트다. 훅을 쓰는 부분만 클라이언트로 내린다.)
 */

/** PRD §7 사이트맵의 /bot/[botId] 하위 5개 화면 */
const NAV_ITEMS = [
  { slug: "documents", label: "문서 관리" },
  { slug: "chat", label: "테스트 채팅" },
  { slug: "quality", label: "품질 대시보드" },
  { slug: "logs", label: "대화 로그" },
  { slug: "settings", label: "설정" },
] as const;

export function BotNav({ botId }: { botId: string }) {
  const pathname = usePathname();

  return (
    <nav aria-label="봇 메뉴" className="w-full shrink-0 sm:w-48">
      <ul className="flex gap-1 overflow-x-auto sm:flex-col sm:overflow-visible">
        {NAV_ITEMS.map((item) => {
          const href = `/bot/${botId}/${item.slug}`;
          const isActive = pathname === href;
          return (
            <li key={item.slug}>
              <Link
                href={href}
                aria-current={isActive ? "page" : undefined}
                className={`block whitespace-nowrap rounded-md px-3 py-2 text-sm transition-colors ${
                  isActive
                    ? "bg-foreground/10 font-semibold"
                    : "text-muted hover:bg-foreground/5"
                }`}
              >
                {item.label}
                {/* 품질 대시보드가 이 제품의 핵심이라는 걸 네비에서도 드러낸다 (PRD §8) */}
                {item.slug === "quality" ? (
                  <span className="ml-1 text-accent" aria-hidden>
                    ★
                  </span>
                ) : null}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
