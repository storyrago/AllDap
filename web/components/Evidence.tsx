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

/*
 * ⚠️ "가정" 이 2026-09-08 에 빠졌다 — 요금제 금액에만 쓰였는데 그 태그를 화면에서 뺐다
 *    (`app/(site)/pricing/page.tsx` 주석에 이유가 있다). 쓰는 곳이 없는 값을 남겨두면
 *    다음 사람이 "쓰는 데가 있나 보다" 하고 찾아 헤맨다. 다시 필요하면 한 줄이면 된다.
 *    ("미정" 은 살아 있다 — `/faq` 의 데이터 정책 항목이 쓴다)
 */
type EvidenceKind = "실측" | "설계" | "미정";

/** 근거의 <성격>을 구분한다. 실측과 계획을 같은 톤으로 쓰면 그게 과장이다. */
const KIND_STYLE: Record<EvidenceKind, string> = {
  실측: "border-success text-success",
  설계: "border-subtle text-muted",
  // 🔴 아직 정해지지 않은 것을 정해진 것처럼 쓰지 않는다.
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
 *
 * ⚠️ `lead` 는 <선택>이다 (2026-09-08). 네 페이지가 전부 제목 아래에 제품 철학을 한 문장씩
 *    달고 있었는데("제품이 지키려는 것과 매출이 같은 방향을 봅니다" 류), 읽는 사람이 알아야
 *    할 것을 하나도 더 주지 않으면서 제목의 힘만 깎았다. 지금 lead 가 남은 곳은 `/demo`
 *    하나이고, 거기서도 <문서 몇 개를 학습했는지>라는 사실과 사용법만 말한다.
 *    새 페이지에 lead 를 넣으려거든 먼저 물을 것: 이 문장이 없으면 독자가 무엇을 못 하는가?
 */
export function PageIntro({
  eyebrow,
  title,
  lead,
}: {
  eyebrow: string;
  title: string;
  lead?: string;
}) {
  return (
    <div className="border-b border-subtle pb-10">
      {/* eyebrow 는 장식이 아니라 <이 페이지가 무엇에 답하는지>를 적는다 */}
      <p className="text-xs font-medium tracking-[0.22em] text-muted">{eyebrow}</p>
      <h1 className="mt-4 text-4xl font-extrabold leading-tight tracking-[-0.035em] sm:text-5xl">
        {title}
      </h1>
      {lead && (
        <p className="mt-5 max-w-2xl text-base leading-relaxed text-muted sm:text-lg">{lead}</p>
      )}
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
