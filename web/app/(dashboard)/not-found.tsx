import Link from "next/link";

/**
 * 관리자 화면 그룹의 404. 현재 이 그룹에서 `notFound()` 를 부르는 곳은
 * `components/BotName.tsx` 하나이므로 문구도 <없는 봇> 기준으로 썼다.
 *
 * ── 🔴 왜 `bot/[botId]/` 안이 아니라 여기인가 (실측으로 알아냈다) ──────────
 * 처음에 `app/(dashboard)/bot/[botId]/not-found.tsx` 에 뒀더니
 * **Next.js 기본 404("This page could not be found.")가 떴다.**
 *
 * 이유는 공식 문서에 있다 — *"`not-found.js` renders between `loading.js` and
 * `page.js`"*. 즉 not-found 는 <page 자리>에 그려지고 **layout 안쪽**이다.
 * 그런데 `notFound()` 를 던지는 `BotName` 은 `bot/[botId]/layout.tsx` 에서 렌더된다.
 * **그 layout 자신이 죽었으니 안쪽 not-found 를 그릴 자리가 없다** —
 * 그래서 한 단계 위로 올라가 버린다.
 *
 * → 던지는 곳이 layout 이면 not-found 는 <그 위 세그먼트>에 있어야 한다.
 *   여기(`(dashboard)`)에 두면 인증 가드와 헤더는 그대로 두른 채 404 만 갈아끼운다.
 *
 * ⚠️ lint·tsc 로는 안 잡히는 부류다. 404 가 <뜨긴 뜨는데> 우리 화면이 아니었고,
 *    브라우저로 열어보고서야 드러났다.
 *
 * ── 🔴 문구가 "없거나 권한이 없다" 를 구분하지 않는 이유 ────────────────────
 * 서버가 <남의 봇에도 404 를 준다>(AGENTS.md 봇 소유권 검사).
 * 403 을 주면 "그 봇은 존재한다"를 알려주는 셈이라, 무작위 UUID 를 던져
 * 403 만 골라내면 남의 봇 존재 여부를 훑을 수 있기 때문이다.
 * 그 설계를 화면이 깨뜨리면 안 된다 — 여기서 "권한이 없습니다" 라고 쓰면
 * 서버가 감춘 사실을 화면이 알려주게 된다. **둘을 같은 문구로 덮는 것이 의도다.**
 */
export default function DashboardNotFound() {
  return (
    <div className="rounded-lg border border-subtle bg-surface px-6 py-12 text-center">
      <h2 className="text-sm font-semibold">이 봇을 찾을 수 없습니다</h2>
      <p className="mt-2 text-sm text-muted">
        주소가 잘못되었거나 이미 삭제된 봇입니다. 내 봇 목록에서 다시 선택해주세요.
      </p>
      <Link
        href="/dashboard"
        className="mt-5 inline-block rounded-md bg-foreground px-4 py-2 text-sm font-medium text-surface"
      >
        내 봇 목록으로
      </Link>
    </div>
  );
}
