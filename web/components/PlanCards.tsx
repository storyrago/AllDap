"use client";

/**
 * 요금제 두 장. `/pricing` 의 본문이자, <요금제를 실제로 바꾸는 유일한 자리>다.
 *
 * ── 왜 이 파일이 생겼나 (2026-09-08) ────────────────────────────────────────
 * 그전에는 요금제 카드가 <두 곳>에 있었다 — 마케팅용 `/pricing` 과 관리용 `/account`.
 * 같은 숫자를 두 벌 그리면 한쪽만 고치는 사고가 반드시 난다(이 저장소가 반복해 낸 부류다).
 * 게다가 `/account` 가 "고르는 화면" 이기도 해서, 마이페이지를 열 때마다 결제 결정을
 * 다시 마주쳐야 했다. 마이페이지에서 알고 싶은 건 <내가 무슨 요금제인가> 하나다.
 *
 * 그래서 역할을 갈랐다:
 *   `/account`  → 지금 요금제를 <확인>만 한다. 바꾸려면 이 페이지로 넘어온다.
 *   `/pricing`  → 요금제를 <비교하고 고른다>. 카드 마크업이 여기 한 벌만 남는다.
 *
 * ── 왜 "use client" 가 이 컴포넌트에만 붙는가 (서버 컴포넌트와의 경계) ──────
 * 감싸는 `/pricing` 페이지는 서버 컴포넌트다 — metadata 를 내보내고 검색엔진이 읽어야 하는
 * 마케팅 페이지라 서버에서 HTML 로 완성되는 편이 낫다. 그런데 "지금 무슨 요금제인가" 를
 * 알려면 JWT 를 봐야 하고 그 토큰은 localStorage, 즉 <브라우저에만> 있다.
 * 그래서 카드 그리드만 클라이언트로 내렸다. `AuthLink` 가 헤더 버튼 하나만 클라이언트로
 * 내린 것과 같은 판단이다 — 페이지 전체를 내리면 마케팅 본문까지 클라이언트 번들에 들어간다.
 *
 * ── 첫 렌더는 항상 <비로그인 모습>이다 ─────────────────────────────────────
 * useSyncExternalStore 의 세 번째 인자(서버 스냅샷)가 undefined 를 주므로, 서버 HTML 과
 * 하이드레이션 첫 렌더가 "비로그인" 으로 일치한다(불일치면 React 가 화면을 깨뜨린다).
 * 로그인한 사람에게는 그 뒤 한 프레임 만에 "사용 중" 배지와 버튼이 붙는다. AuthLink 주석 참고.
 *
 * 호출하는 Spring API
 *   GET /api/plan  → PlanResponse   (로그인했을 때만)
 *   PUT /api/plan  → PlanResponse
 */

import Link from "next/link";
import { useEffect, useState, useSyncExternalStore } from "react";
import {
  ApiError,
  api,
  getAccessToken,
  getAccessTokenServerSnapshot,
  subscribeAccessToken,
} from "@/lib/api";
import { PLANS } from "@/lib/plans";
import type { PlanId } from "@/lib/types";

export function PlanCards() {
  const token = useSyncExternalStore(
    subscribeAccessToken,
    getAccessToken,
    getAccessTokenServerSnapshot,
  );
  /* undefined(아직 모름)와 null(확실히 없음)을 <같이> 비로그인으로 그린다.
     둘 다 보여줄 것이 같기 때문이다 — 요금제를 못 고르는 화면. */
  const signedIn = Boolean(token);

  /*
   * 지금 요금제. `null` 은 <아직 못 불러왔거나 실패했다>는 뜻이고, 그때는 배지도 버튼도
   * 그리지 않는다. 모르는 채로 "사용 중" 을 아무 카드에나 붙이면 그게 거짓말이다.
   */
  const [plan, setPlan] = useState<PlanId | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    /*
     * IIFE 로 감싸는 이유: effect 콜백 자체는 async 일 수 없다(React 가 반환값을 cleanup 으로
     * 본다). `void` 는 "이 프로미스를 일부러 기다리지 않는다" 는 표시이자, eslint 가
     * 처리되지 않은 프로미스로 잡지 않게 하는 관용구다.
     *
     * ⚠️ 취소 플래그를 두지 않는다. 화면을 떠난 뒤 응답이 와도 React 18+ 는 setState 를
     *    조용히 무시한다(경고조차 없다). 이 저장소는 2026-09-07 에 아무것도 막지 못하던
     *    cancelled 플래그를 8곳에서 걷어냈다 — 여기서 되살리지 말 것.
     */
    void (async () => {
      try {
        setPlan((await api.plan.getPlan()).plan);
      } catch {
        /* 못 불러와도 마케팅 본문은 그대로 보여야 한다. 요금제 표시만 조용히 접는다. */
        setPlan(null);
      }
    })();
  }, [token]);
  /*
   * 의존성이 [token] 인 이유: 이 안에서 쓰는 바깥 값이 그것 하나고, <값이 바뀌면 다시
   * 물어야 한다>. 다른 탭에서 로그아웃하거나 다른 계정으로 로그인하면 token 이 바뀌는데,
   * 배열을 []로 비우면 그때 남의 요금제를 계속 보여주게 된다.
   */

  async function handleChange(next: PlanId) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const changed = await api.plan.changePlan(next);
      setPlan(changed.plan);
      // 조사는 "로" 로 고정한다 — 요금제 이름 "무료"·"Pro" 가 둘 다 받침이 없다.
      // 받침 있는 이름을 추가하면 이 줄을 함께 봐야 한다.
      setNotice(`요금제를 ${PLANS.find((p) => p.id === changed.plan)?.name ?? changed.plan}로 바꿨습니다.`);
    } catch (e) {
      /* 대부분 409(카드 없이 유료 선택)인데, 서버 문구가 이미 "카드를 등록한 뒤 다시
         선택해주세요" 라고 <다음에 할 일>까지 알려준다. 우리가 다시 쓰지 않는다. */
      setError(e instanceof ApiError ? e.message : "요금제를 바꾸지 못했습니다.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      {error && (
        <p
          role="alert"
          className="mb-4 rounded-md border border-danger bg-danger-surface px-3 py-2 text-sm text-danger"
        >
          {error}
        </p>
      )}
      {/* role="status" — 급한 오류가 아니라 완료 안내라 스크린리더가 흐름을 끊지 않고 읽는다. */}
      {notice && (
        <p role="status" className="mb-4 text-sm text-success">
          {notice}
        </p>
      )}

      <div className="grid gap-6 sm:grid-cols-2">
        {PLANS.map((p) => {
          const current = signedIn && p.id === plan;
          /*
           * 진한 테두리가 <가리키는 대상이 사람에 따라 다르다.>
           *   비로그인 방문자 → Pro (이게 추천이다)
           *   로그인 사용자   → 지금 쓰는 요금제 (추천보다 "내가 어디 있나" 가 급하다)
           * 요금제를 아직 못 불러왔으면 로그인해도 비로그인과 같게 둔다 — 모르면 추측하지 않는다.
           */
          const emphasized = signedIn && plan !== null ? current : p.id === "pro";
          return (
            <article
              key={p.id}
              className={`flex flex-col rounded-lg border bg-surface p-6 ${
                emphasized ? "border-foreground" : "border-subtle"
              }`}
            >
              <div className="flex items-baseline justify-between gap-2">
                <p className="text-xs font-medium tracking-[0.18em] text-muted">{p.name}</p>
                {current && (
                  <span className="rounded border border-success px-1.5 py-0.5 text-xs font-medium text-success">
                    사용 중
                  </span>
                )}
              </div>
              <p className="mt-3 text-3xl font-bold tracking-[-0.02em]">
                {p.monthlyPriceKrw.toLocaleString("ko-KR")}원
                <span className="ml-1 text-sm font-normal text-muted">/월</span>
              </p>
              <dl className="mt-5 space-y-2 text-sm">
                <div className="flex justify-between gap-4">
                  <dt className="text-muted">답변 (답하지 못한 질문 제외)</dt>
                  <dd className="font-medium">월 {p.includedAnswers.toLocaleString("ko-KR")}건</dd>
                </div>
                <div className="flex justify-between gap-4">
                  <dt className="text-muted">품질 평가 실행</dt>
                  <dd className="font-medium">월 {p.includedEvalRuns}회</dd>
                </div>
                <div className="flex justify-between gap-4">
                  <dt className="text-muted">포함량 초과 답변</dt>
                  <dd className="font-medium">
                    {p.overageAnswerKrw === null ? "한도에서 멈춤" : `건당 ${p.overageAnswerKrw}원`}
                  </dd>
                </div>
                <div className="flex justify-between gap-4">
                  <dt className="text-muted">추가 평가 실행</dt>
                  <dd className="font-medium">
                    {p.extraEvalRunKrw === null
                      ? "불가"
                      : `회당 ${p.extraEvalRunKrw.toLocaleString("ko-KR")}원`}
                  </dd>
                </div>
              </dl>

              {/* 버튼은 <두 장 중 한 장에만> 붙는다(지금 쓰는 요금제에는 바꿀 것이 없다).
                  그리드가 두 카드의 높이를 맞추므로 mt-auto 로 카드 바닥에 내려붙여야
                  버튼이 카드 한가운데 떠 있지 않는다. pt-6 은 dl 과의 최소 간격이다. */}
              {signedIn && plan !== null && !current && (
                <div className="mt-auto pt-6">
                  <button
                    type="button"
                    onClick={() => handleChange(p.id)}
                    disabled={busy}
                    className="w-full rounded-md bg-foreground px-4 py-3 text-sm font-semibold text-surface disabled:opacity-50"
                  >
                    {busy ? "바꾸는 중…" : `${p.name}로 바꾸기`}
                  </button>
                </div>
              )}
            </article>
          );
        })}
      </div>

      {/*
        결제 수단은 여기서 관리하지 않는다 — 어디로 가야 하는지만 알려준다.
        유료로 바꾸려는데 카드가 없으면 서버가 409 로 막고, 그 문구가 "카드를 등록하라" 고
        말한다. 그때 <어디로 가야 하는지>가 화면에 이미 있어야 안내가 완결된다.
        카드 장수를 미리 조회해 버튼을 잠그지 않는 이유: 요청 하나가 늘고, 판단은 어차피
        서버가 한다. 공개 페이지에서 로그인 사용자에게만 나가는 조회를 더 만들 값어치가 없다.
      */}
      {signedIn && (
        <p className="mt-4 text-sm text-muted">
          결제 수단은{" "}
          <Link href="/account" className="font-medium text-foreground underline">
            마이페이지
          </Link>
          에서 관리합니다. 유료 요금제는 카드가 등록돼 있어야 선택할 수 있습니다.
        </p>
      )}

      {/*
        🔴 거짓 완성 금지. 바꾸기 버튼 <바로 옆>에 있어야 하는 문구다 — 금액이 적힌 카드에서
           버튼을 누르면 사용자는 29,000원이 나갔다고 믿는다. 실제로는 users.plan 한 칸이
           바뀔 뿐이고 청구는 요금제 연동 4번 조각이라 아직 없다.
           청구가 붙으면 <반드시 이 문구를 지울 것.> (봇 설정의 낡은 경고를 2026-09-07 에
           뒤늦게 고친 전례가 있다 — 기능이 붙으면 그 기능을 <설명하는 자리>도 함께 고친다)
      */}
      {signedIn && (
        <p className="mt-3 rounded-md border border-warning bg-warning-surface px-3 py-2 text-xs text-warning">
          ⚠️ 요금제를 바꿔도 <b>청구는 일어나지 않습니다.</b> 지금은 선택만 저장되며, 실제 결제와
          사용량 한도는 아직 연결되지 않았습니다.
        </p>
      )}
    </>
  );
}
