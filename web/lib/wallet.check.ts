/**
 * walletView 의 자체 점검. `npm run check` 가 돌린다.
 *
 * 왜 이 파일이 있나: 2026-09-08 코드 리뷰에서 나온 두 버그가 전부 <분기 판단>이었다.
 * 기본 카드가 없으면 카드가 통째로 안 보였고, 2번째 카드는 닫힌 서랍에 숨었다.
 * 마크업이 아니라 "어떤 상태에서 무엇을 그릴지" 가 틀린 것이라 렌더러 없이 잴 수 있다.
 * 🔴 브라우저로만 확인하면 CI 가 아무것도 지키지 않는다. 이 저장소는 이미
 *    "짜둔 검사가 안 돌아서" 오픈 리다이렉트를 배포까지 보냈다.
 */
import type { BillingCard } from "./types";
import { MAX_METHODS, walletView } from "./wallet";

let failed = 0;
let total = 0;

function card(id: string, isDefault: boolean): BillingCard {
  return {
    id,
    issuerCode: "61",
    issuerName: "현대",
    cardNumberMasked: "43301234****123*",
    registeredAt: "2026-09-08T00:00:00Z",
    isDefault,
  };
}

function check(label: string, got: unknown, expected: unknown) {
  total++;
  const ok = JSON.stringify(got) === JSON.stringify(expected);
  if (!ok) failed++;
  console.log(`  ${ok ? "✅" : "❌"} ${label}${ok ? "" : `\n       받음: ${JSON.stringify(got)}  기대: ${JSON.stringify(expected)}`}`);
}

console.log("walletView: 카드 상태별로 무엇을 그리는가\n");

// ── 정상 상태 ───────────────────────────────────────────────────────
{
  const v = walletView([], null);
  check("0장: 서랍을 안 그린다", v.showDrawer, false);
  check("0장: 청구 카드가 없다", v.billed, undefined);
  check("0장: 경고하지 않는다", v.warnNoDefault, false);
  check("0장: 상한이 아니다", v.full, false);
}
{
  const a = card("a", true);
  const v = walletView([a], null);
  check("1장: 그 카드가 청구 카드다", v.billed?.id, "a");
  check("1장: 서랍은 비어 있다", v.others, []);
  check("1장: 서랍은 닫혀 있다", v.drawerOpen, false);
}
{
  const [a, b] = [card("a", true), card("b", false)];
  const v = walletView([a, b], null);
  check("2장: 청구 카드는 서랍에 없다", v.others.map((c) => c.id), ["b"]);
  check("2장: 서랍은 닫혀 있다", v.drawerOpen, false);
}
{
  const v = walletView([card("a", true), card("b", false), card("c", false), card("d", false), card("e", false)], null);
  check(`${MAX_METHODS}장: 상한에 닿았다`, v.full, true);
}

// ── 🔴 리뷰에서 나온 버그 두 개 ─────────────────────────────────────
// B-3: 기본 카드가 없는데 카드는 있는 상태. 서버 불변식이 깨진 것이고
//      (V7 인덱스는 "기본 1장 이하" 만 보장한다) 전에는 이때 목록이
//      통째로 안 그려져 사용자가 자기 카드를 보지도 지우지도 못했다.
{
  const [a, b] = [card("a", false), card("b", false)];
  const v = walletView([a, b], null);
  check("기본 없음: 서랍을 그린다", v.showDrawer, true);
  check("기본 없음: 두 장 다 서랍에 있다", v.others.map((c) => c.id), ["a", "b"]);
  check("기본 없음: 경고한다", v.warnNoDefault, true);
  check("기본 없음: 서랍을 열어둔다", v.drawerOpen, true);
  check("기본 없음: 청구 카드가 없다", v.billed, undefined);
}
{
  const v = walletView([card("a", false), card("b", false), card("c", false), card("d", false), card("e", false)], null);
  check("기본 없음 + 상한: full 가드가 살아 있다", v.full, true);
}

// B-5: 방금 추가한 카드는 첫 장이 아니면 전부 서랍 행이라,
//      서랍이 닫혀 있으면 등록에 성공해도 화면에 아무 변화가 없다.
{
  const v = walletView([card("a", true), card("b", false)], "b");
  check("방금 추가: 서랍을 열어둔다", v.drawerOpen, true);
}
{
  const v = walletView([card("a", true)], "a");
  check("방금 추가한 것이 청구 카드면 서랍을 억지로 열지 않는다", v.drawerOpen, false);
}

console.log(failed === 0 ? `\nOK: ${total}가지 통과` : `\n🔴 ${failed}건 실패`);
if (failed) process.exit(1);
