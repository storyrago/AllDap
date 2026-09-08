/**
 * 로그인·가입 뒤 돌아갈 경로를 <안전하게> 고른다.
 *
 * 🔴 이 파일이 있는 이유는 <오픈 리다이렉트> 때문이다.
 *    `?next=` 를 그대로 믿고 이동하면 공격자가 이런 링크를 뿌릴 수 있다:
 *        https://우리도메인/auth?next=https://피싱사이트
 *    사용자는 <우리 도메인에서> 로그인했는데 곧바로 남의 사이트로 튕겨 나간다.
 *    주소창이 우리 도메인이었으므로 사용자는 그 사이트를 우리 것으로 믿는다.
 *
 * ⚠️ 문자열 검사로 막으려다 빠뜨리기 쉬운 것들:
 *      "//evil.com"    프로토콜 상대 URL — 브라우저가 https://evil.com 으로 간다
 *      "/\\evil.com"   일부 브라우저가 위와 같게 해석한다
 *      "https:/evil.com"  슬래시 하나짜리 변형
 *    그래서 직접 파싱하지 않고 <브라우저의 URL 파서에게 판정을 맡긴다.>
 *    우리가 규칙을 나열하는 것보다 파서가 아는 게 많다.
 */

/** 로그인 후 갈 곳을 못 정했을 때의 기본값. */
export const DEFAULT_AFTER_AUTH = "/dashboard";

/**
 * @param raw    `?next=` 로 받은 값 (신뢰할 수 없는 입력)
 * @param origin 현재 사이트의 origin. 브라우저에서는 `window.location.origin`
 * @returns 같은 사이트 안의 경로. 조금이라도 수상하면 기본값으로 되돌린다.
 */
export function safeRedirectPath(raw: string | null, origin: string): string {
  if (!raw) return DEFAULT_AFTER_AUTH;

  let url: URL;
  try {
    // 두 번째 인자(base)가 있으면 상대 경로도 절대 URL 로 해석된다.
    // "https://evil.com" 처럼 절대 URL 이면 base 를 무시하고 그쪽 origin 이 된다 — 그걸 아래에서 잡는다.
    url = new URL(raw, origin);
  } catch {
    return DEFAULT_AFTER_AUTH;
  }

  // 🔴 판정은 이 한 줄이다. 파싱 결과의 origin 이 우리와 다르면 <어떤 모양이었든> 외부다.
  if (url.origin !== origin) return DEFAULT_AFTER_AUTH;

  // 로그인 화면으로 되돌리지 않는다 — 이미 로그인한 사람에게 의미가 없다.
  if (url.pathname === "/auth") return DEFAULT_AFTER_AUTH;

  // pathname 부터 다시 조립한다. 원본 문자열을 그대로 쓰면 위에서 정규화한 것이 무의미해진다.
  return url.pathname + url.search + url.hash;
}
