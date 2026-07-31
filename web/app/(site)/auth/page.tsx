import { Placeholder } from "@/components/Placeholder";

export const metadata = {
  title: "로그인 · 회원가입 — AllDap",
};

/**
 * `/auth` — PRD §8 "이메일 가입·로그인 / 비밀번호 재설정은 이후"
 *
 * 호출할 Spring API (PRD §10.1):
 *   POST /api/auth/signup  { email, password, name } → { token, user }
 *   POST /api/auth/login   { email, password }       → { token, user }
 *   → lib/api.ts 의 api.auth.signup / api.auth.login
 *
 * 성공하면 setAccessToken(token) 으로 JWT 를 보관하고 /dashboard 로 보낸다.
 *
 * TODO(W2): 이 페이지를 클라이언트 컴포넌트("use client")로 바꾸고 폼 상태를 붙일 것.
 *           폼 라이브러리(react-hook-form 등)는 뼈대 범위 밖이라 설치하지 않았다.
 *           기본 <form> + useState 로 충분하다.
 * TODO(W2): 토큰 보관 방식 확정 (lib/api.ts 의 TOKEN_STORAGE_KEY 주석 참고).
 *           localStorage 는 XSS 에 약하므로 httpOnly 쿠키가 권장된다.
 */
export default function AuthPage() {
  return (
    <div className="mx-auto w-full max-w-md px-6 py-16">
      <h1 className="text-2xl font-semibold">시작하기</h1>
      <p className="mt-2 text-sm text-muted">
        이메일과 비밀번호로 가입합니다. 비밀번호 재설정은 MVP 이후 기능입니다.
      </p>

      <div className="mt-8 space-y-4">
        <Placeholder
          title="로그인 / 회원가입 탭 전환"
          api="POST /api/auth/login · POST /api/auth/signup"
        >
          <p>같은 화면에서 탭으로 전환한다. 입력 필드: 이메일 · 비밀번호 · (가입 시) 이름.</p>
          <p>
            검증 실패 시 PRD §10.3 형식의 에러 message 를 그대로 화면에 띄운다.
            (예: &ldquo;이미 가입된 이메일입니다. 로그인 탭에서 로그인해주세요.&rdquo;)
          </p>
        </Placeholder>

        <Placeholder title="로그인 성공 후 처리">
          <p>
            1) setAccessToken(응답의 token) → 2) router.replace(&quot;/dashboard&quot;)
          </p>
        </Placeholder>
      </div>
    </div>
  );
}
