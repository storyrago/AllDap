import { BotNav } from "@/components/BotNav";

/**
 * 봇 상세 화면 공통 레이아웃 (`/bot/[botId]/*`).
 * 좌측(모바일에서는 상단)에 문서·채팅·품질·로그·설정 네비를 둔다.
 *
 * 호출할 Spring API:
 *   GET /api/bots/{botId} → Bot   (api.bots.get)
 *   → 헤더에 봇 이름을 띄우기 위해 필요하다. 없는 봇이면 404 처리.
 *
 * Next.js 16 메모: layout/page 의 `params` 는 Promise 다. 반드시 await 해야 한다.
 * (14 버전까지는 동기 객체였다. 예전 예제 코드를 그대로 베끼면 여기서 깨진다.)
 */
export default async function BotLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ botId: string }>;
}) {
  const { botId } = await params;

  return (
    <div className="flex flex-col gap-6 sm:flex-row">
      <aside>
        {/* TODO(W2): GET /api/bots/{botId} 로 봇 이름을 가져와 여기에 표시할 것.
            없는 botId 면 notFound() 를 호출해 404 를 띄운다. */}
        <p className="mb-2 truncate px-3 text-xs text-muted" title={botId}>
          봇 {botId.slice(0, 8)}…
        </p>
        <BotNav botId={botId} />
      </aside>

      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}
