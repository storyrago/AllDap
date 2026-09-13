/**
 * JWT 를 <b>읽기만</b> 하는 순수 함수. 서명은 다루지 않는다.
 *
 * <p>`lib/api.ts` 에서 떼어낸 이유는 두 가지다.
 * ① base64url 패딩·타입 좁히기처럼 <b>혼자 틀릴 수 있는 로직</b>이라 검사를 붙이고 싶다.
 *    그런데 `api.ts` 는 `window` 와 `fetch` 를 쓰므로 Node 에서 그냥 부를 수가 없다.
 * ② 이 저장소가 이미 같은 모양을 쓴다: `redirect.ts` + `redirect.check.ts`,
 *    `plans.ts` + `plans.check.ts`. 새 규칙을 만들지 않고 그 결을 따랐다.
 *
 * <p>자체 점검: `lib/token.check.ts` (`npm run check` 로 CI 에서 돈다)
 */

/**
 * JWT 의 `exp`(만료 시각, <b>초</b> 단위)가 지났는가.
 *
 * <p>읽을 수 없는 토큰은 <b>만료된 것으로 본다</b>(true). 우리가 발급한 JWT 는 항상 `exp` 를
 * 담으므로(`JwtService`), 못 읽는다는 것은 우리 것이 아니거나 망가졌다는 뜻이다. 서버도 그런
 * 토큰을 401 로 거절하므로, 화면이 미리 "로그인 안 됨" 으로 보는 편이 대시보드를 그렸다가
 * 401 을 보여주는 것보다 낫다.
 *
 * <p>자체 점검: `lib/token.check.ts` (`npm run check` 로 CI 에서 돈다)
 */
export function isTokenExpired(token: string): boolean {
  /*
   * JWT 는 `header.payload.signature` 를 점으로 이은 것이고 각 조각이 base64url 이다.
   * 우리가 볼 것은 가운데(payload) 하나뿐이라 나머지는 건드리지 않는다.
   */
  const payload = token.split(".")[1];
  /*
   * ⚠️ 이 한 줄도 <없어도 결과는 같다>. 변이 시험으로 확인했다: 지워도 19건이 전부 통과한다.
   *    점이 없으면 payload 가 undefined 라 아래 `.replace` 가 TypeError 를 던지고,
   *    빈 문자열이면 JSON.parse 가 던져서, 어느 쪽이든 catch 가 받아 true 가 되기 때문이다.
   *    그런데도 남긴 이유는 padEnd 를 지운 것과 다르다: padEnd 는 <하는 일이 없었고>,
   *    이건 <같은 일을 더 읽히게 한다>. "토큰이 아니면 못 쓰는 것" 이라고 <말하는> 줄과,
   *    TypeError 가 우연히 catch 로 굴러떨어지는 것은 읽는 사람에게 다르다.
   */
  if (!payload) return true;

  try {
    /*
     * base64url 을 base64 로 되돌린다. 둘의 차이는 두 가지인데 <한 쪽만> 손대면 된다.
     *
     *   ① 글자가 둘 다르다 (`-_` 대 `+/`)  → 여기서 바꾼다. `atob` 는 base64url 을 모른다.
     *   ② 끝의 `=` 패딩을 뗀다           → 🔴 <안 채워도 된다.> 채우지 말 것.
     *
     * ②를 안 채우는 근거: `atob` 는 WHATWG 의 forgiving-base64 를 쓴다. 길이를 4로 나눈
     * 나머지가 1일 때만 실패하고, 2·3 이면 패딩 없이도 그대로 디코딩한다(실측 확인).
     * 처음에는 `padEnd` 로 채워뒀는데, 자체 점검에서 <그 줄을 지워도 17건이 전부 통과>했다.
     * 즉 검사로 존재를 정당화할 수 없는 줄이었다. 나머지가 1인 입력은 채워도 어차피 실패라
     * 아래 catch 가 받는다. 다시 넣고 싶어지면 이 문단을 먼저 읽을 것.
     */
    const padded = payload.replace(/-/g, "+").replace(/_/g, "/");

    /*
     * ⚠️ `atob` 는 바이트를 문자 하나씩 담은 문자열을 준다. 한글처럼 여러 바이트인 글자는
     *    여기서 깨진다. 우리 페이로드는 sub(사용자 id 숫자)·exp·iat 뿐이라 전부 ASCII 이므로 문제없다.
     *    나중에 이름 같은 것을 토큰에 담으면 TextDecoder 로 UTF-8 디코딩을 해야 한다.
     */
    const claims: unknown = JSON.parse(atob(padded));

    /*
     * `unknown` 으로 받아 좁혀 쓰는 이유: 이 값은 <바깥에서 온 것>이라 타입을 단언하면
     * 거짓말이 된다. localStorage 는 사용자가 직접 고칠 수 있어 무엇이든 들어올 수 있다.
     */
    if (typeof claims !== "object" || claims === null) return true;
    const exp = (claims as { exp?: unknown }).exp;
    if (typeof exp !== "number") return true;

    // exp 는 <초>, Date.now() 는 <밀리초>다. 1000 을 안 곱하면 1970년으로 읽혀 항상 만료가 된다.
    return exp * 1000 <= Date.now();
  } catch {
    // base64 가 아니거나 JSON 이 아니다. 우리가 만든 토큰이 아니므로 못 쓰는 것으로 본다.
    return true;
  }
}
