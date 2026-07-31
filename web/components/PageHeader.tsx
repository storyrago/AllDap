/**
 * 페이지 상단 제목 영역.
 * 모든 관리자 화면이 "제목 + 한 줄 설명 + (선택) 우측 액션" 구조를 갖도록 통일한다.
 */
export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  /** 우측에 놓을 버튼 등 */
  actions?: React.ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-4 border-b border-subtle pb-4">
      <div>
        <h1 className="text-xl font-semibold">{title}</h1>
        {description ? (
          <p className="mt-1 text-sm text-muted">{description}</p>
        ) : null}
      </div>
      {actions ? <div className="flex gap-2">{actions}</div> : null}
    </div>
  );
}
