/**
 * isTokenExpired 의 자체 점검. `npx tsx lib/token.check.ts` 로 돌린다(`npm run check` 에 묶여 있다).
 *
 * 프레임워크를 붙이지 않은 이유는 `redirect.check.ts` 와 같다: 검사 대상이 순수 함수 하나고,
 * 이 프로젝트에 프론트 테스트 러너가 아직 없다. 러너를 들이는 것보다 이 파일이 싸다.
 *
 * 🔴 검사 없이 두지 않는 이유: 이 함수가 <틀리는 방향>이 둘 다 사용자에게 보인다.
 *    너무 헐거우면 만료 토큰으로 대시보드에 들어가 401 을 보고,
 *    너무 빡빡하면 <멀쩡히 로그인한 사람이 튕긴다>. 후자가 훨씬 나쁘다.
 *    그리고 base64url 패딩처럼 조용히 틀리기 좋은 대목이 있다.
 */
import { isTokenExpired } from "./token";

let failed = 0;
let total = 0;

function check(label: string, token: string, expected: boolean) {
  total++;
  const got = isTokenExpired(token);
  const ok = got === expected;
  if (!ok) failed++;
  console.log(
    `  ${ok ? "✅" : "❌"} ${label}\n       → ${got}${ok ? "" : `  (기대: ${expected})`}`,
  );
}

/**
 * 테스트용 JWT 를 만든다. <b>서명은 아무 문자열이나 넣는다</b>: 검사 대상이 `exp` 를
 * 읽는 부분뿐이고, 서명 검증은 애초에 프론트가 하지 않기 때문이다(`token.ts` 주석 참고).
 *
 * ⚠️ `Buffer.toString("base64url")` 을 쓴다. 운영 코드가 다루는 것이 <base64url> 이라
 *    평범한 base64 로 만들면 `-` `_` 와 패딩 없는 입력을 <아예 안 겪는> 검사가 된다.
 *    즉 실제로 틀릴 수 있는 자리를 비껴가게 된다.
 */
function makeToken(payload: object): string {
  const head = Buffer.from(JSON.stringify({ alg: "HS256", typ: "JWT" })).toString("base64url");
  const body = Buffer.from(JSON.stringify(payload)).toString("base64url");
  return `${head}.${body}.fake-signature`;
}

const NOW_SEC = Math.floor(Date.now() / 1000);

console.log("isTokenExpired: 쓸 수 있는 토큰과 아닌 것을 가르는가\n");

// ── 아직 쓸 수 있는 것 (false) ──────────────────────────────────────
check("한 시간 뒤 만료", makeToken({ sub: "u1", exp: NOW_SEC + 3600 }), false);
check("우리 토큰과 같은 모양(24시간 TTL)", makeToken({ sub: "u1", iat: NOW_SEC, exp: NOW_SEC + 86400 }), false);
// 페이로드 길이를 하나씩 늘려 base64 길이의 나머지(0·2·3)를 전부 지나가게 한다.
// ⚠️ 이 케이스들은 <패딩 로직을 지켜주지 못한다>. 변이 시험으로 확인했다:
//    padEnd 를 통째로 지워도 17건이 전부 통과한다(atob 이 패딩 없이도 디코딩하기 때문).
//    그래서 그 줄을 지웠다(`token.ts` 주석 참고). 이 케이스들은 남긴다 -
//    "길이에 상관없이 읽힌다" 는 것 자체는 여전히 지킬 값어치가 있다.
for (const pad of ["a", "aa", "aaa", "aaaa"]) {
  check(`길이 경우의 수 (sub 길이 ${pad.length})`, makeToken({ sub: pad, exp: NOW_SEC + 3600 }), false);
}
// 🔴 base64url 전용 글자(`-` `_`)가 <실제로 들어있는> 토큰. 이게 없으면 운영 코드의
//    replace 두 줄을 지워도 검사가 통과한다(평범한 ASCII 페이로드에서는 그 글자가 거의 안 나온다).
//    아래 두 sub 는 그 글자가 나오도록 고른 값이다: ">>" → `-`, "??" → `_`.
check('base64url 의 "-" 가 들어있는 토큰', makeToken({ sub: ">>", exp: NOW_SEC + 3600 }), false);
check('base64url 의 "_" 가 들어있는 토큰', makeToken({ sub: "??", exp: NOW_SEC + 3600 }), false);

// ── 못 쓰는 것 (true) ───────────────────────────────────────────────
check("한 시간 전에 만료", makeToken({ sub: "u1", exp: NOW_SEC - 3600 }), true);
// 경계는 <이미 지난 것>으로 본다. 그 1초를 살려줄 이유가 없고, 서버도 곧 거절한다.
check("정확히 지금 만료", makeToken({ sub: "u1", exp: NOW_SEC }), true);
check("exp 가 아예 없다", makeToken({ sub: "u1" }), true);
// 🔴 초와 밀리초를 헷갈리면 여기가 잡는다. exp 를 밀리초로 넣으면 아주 먼 미래가 되므로
//    "안 만료" 로 나와야 정상이다. 반대로 운영 코드에서 1000 을 안 곱하면 <모든 토큰이
//    만료>로 보여 위쪽 케이스들이 먼저 깨진다. 양쪽에서 조인다.
check("exp 가 밀리초로 들어온 경우(먼 미래로 읽힌다)", makeToken({ sub: "u1", exp: NOW_SEC * 1000 }), false);
check("exp 가 숫자가 아니다", makeToken({ sub: "u1", exp: "나중에" }), true);
check("페이로드가 객체가 아니다", makeToken([1, 2, 3] as unknown as object), true);
check("점이 없다(JWT 가 아니다)", "그냥-문자열", true);
check("페이로드 자리가 비었다", "aaa..bbb", true);
check("페이로드가 base64 가 아니다", "aaa.!!!not-base64!!!.bbb", true);
check("페이로드가 JSON 이 아니다", `aaa.${Buffer.from("hello").toString("base64url")}.bbb`, true);
check("빈 문자열", "", true);

console.log(`\n${failed === 0 ? "✅ 전부 통과" : `❌ ${failed}건 실패`} (${total - failed}/${total})`);
process.exit(failed === 0 ? 0 : 1);
