"use client";

/**
 * 최후의 경계. **루트 레이아웃(`app/layout.tsx`) 자체가 죽었을 때만** 쓰인다.
 *
 * ── 언제 이게 뜨는가 ────────────────────────────────────────────────────────
 * `error.tsx` 는 <같은 세그먼트의 layout 을 감싸지 않는다>(Next 문서). 즉 루트
 * 레이아웃이 렌더 중 터지면 `app/error.tsx` 는 그릴 자리 자체가 없다. 그때 이 파일이
 * **루트 레이아웃을 대신해서** 문서 전체를 그린다.
 * 우리 루트 레이아웃은 폰트 로딩·`metadataBase`·`ViewTransition` 정도만 하므로 여기까지
 * 올 일은 드물다. 드물다고 안 두면, 그 드문 날에 사용자가 보는 것이 이번 사고 때와 똑같은
 * 브라우저 기본 에러 화면이다. **이 파일의 값어치는 그 하루에 있다.**
 *
 * ── 🔴 `<html>` 과 `<body>` 를 직접 그리는 이유 ─────────────────────────────
 * 루트 레이아웃을 <대체>하는 파일이라, 그 둘을 여기서 안 그리면 아무도 안 그린다.
 * Next 문서가 명시적으로 요구한다: *"Global error UI must define its own `<html>`
 * and `<body>` tags"*.
 *
 * ── 🔴 Tailwind 클래스가 아니라 인라인 style 인 이유 ────────────────────────
 * 같은 문서: *"`global-error` and the built-in 500 page render their own document
 * and do **not** include your global styles"*. 즉 `app/globals.css` 가 안 실리고,
 * 그 파일이 정의하는 `--foreground` 같은 토큰도 없다. 여기서 `text-muted` 를 쓰면
 * **아무 스타일도 안 먹은 맨 HTML** 이 뜬다(테스트하기도 어려운 자리라 조용히 그렇게 된다).
 * 그래서 토큰 값을 글자로 박았다. `globals.css` 를 고치면 여기는 따라오지 않는다는 뜻이라,
 * 색을 바꾸는 날 이 파일도 같이 봐야 한다. 그 대가를 알고 택했다.
 * (대안인 `import "./globals.css"` 는 Tailwind 전체를 이 마지막 화면에 끌어오는데,
 *  루트가 이미 죽은 상황에서 의존성을 늘리는 것이라 더 나쁘다)
 *
 * ── ⚠️ 원인을 고치는 파일이 아니다 ─────────────────────────────────────────
 * `app/(dashboard)/error.tsx` 상단 주석과 같다. 경계는 언마운트 범위를 정할 뿐이다.
 */

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    /*
     * `lang="ko"` 는 루트 레이아웃에서 그대로 가져왔다. 이 파일이 그 자리를 대신하므로
     * 여기서 안 적으면 이 화면만 언어가 빠진다(스크린리더가 한국어를 영어로 읽는다).
     */
    <html lang="ko">
      <body
        style={{
          margin: 0,
          minHeight: "100dvh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: "24px",
          // globals.css 의 --background / --foreground / --muted 값을 글자로 옮겨 적은 것.
          backgroundColor: "#eae0de",
          color: "#171514",
          // 폰트도 못 실린다(next/font 는 루트 레이아웃이 붙인다). OS 기본 스택으로 떨어진다.
          fontFamily:
            "-apple-system, BlinkMacSystemFont, 'Apple SD Gothic Neo', 'Malgun Gothic', 'Noto Sans KR', system-ui, sans-serif",
        }}
      >
        {/*
          metadata export 는 클라이언트 컴포넌트에서 못 쓴다(Next 문서). 대신 React 19 의
          <title> 을 그대로 쓴다. 안 적으면 탭 제목이 주소로 남는다.
        */}
        <title>AllDap</title>

        <main style={{ maxWidth: "28rem", textAlign: "center" }}>
          <h1 style={{ fontSize: "1.125rem", fontWeight: 600, margin: 0 }}>
            화면을 불러오지 못했습니다
          </h1>

          <p style={{ marginTop: "12px", fontSize: "0.875rem", color: "#7c716e" }}>
            페이지를 그리는 중에 문제가 생겼습니다. 아래 [다시 시도] 를 눌러주세요.
          </p>
          {/* 재시도로 안 풀리는 경우까지 적는 이유는 app/error.tsx 의 같은 주석 참고 */}
          <p style={{ marginTop: "4px", fontSize: "0.875rem", color: "#7c716e" }}>
            다시 시도해도 같은 화면이면 일시적인 장애가 아닙니다. 브라우저를 새로고침해도
            그대로라면 아래 오류 정보를 첨부해 문의해주세요.
          </p>

          <button
            type="button"
            onClick={reset}
            style={{
              marginTop: "24px",
              border: "none",
              borderRadius: "6px",
              backgroundColor: "#171514",
              color: "#ffffff",
              padding: "10px 18px",
              fontSize: "0.875rem",
              fontWeight: 500,
              cursor: "pointer",
              // 버튼은 폰트를 상속하지 않는 요소라(브라우저 기본값) 여기서 다시 지정한다.
              fontFamily: "inherit",
            }}
          >
            다시 시도
          </button>

          {/*
            여기에는 <Link> 를 두지 않는다. 루트 레이아웃이 죽은 상태라 라우터로 이동해도
            같은 레이아웃을 다시 그리다 또 죽을 수 있다. 이동이 필요하면 브라우저 새로고침이
            확실한 방법이고, 그건 위 문구가 안내한다.
          */}

          {/* 라벨을 digest 와 message 로 가르는 근거는 (dashboard)/error.tsx 의 같은 자리 주석 참고 */}
          {(error.digest ?? error.message) ? (
            <p
              style={{
                marginTop: "24px",
                fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
                fontSize: "0.75rem",
                color: "#7c716e",
              }}
            >
              {error.digest ? `오류 번호: ${error.digest}` : `오류 내용: ${error.message}`}
            </p>
          ) : null}
        </main>
      </body>
    </html>
  );
}
