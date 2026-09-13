/**
 * isValidId 의 자체 점검. `npx tsx lib/ids.check.ts` 로 돌린다(`npm run check` 가 포함한다).
 *
 * 왜 parseId 가 아니라 isValidId 를 재는가:
 *   parseId 는 실패하면 `notFound()` 를 부르는데 그건 Next 의 렌더 흐름 안에서만
 *   의미가 있어 여기서 돌릴 수가 없다. 그래서 <판단>만 순수 함수로 떼어뒀다.
 *   parseId 는 그 판단 위에 notFound() 한 줄을 얹은 것이 전부다.
 *
 * 🔴 검사 없이 두지 않는 이유:
 *   기본키가 BIGINT 가 된 뒤로 여기가 <URL 이 처음 걸러지는 자리>다.
 *   전에는 UUID 라 모양이 틀리면 서버가 걸렀지만 이제는 아니다.
 *   이 저장소는 "짜둔 검사가 아무 데서도 안 돌아서" 오픈 리다이렉트를 배포까지
 *   보낸 전례가 있다(AGENTS.md). 그래서 CI 에서 돈다.
 */
import { isValidId } from "./ids";

let failed = 0;
let total = 0;

function check(label: string, raw: string, expected: boolean) {
  total++;
  const got = isValidId(raw);
  const ok = got === expected;
  if (!ok) failed++;
  console.log(`  ${ok ? "✅" : "❌"} ${label}\n       ${JSON.stringify(raw)} → ${got}${ok ? "" : `  (기대: ${expected})`}`);
}

console.log("isValidId — URL 세그먼트를 id 로 받아도 되는가\n");

// ── 통과해야 하는 것 ────────────────────────────────────────────────
check("1 (IDENTITY 는 1부터다)", "1", true);
check("여러 자리", "12345", true);
check("안전 정수의 최대값", String(Number.MAX_SAFE_INTEGER), true);

// ── 막아야 하는 것 ──────────────────────────────────────────────────
// 전부 Number() 만 썼다면 <조용히 통과했을> 값들이다. 괄호 안이 Number() 의 결과다.
check("빈 문자열 (Number → 0)", "", false);
check("공백 낀 숫자 (Number → 1)", " 1 ", false);
check("소수 (Number → 1.5)", "1.5", false);
check("지수 표기 (Number → 1000)", "1e3", false);
check("16진수 (Number → 16)", "0x10", false);
check("음수", "-1", false);
check("0 (그런 id 는 없다)", "0", false);
check("0 으로 시작", "007", false);
check("숫자가 아님 (Number → NaN)", "abc", false);
check("UUID (옛 형식)", "628d2785-a128-486c-a1ac-556f19f06de3", false);
check("더하기 기호", "+1", false);
// 🔴 2^53 을 넘으면 number 로 정확히 담기지 않는다. 아래 값은 Number() 를 거치면
//    9007199254740992 가 되어 <다른 행>을 가리킨다. 모양만 보는 정규식으로는 못 막는다.
check("안전 정수 초과", "9007199254740993", false);
check("아주 긴 숫자", "1".repeat(40), false);

console.log(failed === 0 ? `\nOK: ${total}가지 통과` : `\n🔴 ${failed}건 실패`);
if (failed) process.exit(1);
