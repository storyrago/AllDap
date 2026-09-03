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

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, api, setAccessToken } from "@/lib/api";

/** 로그인 탭인가 가입 탭인가. 값이 둘뿐이라 문자열 유니온으로 좁혀 오타를 컴파일 단계에서 잡는다. */
type Mode = "login" | "signup";

export default function AuthPage() {
  /*
   * useRouter 는 "코드로 페이지를 이동" 할 때 쓴다. next/navigation 에서 가져온다
   * (구버전 next/router 가 아니다 — App Router 에서는 경로가 다르다).
   * 화면에 보이는 링크라면 <Link> 가 낫고, 여기처럼 "로그인 성공 후 이동" 은 이 훅이 맞다.
   */
  const router = useRouter();

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
      router.replace("/dashboard");
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
