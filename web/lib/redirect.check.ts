/**
 * safeRedirectPath 의 자체 점검. `npx tsx lib/redirect.check.ts` 로 돌린다.
 *
 * 프레임워크를 붙이지 않은 이유: 검사 대상이 순수 함수 하나고, 이 프로젝트에는
 * 프론트 테스트 러너가 아직 없다. 러너를 들이는 것보다 이 파일이 싸다.
 * 🔴 다만 <보안 경계>라 검사 없이 두지 않는다 — 여기가 뚫리면 피싱 경로가 열린다.
 */
import { DEFAULT_AFTER_AUTH, safeRedirectPath } from "./redirect";

const ORIGIN = "https://alldap.example";
let failed = 0;

function check(label: string, raw: string | null, expected: string) {
  const got = safeRedirectPath(raw, ORIGIN);
  const ok = got === expected;
  if (!ok) failed++;
  console.log(`  ${ok ? "✅" : "❌"} ${label}\n       ${JSON.stringify(raw)} → ${got}${ok ? "" : `  (기대: ${expected})`}`);
}

console.log("safeRedirectPath — 같은 사이트만 통과시키는가\n");

// ── 통과해야 하는 것 ────────────────────────────────────────────────
check("내부 경로", "/faq", "/faq");
check("쿼리·해시 유지", "/features?tab=a#b", "/features?tab=a#b");
check("같은 origin 의 절대 URL", `${ORIGIN}/pricing`, "/pricing");

// ── 막아야 하는 것 ──────────────────────────────────────────────────
check("외부 절대 URL", "https://evil.com", DEFAULT_AFTER_AUTH);
check("프로토콜 상대 URL", "//evil.com", DEFAULT_AFTER_AUTH);
check("역슬래시 변형", "/\\evil.com", DEFAULT_AFTER_AUTH);
// ⚠️ 이 케이스는 <통과가 정답이다>. 처음엔 막아야 한다고 적었다가 검사에 걸려 고쳤다.
//    스킴이 base 와 같으면 파서가 상대 참조로 보고 우리 사이트의 "/evil.com" 경로가 된다.
//    origin 이 우리 것이므로 외부로 나가지 않는다 — 그냥 404 가 날 뿐이다.
//    <문자열 모양>이 수상해 보인다고 막으면, 정작 위험한지 아닌지를 우리가 다시 판정하게 된다.
check("슬래시 하나짜리 변형 — 내부 경로로 정규화된다", "https:/evil.com", "/evil.com");
check("javascript: 스킴", "javascript:alert(1)", DEFAULT_AFTER_AUTH);
check("data: 스킴", "data:text/html,<script>1</script>", DEFAULT_AFTER_AUTH);
check("값 없음", null, DEFAULT_AFTER_AUTH);
check("빈 문자열", "", DEFAULT_AFTER_AUTH);
// 로그인 화면으로 되돌리면 무한 왕복처럼 보인다
check("로그인 화면 자기 자신", "/auth", DEFAULT_AFTER_AUTH);

console.log(failed === 0 ? "\nOK — 12가지 통과" : `\n🔴 ${failed}건 실패`);
if (failed) process.exit(1);
