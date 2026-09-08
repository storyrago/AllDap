"use client";

import type { ReactNode } from "react";

/**
 * 켜고 끄는 스위치.
 *
 * <b>체크박스를 쓰지 않은 이유.</b> 체크박스는 "제출할 때 함께 보낼 값" 을 고르는 것이고,
 * 스위치는 "지금 즉시 상태가 바뀐다" 는 뜻이다. 쓰이는 두 곳(로그 필터·내보내기 스니펫 형태)
 * 모두 누르는 즉시 화면이 바뀌므로 스위치가 의미에 맞다.
 *
 * <b>왜 &lt;input type="checkbox"&gt; 에 CSS 를 씌우지 않고 &lt;button role="switch"&gt; 인가.</b>
 * 체크박스를 스위치처럼 보이게 하려면 `appearance-none` 으로 네이티브 모양을 지우고 가짜
 * 눈금을 그려야 하는데, 그러면 포커스 링·키보드 조작·스크린리더 읽기를 전부 직접 다시
 * 만들어야 한다. `role="switch"` 는 브라우저가 "켬/끔" 으로 읽어주고 Space·Enter 도 그냥 동작한다.
 *
 * <b>라벨을 버튼 안에 둔 이유.</b> `<label>` 로 감싸도 button 과는 연결되지 않는다
 * (label 의 for 는 form 컨트롤만 가리킨다). 안에 넣으면 접근 이름이 저절로 생기고
 * 글자를 눌러도 켜진다.
 */
export function Toggle({
  checked,
  onChange,
  label,
  description,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  label: ReactNode;
  /** 있으면 라벨 아래에 작은 글씨로. 없으면 한 줄짜리 스위치가 된다. */
  description?: ReactNode;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className="flex items-start gap-2.5 rounded-md text-left focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-foreground"
    >
      {/* 시각 요소일 뿐이라 aria 에서 숨긴다 — 상태는 위 aria-checked 가 이미 말한다.
          ⚠️ 꺼짐 색을 팔레트 토큰(`bg-subtle`)으로 두면 <페이지 배경>(#eae0de) 위에서
          트랙이 사라지고 흰 손잡이만 떠 보였다. 카드(`surface`) 위에서만
          보고 정하면 놓친다 — 실제로 놓쳤다. 그래서 <알파 틴트>(foreground/15)를 쓴다.
          바탕이 흰 카드든 점토색 배경이든 같은 만큼 어두워지므로 두 곳에서 함께 성립한다.
          ✅ 2026-09-08 에 토큰 자체가 어두워졌지만(#e2d8d6 → #cdbab5, globals.css 참고)
             여기는 알파 틴트를 그대로 둔다 — 트랙은 <면>이라 선보다 더 진해야 하고,
             알파는 배경이 무엇이든 같은 만큼 어두워진다는 성질이 여기서는 여전히 유리하다. */}
      <span
        aria-hidden
        className={`mt-0.5 inline-flex h-5 w-9 shrink-0 items-center rounded-full border transition-colors ${
          checked ? "border-transparent bg-accent" : "border-transparent bg-foreground/15"
        }`}
      >
        <span
          className={`h-4 w-4 rounded-full bg-surface shadow-sm transition-transform ${
            checked ? "translate-x-[18px]" : "translate-x-[2px]"
          }`}
        />
      </span>
      <span className="text-sm">
        {label}
        {description && (
          <span className="mt-0.5 block text-xs text-muted">{description}</span>
        )}
      </span>
    </button>
  );
}
