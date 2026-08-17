/**
 * 공개 페이지의 <시그니처> — 주장 아래에 붙는 근거 태그.
 *
 * ── 왜 이 컴포넌트가 이 제품의 시그니처인가 ──────────────────────────────
 * AllDap 이 파는 것은 "답변에 출처가 붙는다 · 근거가 없으면 답하지 않는다" 다.
 * 그런데 대부분의 랜딩은 자기 제품 자랑을 <근거 없이> 한다. 그건 제품 철학과 모순이다.
 *
 * 그래서 이 페이지들은 <제품이 하는 일을 스스로 실연한다>: 주장마다 근거를 달고,
 * 근거가 없는 주장은 <아예 쓰지 않는다>. 실측치가 있으므로 지어낼 필요가 없다.
 *
 * 챗봇 답변의 `[근거 1] (출처: 취업규칙.md)` 표기를 그대로 가져왔다 —
 * 사용자가 제품 안에서 보게 될 것과 같은 모양이다.
 *
 * ── "use client" 가 없는 이유 ──────────────────────────────────────────
 * 상태도 이벤트도 없는 순수 표시용이다. 서버 컴포넌트로 두면 이 마크업이
 * 브라우저 번들에 들어가지 않는다. 공개 페이지는 SEO 대상이라 그게 유리하다.
 */

type EvidenceKind = "실측" | "설계" | "미정";

/** 근거의 <성격>을 구분한다. 실측과 계획을 같은 톤으로 쓰면 그게 과장이다. */
const KIND_STYLE: Record<EvidenceKind, string> = {
  실측: "border-success text-success",
  설계: "border-subtle text-muted",
  // 🔴 아직 정해지지 않은 것을 정해진 것처럼 쓰지 않는다. 가격이 그렇다.
  미정: "border-warning text-warning",
};

export function Evidence({
  kind = "실측",
  children,
}: {
  kind?: EvidenceKind;
  children: React.ReactNode;
}) {
  return (
    <p className="mt-2 flex items-start gap-2 text-xs leading-relaxed text-muted">
      <span
        className={`mt-px shrink-0 rounded border px-1.5 py-0.5 font-medium ${KIND_STYLE[kind]}`}
      >
        {kind}
      </span>
      <span className="min-w-0">{children}</span>
    </p>
  );
}

/**
 * 페이지 제목 블록. 히어로의 큰 타이포(웨이트 800 · 좁은 자간)를 이어받되
 * 크기를 낮춘다 — 히어로는 극장이고 이 페이지들은 <안내문>이다.
 * 같은 폰트를 쓰면서 역할 차이를 크기로만 두는 것이 이 사이트의 위계다.
 */
export function PageIntro({
  eyebrow,
  title,
  lead,
}: {
  eyebrow: string;
  title: string;
  lead: string;
}) {
  return (
    <div className="border-b border-subtle pb-10">
      {/* eyebrow 는 장식이 아니라 <이 페이지가 무엇에 답하는지>를 적는다 */}
      <p className="text-xs font-medium tracking-[0.22em] text-muted">{eyebrow}</p>
      <h1 className="mt-4 text-4xl font-extrabold leading-tight tracking-[-0.035em] sm:text-5xl">
        {title}
      </h1>
      <p className="mt-5 max-w-2xl text-base leading-relaxed text-muted sm:text-lg">{lead}</p>
    </div>
  );
}

/**
 * 뷰파인더 브래킷 — 히어로 헤더의 네 모서리 모티프를 그대로 가져온 것.
 * 이 사이트에서 <지금 봐야 할 것>을 감싸는 표시로 일관되게 쓴다.
 */
export function Framed({ children }: { children: React.ReactNode }) {
  const corner = "absolute h-4 w-4 border-foreground/30";
  return (
    <div className="relative p-4">
      <span className={`${corner} left-0 top-0 border-l-[1.5px] border-t-[1.5px]`} />
      <span className={`${corner} right-0 top-0 border-r-[1.5px] border-t-[1.5px]`} />
      <span className={`${corner} bottom-0 left-0 border-b-[1.5px] border-l-[1.5px]`} />
      <span className={`${corner} bottom-0 right-0 border-b-[1.5px] border-r-[1.5px]`} />
      {children}
    </div>
  );
}
