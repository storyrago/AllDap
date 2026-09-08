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
 */

import Link from "next/link";
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

  return token ? (
    <Link href="/dashboard" className={CLASS_NAME}>
      대시보드
    </Link>
  ) : (
    <Link href="/auth" className={CLASS_NAME}>
      로그인
    </Link>
  );
}
