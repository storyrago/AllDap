/**
 * resolvePlan 의 자체 점검. `npm run check` 가 돌린다.
 *
 * 재는 것은 하나다: <세 갈래가 뭉개지지 않는가.>
 *   null       서버 응답을 못 받았다 (새로고침하면 될 수도 있다)
 *   undefined  서버는 답했는데 우리가 모르는 요금제 id 다 (새로고침해도 그대로다)
 *   Plan       알아냈다
 * 🔴 이 저장소가 낸 버그가 전부 <원인이 다른 사실을 한 값으로 뭉갠 것>이다
 *    (AGENTS.md "낸 버그 5건"). 그 규칙을 적어둔 파일 안에서 다섯 번째가 났다.
 *    그래서 규칙을 글로 적는 대신 검사로 못박는다.
 */
import { PLANS, resolvePlan } from "./plans";

let failed = 0;
let total = 0;

function check(label: string, got: unknown, expected: unknown) {
  total++;
  const ok = JSON.stringify(got) === JSON.stringify(expected);
  if (!ok) failed++;
  console.log(`  ${ok ? "✅" : "❌"} ${label}${ok ? "" : `\n       받음: ${JSON.stringify(got)}  기대: ${JSON.stringify(expected)}`}`);
}

console.log("resolvePlan: 세 갈래가 뭉개지지 않는가\n");

check("못 불러옴은 null 이다", resolvePlan(null), null);
check("아는 요금제는 그 정의를 준다", resolvePlan(PLANS[0].id)?.id, PLANS[0].id);
check("모르는 id 는 undefined 다", resolvePlan("enterprise"), undefined);
// 위 둘을 각각 통과해도 <서로 같은 값>이면 화면은 구별하지 못한다. 그것까지 못박는다.
check("모르는 id 와 못 불러옴이 같은 값이 아니다", resolvePlan("enterprise") === resolvePlan(null), false);
// 🔴 `plan === null` 을 `!plan` 으로 쓰는 실수를 잡는 줄이다. 그러면 빈 문자열이
//    "모르는 id" 에서 "못 불러옴" 으로 <다시 뭉개진다>. 이 파일이 막으려는 그 부류다.
check("빈 문자열도 모르는 id 다", resolvePlan(""), undefined);

console.log(failed === 0 ? `\nOK: ${total}가지 통과` : `\n🔴 ${failed}건 실패`);
if (failed) process.exit(1);
