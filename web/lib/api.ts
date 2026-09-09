/**
 * Spring API(:8080) 호출 클라이언트.
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * ⚠️ 지금 이 파일의 함수들은 호출해도 전부 실패한다.
 *    Spring API 서버가 아직 없기 때문이다 (api/ 디렉터리는 W2에서 구현 예정).
 *    이 파일의 목적은 "호출 지점과 타입을 제자리에 놓아두는 것"이다.
 *    화면 코드는 여기 있는 함수 이름만 보고 작성하면 되고,
 *    W2에서 서버가 붙으면 이 파일은 (경로가 맞다면) 그대로 동작한다.
 * ─────────────────────────────────────────────────────────────────────────────
 *
 * 왜 fetch 를 직접 감싸고 axios 같은 라이브러리를 안 쓰나:
 *   ① 뼈대 단계에서 의존성을 늘리지 않기 위해
 *   ② Next.js 서버 컴포넌트에서도 fetch 는 그대로 쓸 수 있어서
 *   ③ 에러 포맷 파싱(PRD §10.3)만 한 군데에 모으면 충분해서
 */

import type {
  AuthResponse,
  BillingMethodsResponse,
  PlanId,
  PlanResponse,
  Bot,
  BotSummary,
  ChatMessage,
  ChatRequest,
  ChatResponse,
  Conflict,
  ConflictScan,
  ConversationSummary,
  CreateBotRequest,
  DocumentItem,
  EvalQuestion,
  EvalResult,
  EvalRun,
  LogsQuery,
  Paged,
  UnansweredSummary,
  UpdateBotRequest,
  Usage,
  Uuid,
  WidgetConfig,
} from "./types";
import { isTokenExpired } from "./token";

/**
 * 백엔드 주소. .env.local 에서 주입한다 (.env.local.example 참고).
 * NEXT_PUBLIC_ 접두사가 붙은 값만 브라우저 번들에 포함된다 — 비밀값은 절대 넣지 말 것.
 */
export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8080";

/* ───────────────────────── 에러 ───────────────────────── */

/**
 * PRD §10.3 에러 포맷을 담는 예외.
 *   { "error": { "code": "...", "message": "한국어 설명" } }
 *
 * message 에는 "무엇을 어떻게 하면 되는지"가 들어있다는 게 이 프로젝트의 규약이므로,
 * 화면에서는 이 값을 가공하지 말고 사용자에게 그대로 보여주면 된다.
 */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(code: string, message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }
}

/** 서버가 규약대로 응답하지 못한 경우(네트워크 단절, 500 HTML 페이지 등)의 기본 문구 */
const UNKNOWN_ERROR_MESSAGE =
  "서버와 통신하지 못했습니다. 잠시 후 다시 시도하시고, 계속 실패하면 관리자에게 문의해주세요.";

/**
 * 응답 본문에서 PRD §10.3 형태의 에러를 꺼낸다.
 * 형태가 안 맞으면(HTML 에러 페이지 등) 기본 문구로 대체한다.
 */
async function toApiError(response: Response): Promise<ApiError> {
  try {
    const body: unknown = await response.json();
    if (
      typeof body === "object" &&
      body !== null &&
      "error" in body &&
      typeof (body as { error: unknown }).error === "object" &&
      (body as { error: unknown }).error !== null
    ) {
      const err = (body as { error: { code?: unknown; message?: unknown } })
        .error;
      return new ApiError(
        typeof err.code === "string" ? err.code : "UNKNOWN",
        typeof err.message === "string" ? err.message : UNKNOWN_ERROR_MESSAGE,
        response.status,
      );
    }
  } catch {
    // JSON 이 아니었다 — 아래 기본 에러로 떨어진다.
  }
  return new ApiError("UNKNOWN", UNKNOWN_ERROR_MESSAGE, response.status);
}

/* ───────────────────────── 인증 토큰 보관 ───────────────────────── */

/**
 * JWT 보관 자리.
 *
 * ⚠️ 지금은 localStorage 를 쓴다. 뼈대이므로 가장 단순한 방법을 골랐을 뿐이고,
 *    보안상 최선은 아니다 (XSS 로 토큰이 통째로 털린다).
 * TODO(W2): 인증을 실제로 붙일 때 아래 중 하나로 확정할 것.
 *   (a) httpOnly + Secure 쿠키 — 권장. JS 가 토큰을 읽지 못해 XSS 에 강하다.
 *   (b) 메모리 보관 + refresh 토큰 — 새로고침 시 재발급 흐름이 필요.
 *   면접에서 "왜 localStorage 를 안 썼나"는 자주 나오는 질문이므로 근거를 남길 것.
 */
const TOKEN_STORAGE_KEY = "alldap.token";

/**
 * <b>쓸 수 있는</b> 토큰을 돌려준다. 보관돼 있어도 <b>기한이 지났으면 null</b> 이다.
 *
 * <h2>왜 "보관된 값" 이 아니라 "쓸 수 있는 값" 인가</h2>
 * 예전에는 localStorage 의 문자열을 그대로 돌려줬다. 그런데 이 값을 읽는 곳이 전부
 * <b>"지금 로그인 상태인가"</b> 를 묻는 자리다(대시보드 가드 · AuthLink · 로그인 화면의
 * 되돌리기 · PlanCards · 요청 헤더). 만료된 토큰은 그 질문에 <b>"아니오"</b> 다.
 * 문자열이 남아 있다는 사실 자체는 아무도 궁금해하지 않는다.
 *
 * 그래서 판정을 <b>여기 한 곳</b>에 둔다. 부르는 쪽마다 만료를 따로 검사하게 하면
 * 다섯 곳 중 한 곳을 빠뜨리고, 그러면 <b>화면들이 서로 다른 로그인 상태를 믿는다</b>
 * (헤더는 "로그인됨" 인데 대시보드는 튕기는 식).
 *
 * <h2>⚠️ 이건 서명 검증이 <아니다>. 프론트가 하는 것은 추정이다</h2>
 * 페이로드의 `exp` 만 읽는다. 서명은 확인하지 않고 <b>할 수도 없다</b>: 비밀키는 서버에만 있고,
 * 브라우저에 두면 그 순간 비밀이 아니게 된다. 즉 사용자가 localStorage 를 직접 고쳐
 * `exp` 를 미래로 바꾸면 이 함수는 속는다.
 * <b>그래도 된다.</b> 진짜 판정은 서버가 하고(`JwtService` 가 서명과 exp 를 다시 본다)
 * 위조 토큰은 401 로 떨어진다. 여기 검사의 목적은 보안이 아니라 <b>화면을 정직하게 만드는 것</b>이다:
 * 이미 못 쓰는 토큰으로 "대시보드" 버튼을 띄워놓고, 눌러 들어가면 401 을 보게 하지 않는 것.
 *
 * <h2>⚠️ 사용자 기기의 시계에 딸려 있다</h2>
 * `Date.now()` 는 <b>그 기기의</b> 시계다. 기기 시계가 24시간 이상 앞서 있으면(토큰 TTL 이 24h)
 * 갓 받은 토큰도 만료로 보여 로그인 직후 튕긴다. 그 정도로 틀어진 기기는 HTTPS 인증서부터
 * 깨지므로 실제로 겪을 가능성이 낮다고 보고 보정을 넣지 않았다. 넣는다면 여유(skew)를 두는 것이
 * 아니라 <b>서버 시각을 받아 맞추는</b> 쪽이 맞다. 여유는 "얼마나?" 에 근거가 없다.
 *
 * <h2>⚠️ useSyncExternalStore 와의 관계 (알고 남긴 것)</h2>
 * 이 함수는 `getSnapshot` 자리에 쓰인다. 그 자리는 원래 <b>같은 값을 돌려줘야</b> 하는데
 * 이 함수의 결과는 <b>시간에 딸려 있다</b>: 만료되는 그 순간을 사이에 두고 두 번 불리면
 * 문자열과 null 로 갈릴 수 있다. 실제로는 24시간에 한 번, 1밀리초 폭의 경계이고
 * 걸려도 결과는 React 의 개발 경고와 렌더 한 번이지 무한 루프가 아니다
 * (매번 새 객체를 만들어 진짜로 루프를 내는 경우와 달리 여기는 원시값이다).
 * 이 위험보다 <b>다섯 곳이 서로 다른 로그인 상태를 믿는 것</b>이 훨씬 나쁘다고 판단했다.
 */
export function getAccessToken(): string | null {
  // 서버 컴포넌트에서는 window 가 없다. 그래서 방어한다.
  if (typeof window === "undefined") return null;

  const token = window.localStorage.getItem(TOKEN_STORAGE_KEY);
  if (token === null) return null;

  // 🔴 "만료됐다" 와 "읽을 수 없다" 를 같은 null 로 뭉갠다. 이 저장소가 반복해 낸 버그가
  //    <원인이 다른 두 사실을 같은 값으로 뭉개는 것> 이라 일부러 짚어둔다:
  //    여기서 뭉개도 되는 이유는 부르는 쪽이 알고 싶은 것이 "지금 쓸 수 있나" 하나뿐이고,
  //    두 경우의 <다음 행동이 똑같이 "로그인 화면으로"> 이기 때문이다.
  return isTokenExpired(token) ? null : token;
}

export function setAccessToken(token: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(TOKEN_STORAGE_KEY, token);
  notifyTokenChanged();
}

export function clearAccessToken(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(TOKEN_STORAGE_KEY);
  notifyTokenChanged();
}

/* ── 토큰을 "외부 저장소"로 구독하기 ─────────────────────────────────────
 *
 * localStorage 는 React 바깥에 있는 상태다. 화면이 그 값을 읽어 렌더에 쓰려면
 * "값이 바뀌면 알려달라"는 구독이 필요하고, React 는 그걸 위해 useSyncExternalStore 를 준다.
 *
 * <왜 useEffect + useState 로 안 하나.>
 * effect 안에서 setState 를 하면 렌더가 한 번 더 돌고(cascading render),
 * eslint 의 react-hooks/set-state-in-effect 가 이를 막는다. 규칙이 옳다 —
 * "바깥 저장소를 읽는 일"은 상태 복사가 아니라 구독으로 표현하는 게 맞다.
 *
 * 브라우저의 storage 이벤트는 <다른 탭>에서 바뀔 때만 발생한다.
 * 그래서 같은 탭의 로그인·로그아웃은 위 두 함수가 직접 알린다.
 */
const TOKEN_CHANGED_EVENT = "alldap:token-changed";

function notifyTokenChanged(): void {
  window.dispatchEvent(new Event(TOKEN_CHANGED_EVENT));
}

/** useSyncExternalStore 의 구독 함수. 정리 함수를 돌려줘야 한다. */
export function subscribeAccessToken(onChange: () => void): () => void {
  window.addEventListener("storage", onChange); // 다른 탭
  window.addEventListener(TOKEN_CHANGED_EVENT, onChange); // 같은 탭
  return () => {
    window.removeEventListener("storage", onChange);
    window.removeEventListener(TOKEN_CHANGED_EVENT, onChange);
  };
}

/**
 * 서버 렌더 · 하이드레이션 때 쓸 값. <null 이 아니라 undefined 다.>
 *
 * 서버에는 localStorage 가 없다. 그렇다고 여기서 null 을 주면 안 된다 —
 * React 는 이 값을 <서버 렌더뿐 아니라 하이드레이션 첫 렌더에도> 쓰기 때문이다.
 * (안 그러면 서버가 그린 HTML 과 클라이언트 첫 렌더가 어긋나 hydration mismatch 가 난다)
 *
 * 즉 null 을 주면 "토큰이 없다" 와 "아직 못 읽었다" 가 같은 값이 되고,
 * 가드가 첫 렌더에서 곧바로 /auth 로 튕긴다 — <로그인한 채 새로고침해도 로그아웃된다.>
 * 실제로 그 버그가 났고(2026-08-02 브라우저 실측), undefined 로 갈라서 고쳤다.
 *
 *   undefined = 아직 모름(하이드레이션 전)   null = 확실히 없음(비로그인)
 *
 * 하이드레이션이 끝나면 React 가 getAccessToken 으로 다시 읽어 렌더를 갱신한다.
 */
export function getAccessTokenServerSnapshot(): string | null | undefined {
  return undefined;
}

/* ───────────────────────── 요청 공통부 ───────────────────────── */

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  /** JSON 으로 직렬화해서 보낼 본문 */
  body?: unknown;
  /** 파일 업로드용. 이게 있으면 body 는 무시된다. */
  formData?: FormData;
  /**
   * 인증 헤더를 붙일지 여부. 기본 true.
   * 위젯 공개 API(/api/w/*)와 로그인·가입은 false 로 부른다.
   */
  auth?: boolean;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, formData, auth = true } = options;

  const headers: Record<string, string> = {};

  // JWT 를 싣는 자리. PRD §10.1: Authorization: Bearer {JWT}
  if (auth) {
    const token = getAccessToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }

  // 파일 업로드(multipart)일 때는 Content-Type 을 직접 넣으면 안 된다.
  // boundary 문자열은 브라우저가 만들어야 하기 때문이다.
  if (!formData && body !== undefined) {
    headers["Content-Type"] = "application/json";
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers,
      body: formData ?? (body !== undefined ? JSON.stringify(body) : undefined),
      // 뼈대 단계: 인증을 쿠키로 바꾸면 credentials: "include" 가 필요해진다.
      cache: "no-store",
    });
  } catch {
    // fetch 자체가 실패 = 서버가 안 떠 있거나 네트워크 문제.
    // W2 이전에는 이 경로로만 떨어지는 게 정상이다.
    throw new ApiError("NETWORK_ERROR", UNKNOWN_ERROR_MESSAGE, 0);
  }

  if (!response.ok) {
    throw await toApiError(response);
  }

  // 204 No Content (문서 삭제 등) 는 본문이 없다.
  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

/* ───────────────────────── 엔드포인트 ─────────────────────────
 * 경로는 PRD §10.1 "Spring 공개 API" 표를 그대로 옮긴 것이다.
 * 서버가 없으므로 전부 미검증 상태다.
 * ─────────────────────────────────────────────────────────── */

export const api = {
  /** 인증 (F-08) — 토큰이 아직 없으므로 auth: false */
  auth: {
    signup: (email: string, password: string, name: string) =>
      request<AuthResponse>("/api/auth/signup", {
        method: "POST",
        body: { email, password, name },
        auth: false,
      }),
    login: (email: string, password: string) =>
      request<AuthResponse>("/api/auth/login", {
        method: "POST",
        body: { email, password },
        auth: false,
      }),
  },

  /** 봇 (F-06) */
  bots: {
    /**
     * 목록만 {@link BotSummary} 다. 카드에 얹을 집계(문서 수·주간 대화 수·최근 평가 점수)가 붙는다.
     * 상세·생성·수정은 집계 없는 {@link Bot} 이고, 서버 DTO 도 같은 기준으로 갈라져 있다.
     *
     * 서버는 이 집계를 <b>쿼리 2번</b>(목록 1 + 집계 1)으로 만든다. 봇 개수와 무관하다.
     */
    list: () => request<BotSummary[]>("/api/bots"),
    create: (payload: CreateBotRequest) =>
      request<Bot>("/api/bots", { method: "POST", body: payload }),
    get: (botId: Uuid) => request<Bot>(`/api/bots/${botId}`),
    update: (botId: Uuid, payload: UpdateBotRequest) =>
      request<Bot>(`/api/bots/${botId}`, { method: "PATCH", body: payload }),
    remove: (botId: Uuid) =>
      request<void>(`/api/bots/${botId}`, { method: "DELETE" }),
  },

  /** 문서 (F-01, F-02) */
  documents: {
    /**
     * 업로드는 즉시 202 로 돌아오고 처리는 백그라운드에서 이어진다.
     * 그래서 업로드 직후에는 status 가 "pending" 이다. 화면은 list() 를 폴링해서 따라간다.
     * multipart 필드명은 Python 이 "file" 로 못박아뒀다 (ai-service/app/main.py).
     */
    upload: (botId: Uuid, file: File) => {
      const formData = new FormData();
      formData.append("file", file);
      return request<DocumentItem>(`/api/bots/${botId}/documents`, {
        method: "POST",
        formData,
      });
    },
    list: (botId: Uuid) =>
      request<DocumentItem[]>(`/api/bots/${botId}/documents`),
    /** 문서를 지우면 관련 청크도 연쇄 삭제된다 (DB의 ON DELETE CASCADE) */
    remove: (docId: Uuid) =>
      request<void>(`/api/documents/${docId}`, { method: "DELETE" }),
  },

  /** 테스트 채팅 (F-03) — 관리자가 위젯 공개 전에 검수하는 용도 */
  chat: {
    send: (botId: Uuid, payload: ChatRequest) =>
      request<ChatResponse>(`/api/bots/${botId}/chat`, {
        method: "POST",
        body: payload,
      }),
    /**
     * 👍(1) / 👎(-1)
     *
     * ⚠️ 본문 키가 `feedback` 이다. 뼈대에서는 `{ value }` 로 적혀 있었는데
     * Spring 의 `FeedbackRequest` 는 `{ feedback }` 을 받으므로 그대로 두면 400 이 났다.
     * 서버가 실제로 생긴 뒤 대조해서 고친 것 — 뼈대의 추정값은 이렇게 어긋날 수 있다.
     */
    feedback: (messageId: Uuid, feedback: 1 | -1) =>
      request<void>(`/api/messages/${messageId}/feedback`, {
        method: "POST",
        body: { feedback },
      }),
  },

  /** 대화 로그 (F-07) */
  logs: {
    list: (botId: Uuid, query: LogsQuery = {}) => {
      const params = new URLSearchParams();
      if (query.onlyFallback) params.set("onlyFallback", "true");
      if (query.onlyThumbsDown) params.set("onlyThumbsDown", "true");
      if (query.from) params.set("from", query.from);
      if (query.to) params.set("to", query.to);
      if (query.page !== undefined) params.set("page", String(query.page));
      if (query.size !== undefined) params.set("size", String(query.size));
      const qs = params.toString();
      return request<Paged<ConversationSummary>>(
        `/api/bots/${botId}/logs${qs ? `?${qs}` : ""}`,
      );
    },
    /**
     * 세션 하나의 메시지 전체.
     * TODO(W2): PRD §10.1 표에는 이 경로가 없다. Spring 설계 시 확정할 것.
     *           (후보: GET /api/bots/{botId}/logs/{conversationId})
     */
    messages: (botId: Uuid, conversationId: Uuid) =>
      request<ChatMessage[]>(`/api/bots/${botId}/logs/${conversationId}`),
  },

  /**
   * 품질 평가 (F-05, W3)
   *
   * ✅ 2026-08-02: 아래 경로들은 <실제로 구현되어 동작한다>. 추정이 아니다.
   * ✅ 2026-09-07: updateQuestion·listUnanswered 도 구현 완료를 확인했다.
   *    (예전 주석이 "미구현" 이라고 적어둔 채 낡아 있었다)
   */
  evaluation: {
    /** 테스트 질문 목록 */
    listQuestions: (botId: Uuid) =>
      request<EvalQuestion[]>(`/api/bots/${botId}/eval/questions`),
    /** 문서 청크에서 질문·정답 쌍을 자동 생성 (LLM 이 만든다) */
    generateQuestions: (botId: Uuid, count: number) =>
      request<EvalQuestion[]>(`/api/bots/${botId}/eval/questions/generate`, {
        method: "POST",
        body: { count },
      }),
    /**
     * 테스트 질문 수정. Spring `@PatchMapping("/questions/{questionId}")` 로 구현돼 있다.
     *
     * ⚠️ 아직 <부르는 화면이 없다> — 품질 대시보드에 수정 UI 를 붙이지 않았다.
     * 🔴 groundTruth 를 고치면 과거 실행과 비교할 수 없게 된다. 문항을 빼려면 isActive=false.
     */
    updateQuestion: (
      botId: Uuid,
      questionId: Uuid,
      payload: { question?: string; groundTruth?: string; isActive?: boolean },
    ) =>
      request<EvalQuestion>(
        `/api/bots/${botId}/eval/questions/${questionId}`,
        { method: "PATCH", body: payload },
      ),
    /** 평가 실행 시작. 즉시 running 상태의 run 을 돌려주고 채점은 백그라운드. */
    startRun: (botId: Uuid) =>
      request<EvalRun>(`/api/bots/${botId}/eval/runs`, { method: "POST" }),
    /** 실행 이력 (설정별 비교의 재료) */
    listRuns: (botId: Uuid) =>
      request<EvalRun[]>(`/api/bots/${botId}/eval/runs`),
    /** 실행 1건의 질문별 상세 채점 결과 */
    getRunResults: (botId: Uuid, runId: Uuid) =>
      request<EvalResult[]>(`/api/bots/${botId}/eval/runs/${runId}/results`),
    /**
     * 봇이 근거를 못 찾아 거절한 질문 모음 (자주 물어본 순).
     *
     * LLM 을 부르지 않고 messages 집계만 하므로 <비용이 0>이다 — 마음껏 다시 불러도 된다.
     * 응답이 배열이 아니라 객체인 이유는 UnansweredSummary 주석 참고.
     */
    listUnanswered: (botId: Uuid, limit = 50) =>
      request<UnansweredSummary>(`/api/bots/${botId}/eval/unanswered?limit=${limit}`),
  },

  /**
   * 사용량 (요금제 연동 1조각)
   *
   * ✅ 구현되어 동작한다. 추정이 아니다.
   * botId 를 받지 않는 이유: 청구 대상이 <계정>이라 서버가 토큰의 주인으로 조회한다.
   */
  usage: {
    /**
     * @param month "2026-09" 형식. 생략하면 이번 달(한국 시간 기준)
     * encodeURIComponent 로 감싸는 이유: 지금은 호출부가 없어 실제 버그는 아니지만,
     * 나중에 월 선택 UI 가 붙어 사용자 입력이 그대로 들어오면 "+" 같은 문자가
     * 쿼리스트링에서 서버 쪽 디코딩 시 공백으로 풀려 서버가 다른 문자열을 받게 된다.
     */
    current: (month?: string) =>
      request<Usage>(
        month ? `/api/usage?month=${encodeURIComponent(month)}` : "/api/usage",
      ),
  },

  /**
   * 결제 수단 (요금제 연동 3조각)
   *
   * botId 를 받지 않는 이유: 청구 대상이 <계정>이라 서버가 토큰의 주인으로 조회한다.
   * 위 usage 와 같다.
   *
   * 함수 이름이 `get`·`register`·`remove` 가 아니라 `getBillingMethod` 처럼 긴 것은
   * 설계 문서가 고정한 이름이기 때문이다. 짧게 줄이지 말 것.
   */
  billing: {
    /** 카드가 없어도 customerKey 는 항상 온다 (결제창을 띄우려면 그게 필요하다). 카드는 등록 순서대로 */
    listBillingMethods: () => request<BillingMethodsResponse>("/api/billing/methods"),
    /**
     * 토스 결제창에서 돌아온 authKey 로 빌링키를 발급받아 저장하고 <목록 전체>를 돌려준다.
     * 등록 직후 다시 GET 할 필요가 없다 — 화면에 보이는 카드의 출처가 이 응답 하나다.
     *
     * 🔴 customerKey 를 같이 보내지만 서버는 그 값을 <신뢰하지 않는다> — 토큰의 주인 것을
     *    DB 에서 읽어 쓰고, 여기 실린 값은 <대조만> 하고 다르면 400 이다.
     *    신뢰했다면 남의 customerKey 를 적어 보내는 것만으로 카드가 남에게 붙는다.
     *    userId 를 @AuthenticationPrincipal 로만 받는 이 저장소의 규칙과 같은 이유다.
     *
     * 실패 코드가 넷으로 갈린다 — 프론트가 "카드를 바꿔 다시" 와 "우리 버그" 를 구분해
     * 안내해야 해서다: BILLING_AUTH_FAILED(400) · BILLING_PROVIDER_UNAVAILABLE(503) ·
     * BILLING_METHOD_LIMIT_EXCEEDED(409, 5장) · BILLING_METHOD_CONFLICT(409, 동시 첫 등록).
     * 전부 ApiError.message 에 한국어 안내가 들어 있다.
     */
    registerBillingMethod: (authKey: string, customerKey: string) =>
      request<BillingMethodsResponse>("/api/billing/methods", {
        method: "POST",
        body: { authKey, customerKey },
      }),
    /**
     * 카드 한 장 삭제. 204 라 반환값이 없다. request() 가 204 를 이미 다룬다.
     *
     * ⚠️ 서버는 <토스를 먼저> 부르고 우리 행을 나중에 지운다. 그래서 503 이 오면
     *    카드가 <그대로 남아 있다> — 화면은 그 경우 목록을 다시 부르지 말고
     *    오류만 띄워야 한다(page.tsx 의 handleDelete 참고).
     * ⚠️ 기본 카드는 다른 카드가 남아 있으면 409(BILLING_DEFAULT_METHOD_IN_USE)다.
     *    화면은 그 버튼을 미리 비활성화하지만 판단은 서버가 한다.
     */
    deleteBillingMethod: (id: string) =>
      request<void>(`/api/billing/methods/${id}`, { method: "DELETE" }),
    /**
     * 그 카드를 기본(청구에 쓸 카드)으로. <목록 전체>를 돌려준다. PUT 이라 연타해도 결과가 같다.
     */
    setDefaultBillingMethod: (id: string) =>
      request<BillingMethodsResponse>(`/api/billing/methods/${id}/default`, { method: "PUT" }),
  },

  /**
   * 요금제 (요금제 연동 4조각 중 2번).
   *
   * 🔴 <이 호출로 돈이 나가지 않는다.> 서버가 하는 일은 users.plan 한 칸을 읽고 쓰는 것이
   *    전부이고, 청구는 4번 조각이라 아직 없다. 화면도 그렇게 안내한다.
   *
   * botId 를 받지 않는 이유: 요금제는 <계정>에 붙는다. 봇을 여러 개 만들어도 요금제는 하나다.
   * 위 usage·billing 과 같다.
   */
  plan: {
    getPlan: () => request<PlanResponse>("/api/plan"),
    /**
     * 요금제 변경. PUT 이라 같은 값을 몇 번 보내도 결과가 같다(버튼 연타가 안전하다).
     *
     * 🔴 카드가 한 장도 없는데 유료로 바꾸려 하면 409(PLAN_REQUIRES_BILLING_METHOD)다.
     *    ApiError.message 에 "카드를 등록한 뒤 다시 선택해주세요" 가 들어 있으니 그대로 보여주면 된다.
     */
    changePlan: (plan: PlanId) =>
      request<PlanResponse>("/api/plan", { method: "PUT", body: { plan } }),
  },

  /**
   * 문서 간 사실 충돌 진단
   *
   * 환각 억제는 "문서에 없는 것"을 막지만 "문서에 <둘 다> 있는 것"은 못 막는다.
   * 구버전·신버전이 같이 올라가 있으면 챗봇은 둘 중 하나를 골라 자신 있게 답한다.
   */
  conflicts: {
    /** 목록. 기본은 아직 안 본 것(open)만 — ignored·clear 까지 섞으면 노이즈로 덮인다. */
    list: (botId: Uuid, status: "open" | "ignored" | "resolved" | "clear" = "open") =>
      request<Conflict[]>(`/api/bots/${botId}/conflicts?status=${status}`),
    /**
     * 스캔. 동기라 수십 초 걸린다(판정 1건에 1~2초).
     * 서버가 판정 쌍 수를 상한으로 묶으므로, candidates 가 상한과 같으면 다시 눌러야 한다.
     */
    scan: (botId: Uuid) =>
      request<ConflictScan>(`/api/bots/${botId}/conflicts/scan`, { method: "POST" }),
    /** 오탐을 치운다. 이게 없으면 헛짚은 항목이 영원히 남아 화면 자체를 안 보게 된다. */
    updateStatus: (botId: Uuid, conflictId: Uuid, status: "open" | "ignored" | "resolved") =>
      request<Conflict>(`/api/bots/${botId}/conflicts/${conflictId}`, {
        method: "PATCH",
        body: { status },
      }),
  },

  /** 임베드 위젯 (F-04) — 인증 없음. public_key + Origin 검증 + rate limit 으로 보호된다. */
  widget: {
    config: (publicKey: string) =>
      request<WidgetConfig>(`/api/w/${publicKey}/config`, { auth: false }),
    chat: (publicKey: string, payload: ChatRequest) =>
      request<ChatResponse>(`/api/w/${publicKey}/chat`, {
        method: "POST",
        body: payload,
        auth: false,
      }),
  },
};
