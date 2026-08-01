"use client";

/*
 * ─────────────────────────────────────────────────────────────────────────────
 * 관리자 대시보드 공통 레이아웃 (`/dashboard`, `/bot/[botId]/*`).
 *
 * 왜 레이아웃까지 클라이언트 컴포넌트인가 — 그리고 왜 이 화면들의 데이터를
 * 서버에서 안 가져오는가. (이 프로젝트에서 가장 중요한 프론트 설계 결정이다)
 * ─────────────────────────────────────────────────────────────────────────────
 * Next.js 의 장점은 "서버에서 데이터를 미리 가져와 HTML 로 내려주는 것" 이다.
 * 그런데 우리는 그걸 <쓸 수가 없다>. 이유는 하나다 —
 *
 *      JWT 를 브라우저의 localStorage 에 보관하기 때문이다.
 *
 * 서버 컴포넌트는 서버에서 실행되므로 localStorage 에 접근할 방법이 없다.
 * 즉 서버는 "이 요청을 보낸 사람이 누구인지" 를 알 수 없고, 따라서 그 사람의 봇 목록을
 * 대신 가져와 줄 수도 없다. 결국 <브라우저가 토큰을 들고 직접 Spring 을 호출>해야 한다.
 *
 * 쿠키(httpOnly)로 바꾸면 이 제약이 사라진다. 브라우저가 쿠키를 자동으로 붙여 보내므로
 * 서버 컴포넌트도 인증된 요청을 만들 수 있고, 아래 "깜빡임" 문제도 middleware 로 해결된다.
 * 그게 더 나은 설계지만 <지금은 localStorage 다>. 그래서 이 구조를 택했고,
 * 이 주석이 그 트레이드오프의 기록이다.
 *   TODO(W2 이후): 토큰을 httpOnly 쿠키로 옮기고 가드를 middleware 로 내릴 것.
 *
 * ⚠️ 이 방식의 알려진 약점: 토큰 확인이 <브라우저에서> 일어나므로,
 *    로그인하지 않은 사람에게도 화면 껍데기가 잠깐 그려졌다가 이동한다.
 *    아래에서 checking 상태를 두어 그동안 내용을 그리지 않는 것으로 가린다.
 *    다만 이건 UX 보정일 뿐 <보안 장치가 아니다> — 진짜 방어는 서버가 401 을 주는 것이고,
 *    그건 이미 SecurityConfig 가 하고 있다.
 * ─────────────────────────────────────────────────────────────────────────────
 */

import { useEffect, useSyncExternalStore } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  clearAccessToken,
  getAccessToken,
  getAccessTokenServerSnapshot,
  subscribeAccessToken,
} from "@/lib/api";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();

  /*
   * 토큰을 <상태로 복사하지 않고 구독해서 읽는다>.
   *
   * useSyncExternalStore 는 "React 바깥에 있는 값"을 렌더에 안전하게 끌어오는 훅이다.
   * 인자 셋의 뜻: (구독 함수, 브라우저에서 읽는 함수, 서버에서 읽는 함수).
   *
   * <왜 useEffect + useState 가 아닌가.> 그렇게 하면 effect 안에서 setState 를 하게 되어
   * 렌더가 한 번 더 돌고, eslint 의 react-hooks/set-state-in-effect 가 이를 막는다.
   * 규칙이 옳다 — 바깥 저장소를 읽는 일은 "상태 복사"가 아니라 "구독"으로 표현하는 게 맞다.
   *
   * 덤으로 얻는 것: 다른 탭에서 로그아웃하면 이 탭도 즉시 로그인 화면으로 간다.
   * 예전 방식은 처음 한 번만 읽어서 그걸 못 잡았다.
   */
  const token = useSyncExternalStore(
    subscribeAccessToken,
    getAccessToken,
    getAccessTokenServerSnapshot,
  );

  useEffect(() => {
    // 여기서는 setState 를 하지 않는다. 화면 이동이라는 <바깥 세계의 일>만 한다.
    if (token === null) router.replace("/auth");
  }, [token, router]);
  /*
   * 의존성에 token 과 router 를 적는 이유: 이 안에서 쓰는 바깥 값이 그 둘이다.
   * token 이 바뀌면(로그아웃) 다시 판단해야 하므로 반드시 들어가야 한다.
   */

  function handleLogout() {
    clearAccessToken();
    router.replace("/auth");
  }

  return (
    <div className="flex min-h-dvh flex-col">
      <header className="border-b border-subtle bg-surface">
        <div className="mx-auto flex w-full max-w-6xl items-center justify-between px-6 py-3">
          <Link href="/dashboard" className="text-base font-semibold">
            AllDap
          </Link>
          {/* 사용자 이름을 띄우려면 GET /api/auth/me 가 필요한데 아직 없다.
              지금은 로그아웃만 둔다 — 토큰을 지우고 /auth 로 보낸다. */}
          <button
            type="button"
            onClick={handleLogout}
            className="text-xs text-muted hover:text-foreground"
          >
            로그아웃
          </button>
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-8">
        {/* 토큰이 없으면 내용을 그리지 않는다 — 위로 이동하는 중이다 (위 "깜빡임" 주석 참고) */}
        {token === null ? <p className="text-sm text-muted">불러오는 중…</p> : children}
      </main>
    </div>
  );
}
