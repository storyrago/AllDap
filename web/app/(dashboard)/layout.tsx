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

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { clearAccessToken, getAccessToken } from "@/lib/api";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();

  /*
   * "아직 토큰을 확인하지 못했다" 상태.
   *
   * 왜 boolean 하나가 필요한가: 첫 렌더는 토큰을 읽기 <전>에 일어난다
   * (useEffect 는 렌더가 끝난 뒤 실행된다). 이 값이 없으면 그 찰나에
   * 대시보드 내용이 그려졌다가 사라져 화면이 번쩍인다.
   */
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    if (getAccessToken() === null) {
      router.replace("/auth");
      return; // 이동할 것이므로 checking 을 풀지 않는다 — 풀면 내용이 잠깐 보인다
    }
    setChecking(false);
  }, [router]);
  /*
   * 의존성 배열에 왜 router 가 들어갔나.
   *
   * useEffect 는 "이 안에서 쓰는 바깥 값이 바뀌면 다시 실행하라" 는 규칙이다.
   * 여기서 쓰는 바깥 값은 router 하나뿐이므로 그것만 적는다.
   * (getAccessToken 은 import 한 함수라 렌더마다 새로 만들어지지 않아 넣지 않는다)
   *
   * router 는 실제로는 거의 안 바뀌므로 이 effect 는 사실상 처음 한 번만 돈다.
   * 그렇다고 빈 배열 [] 로 두면 안 된다 — 쓰는 값을 적지 않는 습관이 붙으면
   * 나중에 "왜 값이 안 바뀌지" 하는 버그를 반드시 만든다. 규칙대로 적는다.
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
        {/* 토큰 확인 전에는 내용을 그리지 않는다 (위 "깜빡임" 주석 참고) */}
        {checking ? <p className="text-sm text-muted">불러오는 중…</p> : children}
      </main>
    </div>
  );
}
