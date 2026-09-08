"use client";

/**
 * 마케팅 헤더 오른쪽 끝의 버튼 — 로그인 전에는 "로그인", 로그인 뒤에는 "대시보드".
 *
 * ── 왜 이것만 클라이언트 컴포넌트인가 ──────────────────────────────────────
 * 감싸는 레이아웃(`app/(site)/layout.tsx`)은 서버 컴포넌트다. 그런데 "로그인했는가"를
 * 알려면 JWT 를 봐야 하고, 그 토큰은 localStorage 에 있다 — 즉 <브라우저에만 있다>.
 * 서버는 요청을 보낸 사람이 누구인지 자체를 모르므로 대신 판단해 줄 수가 없다.
 * (`BotName` 이 봇 이름을 클라이언트에서 가져오는 것과 같은 이유다)
 *
 * 그래서 <이 버튼만> 클라이언트로 내렸다. 레이아웃 전체를 클라이언트로 바꾸면
 * 공개 페이지 전부가 클라이언트 번들에 들어간다.
 *
 * ── 첫 렌더는 항상 "로그인" 이다 ───────────────────────────────────────────
 * useSyncExternalStore 의 세 번째 인자(서버 스냅샷)는 undefined 를 준다 — "아직 모름".
 * 서버 HTML 도, 하이드레이션 첫 렌더도 이 값을 쓰므로 둘이 "로그인" 으로 일치하고
 * (불일치면 React 가 경고하고 화면이 깨진다), 하이드레이션이 끝난 뒤 실제 토큰을 읽어
 * "대시보드" 로 바뀐다. 로그인한 사람에게만 한 프레임 깜빡임이 있다 — 하이드레이션
 * 불일치를 내지 않는 유일한 방법이라 받아들인다.
 * undefined(아직 모름)와 null(확실히 없음)을 여기서는 <같이> "로그인" 으로 그린다.
 * 대시보드 가드는 둘을 갈라야 했지만(null 만 튕김) 이 버튼은 어느 쪽이든 보여줄 글자가 같다.
 *
 * ── `?next=` 를 왜 여기서 붙이는가 (별도 LoginLink 가 아니라) ───────────────
 * 2026-08-18 에 만들어졌다가 머지되지 않고 브랜치에 남아 있던 `components/LoginLink.tsx`
 * 가 이 일을 하려던 컴포넌트다. 되살리면서 <이쪽으로 합쳤다> — 헤더 오른쪽 끝 자리는
 * 하나뿐인데 컴포넌트를 둘 두면 "로그인했을 때" 와 "로그인 안 했을 때" 를 서로 다른
 * 파일이 맡게 된다. 한쪽만 고치는 사고가 나는 모양이다.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSyncExternalStore } from "react";
import {
  getAccessToken,
  getAccessTokenServerSnapshot,
  subscribeAccessToken,
} from "@/lib/api";

const CLASS_NAME = "ml-2 rounded-lg bg-foreground px-4 py-2 font-medium text-surface";

export function AuthLink() {
  const token = useSyncExternalStore(
    subscribeAccessToken,
    getAccessToken,
    getAccessTokenServerSnapshot,
  );
  /*
   * 지금 보고 있는 경로. 로그인 링크에 `?next=` 로 실어 보내면 인증이 끝난 뒤 여기로 돌아온다 —
   * FAQ 를 읽다 로그인한 사람을 대시보드로 던지면 읽던 맥락이 끊긴다.
   *
   * ⚠️ `useSearchParams` 가 아니라 `usePathname` 이다. 전자만 프리렌더된 트리에서
   *    Suspense 경계를 요구한다(Next 16 문서).
   */
  const pathname = usePathname();

  if (token) {
    return (
      <Link href="/dashboard" className={CLASS_NAME}>
        대시보드
      </Link>
    );
  }

  /*
   * 로그인 화면에서 또 로그인 링크를 누르면 `next` 를 붙이지 않는다 — 제자리걸음이 된다.
   * (`safeRedirectPath` 도 `/auth` 를 기본값으로 되돌리지만, 애초에 안 실어 보내는 편이 낫다:
   *  주소창에 의미 없는 쿼리가 남지 않는다)
   */
  /*
   * ⚠️ 알고 남긴 한계: `usePathname()` 은 쿼리스트링과 해시를 버린다(Next 16 문서).
   *    그래서 `/pricing#plans` 에서 로그인하면 `/pricing` 으로 돌아온다. 해시가 사라진다.
   *    지금은 실해가 없어서 두었다. 해시로 특정 자리를 겨냥하는 링크가 늘면
   *    `window.location` 을 읽어야 하는데, 그러면 이 컴포넌트가 서버에서 그려질 때
   *    쓸 값이 없어져 하이드레이션을 다시 따져야 한다. 값어치가 생기면 그때 한다.
   */
  const href =
    pathname && pathname !== "/auth" ? `/auth?next=${encodeURIComponent(pathname)}` : "/auth";

  return (
    <Link href={href} className={CLASS_NAME}>
      로그인
    </Link>
  );
}
