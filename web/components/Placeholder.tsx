/**
 * "여기에 무엇이 들어갈 자리인지"를 표시하는 뼈대용 블록.
 *
 * 왜 이런 컴포넌트를 따로 두나:
 *   가짜 더미 데이터를 진짜처럼 렌더하면, 나중에 이 화면이 완성된 건지
 *   아직 껍데기인지 구분이 안 된다. 점선 테두리로 "미구현"임을 눈에 보이게 못박는다.
 *   실제 구현이 들어가면 이 컴포넌트를 지우면 된다 — 남아 있으면 아직 안 만든 곳이다.
 */
export function Placeholder({
  title,
  api,
  children,
  className = "",
}: {
  /** 이 자리에 들어갈 UI 이름 (예: "문서 목록 테이블") */
  title: string;
  /** 이 자리를 채우기 위해 호출할 Spring API (예: "GET /api/bots/{botId}/documents") */
  api?: string;
  /** 무엇이 들어가는지에 대한 설명 */
  children?: React.ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`rounded-lg border border-dashed border-subtle bg-surface/60 p-5 ${className}`}
    >
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 className="text-sm font-semibold">{title}</h2>
        <span className="rounded bg-foreground/5 px-1.5 py-0.5 text-[11px] text-muted">
          미구현
        </span>
      </div>
      {children ? (
        <div className="mt-2 space-y-1 text-sm text-muted">{children}</div>
      ) : null}
      {api ? (
        <p className="mt-3 font-mono text-[11px] text-muted">호출: {api}</p>
      ) : null}
    </section>
  );
}

/**
 * 숫자 하나를 크게 보여주는 지표 카드의 자리.
 * 품질 대시보드·봇 목록처럼 "점수/개수"가 먼저 눈에 들어와야 하는 화면에서 쓴다.
 */
export function MetricPlaceholder({
  label,
  hint,
}: {
  label: string;
  hint?: string;
}) {
  return (
    <div className="rounded-lg border border-dashed border-subtle bg-surface/60 p-4">
      <p className="text-xs text-muted">{label}</p>
      {/* 실제 값 대신 —. 가짜 숫자를 넣으면 완성된 화면처럼 보여서 위험하다. */}
      <p className="mt-1 text-2xl font-semibold tabular-nums text-muted">—</p>
      {hint ? <p className="mt-1 text-[11px] text-muted">{hint}</p> : null}
    </div>
  );
}
