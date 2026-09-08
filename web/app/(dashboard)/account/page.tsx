"use client";

/*
 * `/account` — 마이페이지. 결제 수단(카드)과 요금제를 한 화면에서 관리한다.
 *
 * 2026-09-08 에 `/billing` 에서 옮겨 왔다. 옮긴 이유: 카드와 요금제는 <같은 결정>의 앞뒤다 —
 * "어떤 요금제를 쓸지" 를 고르면 곧바로 "어느 카드로 낼지" 가 따라온다. 화면이 둘로 나뉘어 있으면
 * 사용자가 그 사이를 오가야 한다. 옛 주소는 이 화면으로 넘긴다(`app/(dashboard)/billing/page.tsx`).
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
 *   GET    /api/billing/methods               → BillingMethodsResponse
 *   POST   /api/billing/methods               → BillingMethodsResponse  (authKey 로 빌링키 발급)
 *   DELETE /api/billing/methods/{id}          → 204
 *   PUT    /api/billing/methods/{id}/default  → BillingMethodsResponse
 * ─────────────────────────────────────────────────────────────────────────────
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { loadTossPayments } from "@tosspayments/tosspayments-sdk";
import { ApiError, api } from "@/lib/api";
import type { BillingCard, BillingMethodsResponse, PlanId } from "@/lib/types";
import { PLANS } from "@/lib/plans";
import { PageHeader } from "@/components/PageHeader";
import { CardFace } from "@/components/CardFace";

/*
 * 빌드 시점에 값이 그대로 박힌다(NEXT_PUBLIC_ 접두사의 뜻). lib/api.ts 의 API_BASE_URL 과 같은 방식.
 *
 * ⚠️ process.env.NEXT_PUBLIC_* 는 <통짜 표현식>으로 써야 치환된다.
 *    구조분해하거나 변수로 키를 만들면 undefined 가 된다.
 * ⚠️ 값을 바꾸면 dev 서버를 다시 띄워야 반영된다.
 */
const TOSS_CLIENT_KEY = process.env.NEXT_PUBLIC_TOSS_CLIENT_KEY ?? "";

/*
 * 계정당 카드 상한. 서버(BillingService.MAX_METHODS)와 같은 값이다.
 * 여기 두는 이유는 <버튼을 미리 감추기> 위해서일 뿐, 판단은 서버가 한다(넘으면 409).
 * 두 값이 어긋나면 화면이 허용한 등록을 서버가 거부하는 것으로 드러난다 — 조용히 틀리진 않는다.
 */
const MAX_METHODS = 5;

/*
 * "취소"라는 같은 사용자 의도가 두 개의 다른 경로로 들어온다 — 하나로 묶어 <한 번만 판정>한다.
 *   ① 결제창의 X 버튼 → SDK 가 예외를 던진다 → 코드가 "USER_CANCEL"(handleOpenBillingWindow 의 catch)
 *   ② 토스 창 <안의> 취소 버튼 → failUrl 로 리다이렉트한다 → 코드가 "PAY_PROCESS_CANCELED"(토스 문서 명시)
 * 둘 다 "닫았을 뿐"인데 빨간 오류를 띄우면 "뭐가 고장났나"로 읽힌다. 리터럴을 두 곳에 따로 두면
 * 나중에 한쪽만 코드가 바뀌거나(예: 새 취소 사유 추가) 한쪽만 고치는 사고가 난다 — Set 하나로 공유한다.
 * ⚠️ PAY_PROCESS_ABORTED(결제 승인 실패)·REJECT_CARD_COMPANY(카드사 거절)는 여기 넣지 않는다.
 *    둘은 진짜 실패라 사용자가 원인을 알아야 한다.
 */
const CANCEL_CODES = new Set(["USER_CANCEL", "PAY_PROCESS_CANCELED"]);

export default function AccountPage() {
  const router = useRouter();

  /*
   * 상태를 뭉치지 않고 나눈 이유는 대시보드 화면과 같다 —
   * "아직 안 불러옴" 과 "불러왔는데 카드가 없음" 은 화면에 다르게 보여야 한다.
   */
  const [data, setData] = useState<BillingMethodsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  /* 결제창을 여는 중. 연타로 창이 두 번 뜨는 것을 막는다. */
  const [opening, setOpening] = useState(false);
  /*
   * 삭제 확인이 열린 카드의 id. window.confirm 을 대신한다(handleDelete 주석 참고).
   * 카드가 여러 장이라 boolean 이 아니라 <어느 카드인지> 를 들고 있어야 한다 — boolean 이면
   * 확인 패널이 모든 카드 아래에 동시에 열린다.
   */
  const [armedId, setArmedId] = useState<string | null>(null);
  /* 요청이 나가 있는 카드의 id. 그 카드의 버튼만 잠근다 — 목록 전체를 잠그면 무관한 카드까지 멈춘다. */
  const [busyId, setBusyId] = useState<string | null>(null);
  /* 지금 지우는 중인 카드. 퇴장 애니메이션을 <요청이 나가 있는 동안> 돌리는 데만 쓴다. */
  const [deletingId, setDeletingId] = useState<string | null>(null);
  /* 방금 등록한 카드. 그 한 장에만 등장 애니메이션을 붙인다(globals.css 주석 참고). */
  const [justAddedId, setJustAddedId] = useState<string | null>(null);

  /*
   * 지금 요금제. 카드 목록과 <따로> 들고 있는 이유: 출처가 다른 API 이고(GET /api/plan),
   * 한쪽이 실패해도 다른 쪽은 보여줘야 하기 때문이다 — 카드를 못 불러온 것과 요금제를 못 불러온 것은
   * 사용자가 할 수 있는 일이 다르다.
   * `null` 은 <아직/못 불러옴> 이다. 로딩이 끝난 뒤에도 null 이면 요금제 칸만 안내 문구로 바뀐다.
   */
  const [plan, setPlan] = useState<PlanId | null>(null);
  /* 요금제 변경 요청이 나가 있는 동안. 두 버튼을 함께 잠근다 — 어느 쪽을 눌러도 같은 값을 바꾼다. */
  const [planBusy, setPlanBusy] = useState(false);

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
   * 서버가 아는 현재 목록을 가져온다. loading 은 여기서 끄지 않는다 — 부르는 쪽이 끈다
   * (착지 effect 는 등록 응답으로 목록을 이미 받은 경우 이 함수를 건너뛰기 때문이다).
   *
   * useCallback 으로 감싸는 이유: 아래 useEffect 의 의존성 배열에 이 함수가 들어가는데,
   * 매 렌더마다 새 함수가 만들어지면 의존성이 매번 바뀐 것으로 보여 effect 가 무한히 돈다.
   * 바깥 값을 쓰지 않으므로 의존성은 빈 배열이고, 따라서 이 함수는 <항상 같은 함수>다.
   */
  const load = useCallback(async () => {
    try {
      setData(await api.billing.listBillingMethods());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "결제 수단을 불러오지 못했습니다.");
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
      /*
       * 요금제 조회를 <먼저 띄워두고> 카드 쪽 일을 한다. 두 요청이 겹쳐 돌아 화면이 한 번에 뜬다.
       * ⚠️ `.catch` 를 <이 자리에서> 붙이는 것이 중요하다. 아래에서 await 할 때까지 미뤄두면
       *    그 사이 거절된 프로미스가 "처리되지 않은 거부" 로 콘솔에 오류를 남긴다.
       *    실패는 null 로 바꿔 요금제 칸에서만 안내한다 — 카드 화면까지 같이 죽이지 않는다.
       */
      const planPromise = api.plan
        .getPlan()
        .then((r) => r.plan)
        .catch(() => null);

      const params = new URLSearchParams(window.location.search);
      const authKey = params.get("authKey");
      const failCode = params.get("code");

      /*
       * 🔴 URL 을 <POST 하기 전에> 비운다.
       *    registerBillingMethod 는 토스 발급 + I/O 실패 시 1회 재시도까지 하므로 수 초가 걸린다.
       *    POST 가 끝난 뒤 비우면 그 몇 초 동안 주소창에 authKey 가 남아 있고, 그 창에서
       *    새로고침하면 <이미 소모된 authKey> 가 한 번 더 POST 된다 — 막으려던 바로 그 사고다.
       *    authKey·customerKey·failCode 는 이미 위 지역 변수에 담겨 있으므로 URL 을 먼저
       *    비워도 <클로저> 안의 값은 그대로 살아 있다. 같은 라우트로의 replace 라 컴포넌트도
       *    다시 마운트되지 않는다(= landedRef 가드가 다시 걸릴 일도 없다).
       */
      if (failCode || authKey) router.replace("/account");

      /*
       * 착지 결과를 <먼저 계산>하고 setState 는 아래 await 뒤에 몰아서 한다.
       * 이렇게 두면 eslint 의 react-hooks/set-state-in-effect 규칙과도 맞고
       * ("effect 에서 곧바로 setState 하는" 모양을 만들지 않는다),
       * 분기마다 "여기서 로딩을 언제 끄더라" 를 따로 챙길 필요도 없어진다.
       */
      let landedError: string | null = null;
      let landedNotice: string | null = null;
      /* 등록 응답이 목록을 실어 오므로, 성공했으면 다시 GET 하지 않고 그걸 그대로 쓴다. */
      let landedData: BillingMethodsResponse | null = null;

      if (failCode) {
        /*
         * 🔴 취소는 오류가 아니다 — CANCEL_CODES 참고. handleOpenBillingWindow 의 catch(SDK
         * 예외 경로)와 여기(failUrl 리다이렉트 경로)가 <같은 판정>을 공유해야 한다. 한쪽만
         * 걸러내면 "결제창의 X"는 조용한데 "토스 창 안의 취소 버튼"만 빨간 오류가 뜨는,
         * 사용자 입장에서 똑같은 취소 행동이 다르게 보이는 버그가 난다.
         */
        if (!CANCEL_CODES.has(failCode)) {
          // 토스가 실패 사유를 한국어 message 로 실어 보낸다. 우리가 다시 쓰지 않고 그대로 보여준다.
          landedError =
            params.get("message") ??
            "카드를 등록하지 못했습니다. 카드를 확인한 뒤 다시 시도해주세요.";
        }
      } else if (authKey) {
        try {
          /*
           * customerKey 가 비어 오면 서버가 @NotBlank 로 400 을 준다 — 조용히 넘어가지 않는다.
           * 어차피 서버는 이 값을 신뢰하지 않고 <대조만> 하므로, 여기서 미리 판단할 것이 없다.
           */
          landedData = await api.billing.registerBillingMethod(
            authKey,
            params.get("customerKey") ?? "",
          );
          landedNotice = "카드를 등록했습니다.";
        } catch (e) {
          landedError = e instanceof ApiError ? e.message : "카드를 등록하지 못했습니다.";
        }
      }

      if (landedData) {
        setData(landedData);
        /* 방금 등록한 카드는 <목록의 마지막>이다 — 서버가 등록 순서대로 내려준다. */
        const added = landedData.methods.at(-1);
        if (added) setJustAddedId(added.id);
      } else {
        await load();
      }
      setPlan(await planPromise);
      setLoading(false);
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
        successUrl: `${window.location.origin}/account`,
        failUrl: `${window.location.origin}/account`,
      });
    } catch (e) {
      /*
       * 사용자가 창을 그냥 닫으면 SDK 가 USER_CANCEL 을 던진다. 이건 오류가 아니라 <취소>다.
       * 빨간 문구를 띄우면 "닫았을 뿐인데 뭐가 고장났나" 로 읽힌다.
       * (토스 창 <안의> 취소 버튼은 이 경로를 안 타고 failUrl 로 리다이렉트한다 —
       *  그 경로의 판정은 위 useEffect 가 <같은 CANCEL_CODES> 로 내린다.)
       *
       * 에러 객체의 모양을 확신할 수 없어(실제 SDK 는 CDN 에서 오고 타입이 없다)
       * code 를 조심스럽게 꺼낸다.
       */
      const code =
        typeof e === "object" && e !== null && "code" in e
          ? String((e as { code: unknown }).code)
          : "";
      if (!CANCEL_CODES.has(code)) {
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
   * 그래서 봇 삭제(settings)와 같은 <인라인 확인>을 쓴다.
   *
   * ⚠️ 실패해도 기본은 load() 를 부르지 않는다. 서버는 <토스를 먼저> 부르고 우리 행을 나중에
   *    지우므로, 503(토스 5xx)이면 카드가 그대로 남아 있다. 다시 조회하면 같은 카드가 다시
   *    그려질 뿐이고, "지워진 것 같은데 남아 있네" 라는 깜빡임만 만든다. 오류만 띄우고 화면은
   *    그대로 둔다. 409(기본 카드인데 다른 카드가 남아 있음)도 같다 — 서버 문구가 다음 행동을 알려준다.
   *
   * 🔴 단, 404(BILLING_METHOD_NOT_FOUND)는 정반대다 — 서버 행이 <이미 없다>는 뜻이라
   *    화면을 그대로 두면 실제로는 없는 카드를 계속 그리게 된다(탭 두 개로 지운 경우 등).
   *    이때는 load() 로 다시 맞추고, "삭제하지 못했습니다" 대신 <이미 지워졌다>는 걸
   *    안내한다 — 사용자에게는 오류가 아니라 "화면이 낡아 있었을 뿐"이기 때문이다.
   */
  async function handleDelete(id: string) {
    setBusyId(id);
    setDeletingId(id);
    setError(null);
    setNotice(null);
    try {
      await api.billing.deleteBillingMethod(id);
      setNotice("카드를 삭제했습니다.");
      await load();
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        setNotice("이미 삭제된 카드입니다. 최신 상태로 다시 불러왔습니다.");
        await load();
      } else {
        setError(e instanceof ApiError ? e.message : "카드를 삭제하지 못했습니다.");
      }
    } finally {
      setArmedId(null);
      setBusyId(null);
      // 실패했으면 카드가 그대로 남아 있다. 퇴장 애니메이션을 걷어 도로 보이게 한다.
      setDeletingId(null);
    }
  }

  /*
   * 기본 카드 변경. 응답이 목록 전체라 load() 를 다시 부르지 않는다.
   * 404 는 삭제와 같은 이유로 다시 맞춘다(탭 두 개로 그 카드를 지운 경우).
   */
  async function handleSetDefault(id: string) {
    setBusyId(id);
    setError(null);
    setNotice(null);
    try {
      setData(await api.billing.setDefaultBillingMethod(id));
      setNotice("기본 카드를 바꿨습니다.");
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        setNotice("이미 삭제된 카드입니다. 최신 상태로 다시 불러왔습니다.");
        await load();
      } else {
        setError(e instanceof ApiError ? e.message : "기본 카드를 바꾸지 못했습니다.");
      }
    } finally {
      setBusyId(null);
    }
  }

  /*
   * 요금제 변경. 응답이 바뀐 요금제를 돌려주므로 다시 조회하지 않는다.
   *
   * 🔴 실패는 대부분 409(카드가 없는데 유료로 바꾸려 함)인데, 서버 문구가 이미
   *    "카드를 등록한 뒤 다시 선택해주세요" 라고 <다음에 할 일>까지 알려준다. 우리가 다시 쓰지 않는다.
   */
  async function handleChangePlan(next: PlanId) {
    setPlanBusy(true);
    setError(null);
    setNotice(null);
    try {
      const changed = await api.plan.changePlan(next);
      setPlan(changed.plan);
      // 조사는 "로" 로 고정한다 — 요금제 이름이 "무료"·"Pro" 라 둘 다 받침이 없어 "으로" 가 필요 없다.
      // 받침 있는 이름을 추가하면 이 줄을 함께 봐야 한다.
      setNotice(`요금제를 ${PLANS.find((p) => p.id === changed.plan)?.name ?? changed.plan}로 바꿨습니다.`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "요금제를 바꾸지 못했습니다.");
    } finally {
      setPlanBusy(false);
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

  const full = data.methods.length >= MAX_METHODS;
  /* 청구에 쓰이는 카드 = 기본 카드. 서버가 "카드가 있으면 기본이 정확히 하나" 를 보장하므로
     (V7 의 부분 유니크 인덱스) 여기서 여러 장을 걱정할 필요가 없다. */
  const billed = data.methods.find((m) => m.isDefault);

  return (
    <>
      <PageHeader title="마이페이지" />

      {error && (
        <p
          role="alert"
          className="mb-6 rounded-md border border-danger bg-danger-surface px-3 py-2 text-sm text-danger"
        >
          {error}
        </p>
      )}
      {/* role="status" — alert 이 아니다. 급한 오류가 아니라 상태 변화(등록·삭제 완료) 안내라
          스크린리더가 현재 흐름을 방해하지 않고 조용히 읽어주는 쪽이 맞다. */}
      {notice && (
        <p role="status" className="mb-6 text-sm text-success">
          {notice}
        </p>
      )}

      <section aria-labelledby="methods-heading">
        <div className="flex items-baseline justify-between border-b border-subtle pb-2">
          <h2 id="methods-heading" className="text-base font-semibold">
            결제 수단
          </h2>
          <span className="text-xs text-muted">
            {data.methods.length} / {MAX_METHODS}장
          </span>
        </div>

        <p className="mt-3 text-sm text-muted">
          청구는 <b className="font-medium text-foreground">기본</b> 카드로 한 장에만 이뤄집니다. 카드
          번호는 토스페이먼츠 결제창에서만 입력되며 AllDap 서버에는 저장되지 않습니다.
        </p>

        {/*
          🔴 거짓 완성 금지. 지금은 토스 <테스트 키>로만 동작한다 — 라이브 전환에는
          전자결제 계약 + 자동결제 추가 계약이 필요하고 둘 다 사업자등록이 전제다.
          적어두지 않으면 사용자는 진짜 카드를 넣고 결제가 된다고 믿는다.
          ⚠️ 선례로 들던 봇 설정의 "저장만 되고 답변에는 반영되지 않습니다" 경고는 2026-09-07 에
          없어졌다 — 기능이 붙었는데 문구를 안 고쳐 <되는 기능을 안 된다고> 안내하고 있었다.
          여기 경고도 같은 운명을 맞아야 한다: 라이브 전환이 끝나면 <반드시 이 문구를 지울 것.>
        */}
        <p className="mt-3 rounded-md border border-warning bg-warning-surface px-3 py-2 text-xs text-warning">
          ⚠️ 지금은 <b>테스트 환경</b>입니다. 카드를 등록해도 <b>실제로 결제되지 않습니다.</b>
        </p>

        {/*
          auto-fill + minmax 로 열 수를 정한다 — sm:/lg: 중단점을 쓰지 않는 이유는 카드가
          <고정 비율>이라 폭이 곧 높이이기 때문이다. 중단점으로 열을 정하면 화면 폭에 따라
          카드가 어정쩡하게 커지는 구간이 생긴다. minmax 는 "이보다 작아지면 한 장 줄인다" 라
          카드 크기가 항상 읽기 좋은 범위에 머문다.
        */}
        <ul className="mt-5 grid list-none grid-cols-[repeat(auto-fill,minmax(240px,1fr))] gap-5">
          {data.methods.map((card) => (
            <CardItem
              key={card.id}
              card={card}
              /* 기본 카드는 다른 카드가 남아 있으면 못 지운다 — 서버 규칙을 버튼에 미리 반영한다.
                 판단은 서버가 하고(409), 여기는 안내를 앞당길 뿐이다. */
              deletable={!card.isDefault || data.methods.length === 1}
              armed={armedId === card.id}
              busy={busyId === card.id}
              leaving={deletingId === card.id}
              entering={justAddedId === card.id}
              onArm={() => setArmedId(armedId === card.id ? null : card.id)}
              onDelete={() => handleDelete(card.id)}
              onSetDefault={() => handleSetDefault(card.id)}
            />
          ))}

          {!full && (
            <li>
              {/*
                "추가" 를 목록 밖의 버튼이 아니라 <카드 자리> 로 둔다. 실제로 생길 물건의 크기와
                자리를 미리 보여주므로 무엇이 추가되는지가 분명하고, 그리드 리듬도 안 깨진다.
              */}
              <button
                type="button"
                onClick={handleOpenBillingWindow}
                disabled={opening}
                className="flex aspect-[1.586] w-full flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-subtle text-sm text-muted transition-colors hover:border-foreground hover:text-foreground disabled:opacity-50"
              >
                <span aria-hidden className="text-2xl leading-none">
                  +
                </span>
                {opening ? "결제창을 여는 중…" : "카드 추가"}
              </button>
            </li>
          )}
        </ul>

        {full && (
          <p className="mt-4 text-xs text-muted">
            카드는 최대 {MAX_METHODS}장까지 등록할 수 있습니다. 쓰지 않는 카드를 삭제하면 추가할 수
            있습니다.
          </p>
        )}
      </section>

      <section aria-labelledby="plan-heading" className="mt-12">
        <div className="flex items-baseline justify-between border-b border-subtle pb-2">
          <h2 id="plan-heading" className="text-base font-semibold">
            요금제
          </h2>
          <Link href="/pricing" className="text-xs text-muted underline hover:text-foreground">
            요금제 보기
          </Link>
        </div>

        {/*
          🔴 이 자리에는 이제 <금액이 있다.> B2 까지는 "청구되지 않을 돈이 청구될 것처럼 읽힌다" 며
             금액을 뺐는데, 요금제를 <고르는> 화면에서 값을 감추면 무엇을 고르는지 알 수 없다.
             대신 <청구가 없다는 사실>을 아래 경고로 같은 자리에 붙인다 — 감추는 대신 말한다.
             ⚠️ /dashboard 의 사용량 카드는 여전히 금액을 <계산하지> 않는다. 거기서 금액이 나오면
                "이번 달에 이만큼 나간다" 로 읽히는데 그건 사실이 아니다. 고르는 값과 청구되는 값은 다르다.

             숫자의 원본은 lib/plans.ts 하나다. 여기에 숫자를 직접 적지 않는다 —
             /pricing 과 이 화면이 다른 금액을 말하는 일이 생길 자리를 만들지 않는다.
        */}
        {plan === null ? (
          <p className="mt-4 text-sm text-muted">
            요금제를 불러오지 못했습니다. 화면을 새로고침해주세요. (카드 관리는 위에서 계속 쓸 수 있습니다)
          </p>
        ) : (
          <>
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              {PLANS.map((p) => {
                const current = p.id === plan;
                /* 카드가 없으면 유료로 못 바꾼다 — 서버 규칙(409)을 버튼에 미리 반영한다.
                   판단은 서버가 하고, 여기는 왜 안 되는지를 앞당겨 알려줄 뿐이다. */
                const blocked = p.monthlyPriceKrw > 0 && data.methods.length === 0;
                return (
                  <article
                    key={p.id}
                    className={`rounded-lg border bg-surface p-5 ${
                      current ? "border-foreground" : "border-subtle"
                    }`}
                  >
                    <div className="flex items-baseline justify-between">
                      <p className="text-xs font-medium tracking-[0.18em] text-muted">{p.name}</p>
                      {current && (
                        <span className="rounded border border-success px-1.5 py-0.5 text-xs font-medium text-success">
                          사용 중
                        </span>
                      )}
                    </div>
                    <p className="mt-2 text-2xl font-bold tracking-[-0.02em]">
                      {p.monthlyPriceKrw.toLocaleString("ko-KR")}원
                      <span className="ml-1 text-sm font-normal text-muted">/월</span>
                    </p>
                    <dl className="mt-4 space-y-1.5 text-sm">
                      <div className="flex justify-between gap-4">
                        <dt className="text-muted">답변</dt>
                        <dd className="font-medium">
                          월 {p.includedAnswers.toLocaleString("ko-KR")}건
                        </dd>
                      </div>
                      <div className="flex justify-between gap-4">
                        <dt className="text-muted">품질 평가</dt>
                        <dd className="font-medium">월 {p.includedEvalRuns}회</dd>
                      </div>
                      <div className="flex justify-between gap-4">
                        <dt className="text-muted">포함량 초과 답변</dt>
                        <dd className="font-medium">
                          {p.overageAnswerKrw === null
                            ? "한도에서 멈춤"
                            : `건당 ${p.overageAnswerKrw}원`}
                        </dd>
                      </div>
                    </dl>

                    {!current && (
                      <>
                        <button
                          type="button"
                          onClick={() => handleChangePlan(p.id)}
                          disabled={planBusy || blocked}
                          className="mt-4 w-full rounded-md bg-foreground px-4 py-2 text-sm font-medium text-surface disabled:opacity-50"
                        >
                          {planBusy ? "바꾸는 중…" : `${p.name}로 바꾸기`}
                        </button>
                        {blocked && (
                          <p className="mt-2 text-xs text-muted">
                            유료 요금제로 바꾸려면 카드를 먼저 등록해주세요.
                          </p>
                        )}
                      </>
                    )}
                  </article>
                );
              })}
            </div>

            <p className="mt-3 text-xs text-muted">모든 금액은 부가세 별도입니다.</p>

            {/* 어느 카드로 청구되는지를 <요금제 칸에서> 보여준다. 위 결제 수단에도 같은 표시가 있지만,
                "요금제를 고르는 순간" 사용자가 알고 싶은 것이 그것이라 여기서 한 번 더 말한다.
                기본 카드가 곧 청구 카드다 — 개념이 하나라 두 화면이 어긋날 수 없다(V7 설계). */}
            {billed && (
              <p className="mt-3 text-sm text-muted">
                청구 카드 ·{" "}
                <b className="font-medium text-foreground">
                  {billed.issuerName} {billed.cardNumberMasked}
                </b>{" "}
                — 위 결제 수단에서 기본 카드를 바꾸면 청구 카드도 함께 바뀝니다.
              </p>
            )}

            {/*
              🔴 거짓 완성 금지. 이 화면에서 가장 중요한 한 줄이다 — 위 카드들이 금액을 보여주므로
                 이 문구가 없으면 사용자는 "Pro 를 눌렀으니 29,000원이 나간다" 고 믿는다.
                 실제로는 users.plan 한 칸이 바뀔 뿐이고 청구는 4번 조각이라 아직 없다.
                 청구가 붙으면 <반드시 이 문구를 지울 것.> (봇 설정의 낡은 경고를 2026-09-07 에
                 뒤늦게 고친 전례가 있다 — 기능이 붙으면 그 기능을 <설명하는 자리>도 함께 고친다)
            */}
            <p className="mt-3 rounded-md border border-warning bg-warning-surface px-3 py-2 text-xs text-warning">
              ⚠️ 요금제를 바꿔도 <b>청구는 일어나지 않습니다.</b> 지금은 선택만 저장되며, 실제 결제와
              사용량 한도는 아직 연결되지 않았습니다.
            </p>
          </>
        )}
      </section>
    </>
  );
}

/*
 * 카드 한 장과 그 아래 조작 줄. 별도 파일로 빼지 않은 이유: 이 화면 밖에서 쓸 일이 없고,
 * 부모의 상태(어느 카드가 열렸나·바쁜가)와 짝이라 같이 읽는 편이 낫다.
 * <카드 면>은 다르다 — 그건 순수 표시라 components/CardFace.tsx 로 나가 있다.
 *
 * props 로 콜백을 받는 이유: 이 컴포넌트는 서버를 모른다. "삭제" 를 눌렀을 때 무엇이 일어나는지는
 * 부모(AccountPage)가 정한다 — 그래야 요청 상태·오류·목록 갱신이 한 곳에 모인다.
 */
function CardItem({
  card,
  deletable,
  armed,
  busy,
  leaving,
  entering,
  onArm,
  onDelete,
  onSetDefault,
}: {
  card: BillingCard;
  deletable: boolean;
  armed: boolean;
  busy: boolean;
  leaving: boolean;
  entering: boolean;
  onArm: () => void;
  onDelete: () => void;
  onSetDefault: () => void;
}) {
  /* 카드사 이름을 버튼 레이블에 넣는다 — 카드가 여러 장이라 "삭제" 만으로는
     스크린리더 사용자가 <어느 카드의> 삭제인지 알 수 없다. */
  const label = `${card.issuerName} ${card.cardNumberMasked}`;

  return (
    <li className={leaving ? "alldap-card-out" : entering ? "alldap-card-in" : undefined}>
      <div className="alldap-card">
        <CardFace card={card} />
      </div>

      {armed ? (
        /* 확인은 <카드 아래 같은 자리>에 그린다. 카드 위에 겹치면 무엇을 지우는지 가리고,
           카드 밖 새 영역에 띄우면 그리드 칸 높이가 흔들려 옆 카드까지 밀린다. */
        <div className="mt-2">
          <p className="text-xs text-danger">토스페이먼츠에 등록된 결제 정보도 함께 삭제됩니다.</p>
          <div className="mt-2 flex gap-2">
            <button
              type="button"
              onClick={onDelete}
              disabled={busy}
              className="rounded-md bg-danger px-3 py-1 text-xs font-medium text-surface disabled:opacity-50"
            >
              {busy ? "삭제하는 중…" : "삭제"}
            </button>
            <button
              type="button"
              onClick={onArm}
              disabled={busy}
              className="rounded-md border border-subtle px-3 py-1 text-xs"
            >
              취소
            </button>
          </div>
        </div>
      ) : (
        <div className="mt-2 flex items-center gap-3">
          {card.isDefault ? (
            /* 기본이라는 사실은 <카드 면>이 이미 말한다. 여기서 또 배지를 달면 같은 말이 두 번이라,
               대신 이 카드가 무엇을 하는 카드인지를 문장으로 적는다. */
            <span className="text-xs text-muted">이 카드로 청구됩니다</span>
          ) : (
            <button
              type="button"
              onClick={onSetDefault}
              disabled={busy}
              className="text-xs text-muted underline hover:text-foreground disabled:opacity-50"
            >
              기본으로
            </button>
          )}
          <button
            type="button"
            onClick={onArm}
            disabled={busy || !deletable}
            aria-label={`${label} 삭제`}
            title={deletable ? undefined : "다른 카드를 기본으로 지정한 뒤 삭제할 수 있습니다."}
            className="ml-auto text-xs text-danger underline disabled:opacity-40 disabled:no-underline"
          >
            삭제
          </button>
        </div>
      )}
    </li>
  );
}
