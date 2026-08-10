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
/*
 * 순서는 <사용자가 실제로 밟는 순서>다. 기능을 종류별로 묶은 목록이 아니다.
 *
 *   문서를 먹인다 → 잘 답하는지 본다 → 내 사이트에 내보낸다
 *   ─────────── 여기까지가 처음 온 사람이 끝내야 할 일 ───────────
 *   품질·진단·로그는 <내보낸 뒤에> 보는 화면이고, 설정은 다 되고 나서 손보는 곳이다.
 *
 *   진단이 품질 <바로 뒤>인 이유: 둘 다 "이 봇이 괜찮은가"를 다룬다.
 *   품질이 <지금 얼마나 좋은가>(측정)라면 진단은 <뭘 고치면 좋아지나>(처방)다.
 *   문서 관리 옆에 두지 않은 이유는, 나중에 여기에 <미답변 질문>을 얹을 것이기 때문이다 —
 *   그건 문서가 아니라 대화에서 나온다.
 *
 * 예전에는 임베드 코드가 "설정" 안에 있었다. PRD §8 이 "코드 복사가 전환 포인트" 라고
 * 못박은 자리가, 보통 맨 나중에 한 번 들어가는 메뉴에 묻혀 있었던 셈이다.
 */
const NAV_ITEMS = [
  { slug: "documents", label: "문서 관리" },
  { slug: "chat", label: "테스트 채팅" },
  { slug: "export", label: "내보내기" },
  { slug: "quality", label: "품질 대시보드" },
  { slug: "diagnostics", label: "진단" },
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
