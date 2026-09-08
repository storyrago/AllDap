"use client";

/*
 * ─────────────────────────────────────────────────────────────────────────────
 * 왜 이 파일 맨 위에 "use client" 가 붙었나
 * ─────────────────────────────────────────────────────────────────────────────
 * Next.js(App Router)에서 페이지는 <기본이 서버 컴포넌트>다. 서버에서 렌더되어
 * HTML 로 내려가고, 브라우저에는 자바스크립트가 거의 안 실린다.
 *
 * 그런데 이 화면은 서버 컴포넌트로 만들 수가 없다. 세 가지를 쓰기 때문이다.
 *   ① useState        — 입력값·에러·로딩 같은 "화면 상태"
 *   ② onSubmit/onClick — 사용자 이벤트 처리
 *   ③ localStorage     — 토큰 저장 (브라우저에만 있는 API)
 * 셋 다 서버에는 존재하지 않는다. "use client" 는 "이 파일부터는 브라우저에서
 * 실행되는 코드다" 라고 경계를 긋는 선언이다.
 *
 * 경계는 <파일 단위>이고 아래로 전파된다. 여기서 import 하는 컴포넌트도 함께
 * 클라이언트 번들에 들어간다. 그래서 이 지시어는 필요한 파일에만 붙인다.
 *
 * ※ metadata export 가 사라진 이유: `export const metadata` 는 서버 컴포넌트 전용이라
 *   "use client" 파일에서는 쓸 수 없다. 이 화면의 <title> 은 상위 레이아웃이 정한다.
 * ─────────────────────────────────────────────────────────────────────────────
 */

import { useEffect, useState, useSyncExternalStore } from "react";
import { useRouter } from "next/navigation";
import {
  ApiError,
  api,
  getAccessToken,
  getAccessTokenServerSnapshot,
  setAccessToken,
  subscribeAccessToken,
} from "@/lib/api";
import { safeRedirectPath } from "@/lib/redirect";

/** 로그인 탭인가 가입 탭인가. 값이 둘뿐이라 문자열 유니온으로 좁혀 오타를 컴파일 단계에서 잡는다. */
type Mode = "login" | "signup";

/**
 * 이 화면을 떠날 때 갈 곳. `?next=` 가 있으면 <있던 자리로> 돌려보낸다.
 *
 * 🔴 이 화면에서 나가는 길이 둘인데(방금 로그인함 · 이미 로그인해 있었음) 둘 다 이 함수를 쓴다.
 *    한쪽만 `?next=` 를 보면, 로그인한 채 `/auth?next=/faq` 링크를 누른 사람만 대시보드로
 *    떨어지는 <설명할 수 없는 차이>가 생긴다. 판정은 한 곳에 둔다.
 *
 * ⚠️ `useSearchParams` 훅을 쓰지 않는다. 그 훅은 프리렌더된 트리에서 Suspense 경계를
 *    요구한다(Next 16 문서). 이 함수는 effect 와 제출 핸들러 안에서만 불리므로 브라우저인
 *    것이 확실하다 — window 를 직접 읽으면 그 제약을 질 이유가 없다.
 * 🔴 값을 그대로 쓰지 않는다. 오픈 리다이렉트를 막는 판정은 `lib/redirect.ts` 에 있다.
 */
function nextPath(): string {
  const raw = new URLSearchParams(window.location.search).get("next");
  return safeRedirectPath(raw, window.location.origin);
}

export default function AuthPage() {
  /*
   * useRouter 는 "코드로 페이지를 이동" 할 때 쓴다. next/navigation 에서 가져온다
   * (구버전 next/router 가 아니다 — App Router 에서는 경로가 다르다).
   * 화면에 보이는 링크라면 <Link> 가 낫고, 여기처럼 "로그인 성공 후 이동" 은 이 훅이 맞다.
   */
  const router = useRouter();

  /*
   * ─────────────────────────────────────────────────────────────────────────
   * 🔴 이미 로그인한 사람이 여기 오면 대시보드로 보낸다 (2026-09-08)
   * ─────────────────────────────────────────────────────────────────────────
   * 없을 때 무슨 일이 났나: 로그인한 채로 랜딩에 가서 "고용하기" 를 누르면 <로그인 창이
   * 다시 떴다.> 사용자가 실제로 겪은 경로다. 헤더 버튼(components/AuthLink.tsx)만
   * 로그인 여부를 보고 갈래를 타고 있었고, 나머지 세 곳은 `/auth` 로 직행했다 —
   * 랜딩 히어로의 "고용하기", `/pricing` 의 "도입 문의하기", `/faq` 의 "문의를 남겨주세요".
   *
   * 🔴 링크 세 개를 각각 고치지 않고 <도착지 한 곳>에서 막는다. 링크마다 고치면
   *    ① 세 곳 모두 토큰을 읽어야 해서 공개 페이지 셋이 클라이언트 컴포넌트가 되고
   *    ② 나중에 `/auth` 로 보내는 링크를 하나 더 만드는 순간 같은 버그가 되살아난다.
   *    "로그인 화면은 로그인하지 않은 사람만 본다" 는 <이 화면의 성질>이지 링크의 성질이 아니다.
   *
   * ⚠️ 첫 렌더는 반드시 <비로그인 모습>이어야 한다. 서버 스냅샷이 undefined 를 주므로
   *    서버 HTML 과 하이드레이션 첫 렌더가 "폼" 으로 일치한다(불일치면 React 가 화면을 깨뜨린다).
   *    그 다음 실제 토큰을 읽어 갈라진다 — AuthLink·대시보드 레이아웃과 같은 방식이다.
   */
  const token = useSyncExternalStore(
    subscribeAccessToken,
    getAccessToken,
    getAccessTokenServerSnapshot,
  );

  useEffect(() => {
    /*
     * `=== null` 이 아니라 `token` 인 것에 주의. 여기서 갈라야 하는 것은 <있다>이고,
     * undefined(아직 못 읽음)와 null(확실히 없음)은 <둘 다 폼을 보여준다>. 대시보드
     * 가드는 반대라 `=== null` 을 썼다 — 거기서는 "아직 모름" 에 튕기면 안 됐다.
     *
     * replace 인 이유는 로그인 성공 뒤 이동과 같다: push 면 대시보드에서 뒤로 가기를
     * 눌렀을 때 로그인 화면으로 돌아오고, 그 화면이 다시 대시보드로 보내 <뒤로 가기가 막힌다>.
     */
    if (token) router.replace(nextPath());
  }, [token, router]);

  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");

  /*
   * 에러는 문자열 하나로 충분하다. 서버가 주는 message 에 "무엇을 어떻게 하면 되는지" 가
   * 이미 들어 있다는 게 이 프로젝트의 규약이라(PRD §10.3), 화면은 가공하지 않고 그대로 보여준다.
   * null = "에러 없음". 빈 문자열("")을 쓰지 않는 이유는 "에러 없음" 과
   * "에러인데 문구가 비었음" 을 구분하기 위해서다.
   */
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const isSignup = mode === "signup";

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    // <form> 의 기본 동작은 페이지를 통째로 새로고침하는 것이다. 그러면 화면 상태가 전부 날아간다.
    event.preventDefault();
    setError(null);
    setSubmitting(true);

    try {
      const response = isSignup
        ? await api.auth.signup(email, password, name)
        : await api.auth.login(email, password);

      // 토큰을 먼저 저장하고 이동한다. 순서가 반대면 이동한 화면이 토큰 없이 API 를 부른다.
      setAccessToken(response.token);

      /*
       * push 가 아니라 replace 를 쓰는 이유:
       * push 는 히스토리에 쌓여서, 대시보드에서 <뒤로 가기>를 누르면 로그인 화면으로 돌아온다.
       * 이미 로그인한 사람에게 로그인 화면은 의미가 없다. replace 는 현재 항목을 대체해 그 문제를 없앤다.
       */
      router.replace(nextPath());
    } catch (e) {
      // ApiError 는 서버가 규약대로 준 에러다. 그 외(네트워크 단절 등)는 우리가 문구를 만들어야 한다.
      setError(
        e instanceof ApiError
          ? e.message
          : "요청을 보내지 못했습니다. 네트워크 상태를 확인한 뒤 다시 시도해주세요.",
      );
    } finally {
      // 성공하든 실패하든 버튼은 풀어준다. finally 가 아니면 실패했을 때 버튼이 잠긴 채로 남는다.
      setSubmitting(false);
    }
  }

  function switchMode(next: Mode) {
    setMode(next);
    // 탭을 바꾸면 이전 탭에서 난 에러는 더 이상 맞지 않는다. 남겨두면 사용자가 혼란스럽다.
    setError(null);
  }

  /*
   * 이동하는 동안 폼을 그리지 않는다. 그리면 로그인한 사람에게 로그인 창이 한 번 번쩍이는데,
   * 그게 정확히 이 수정이 없애려는 증상이다. (훅을 전부 부른 <뒤>에 반환해야 한다 —
   * 조건부로 훅을 건너뛰면 React 가 훅 순서를 잃는다)
   */
  /* 목적지를 적지 않는다. `?next=` 가 있으면 대시보드가 아니라 있던 자리로 간다. */
  if (token) return <p className="px-6 py-16 text-sm text-muted">이동합니다…</p>;

  return (
    <div className="mx-auto w-full max-w-md px-6 py-16">
      <h1 className="text-2xl font-semibold">시작하기</h1>
      <p className="mt-2 text-sm text-muted">
        이메일과 비밀번호로 가입합니다. 비밀번호 재설정은 MVP 이후 기능입니다.
      </p>

      {/* 탭 */}
      <div className="mt-8 flex gap-1 rounded-lg border border-subtle bg-surface p-1">
        {(["login", "signup"] as const).map((value) => (
          <button
            key={value}
            type="button"
            onClick={() => switchMode(value)}
            className={`flex-1 rounded-md px-3 py-2 text-sm transition ${
              mode === value
                ? "bg-foreground text-surface"
                : "text-muted hover:text-foreground"
            }`}
          >
            {value === "login" ? "로그인" : "회원가입"}
          </button>
        ))}
      </div>

      <form onSubmit={handleSubmit} className="mt-6 space-y-4">
        <Field label="이메일">
          <input
            type="email"
            name="email"
            required
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className={inputClass}
            placeholder="you@example.com"
          />
        </Field>

        <Field label="비밀번호">
          <input
            type="password"
            name="password"
            required
            /* 가입은 새 비밀번호, 로그인은 기존 비밀번호. 브라우저 자동완성 동작이 달라진다. */
            autoComplete={isSignup ? "new-password" : "current-password"}
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className={inputClass}
            placeholder="8자 이상"
          />
        </Field>

        {/* 이름은 가입할 때만 받는다. 조건부 렌더링은 && 로 쓴다 — 왼쪽이 false 면 아무것도 그리지 않는다. */}
        {isSignup && (
          <Field label="이름 (선택)">
            <input
              type="text"
              name="name"
              autoComplete="name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className={inputClass}
              placeholder="홍길동"
            />
          </Field>
        )}

        {error && (
          <p
            /* role="alert" 를 붙이면 스크린리더가 이 문구를 즉시 읽는다. 에러는 놓치면 안 되는 정보다. */
            role="alert"
            className="rounded-md border border-danger bg-danger-surface px-3 py-2 text-sm text-danger"
          >
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded-md bg-foreground px-4 py-2.5 text-sm font-medium text-surface disabled:opacity-50"
        >
          {submitting ? "처리 중…" : isSignup ? "가입하고 시작하기" : "로그인"}
        </button>
      </form>
    </div>
  );
}

/**
 * 라벨 + 입력칸 묶음.
 *
 * children 은 "이 컴포넌트 태그 사이에 넣은 것" 을 받는 특별한 prop 이다.
 * 입력 요소마다 라벨 마크업을 복사하지 않으려고 만들었다.
 *
 * <label> 로 감싸면 라벨을 눌러도 입력칸에 포커스가 간다 —
 * htmlFor/id 를 짝지어 줄 필요가 없어 실수할 여지가 준다(접근성).
 */
function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium">{label}</span>
      {children}
    </label>
  );
}

/** 입력칸 공통 스타일. 문자열로 빼둬 세 군데가 어긋나지 않게 한다. */
const inputClass =
  "w-full rounded-md border border-subtle bg-surface px-3 py-2 text-sm outline-none focus:border-accent " +
  /* 🔴 outline-none 이 브라우저 기본 포커스 링을 지우는데, 대체가 1px 민트 테두리뿐이었다.
     민트(#7ED0C0)는 흰 배경 대비 1.8:1 이고 <테두리 색이 바뀌는 것>만 보면 1.29:1 이라
     WCAG 1.4.11 의 3:1 에 한참 못 미친다. 값은 globals.css 의 .alldap-scene-nav
     a:focus-visible 과 같은 언어이고, outline 은 레이아웃을 밀지 않아 간격이 안 바뀐다.
     ⚠️ outline-solid 를 빼면 안 된다 — outline-none 이 --tw-outline-style 을 none 으로
        박아둬서, 폭만 2px 로 줘봐야 선이 안 그려진다. */
  "focus-visible:outline-solid focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-foreground";
