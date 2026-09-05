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
  Bot,
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

export function getAccessToken(): string | null {
  // 서버 컴포넌트에서는 window 가 없다. 그래서 방어한다.
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_STORAGE_KEY);
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
  method?: "GET" | "POST" | "PATCH" | "DELETE";
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
     * ⚠️ 반환 타입이 {@link BotSummary} 가 아니라 {@link Bot} 이다.
     *
     * 뼈대에서는 `BotSummary[]`(문서 수·주간 대화 수·최근 평가 점수 포함)로 적어뒀지만,
     * <b>서버는 그 집계를 아직 내려주지 않는다.</b> 집계를 붙이려면 봇마다 count 를 돌리게 되어
     * N+1 이 되므로 group by 한 번으로 가져오는 쿼리가 필요한데, 그건 별도 작업이다.
     *
     * 타입을 `BotSummary[]` 로 두면 <b>화면 코드가 없는 필드를 있다고 믿게 된다</b> —
     * 컴파일은 통과하고 런타임에 `undefined` 가 화면에 찍힌다.
     * 실제로 내려오는 것만 타입에 적는 편이 안전하다.
     */
    list: () => request<Bot[]>("/api/bots"),
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
   *    (예외: updateQuestion 과 listUnanswered 는 아직 미구현 — 각 주석 참고)
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
    /** ⚠️ 미구현 — Spring 에 PATCH 엔드포인트가 아직 없다. 화면에서 부르지 말 것. */
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
