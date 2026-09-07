/**
 * 카드사 발급사 코드 → 카드 면에 쓸 브랜드 색.
 *
 * ── 🔴 왜 "그 카드의 디자인" 이 아니라 브랜드 색인가 ─────────────────────────
 * 토스가 빌링키를 발급하며 주는 카드 정보는 <발급사 코드 · 마스킹된 번호 · 신용/체크 ·
 * 개인/법인> 이 전부다(`TossBillingKeyResponse`). **어느 카드 <상품>인지는 알려주지 않는다.**
 * 신한 하나만 해도 상품이 수백 개인데 딥드림인지 미스터라이프인지 구별할 값이 응답에 없고,
 * 카드 이미지 URL 도 없다. 즉 실물 카드 디자인을 띄우려 해도 <어느 그림을 띄울지> 를
 * 우리가 알 수 없다 — 노력의 문제가 아니라 데이터가 없는 것이다.
 *
 * 그래서 우리가 정확히 알 수 있는 것 두 가지로 카드를 만든다:
 *   ① 발급사의 브랜드 색 (아래 표)
 *   ② 실물 카드의 <규격> — 비율 1.586:1 · 모서리 반경 · IC 칩 위치 (`components/CardFace.tsx`)
 *
 * ⚠️ 아래 색은 브랜드 <방향>을 잡은 근사값이지 공식 브랜드 가이드의 정확한 값이 아니다.
 *    로고도 넣지 않았다 — 상표이고, 기억으로 그리면 어설픈 짝퉁 마크가 된다.
 *    나중에 로고 파일을 정식으로 확보하면 CardFace 의 왼쪽 위(지금 이름이 있는 자리)에 얹으면 된다.
 *
 * ── 왜 이름이 아니라 <코드>로 키를 잡는가 ────────────────────────────────────
 * 백엔드가 코드→이름 변환을 책임진다는 규칙(AGENTS.md)은 <표시 문구>에 대한 것이고,
 * 색은 표시 문구가 아니라 스타일이라 프론트가 갖는 게 맞다. 다만 키를 이름("현대")으로 잡으면
 * 백엔드가 "현대카드"로 문구를 다듬는 순간 <모든 현대 카드가 조용히 회색이 된다.>
 * 코드("61")는 토스가 정한 값이라 우리 사정으로 바뀌지 않는다. 그래서 응답에 issuerCode 를 실었다.
 */

/** 카드 면 위 글자를 밝게 쓸지(어두운 카드) 어둡게 쓸지(밝은 카드). 실행 시 명도를 계산하지 않고 <미리 정한다>. */
export type CardInk = "light" | "dark";

export interface CardBrand {
  /** 카드 면 바탕색. CardFace 가 여기서 그라데이션을 만든다 */
  color: string;
  ink: CardInk;
}

/** 코드는 `api/.../service/CardIssuer.java` 의 것과 같다. 거기 없는 코드는 서버가 "카드" 로 내려준다. */
const BRANDS: Record<string, CardBrand> = {
  "11": { color: "#4f4b47", ink: "light" }, // 국민 (KB 그레이)
  "15": { color: "#fee500", ink: "dark" }, //  카카오뱅크
  "21": { color: "#008485", ink: "light" }, // 하나
  "24": { color: "#0064ff", ink: "light" }, // 토스뱅크
  "30": { color: "#00396b", ink: "light" }, // KDB산업
  "31": { color: "#e51e2a", ink: "light" }, // BC
  "33": { color: "#0067ac", ink: "light" }, // 우리BC
  "34": { color: "#0079c1", ink: "light" }, // 수협
  "35": { color: "#00539b", ink: "light" }, // 전북
  "36": { color: "#056dae", ink: "light" }, // 씨티
  "37": { color: "#e8340c", ink: "light" }, // 우체국예금보험
  "38": { color: "#00a0b0", ink: "light" }, // 새마을
  "39": { color: "#c8102e", ink: "light" }, // 저축은행중앙회
  "41": { color: "#0046ff", ink: "light" }, // 신한
  "42": { color: "#0067a3", ink: "light" }, // 제주
  "46": { color: "#005bac", ink: "light" }, // 광주
  "51": { color: "#1428a0", ink: "light" }, // 삼성
  "61": { color: "#141414", ink: "light" }, // 현대
  "62": { color: "#0068b7", ink: "light" }, // 신협
  "71": { color: "#da291c", ink: "light" }, // 롯데
  "91": { color: "#01a05e", ink: "light" }, // NH농협
  "3A": { color: "#4b5ffa", ink: "light" }, // 케이뱅크
  "3K": { color: "#00477d", ink: "light" }, // 기업BC
  W1: { color: "#0067ac", ink: "light" }, //  우리
};

/**
 * 모르는 발급사의 카드 면. 이 사이트의 따뜻한 배경(#eae0de)과 싸우지 않는 어두운 갈회색이다.
 * Tailwind 기본 팔레트의 gray-800 을 쓰지 않은 이유는 `globals.css` 의 상태색 주석과 같다 —
 * 그 계열은 파란기가 돌아 이 배경 위에서 겉돈다.
 */
const UNKNOWN: CardBrand = { color: "#4a4341", ink: "light" };

export function brandOf(issuerCode: string): CardBrand {
  return BRANDS[issuerCode] ?? UNKNOWN;
}
