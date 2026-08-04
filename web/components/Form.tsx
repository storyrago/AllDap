/*
 * 설정 계열 화면에서 함께 쓰는 폼 조각들.
 *
 * 원래 `settings/page.tsx` 안에만 있었고, 그 파일에 이렇게 적혀 있었다 —
 * "별도 파일로 빼지 않은 이유: 다른 화면에서 쓸 일이 아직 없다.
 *  두 번째 사용처가 생기면 그때 components/ 로 옮긴다."
 * 내보내기 화면이 갈라져 나오면서 그 두 번째 사용처가 생겨 여기로 옮겼다.
 * <미리 빼두지 않은 것이 맞았다> — 쓰는 곳이 하나뿐인 공용 컴포넌트는 공용이 아니다.
 *
 * 서버 컴포넌트가 아니다("use client" 는 이 파일을 쓰는 페이지들이 이미 붙여둔다).
 * onChange 로 상태를 바꾸는 입력이라 브라우저에서만 의미가 있다.
 */

export function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-6 space-y-3 rounded-lg border border-subtle bg-surface p-4">
      <h2 className="text-sm font-semibold">{title}</h2>
      {children}
    </section>
  );
}

export function TextField({
  label,
  hint,
  value,
  onChange,
  maxLength,
}: {
  label: string;
  hint?: string;
  value: string;
  /* 이벤트가 아니라 <값>을 넘기는 시그니처로 둔다 — 호출부가 e.target.value 를 몰라도 된다. */
  onChange: (value: string) => void;
  maxLength?: number;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium">{label}</span>
      {hint && <span className="mb-1 block text-xs text-muted">{hint}</span>}
      <input
        type="text"
        value={value}
        maxLength={maxLength}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-md border border-subtle bg-background px-3 py-2 text-sm outline-none focus:border-accent"
      />
    </label>
  );
}

export function TextArea({
  label,
  hint,
  value,
  onChange,
  rows,
  placeholder,
}: {
  label: string;
  hint?: string;
  value: string;
  onChange: (value: string) => void;
  rows: number;
  placeholder?: string;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium">{label}</span>
      {hint && <span className="mb-1 block text-xs text-muted">{hint}</span>}
      <textarea
        value={value}
        rows={rows}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-md border border-subtle bg-background px-3 py-2 text-sm outline-none focus:border-accent"
      />
    </label>
  );
}
