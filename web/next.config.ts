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

  /**
   * 옛 주소 → 새 주소. 결제 수단은 2026-09-08 에 마이페이지(`/account`)로 들어갔다.
   *
   * ── 왜 페이지에서 `redirect()` 를 부르지 않고 여기 두는가 ──────────────────
   * 처음에는 `app/(dashboard)/billing/page.tsx` 에서 `redirect("/account")` 를 불렀는데,
   * Next 문서(01-app/02-guides/redirecting.md)가 명시한다 — *"렌더 <전에> 넘기려면
   * next.config 나 Proxy 를 쓰라"*. 여기 두면 얻는 것이 셋이다:
   *
   *   ① 🔴 **쿼리스트링이 그대로 따라간다.** 문서 원문: "any query values provided in the
   *      request will be passed through to the redirect destination". 페이지 방식은 이걸
   *      잃는다 — 옛 주소로 `?authKey=…` 가 들어오면 <등록이 조용히 사라진다.>
   *      (토스 결제창은 이제 `/account` 를 직접 가리키지만, 이미 열려 있던 탭이나
   *       북마크가 옛 주소를 물고 올 수 있다)
   *   ② 렌더 자체가 없다. 페이지 방식은 RSC 를 한 번 그리고 리다이렉트 신호를 던지는데,
   *      개발 모드에서 그 경로가 500 과 콘솔 오류를 남기는 것을 실제로 봤다.
   *   ③ 라우트 파일이 없어진다 — 옮긴 화면의 껍데기가 저장소에 남지 않는다.
   *
   * `permanent: true` = 308. 브라우저·검색엔진이 캐시해도 되는 이동이다(되돌릴 계획이 없다).
   * ⚠️ 308 은 <캐시된다>. 되돌리려면 사용자 브라우저 캐시가 남아 있어 오래 걸린다.
   */
  redirects() {
    return Promise.resolve([{ source: "/billing", destination: "/account", permanent: true }]);
  },
};

export default nextConfig;
