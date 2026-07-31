/**
 * 위젯 전용 레이아웃 (`/w/[publicKey]`).
 *
 * 이 layout 은 children 을 거의 그대로 내보낸다. 일부러 그렇다.
 *
 * 왜 굳이 라우트 그룹 `(widget)` 을 따로 만들었나:
 *   위젯은 고객사 사이트의 iframe 안에서 뜨는 공개 화면이다.
 *   관리자 헤더·좌측 네비가 같이 딸려 들어가면 안 된다.
 *   Next.js App Router 는 폴더 계층대로 layout 이 중첩되므로, 대시보드 layout 아래에
 *   두면 자동으로 상속된다. 그룹을 나누는 것이 이를 막는 정석적인 방법이다.
 *
 * 또 하나: 위젯은 로그인하지 않은 익명 사용자가 본다.
 *   여기서는 JWT 를 절대 쓰지 않고, public_key + Origin 검증 + rate limit 으로만 보호된다.
 *   (lib/api.ts 의 api.widget.* 는 auth: false 로 호출한다)
 */
export default function WidgetLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <div className="flex min-h-dvh flex-col">{children}</div>;
}
