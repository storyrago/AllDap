"use client";

/**
 * 사이드바 맨 위의 봇 이름.
 *
 * ── 왜 이것만 클라이언트 컴포넌트인가 ──────────────────────────────────────
 * 감싸는 레이아웃(`app/(dashboard)/bot/[botId]/layout.tsx`)은 서버 컴포넌트다.
 * 그런데 봇 이름을 가져오려면 `GET /api/bots/{botId}` 에 <JWT 를 붙여야> 하고,
 * 그 토큰은 localStorage 에 있다 — 즉 <브라우저에만 있다>. 서버는 이 요청을 보낸
 * 사람이 누구인지 자체를 모르므로 대신 가져와 줄 수가 없다.
 * (`/quality` 가 클라이언트 컴포넌트인 이유와 같다. 이 프로젝트에서 반복되는 지점이다)
 *
 * 그래서 <이름 한 줄만> 클라이언트로 내렸다. 레이아웃 전체를 클라이언트로 바꾸면
 * 그 아래 모든 화면이 함께 클라이언트 번들에 들어간다.
 *
 * ── 못 가져왔을 때 ─────────────────────────────────────────────────────────
 * 이름이 없다고 화면을 막지 않는다. 이름은 <길잡이>일 뿐 이 페이지의 내용이 아니다.
 * 실패하면 조용히 id 앞자리로 떨어진다 — 지금까지 보이던 것과 같은 모습이라
 * 나빠지지 않는다. 없는 봇인지(404) 여부는 각 화면이 자기 데이터를 부를 때 드러난다.
 */

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export function BotName({ botId }: { botId: string }) {
  const [name, setName] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const bot = await api.bots.get(botId);
        if (!cancelled) setName(bot.name);
      } catch {
        // 위 주석 참고 — 이름을 못 가져와도 화면은 그대로 쓸 수 있어야 한다.
      }
    })();
    return () => {
      cancelled = true;
    };
    // botId 가 바뀌면 <그 봇의> 이름을 다시 가져와야 한다.
  }, [botId]);

  return (
    <p
      className="mb-2 truncate px-3 text-xs font-medium text-muted"
      title={name ?? botId}
    >
      {name ?? `봇 ${botId.slice(0, 8)}…`}
    </p>
  );
}
