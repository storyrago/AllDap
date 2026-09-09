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
    //
    // ⚠️ `=== null` 이지 `!token` 이 아니다. undefined 는 "아직 못 읽었다"(하이드레이션 전)이고
    //    null 이 "확실히 없다"(비로그인)다. 여기서 undefined 까지 튕기면
    //    <로그인한 채 새로고침해도 /auth 로 쫓겨난다> — 실제로 났던 버그다.
    //    (getAccessTokenServerSnapshot 주석 참고)
    //
    // 🔴 <만료된 토큰도 여기서 null 이다.> getAccessToken 이 기한을 보고 걸러내기 때문이고,
    //    이건 부수 효과가 아니라 <의도한 동작 변경>이다(2026-09-09).
    //    그전에는 만료 토큰으로도 이 화면이 그려졌고, 모든 API 호출이 401 로 떨어져
    //    화면마다 오류만 뜬 채 <다시 로그인할 길이 로그아웃 버튼밖에> 없었다.
    //    지금은 로그인 화면으로 보낸다. 사용자가 어차피 해야 할 일이 그것이다.
    //    ⚠️ `/auth` 는 이 값을 같은 함수로 읽으므로 만료 토큰을 "로그인됨" 으로 보지 않는다.
    //       즉 되돌려 보내지 않는다 = 왕복 루프가 생기지 않는다. (직접 확인함)
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
          {/*
            🔴 로고는 `/dashboard` 가 아니라 <랜딩>으로 간다 (2026-09-08).
               사용자가 봇 목록에서 로고를 눌렀는데 아무 일도 안 일어나 겪은 문제다 —
               이미 `/dashboard` 에 있으니 제자리 링크였다. 웹에서 워드마크는 <사이트의
               처음 화면>으로 가는 것이 보편 관례이고, 공개 페이지 헤더(`(site)/layout.tsx`)의
               같은 로고가 이미 `/` 로 간다. 두 헤더가 같은 글자로 다른 곳에 가면 안 된다.

               ⚠️ 대신 <봇 목록으로 돌아가는 길을 새로 내야 했다.> 이 로고가 그 유일한
                  길이었다(`BotNav` 에는 목록 링크가 없다). 아래 "봇 목록" 이 그것이다 —
                  로고를 옮기기만 하고 이 링크를 안 만들면 봇 상세에 <갇힌다.>
          */}
          <Link href="/" className="text-base font-semibold">
            AllDap
          </Link>
          {/* 사용자 이름을 띄우려면 GET /api/auth/me 가 필요한데 아직 없다.
              지금은 계정 메뉴 자리에 소개·마이페이지·로그아웃 셋만 둔다.

              공개 페이지로 돌아갈 길은 <로고>가 맡는다(2026-09-08 에 "소개" 링크에서 옮겼다).
              랜딩에 "기능" 메뉴가 있고 기능 페이지 상단에서 요금제·FAQ 로 이어지므로
              링크 하나면 공개 페이지 전부에 닿는다.
              반대 방향(마케팅 헤더 → 대시보드)은 components/AuthLink.tsx 가 맡고,
              공개 페이지의 CTA 들은 `/auth` 가 스스로 로그인 여부를 보고 되돌려보낸다.

              마이페이지가 <봇 화면이 아니라 헤더>에 있는 이유: 결제도 요금제도 대상이 계정이라
              봇을 여러 개 만들어도 카드와 요금제는 계정 하나에 붙는다. 봇 하위에 두면
              "봇마다 따로인가?" 라는 잘못된 인상을 준다. 사용량 카드가 /dashboard 에 있는 것과 같은 판단이다.
              ⚠️ 2026-09-08 에 /billing 을 /account 로 옮겼다. 옛 주소에는 리다이렉트만 남아 있다. */}
          <div className="flex items-center gap-4">
            {/* 🔴 "소개"(→ `/`) 자리를 "봇 목록"(→ `/dashboard`)이 대신한다. 로고가 랜딩을
                   맡았으므로 소개는 같은 곳으로 가는 두 번째 링크가 되어 지웠고, 대신 로고가
                   내려놓은 <봇 목록> 을 여기서 받는다. 링크 개수는 그대로다. */}
            <Link href="/dashboard" className="text-xs text-muted hover:text-foreground">
              봇 목록
            </Link>
            <Link
              href="/account"
              className="text-xs text-muted hover:text-foreground"
            >
              마이페이지
            </Link>
            <button
              type="button"
              onClick={handleLogout}
              className="text-xs text-muted hover:text-foreground"
            >
              로그아웃
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-8">
        {/* 토큰을 확인하기 전(undefined)과 없을 때(null) 모두 내용을 그리지 않는다.
            전자는 읽는 중이고 후자는 위로 이동하는 중이다 (위 "깜빡임" 주석 참고) */}
        {token ? children : <p className="text-sm text-muted">불러오는 중…</p>}
      </main>
    </div>
  );
}
