/**
 * 등록된 결제 수단을 <실물 카드 모양>으로 그린다.
 *
 * ── 왜 "use client" 가 없는가 ────────────────────────────────────────────────
 * 상태도 이벤트도 없는 순수 표시용이라 서버 컴포넌트로 둔다. 부모(`/account`)는 클라이언트
 * 컴포넌트지만, 클라이언트 컴포넌트가 렌더하는 자식은 <자동으로 클라이언트 번들에 들어간다> —
 * 즉 여기에 "use client" 를 또 적어도 얻는 게 없고, 없으면 나중에 서버 컴포넌트에서도
 * 그대로 쓸 수 있다. `components/Evidence.tsx` 와 같은 판단이다.
 *
 * ── 🔴 왜 카드사 <로고>도 <실제 카드 디자인>도 없는가 ────────────────────────
 * 토스가 빌링키를 발급하며 주는 값은 발급사 코드·마스킹 번호·신용/체크·개인/법인이 전부다.
 * **어느 카드 <상품>인지를 알려주지 않는다** — 신한 하나만 해도 상품이 수백 개인데
 * 딥드림인지 미스터라이프인지 구별할 값이 없고 이미지 URL 도 없다. 즉 진짜 카드 그림을
 * 띄우려 해도 <어느 그림인지> 를 우리가 알 수 없다. 데이터가 없는 것이지 노력의 문제가 아니다.
 * 로고 역시 상표라 기억으로 그리면 어설픈 짝퉁 마크가 된다.
 *
 * 그래서 <우리가 정확히 아는 것>으로만 만든다:
 *   ① 발급사 브랜드 색 (`lib/cardBrand.ts`)
 *   ② 실물 카드의 규격 — ISO/IEC 7810 ID-1: 85.60 × 53.98mm = 가로세로 <1.586:1>,
 *      모서리 반경, IC 칩의 위치. 이건 규격이라 정확히 그릴 수 있다.
 * 로고 파일을 정식으로 확보하면 아래 "발급사 이름" 자리에 얹으면 된다 — 실물 카드도 거기 넣는다.
 */

import { brandOf } from "@/lib/cardBrand";
import type { BillingCard } from "@/lib/types";

export function CardFace({ card }: { card: BillingCard }) {
  const brand = brandOf(card.issuerCode);
  /*
   * 실물 카드는 단색이 거의 없다. 브랜드 색에서 어두운 쪽으로 살짝 기울인 그라데이션을 준다.
   * color-mix() 를 쓰면 카드사마다 어두운 색을 따로 정해둘 필요가 없다 — 색이 24개면
   * 손으로 짝을 맞춘 값도 24쌍이 되고, 하나가 어긋나도 아무도 모른다.
   * oklab 으로 섞는 이유: sRGB 로 검정과 섞으면 채도가 먼저 죽어 탁해진다.
   */
  const face = `linear-gradient(145deg, ${brand.color}, color-mix(in oklab, ${brand.color} 74%, #000))`;
  const light = brand.ink === "light";

  return (
    <div
      /* aspect-[1.586] 이 이 컴포넌트의 핵심이다 — 이 비율이 아니면 무엇을 그려도 카드로 안 보인다. */
      className="relative aspect-[1.586] w-full overflow-hidden rounded-xl shadow-[0_6px_20px_rgba(74,50,46,0.22)]"
      style={{ background: face, color: light ? "#fff" : "#171514" }}
    >
      {/* 카드 면의 광택. 실물 카드는 평평한 판이 아니라 빛을 받는 면이라, 이 한 겹이 없으면
          "색칠한 사각형" 으로 보인다. 흰색 낮은 투명도라 어떤 브랜드 색 위에서도 같은 방향으로 작동한다. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "linear-gradient(115deg, rgba(255,255,255,0.16) 0%, rgba(255,255,255,0) 42%, rgba(0,0,0,0.10) 100%)",
        }}
      />

      <div className="relative flex h-full flex-col justify-between p-[6%]">
        <div className="flex items-start justify-between">
          {/* 발급사 이름 — 실물 카드도 여기에 넣는다. 로고 파일을 확보하면 이 자리를 대체한다. */}
          <span className="text-[0.95rem] font-semibold tracking-[-0.01em]">{card.issuerName}</span>
          <Contactless dim={light ? 0.72 : 0.5} />
        </div>

        <Chip />

        {/*
          번호는 실물 카드처럼 <넓은 자간의 등폭>이다. tabular 숫자가 아니면 마스킹 별표와 숫자의
          폭이 달라 칸이 흔들린다. 서버가 준 문자열을 그대로 쓴다 — 우리가 자르지 않는다.
        */}
        <div className="flex items-end justify-between gap-2">
          <span className="font-mono text-[0.8rem] tracking-[0.14em]">{card.cardNumberMasked}</span>
          {card.isDefault && (
            /* 실물 카드가 오른쪽 아래에 결제망 마크를 넣는 자리다. 우리는 결제망을 모르므로
               (토스가 안 준다) 그 자리에 "이 카드로 청구된다" 는 사실을 넣는다. */
            <span
              className="shrink-0 rounded-full px-2 py-0.5 text-[0.62rem] font-semibold tracking-[0.06em]"
              style={{
                background: light ? "rgba(255,255,255,0.22)" : "rgba(23,21,20,0.12)",
                border: `1px solid ${light ? "rgba(255,255,255,0.4)" : "rgba(23,21,20,0.24)"}`,
              }}
            >
              기본
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * IC 칩. 실물 EMV 칩의 접점 무늬다 — 가운데 사각 접점 하나와 그 둘레로 뻗는 분할선들.
 * 이미지가 아니라 SVG 인 이유: 카드 폭이 화면에 따라 변하는데 이미지는 그때 흐려지고,
 * 파일 하나가 늘면 그만큼 요청도 는다. 여기서는 도형 몇 개면 끝난다.
 */
function Chip() {
  return (
    <svg viewBox="0 0 40 31" className="w-[15%] min-w-[34px]" aria-hidden>
      <defs>
        <linearGradient id="alldapChipGold" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#f5e2a8" />
          <stop offset="0.5" stopColor="#d9b968" />
          <stop offset="1" stopColor="#b9954a" />
        </linearGradient>
      </defs>
      <rect x="0.6" y="0.6" width="38.8" height="29.8" rx="4.5" fill="url(#alldapChipGold)" />
      <g stroke="rgba(90,66,20,0.55)" strokeWidth="1.1" fill="none">
        <rect x="0.6" y="0.6" width="38.8" height="29.8" rx="4.5" />
        {/* 가운데 접점 */}
        <rect x="13.5" y="9" width="13" height="13" rx="1.6" />
        {/* 좌우로 뻗는 선 */}
        <path d="M0.6 9h12.9M0.6 22h12.9M26.5 9h12.9M26.5 22h12.9" />
        {/* 위아래로 뻗는 선 */}
        <path d="M13.5 0.6v8.4M26.5 0.6v8.4M13.5 22v8.4M26.5 22v8.4" />
      </g>
    </svg>
  );
}

/** 비접촉 결제 표시. 실물 카드는 오른쪽 위에 넣는다. */
function Contactless({ dim }: { dim: number }) {
  return (
    <svg viewBox="0 0 20 20" className="w-[9%] min-w-[18px]" aria-hidden style={{ opacity: dim }}>
      <g fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
        <path d="M6 5.5a7 7 0 0 1 0 9" />
        <path d="M10 3a11 11 0 0 1 0 14" />
        <path d="M14 0.5a15 15 0 0 1 0 19" />
      </g>
    </svg>
  );
}
