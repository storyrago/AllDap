"use client";

/**
 * 루트 에러 경계. **우리 사용자가 보는 공개 화면**을 덮는다:
 * 랜딩(`app/page.tsx`)과 `(site)` 그룹(로그인·기능·요금제·FAQ·데모).
 *
 * ── 왜 그룹마다 경계를 따로 두는가 (지금 셋이다) ────────────────────────────
 * 에러 경계는 <가장 가까운 것>이 잡으므로, 나누는 기준은 **"무엇이 살아남기를 바라는가"**와
 * **"누가 이 화면을 보는가"** 다.
 *   `(dashboard)/error.tsx` : 우리 사용자. 관리자 헤더를 남겨 빠져나갈 길을 준다
 *   `(widget)/error.tsx`    : <고객사 사이트 방문자>. 링크도 내부 정보도 주지 않는다
 *   여기                     : 우리 사용자. 감쌀 공통 크롬이 없어 화면 전체를 쓴다
 * 하나로 합치면 어느 한쪽에 맞지 않는 안내가 나간다. 실제로 그랬다(아래 참고).
 *
 * ── 🔴 위젯을 여기서 떼어낸 이유 (PR #96 리뷰) ─────────────────────────────
 * 처음에는 이 파일이 `(widget)` 까지 덮었다. 그런데 그 화면은 <고객사 사이트의 iframe 안>이라
 * 아래 `오류 내용: ...` 이 **남의 사이트에 우리 예외 문구를 그리고**, "처음 화면으로" 링크가
 * **그 iframe 을 우리 랜딩으로 바꿔버린다.**
 * 당시 전용 경계를 안 만든 근거는 "iframe 밖에서는 제대로 안 떠서 깨뜨려 확인할 수 없다" 였는데
 * **그 근거가 틀렸다.** 그 페이지는 직접 열어도 렌더된다. 재보고 만들었다.
 * (자세한 것은 `app/(widget)/error.tsx` 주석)
 *
 * ── ⚠️ 이 파일은 증상을 가리는 것이지 원인을 고치는 게 아니다 ───────────────
 * 자세한 근거는 `app/(dashboard)/error.tsx` 상단 주석에 적었다. 요지는 같다:
 * 경계는 <언마운트 범위>를 정할 뿐이고, 예외를 낸 코드는 그대로 있다.
 *
 * ── ⚠️ 여기서 예외 문구를 보여주는 것은 <보는 사람이 우리 사용자>이기 때문이다 ──
 * 문의할 때 붙일 단서가 되므로 값어치가 있다. 이 판단은 **이 파일에만** 유효하다.
 * 같은 것을 위젯에서 하면 위 ①번 문제가 된다. 새 그룹에 경계를 만들 때 다시 물을 것:
 * **"이 화면을 보는 사람이 우리에게 문의할 수 있는 사람인가?"**
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
