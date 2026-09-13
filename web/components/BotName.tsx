"use client";

/**
 * 사이드바 맨 위의 봇 이름 — 그리고 <없는 봇을 404 로 떨어뜨리는 자리>.
 *
 * ── 왜 이것만 클라이언트 컴포넌트인가 ──────────────────────────────────────
 * 감싸는 레이아웃(`app/(dashboard)/bot/[botId]/layout.tsx`)은 서버 컴포넌트다.
 * 그런데 봇을 가져오려면 `GET /api/bots/{botId}` 에 <JWT 를 붙여야> 하고,
 * 그 토큰은 localStorage 에 있다 — 즉 <브라우저에만 있다>. 서버는 이 요청을 보낸
 * 사람이 누구인지 자체를 모르므로 대신 가져와 줄 수가 없다.
 * (`/quality` 가 클라이언트 컴포넌트인 이유와 같다. 이 프로젝트에서 반복되는 지점이다)
 *
 * 그래서 <이 조각만> 클라이언트로 내렸다. 레이아웃 전체를 클라이언트로 바꾸면
 * 그 아래 모든 화면이 함께 클라이언트 번들에 들어간다.
 *
 * ── 🔴 왜 "이름 컴포넌트" 가 404 까지 책임지는가 ────────────────────────────
 * 어색해 보이지만 <요청을 한 번만 보내기 위해서다>. 봇 존재 여부를 알려면
 * `GET /api/bots/{botId}` 를 불러야 하는데, 이 컴포넌트가 이미 그걸 부르고 있다.
 * 가드를 따로 만들면 같은 요청이 두 번 나간다.
 */

import { useEffect, useState } from "react";
import { notFound } from "next/navigation";
import { ApiError, api } from "@/lib/api";
import type { Id } from "@/lib/types";

export function BotName({ botId }: { botId: Id }) {
  const [name, setName] = useState<string | null>(null);

  /*
   * 🔴 "없는 봇" 을 <어느 봇에 대한 판정인지와 함께> 저장한다.
   *
   * 단순 boolean 으로 두면 봇을 바꿔 이동했을 때 이전 판정이 남아 멀쩡한 봇이
   * 404 로 보인다. effect 안에서 리셋하는 방법도 있지만, 그건 eslint 의
   * react-hooks/set-state-in-effect 가 막는 모양이고 리셋 타이밍도 한 박자 늦는다.
   * botId 를 함께 담아두면 <값이 스스로 낡는다> — 아래 비교 한 줄이면 끝난다.
   */
  const [goneFor, setGoneFor] = useState<Id | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const bot = await api.bots.get(botId);
        if (!cancelled) setName(bot.name);
      } catch (e) {
        /*
         * 🔴 404 만 갈라낸다. 예전에는 이 catch 가 <전부 삼켰다> —
         *    "이 봇은 없다"(404)와 "지금 못 가져왔다"(네트워크 끊김·500)를
         *    같은 값으로 뭉갠 것이다. 이 저장소가 반복해 낸 버그가 정확히 그 부류다
         *    (AGENTS.md 의 "낸 버그" 절 — 전부 같은 부류다).
         *
         *    ⚠️ 남의 봇도 404 다(서버가 일부러 그렇게 준다 — not-found.tsx 주석 참고).
         *       그래서 이 분기는 "없는 봇" 과 "남의 봇" 을 함께 받는다. 그게 의도다.
         *
         *    나머지 오류는 <그대로 삼킨다>. 이름은 길잡이일 뿐 이 페이지의 내용이 아니라,
         *    일시적 실패로 화면 전체를 404 로 덮으면 오히려 사실과 멀어진다.
         */
        if (!cancelled && e instanceof ApiError && e.status === 404) {
          setGoneFor(botId);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
    // botId 가 바뀌면 <그 봇의> 이름을 다시 가져와야 한다.
  }, [botId]);

  /*
   * 🔴 notFound() 는 <렌더 중>에 불러야 한다.
   *    위 effect 안에서 바로 부르면 그 예외는 비동기 콜백에서 던져지는 것이라
   *    React 가 라우터까지 전달하지 못한다(공식 문서: "terminates rendering of
   *    the route segment in which it was thrown" — 렌더가 전제다).
   *    그래서 effect 는 <상태만> 남기고, 판정은 여기서 한다.
   */
  if (goneFor === botId) notFound();

  return (
    <p
      className="mb-2 truncate px-3 text-xs font-medium text-muted"
      title={name ?? `봇 ${botId}`}
    >
      {/* 이름을 아직 못 가져왔으면 번호로 대신한다. 기본키가 BIGINT 가 된 뒤로는
          앞 8글자를 자를 이유가 없다 — UUID 와 달리 번호는 원래 짧다. */}
      {name ?? `봇 ${botId}`}
    </p>
  );
}
