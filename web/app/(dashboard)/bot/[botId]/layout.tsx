import { BotName } from "@/components/BotName";
import { BotNav } from "@/components/BotNav";
import { parseId } from "@/lib/ids";

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
 *
 * ⚠️ await 해서 꺼낸 `botId` 는 <문자열>이다. URL 이 텍스트라 그럴 수밖에 없다.
 *    기본키가 BIGINT 가 된 뒤로는 숫자로 바꿔야 하고, 그 변환과 검사는 parseId 가 한다
 *    (형식이 틀리면 거기서 404 로 떨어진다 — `lib/ids.ts` 주석 참고).
 */
export default async function BotLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  /* URL 세그먼트는 언제나 string 이다. 숫자로 바꾸는 것은 아래 parseId 의 몫. */
  params: Promise<{ botId: string }>;
}) {
  const { botId: rawBotId } = await params;
  const botId = parseId(rawBotId);

  return (
    <div className="flex flex-col gap-6 sm:flex-row">
      <aside>
        {/* 이름만 클라이언트에서 가져온다 — 토큰이 브라우저에만 있어서다(BotName 주석 참고).
            ✅ 없는 봇(과 남의 봇)의 404 판정도 BotName 이 한다 — 이미 GET /api/bots/{botId} 를
               부르고 있어 거기 얹으면 요청이 늘지 않는다. 화면은 같은 세그먼트의
               not-found.tsx 가 그린다. */}
        <BotName botId={botId} />
        <BotNav botId={botId} />
      </aside>

      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}
