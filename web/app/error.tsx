"use client";

/**
 * 루트 에러 경계. 대시보드를 <뺀> 나머지 전부를 덮는다:
 * 랜딩(`app/page.tsx`), 공개 페이지(`(site)`: 로그인·기능·요금제·FAQ·데모),
 * 그리고 위젯(`(widget)/w/[publicKey]`).
 *
 * ── 왜 `(dashboard)/error.tsx` 와 <둘 다> 두는가 ────────────────────────────
 * 에러 경계는 <가장 가까운 것>이 잡는다. 대시보드 안에서 난 예외는 대시보드 경계가
 * 잡으므로 이 파일까지 올라오지 않는다. 나눠 둔 이유는 **살아남는 것이 다르기 때문**이다:
 * 대시보드 경계는 관리자 헤더를 남겨 다른 화면으로 빠져나갈 길을 주는데,
 * 여기는 감쌀 공통 크롬이 애초에 없다(랜딩·위젯은 자기 헤더를 갖거나 크롬이 없다).
 * 그래서 문구도 링크도 다르다. 하나로 합치면 어느 한쪽에 맞지 않는 안내가 나간다.
 *
 * ── ⚠️ 이 파일은 증상을 가리는 것이지 원인을 고치는 게 아니다 ───────────────
 * 자세한 근거는 `app/(dashboard)/error.tsx` 상단 주석에 적었다. 요지는 같다:
 * 경계는 <언마운트 범위>를 정할 뿐이고, 예외를 낸 코드는 그대로 있다.
 *
 * ── 🔴 알고 남긴 한계: 위젯도 이 경계가 덮는다 ──────────────────────────────
 * `(widget)/w/[publicKey]` 는 <고객사 사이트의 iframe 안>에서 방문자가 보는 화면이다.
 * 거기서 이 화면이 뜨면 남의 사이트 안에 우리 문구가 그려지고, 아래 "처음 화면으로"
 * 링크는 **그 iframe 을 우리 랜딩으로 바꿔버린다.** 방문자에게는 뜬금없는 이동이다.
 * 그래도 지금 `(widget)/error.tsx` 를 따로 만들지 않은 이유:
 *   ① 이번 사고는 대시보드에서 났고, 위젯에서 같은 종류가 난 적은 없다.
 *   ② 위젯 화면은 iframe 안에서만 제대로 동작해(로더가 `postMessage` 로 설정을 준다)
 *      브라우저로 <실제로 깨뜨려 확인>할 수가 없다. 못 재보는 것을 지금 만들면
 *      "만들었는데 되는지는 모른다" 가 된다.
 * → 위젯에서 실제로 렌더 예외가 관측되면 그때 링크 없는 전용 경계를 만들 것.
 */

import Link from "next/link";

export default function RootError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  /*
   * `unstable_retry` 대신 `reset` 을 쓰는 근거는 `(dashboard)/error.tsx` 주석 참고.
   * (요약: 우리 데이터는 서버 페이로드가 아니라 클라이언트 useEffect 에서 오므로
   *  리마운트만으로 다시 가져와진다. 이점 없는 unstable_ API 를 운영에 들이지 않는다)
   */
  return (
    <main className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center px-6 py-16 text-center">
      <h1 className="text-lg font-semibold">화면을 그리지 못했습니다</h1>

      <p className="mt-3 text-sm text-muted">
        예상하지 못한 문제가 생겨 이 화면을 끝까지 그리지 못했습니다. 아래 [다시 시도] 를
        눌러주세요.
      </p>
      {/*
        재시도로 안 풀리는 경우까지 안내한다. 근거는 (dashboard)/error.tsx 의 같은 주석 참고.
        "일시적인 오류입니다" 로 끝내면, 원인이 코드에 있을 때 사용자를 무한 재시도로 보낸다.
      */}
      <p className="mt-1 text-sm text-muted">
        다시 시도해도 같은 화면이면 일시적인 장애가 아니라 이 화면의 문제입니다. 처음 화면으로
        돌아가거나, 아래 오류 정보를 첨부해 문의해주세요.
      </p>

      <div className="mt-6 flex items-center justify-center gap-2">
        <button
          type="button"
          onClick={reset}
          className="rounded-md bg-foreground px-4 py-2 text-sm font-medium text-surface"
        >
          다시 시도
        </button>
        <Link
          href="/"
          className="rounded-md border border-subtle px-4 py-2 text-sm font-medium"
        >
          처음 화면으로
        </Link>
      </div>

      {/* 라벨을 digest 와 message 로 가르는 근거는 (dashboard)/error.tsx 의 같은 자리 주석 참고 */}
      {error.digest ? (
        <p className="mt-6 font-mono text-xs text-muted">오류 번호: {error.digest}</p>
      ) : error.message ? (
        <p className="mt-6 font-mono text-xs text-muted">오류 내용: {error.message}</p>
      ) : null}
    </main>
  );
}
