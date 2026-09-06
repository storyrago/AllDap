"use client";

/*
 * `/billing` — 결제 수단(카드) 등록 · 조회 · 삭제.
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * 왜 이 파일에 "use client" 가 붙는가 (서버 컴포넌트와의 경계)
 * ─────────────────────────────────────────────────────────────────────────────
 * 이유가 둘 겹친다. 하나만으로도 클라이언트 컴포넌트여야 한다.
 *
 * ① 토스 SDK 가 <브라우저 전용>이다. loadTossPayments 는 문서에
 *    <script src="https://js.tosspayments.com/v2/standard"> 를 꽂고 결제창을 iframe 으로 띄운다.
 *    document 도 window 도 없는 서버에서는 실행 자체가 불가능하다.
 *    ⚠️ npm 패키지는 <로더>일 뿐이고 실제 SDK 는 매번 토스 CDN 에서 내려온다.
 *       인터넷이 막힌 환경에서는 등록 버튼이 동작하지 않는다 — 알고 남기는 제약이다.
 *
 * ② JWT 가 localStorage 에 있다. 서버 컴포넌트는 그걸 읽을 수 없어 사용자를 대신해
 *    Spring 을 부를 수 없다. 상위 (dashboard)/layout.tsx 주석과 같은 이유이고,
 *    그래서 이 화면의 데이터도 <브라우저에서> 가져온다.
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * 호출하는 Spring API
 *   GET    /api/billing/method  → BillingMethodResponse
 *   POST   /api/billing/method  → BillingMethodResponse  (authKey 로 빌링키 발급)
 *   DELETE /api/billing/method  → 204
 * ─────────────────────────────────────────────────────────────────────────────
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { loadTossPayments } from "@tosspayments/tosspayments-sdk";
import { ApiError, api } from "@/lib/api";
import type { BillingMethodResponse } from "@/lib/types";
import { PageHeader } from "@/components/PageHeader";
import { Section } from "@/components/Form";

/*
 * 빌드 시점에 값이 그대로 박힌다(NEXT_PUBLIC_ 접두사의 뜻). lib/api.ts 의 API_BASE_URL 과 같은 방식.
 *
 * ⚠️ process.env.NEXT_PUBLIC_* 는 <통짜 표현식>으로 써야 치환된다.
 *    구조분해하거나 변수로 키를 만들면 undefined 가 된다.
 * ⚠️ 값을 바꾸면 dev 서버를 다시 띄워야 반영된다.
 */
const TOSS_CLIENT_KEY = process.env.NEXT_PUBLIC_TOSS_CLIENT_KEY ?? "";

export default function BillingPage() {
  const router = useRouter();

  /*
   * 상태를 뭉치지 않고 나눈 이유는 대시보드 화면과 같다 —
   * "아직 안 불러옴" 과 "불러왔는데 카드가 없음" 은 화면에 다르게 보여야 한다.
   * 전자는 "불러오는 중…", 후자는 "아직 등록된 카드가 없습니다" + 등록 버튼이다.
   */
  const [data, setData] = useState<BillingMethodResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  /* 결제창을 여는 중. 연타로 창이 두 번 뜨는 것을 막는다. */
  const [opening, setOpening] = useState(false);
  /* 삭제 확인 패널이 열렸는가. window.confirm 을 대신한다(handleDelete 주석 참고). */
  const [armed, setArmed] = useState(false);
  const [deleting, setDeleting] = useState(false);

  /*
   * 착지 처리를 이미 했는가. <상태가 아니라 ref 다> — 이 값이 바뀐다고 화면을 다시 그릴
   * 필요가 없고, 오히려 다시 그리면 안 된다.
   *
   * 왜 필요한가: 개발 모드의 React StrictMode 는 effect 를 일부러 두 번 실행한다
   * (setup → cleanup → setup). 가드가 없으면 <일회용인 authKey 가 두 번 POST 된다.>
   * 두 번째는 토스가 거절하므로, 방금 카드를 성공적으로 등록한 화면에 빨간 오류가 뜬다.
   * ref 는 같은 컴포넌트 인스턴스에서 그대로 살아남아 두 번째 실행을 막아준다.
   */
  const landedRef = useRef(false);

  /**
   * 서버가 아는 현재 상태를 가져온다.
   *
   * useCallback 으로 감싸는 이유: 아래 useEffect 의 의존성 배열에 이 함수가 들어가는데,
   * 매 렌더마다 새 함수가 만들어지면 의존성이 매번 바뀐 것으로 보여 effect 가 무한히 돈다.
   * 바깥 값을 쓰지 않으므로 의존성은 빈 배열이고, 따라서 이 함수는 <항상 같은 함수>다.
   */
  const load = useCallback(async () => {
    try {
      setData(await api.billing.getBillingMethod());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "결제 수단을 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // StrictMode 의 두 번째 실행을 여기서 끊는다 (landedRef 주석 참고).
    if (landedRef.current) return;
    landedRef.current = true;

    void (async () => {
      /*
       * 🔴 useSearchParams() 를 <일부러 안 쓴다.>
       *
       * Next 문서(01-app/.../use-search-params.md)가 명시한다 — 정적으로 프리렌더되는
       * 페이지에서 Suspense 경계 없이 쓰면 production 빌드가
       * "Missing Suspense boundary with useSearchParams" 로 <실패>한다.
       * 경계를 두려면 이 페이지를 컴포넌트 둘로 쪼개야 한다.
       *
       * 우리가 필요한 건 "돌아온 직후 딱 한 번 읽고 즉시 지우는" 것뿐이라 구독이 필요 없다.
       * effect 안이므로 여기는 반드시 브라우저다 — window 가 없을 걱정이 없다.
       */
      const params = new URLSearchParams(window.location.search);
      const authKey = params.get("authKey");
      const failCode = params.get("code");

      /*
       * 착지 결과를 <먼저 계산>하고 setState 는 아래 await 뒤에 몰아서 한다.
       * 이렇게 두면 eslint 의 react-hooks/set-state-in-effect 규칙과도 맞고
       * ("effect 에서 곧바로 setState 하는" 모양을 만들지 않는다),
       * 분기마다 "여기서 로딩을 언제 끄더라" 를 따로 챙길 필요도 없어진다.
       */
      let landedError: string | null = null;
      let landedNotice: string | null = null;

      if (failCode) {
        // 토스가 실패 사유를 한국어 message 로 실어 보낸다. 우리가 다시 쓰지 않고 그대로 보여준다.
        landedError =
          params.get("message") ??
          "카드 등록에 실패했습니다. 카드를 확인한 뒤 다시 시도해주세요.";
      } else if (authKey) {
        try {
          /*
           * customerKey 가 비어 오면 서버가 @NotBlank 로 400 을 준다 — 조용히 넘어가지 않는다.
           * 어차피 서버는 이 값을 신뢰하지 않고 <대조만> 하므로, 여기서 미리 판단할 것이 없다.
           */
          await api.billing.registerBillingMethod(authKey, params.get("customerKey") ?? "");
          landedNotice = "카드를 등록했습니다.";
        } catch (e) {
          landedError = e instanceof ApiError ? e.message : "카드를 등록하지 못했습니다.";
        }
      }

      /*
       * 🔴 URL 을 비운다. 안 비우면 새로고침 한 번에 <이미 소모된 authKey> 가 다시 POST 되고,
       *    토스가 그걸 거절해서 방금 성공한 화면에 빨간 오류가 뜬다.
       *    authKey 는 한 번만 쓸 수 있는 값이다 — 브라우저 주소창에 남겨둘 이유가 없다.
       *    같은 라우트로의 replace 라 컴포넌트는 다시 마운트되지 않는다.
       */
      if (failCode || authKey) router.replace("/billing");

      /*
       * 등록 응답에도 카드 정보가 들어 있지만 <쓰지 않고> 다시 조회한다.
       * 화면에 보이는 카드의 출처를 GET 한 곳으로 묶어두면 "등록 직후만 다르게 보이는" 버그가
       * 생길 자리가 없어진다. 왕복 한 번은 등록 직후에만 일어나므로 값싸다.
       */
      await load();
      if (landedError) setError(landedError);
      if (landedNotice) setNotice(landedNotice);
    })();
  }, [load, router]);
  /*
   * 의존성에 load 와 router 를 적는 이유: 이 안에서 쓰는 <바깥 값>이 정확히 그 둘이다.
   * 둘 다 사실상 고정이라(load 는 useCallback [], router 는 Next 가 안정적으로 준다)
   * 이 effect 는 마운트 때 한 번만 돈다. 그럼에도 배열을 []로 비우지 않는 이유는,
   * 비우면 lint 가 "빠진 의존성" 을 경고하고 <나중에 load 가 인자를 받게 바뀌었을 때>
   * 조용히 옛 함수를 계속 쓰는 버그가 나기 때문이다.
   *
   * landedRef 는 의존성에 넣지 않는다 — ref 는 값이 바뀌어도 렌더를 유발하지 않는
   * "상자" 라서 React 가 의존성으로 추적하지 않는다(lint 도 요구하지 않는다).
   *
   * ⚠️ 이 파일은 이 저장소의 다른 화면과 달리 cancelled 플래그를 쓰지 않는다.
   *    landedRef 가드와 함께 쓰면 StrictMode 에서 <첫 실행의 cleanup 이 cancelled 를 켜고
   *    두 번째 실행은 가드에 막혀> 아무것도 그려지지 않기 때문이다.
   *    화면을 떠난 뒤 응답이 와서 setState 가 불리는 것은 React 18+ 에서 무시된다(경고도 없다).
   */

  /**
   * 토스 결제창을 띄워 카드 등록을 요청한다.
   *
   * 🔴 카드번호는 <토스 창 안에서만> 존재한다. 우리 페이지도 우리 서버도 만지지 않는다.
   *    우리가 받는 건 authKey 하나뿐이다 — PCI-DSS 대상 데이터를 우리가 갖지 않는다는 뜻이다.
   */
  async function handleOpenBillingWindow() {
    if (!data) return;
    setError(null);
    setNotice(null);
    setOpening(true);
    try {
      const tossPayments = await loadTossPayments(TOSS_CLIENT_KEY);

      /*
       * ⚠️ `.widgets()` 가 아니라 `.payment()` 다. 가장 헷갈리기 쉬운 자리다.
       *    `.widgets()` 는 주문서형·결제창형(결제위젯) 쪽이고 <자동결제 등록 메서드가 아예 없다.>
       *    키 세트도 다르다 — 자동결제는 API 개별 연동 키(test_ck_)를 쓰고,
       *    결제위젯 키(test_gck_)를 넣으면 SDK 가 NotSupportedWidgetKeyError 를 던진다.
       */
      const payment = tossPayments.payment({ customerKey: data.customerKey });

      await payment.requestBillingAuth({
        method: "CARD",
        /*
         * 🔴 successUrl·failUrl 은 <오리진을 포함해야 한다>(토스 요구).
         *    경로만 주면 IncorrectSuccessUrlFormatError 가 난다.
         *    성공·실패 모두 이 화면으로 돌려보낸다 — 착지 처리 코드가 위 useEffect 한 곳뿐이라
         *    화면을 나누면 같은 로직을 두 벌 갖게 된다.
         *    성공이면 ?customerKey=..&authKey=.. , 실패면 ?code=..&message=.. 가 붙어 온다.
         */
        successUrl: `${window.location.origin}/billing`,
        failUrl: `${window.location.origin}/billing`,
      });
    } catch (e) {
      /*
       * 사용자가 창을 그냥 닫으면 SDK 가 USER_CANCEL 을 던진다. 이건 오류가 아니라 <취소>다.
       * 빨간 문구를 띄우면 "닫았을 뿐인데 뭐가 고장났나" 로 읽힌다.
       *
       * 에러 객체의 모양을 확신할 수 없어(실제 SDK 는 CDN 에서 오고 타입이 없다)
       * code 를 조심스럽게 꺼낸다.
       */
      const code =
        typeof e === "object" && e !== null && "code" in e
          ? String((e as { code: unknown }).code)
          : "";
      if (code !== "USER_CANCEL") {
        setError(
          e instanceof Error
            ? e.message
            : "카드 등록창을 열지 못했습니다. 잠시 후 다시 시도해주세요.",
        );
      }
      setOpening(false);
    }
    // 성공하면 브라우저가 토스로 이동하므로 이 아래에 도달하지 않는다. opening 을 끄지 않는 게 맞다.
  }

  /*
   * 🔴 window.confirm 을 쓰지 않는 이유 (2026-08-10, 문서 삭제에서 겪었다)
   * ─────────────────────────────────────────────────────────────────────
   * 크롬은 같은 페이지에서 대화상자가 반복되면 "추가 대화상자를 만들지 않도록 차단"
   * 체크박스를 띄운다. 켜지면 confirm() 은 <항상 false> 를 돌려주고, 요청조차 안 나가고,
   * 오류도 안 뜬다. 밖에서 보면 "버튼이 고장났다" 와 구별할 수 없다.
   * 그래서 봇 삭제(settings)와 같은 <인라인 패널>을 쓴다.
   *
   * ⚠️ 실패해도 load() 를 부르지 않는다. 서버는 <토스를 먼저> 부르고 우리 행을 나중에 지우므로,
   *    503(토스 5xx)이면 카드가 그대로 남아 있다. 다시 조회하면 같은 카드가 다시 그려질 뿐이고,
   *    "지워진 것 같은데 남아 있네" 라는 깜빡임만 만든다. 오류만 띄우고 화면은 그대로 둔다.
   */
  async function handleDelete() {
    setDeleting(true);
    setError(null);
    setNotice(null);
    try {
      await api.billing.deleteBillingMethod();
      setArmed(false);
      setNotice("카드를 삭제했습니다.");
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "카드를 삭제하지 못했습니다.");
      setArmed(false);
    } finally {
      setDeleting(false);
    }
  }

  if (loading) return <p className="text-sm text-muted">불러오는 중…</p>;
  if (!data) {
    return (
      <p role="alert" className="text-sm text-danger">
        {error ?? "결제 수단을 불러오지 못했습니다."}
      </p>
    );
  }

  return (
    <>
      <PageHeader
        title="결제 수단"
        description="자동결제에 쓸 카드를 한 장 등록합니다. 카드 번호는 토스페이먼츠 결제창에서만 입력되며 AllDap 서버에는 저장되지 않습니다."
      />

      {/*
        🔴 거짓 완성 금지. 지금은 토스 <테스트 키>로만 동작한다 — 라이브 전환에는
        전자결제 계약 + 자동결제 추가 계약이 필요하고 둘 다 사업자등록이 전제다.
        적어두지 않으면 사용자는 진짜 카드를 넣고 결제가 된다고 믿는다.
        같은 이유로 이 화면에는 <금액이 한 글자도 없다> — /pricing 이 "금액이 아직 없다" 고
        말하고 있어서, 여기서만 있는 척하면 화면끼리 거짓말을 하게 된다.
        선례: 봇 설정의 "저장만 되고 답변에는 반영되지 않습니다" 경고와 같은 자리다.
      */}
      <p className="mt-4 rounded-md border border-warning bg-warning-surface px-3 py-2 text-xs text-warning">
        ⚠️ 지금은 <b>테스트 환경</b>입니다. 카드를 등록해도 <b>실제로 결제되지 않습니다.</b>
      </p>

      {error && (
        <p
          role="alert"
          className="mt-4 rounded-md border border-danger bg-danger-surface px-3 py-2 text-sm text-danger"
        >
          {error}
        </p>
      )}
      {notice && <p className="mt-4 text-sm text-success">{notice}</p>}

      <Section title="등록된 카드">
        {data.method ? (
          <>
            <dl className="grid grid-cols-3 gap-3">
              <div>
                <dt className="text-xs text-muted">카드사</dt>
                <dd className="mt-1 text-sm font-medium">{data.method.issuerName}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted">카드 번호</dt>
                <dd className="mt-1 font-mono text-sm font-medium">
                  {data.method.cardNumberMasked}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted">등록일</dt>
                <dd className="mt-1 text-sm font-medium">
                  {new Date(data.method.registeredAt).toLocaleDateString("ko-KR")}
                </dd>
              </div>
            </dl>
            {/*
              카드 <교체>는 만들지 않았다. 삭제 후 재등록으로 같은 일이 되고,
              상태 전이가 하나 늘면 그만큼 틀릴 자리가 는다. 계정당 한 장은 DB 의
              UNIQUE(user_id) 가 보장하므로 등록 버튼을 여기서 숨긴다(눌러도 409 다).
            */}
            <p className="text-xs text-muted">
              카드를 바꾸려면 아래에서 지운 뒤 다시 등록해주세요. 계정당 한 장만 등록할 수 있습니다.
            </p>
          </>
        ) : (
          <>
            <p className="text-sm text-muted">아직 등록된 카드가 없습니다.</p>
            <button
              type="button"
              onClick={() => void handleOpenBillingWindow()}
              disabled={opening || !TOSS_CLIENT_KEY}
              className="rounded-md bg-foreground px-4 py-2 text-sm font-medium text-surface disabled:opacity-50"
            >
              {opening ? "결제창을 여는 중…" : "카드 등록"}
            </button>
            {/*
              키가 없으면 버튼이 조용히 실패하는 대신 <무엇을 어떻게 하면 되는지>를 말한다.
              이 저장소의 에러 규약(PRD §10.3)을 화면 안내에도 그대로 적용한 것이다.
            */}
            {!TOSS_CLIENT_KEY && (
              <p role="alert" className="text-xs text-danger">
                <code>NEXT_PUBLIC_TOSS_CLIENT_KEY</code> 가 설정되지 않았습니다.{" "}
                <code>web/.env.local</code> 에 토스 <b>API 개별 연동</b> 클라이언트 키(
                <code>test_ck_…</code>)를 넣고 개발 서버를 다시 띄워주세요.
              </p>
            )}
          </>
        )}
      </Section>

      {data.method && (
        <Section title="위험 구역">
          {/* 🔴 "토스페이먼츠에서도 함께 폐기됩니다" 는 사실이다 —
              토스에 DELETE /v1/billing/{billingKey} 가 있고 서버가 그걸 먼저 부른다.
              (설계 초안은 폐기 API 가 없다고 적었는데 문서를 직접 확인해 뒤집었다) */}
          <p className="text-xs text-muted">
            등록된 카드를 삭제합니다. <b>토스페이먼츠에서도 함께 폐기됩니다.</b>
          </p>

          {!armed ? (
            <button
              type="button"
              onClick={() => setArmed(true)}
              className="rounded-md border border-danger px-3 py-1.5 text-sm text-danger"
            >
              카드 삭제
            </button>
          ) : (
            /*
              confirm 이 보여주던 것을 그대로 화면에 옮겼다 — <어느 카드인지>와 <무엇이 사라지는지>.
              카드사와 마스킹 번호를 다시 적는 이유: 지우기 직전에 한 번 더 눈으로 확인시킨다.
            */
            <div className="rounded-md border border-danger bg-danger-surface p-3">
              <p className="text-sm">
                <b>
                  {data.method.issuerName} {data.method.cardNumberMasked}
                </b>{" "}
                카드를 정말 삭제할까요?
              </p>
              <p className="mt-1 text-xs">
                토스페이먼츠에서도 함께 폐기되어 <b>되돌릴 수 없습니다.</b> 다시 쓰려면 카드를
                새로 등록해야 합니다.
              </p>
              <div className="mt-3 flex gap-2">
                {/* 취소를 <먼저> 둔다. 습관적으로 왼쪽을 누르는 사람이 실수로 지우지 않도록
                    (봇 설정 화면과 같은 규칙이다). */}
                <button
                  type="button"
                  onClick={() => setArmed(false)}
                  disabled={deleting}
                  className="rounded-md border border-subtle bg-surface px-3 py-1.5 text-sm disabled:opacity-50"
                >
                  취소
                </button>
                <button
                  type="button"
                  onClick={() => void handleDelete()}
                  disabled={deleting}
                  className="rounded-md bg-danger px-3 py-1.5 text-sm font-medium text-surface disabled:opacity-50"
                >
                  {deleting ? "삭제 중…" : "삭제합니다"}
                </button>
              </div>
            </div>
          )}
        </Section>
      )}
    </>
  );
}
