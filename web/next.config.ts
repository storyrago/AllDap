import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  experimental: {
    /**
     * 라우트 이동에 View Transitions 를 쓴다(페이지 전환 연출).
     * ⚠️ experimental 이다 — Next 를 올릴 때 이름이 바뀌거나 빠질 수 있다.
     *    그래도 안전한 이유: 이 값이 사라지면 애니메이션만 없어지고 이동은 그대로 된다.
     */
    viewTransition: true,
  },
};

export default nextConfig;
