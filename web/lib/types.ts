/**
 * Spring API(:8080) 응답 타입 정의.
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * ★ 이 파일에서 가장 중요한 전제 (읽고 넘어갈 것)
 * ─────────────────────────────────────────────────────────────────────────────
 * 브라우저는 Python AI 서비스(:8001)를 직접 부르지 않는다. 항상 Spring 을 거친다.
 * (Python 은 인증이 없어서 외부에 노출하면 안 되기 때문 — CLAUDE.md 아키텍처 참고)
 *
 * 그런데 두 계층의 JSON 표기법이 다르다.
 *   - Python(FastAPI/Pydantic) 은 snake_case  → `is_fallback`, `latency_ms`, `chunk_id`
 *   - Spring(Jackson 기본값)   은 camelCase   → `isFallback`, `latencyMs`, `chunkId`
 *
 * 이 파일은 **Spring 이 camelCase 로 변환해서 내려준다는 전제**로 작성했다.
 * 즉 프론트는 camelCase 만 본다. snake_case ↔ camelCase 변환 책임은 Spring 에 있다.
 *
 * ⚠️ W2 에서 Spring 을 구현할 때 이 전제를 반드시 맞춰야 한다.
 *    Spring 이 Python 응답을 그대로 파이프처럼 흘려보내면 프론트에 snake_case 가
 *    도착해서 여기 타입이 전부 거짓말이 된다. Spring 쪽에 DTO 를 두고
 *    (@JsonProperty("is_fallback") 같은 매핑으로) 반드시 변환할 것.
 *
 * 참고 — Python 실제 컨트랙트 (ai-service/app/schemas.py):
 *   DocumentOut  = {id, filename, file_type, status, error_message, char_count, chunk_count}
 *   ChatResponse = {answer, sources[], is_fallback, latency_ms}
 *   Source       = {chunk_id, document_id, filename, score, preview}
 *
 * TODO(W2): Spring API 가 실제로 완성되면 응답을 찍어보고 이 파일과 대조할 것.
 *           다르면 "코드가 맞다" — 이 파일을 고칠 것.
 */

/* ───────────────────────── 공통 ───────────────────────── */

/**
 * PRD §10.3 공통 에러 포맷. 전 계층(Spring·Python)이 이 모양으로 내려준다.
 *   { "error": { "code": "...", "message": "무엇을 어떻게 하면 되는지까지 담은 한국어 설명" } }
 */
export interface ApiErrorBody {
  error: {
    code: string;
    /** 사용자에게 그대로 보여줄 수 있는 한국어 문장 */
    message: string;
  };
}

/** UUID 는 문자열로 온다. 그냥 string 보다 의도가 드러나게 별칭을 둔다. */
export type Uuid = string;

/** TIMESTAMPTZ → ISO-8601 문자열 (예: "2026-07-31T02:11:00Z") */
export type IsoDateTime = string;

/* ───────────────────────── 인증 (F-08) ───────────────────────── */

export interface User {
  id: Uuid;
  email: string;
  name: string | null;
  createdAt: IsoDateTime;
}

/** POST /api/auth/signup, POST /api/auth/login 응답 */
export interface AuthResponse {
  /** JWT. Authorization: Bearer {token} 으로 실어 보낸다. */
  token: string;
  user: User;
}

/* ───────────────────────── 봇 (F-06) ───────────────────────── */

/** bots 테이블(db/V1__init.sql) 과 1:1 대응 */
export interface Bot {
  id: Uuid;
  name: string;
  /** 위젯 공개 주소 /w/[publicKey] 에 쓰이는 키. 예: "pk_local_dev" */
  publicKey: string;
  /**
   * ⚠️ 알려진 갭: 이 값은 지금 실제 답변에 반영되지 않는다.
   * Python 의 POST /internal/chat 이 systemPrompt 를 파라미터로 받지 않기 때문.
   * (ai-service/app/schemas.py 의 ChatRequest = {bot_id, message, session_id})
   * → Python 을 고치기 전까지 설정 화면에서 저장은 되지만 동작에는 영향이 없다.
   * TODO(W3 이후): Python ChatRequest 에 system_prompt 를 추가하고 Spring 이 전달하도록 할 것.
   */
  systemPrompt: string | null;
  /** 대화 시작 시 위젯이 먼저 띄우는 인사말 */
  welcomeMessage: string;
  /**
   * 근거를 못 찾았을 때 보여줄 문구.
   * Python 은 is_fallback=true 만 돌려주고 이 문구를 모른다.
   * → Spring 이 is_fallback=true 를 받으면 answer 를 이 문구로 치환한다. (현재 가능한 유일한 방법)
   */
  fallbackMessage: string;
  /** 위젯 임베드를 허용할 도메인 목록 (CORS/Origin 검증용) */
  allowedOrigins: string[];
  createdAt: IsoDateTime;
}

/**
 * GET /api/bots — 봇 목록 카드에 필요한 집계까지 얹은 형태.
 * PRD §8 "봇 카드(문서 수·주간 대화 수·최근 평가 점수)" 요구사항에서 나온 타입.
 * TODO(W2): 이 집계를 Spring 이 한 번에 내려줄지, 별도 API 로 뺄지 결정할 것.
 */
/**
 * ⚠️ **서버가 아직 이 모양으로 내려주지 않는다.** `GET /api/bots` 는 집계 없이 {@link Bot} 배열을 준다.
 * 집계를 붙이려면 봇마다 count 를 돌리지 않고 group by 한 번으로 가져와야 해서 별도 작업이다.
 * 그때까지 이 타입을 화면에서 쓰지 말 것 — 없는 필드를 있다고 믿게 만든다.
 */
export interface BotSummary extends Bot {
  documentCount: number;
  /** 최근 7일 대화 수 */
  weeklyConversationCount: number;
  /** 가장 최근 평가 실행의 충실성 평균. 평가를 한 번도 안 돌렸으면 null */
  latestFaithfulness: number | null;
}

/** POST /api/bots 요청 본문 */
export interface CreateBotRequest {
  name: string;
}

/** PATCH /api/bots/{botId} 요청 본문 — 보낸 필드만 수정된다 */
export interface UpdateBotRequest {
  name?: string;
  systemPrompt?: string | null;
  welcomeMessage?: string;
  fallbackMessage?: string;
  allowedOrigins?: string[];
}

/* ───────────────────────── 문서 (F-01, F-02) ───────────────────────── */

/**
 * documents.status 는 pending → processing → ready(또는 failed) 로 흐른다.
 * Python 이 백그라운드로 갱신하므로 화면은 폴링해서 따라간다.
 */
export type DocumentStatus = "pending" | "processing" | "ready" | "failed";

/** Python DocumentOut 을 Spring 이 camelCase 로 바꿔 내려준 형태 */
export interface DocumentItem {
  id: Uuid;
  filename: string;
  /** pdf | docx | hwpx | txt | md (구버전 .hwp 는 미지원) */
  fileType: string;
  status: DocumentStatus;
  /** status === "failed" 일 때 사용자에게 보여줄 한국어 사유 */
  errorMessage: string | null;
  charCount: number | null;
  chunkCount: number | null;
  /**
   * Python DocumentOut 에는 없는 필드다. Spring 이 documents 테이블에서 읽어 채워준다.
   *
   * ⚠️ **목록 조회에만 값이 있고 업로드 응답에는 null 이다.** 업로드는 Python 응답을 그대로
   * 변환해 돌려주는데 거기에 created_at 이 없기 때문이다(종단 확인에서 실측).
   * 그래서 optional 로 둔다 — 업로드 직후 화면에서 이 값을 쓰면 비어 있다.
   */
  createdAt?: IsoDateTime | null;
}

/* ───────────────────────── 채팅 (F-03) ───────────────────────── */

/** 답변의 근거가 된 청크 하나 */
export interface Source {
  chunkId: Uuid;
  documentId: Uuid;
  filename: string;
  /** 0~1. 1에 가까울수록 관련성 높음 (1 - 코사인거리) */
  score: number;
  /** 청크 본문 앞 200자. 출처 카드 클릭 시 미리보기로 쓴다. */
  preview: string;
}

/** POST /api/bots/{botId}/chat, POST /api/w/{publicKey}/chat 응답 */
export interface ChatResponse {
  /**
   * Python 이 만든 answer.
   * is_fallback 이 true 면 Spring 이 봇의 fallbackMessage 로 치환해서 내려준다.
   */
  answer: string;
  sources: Source[];
  /** true = 문서에서 근거를 못 찾아 거절한 것. 환각 대신 모른다고 답한 상태. */
  isFallback: boolean;
  latencyMs: number;
  /**
   * 피드백(POST /api/messages/{msgId}/feedback)을 보내려면 메시지 id 가 필요하다.
   * Python 은 이 값을 모르고, messages 행을 만드는 건 Spring 이므로 Spring 이 붙여줘야 한다.
   * TODO(W2): Spring ChatResponse DTO 에 messageId 를 포함시킬 것. 없으면 피드백 UI 를 붙일 수 없다.
   */
  messageId?: Uuid;
}

/** POST /api/bots/{botId}/chat 요청 본문 */
export interface ChatRequest {
  /** 1~2000자 (Python ChatRequest 제약을 그대로 따른다) */
  message: string;
  /** 최대 64자. 같은 세션의 대화를 묶는 키. */
  sessionId: string;
}

/* ───────────────────────── 대화 로그 · 피드백 (F-07) ───────────────────────── */

/** messages.role */
export type MessageRole = "user" | "assistant";

/** messages.feedback — 1(👍) / -1(👎) / null(무응답) */
export type Feedback = 1 | -1 | null;

export interface ChatMessage {
  id: Uuid;
  role: MessageRole;
  content: string;
  /** role === "assistant" 일 때만 값이 있다 */
  sources: Source[] | null;
  isFallback: boolean;
  feedback: Feedback;
  latencyMs: number | null;
  createdAt: IsoDateTime;
}

/** conversations 한 건. 로그 목록에서 한 줄로 보여줄 요약. */
export interface ConversationSummary {
  id: Uuid;
  sessionId: string;
  /** widget = 실제 엔드유저 / test = 관리자 테스트 채팅 */
  channel: "widget" | "test";
  createdAt: IsoDateTime;
  messageCount: number;
  /** 이 세션에 fallback(미답변)이 하나라도 있었는가 — 목록 필터의 근거 */
  hasFallback: boolean;
  /** 목록에서 미리 보여줄 첫 질문 */
  firstUserMessage: string | null;
}

/** GET /api/bots/{botId}/logs 쿼리 파라미터 */
export interface LogsQuery {
  /** true 면 fallback 이 포함된 세션만 */
  onlyFallback?: boolean;
  /** true 면 👎 가 달린 세션만 */
  onlyThumbsDown?: boolean;
  /** YYYY-MM-DD */
  from?: string;
  to?: string;
  page?: number;
  size?: number;
}

/** 페이지네이션 공통 껍데기.
 *  TODO(W2): Spring 이 Spring Data Page 를 그대로 내리면 필드명이 다르다
 *            (content/totalElements/number ...). 실제 응답에 맞춰 고칠 것. */
export interface Paged<T> {
  items: T[];
  page: number;
  size: number;
  totalElements: number;
  totalPages: number;
}

/* ───────────────────────── 품질 평가 (F-05, W3) ───────────────────────── */

/**
 * ✅ 2026-08-02: 실제 API 응답과 대조 완료.
 *    Python 의 /internal/eval/* 과 Spring 의 /api/bots/{botId}/eval/* 이 모두 구현됐고,
 *    아래 타입은 <실제로 돌려받은 JSON> 을 보고 고친 것이다(더 이상 추측이 아니다).
   *    ✅ 2026-09-07: `UnansweredQuestion` 도 구현됐다(GET /api/bots/{botId}/eval/unanswered).
   *       진단 화면이 실제로 쓰고 있다.
 */

/** 테스트 질문 1건 (eval_questions) */
export interface EvalQuestion {
  id: Uuid;
  question: string;
  /** 문서 청크에서 뽑아낸 기대 답변 */
  groundTruth: string;
  /** 이 질문이 어느 청크에서 생성됐는지 */
  sourceChunkId: Uuid | null;
  /** false 면 평가 실행에서 제외된다 (관리자가 끌 수 있음) */
  isActive: boolean;
  createdAt: IsoDateTime;
}

/**
 * eval_runs.config (JSONB) — 실행 시점의 검색 설정.
 * PRD §9.3: "이게 있어야 before/after 비교가 성립한다."
 * W4에서 하이브리드 검색·리랭커를 켜고 끄며 비교할 때 이 값이 축이 된다.
 */
export interface EvalConfig {
  topK?: number;
  /** 검색 단계에서 잘라내는 최대 코사인 거리 (환각 억제 1차 방어선) */
  maxDistance?: number;
  /** W4: 키워드+벡터 하이브리드 사용 여부 */
  hybrid?: boolean;
  /** W4: 리랭커 사용 여부 */
  reranker?: boolean;
  /** 답변 생성에 쓴 모델 이름 */
  model?: string;
}

/**
 * 평가 실행의 상태.
 *
 * 🔴 `partial` 이 왜 따로 있는가 — <덜 잰 실행과 다 잰 실행은 다른 사실>이기 때문이다.
 *    일부 질문이 처리 실패(429·타임아웃)하면 분모가 달라져 <다른 설정과 비교할 수 없다.>
 *    실제로 2026-08-12 에 16문항 중 13개만 처리된 실행을 유효한 측정으로 읽어
 *    잘못된 결론을 냈다. 그래서 화면의 대표 수치는 `completed` 만 고른다.
 */
export type EvalRunStatus = "running" | "completed" | "partial" | "failed";

/** 평가 실행 1회 (eval_runs) */
export interface EvalRun {
  id: Uuid;
  config: EvalConfig | null;
  /** 충실성: 답이 근거 문서와 일치하는가 (0~1) */
  avgFaithfulness: number | null;
  /** 관련성: 질문에 맞는 답인가 (0~1) */
  avgRelevancy: number | null;
  /** 응답률: fallback 하지 않고 답한 비율 (0~1) */
  answeredRate: number | null;
  status: EvalRunStatus;
  /** 이 실행의 대상 질문 수. avgFaithfulness 를 해석하려면 반드시 필요한 분모. 옛 실행은 null */
  questionCount: number | null;
  /** 실제로 채점된 질문 수. avgFaithfulness 의 진짜 분모 */
  scoredCount: number | null;
  /**
   * ★ 설정 비교(W4 before/after)에는 <이 값>을 써야 한다.
   *
   * `avgFaithfulness` 는 <답을 덜 할수록 저절로 올라간다>. fallback 은 채점에서 빠지므로
   * 어려운 질문이 fallback 되면 남은 쉬운 질문들만 평균에 남는다(생존 편향).
   *
   * 실제로 속았다 — 리랭커 비교에서 충실성이 0.714 → 0.789 로 올랐는데,
   * 0점짜리 2건이 fallback 된 결과였고 그 2건을 0으로 환산하면 0.714 로 동일했다.
   *
   * 이 값은 분모를 전체 질문 수로 되돌린 것이라 답을 덜 하면 같이 내려간다.
   * 분모를 모르는 옛 실행은 null 이다 — 0 으로 그리면 또 속는다.
   */
  overallFaithfulness: number | null;
  createdAt: IsoDateTime;
}

/**
 * 평가 중 검색된 청크 하나 (스냅샷).
 *
 * ⚠️ 채팅의 `Source` 와 <다른 타입>이다. 필드가 적다 —
 *    Python 이 평가 결과에 남기는 건 chunkId / filename / score 셋뿐이라
 *    documentId·preview 가 없다. 같은 타입인 척하면 화면이
 *    "왜 여기만 preview 가 비지?" 를 계속 묻게 된다.
 */
export interface EvalRetrievedChunk {
  chunkId: Uuid;
  filename: string;
  /** 0~1. 1에 가까울수록 관련성 높음 */
  score: number | null;
}

/**
 * 질문 하나에 대한 채점 결과 (eval_results). 2026-08-02 실제 응답과 대조해 맞춤.
 *
 * ⚠️ `faithfulness`/`relevancy` 가 null 이면 <채점하지 못했다>는 뜻이지 0점이 아니다.
 *    ① 답변이 fallback 이라 채점 대상이 아니었거나 ② 채점 호출이 실패한 경우다.
 *    화면은 이 둘을 "—" 처럼 <점수가 아닌 표시>로 그려야 한다. 0 으로 그리면 거짓말이 된다.
 */
export interface EvalResult {
  id: Uuid;
  questionId: Uuid;
  question: string;
  /** 질문 생성 시 함께 만든 기대 답변 */
  groundTruth: string;
  generatedAnswer: string | null;
  /** 이 답변이 실제로 참고한 청크들. 파싱 실패 시 빈 배열. */
  retrievedChunks: EvalRetrievedChunk[];
  faithfulness: number | null;
  relevancy: number | null;
}

/**
 * 미답변(fallback) 집계 1건 — <진단> 화면의 "답하지 못한 질문" 영역.
 *
 * ✅ 구현됨: `GET /api/bots/{botId}/eval/unanswered`.
 *    eval_* 테이블이 아니라 messages(is_fallback = true) 에서 나오므로
 *    Python 이 아니라 <Spring 이> 집계한다. LLM 을 안 부르니 비용이 0 이다.
 *
 * ⚠️ 남은 것: "보강 제안" 문장을 누가 생성할지는 아직 미정이라 화면에 없다.
 */
export interface UnansweredQuestion {
  /** 같은 문장끼리 묶은 대표 질문 */
  question: string;
  /** 같은 문장이 몇 번 들어왔는지 */
  count: number;
  lastAskedAt: IsoDateTime;
  /**
   * "이 내용을 문서에 추가하세요" 류의 한국어 제안.
   * ⚠️ 지금은 항상 null 이다 — 만들려면 LLM 을 불러야 하는데,
   *    목록을 여는 것만으로 비용이 나가면 안 된다.
   */
  suggestion: string | null;
}

/**
 * 미답변 집계 결과.
 *
 * 🔴 왜 배열이 아니라 객체인가 — `failedTurns` 를 함께 받아야 하기 때문이다.
 *
 * `fallback`(물어봤는데 문서에 없었다)과 `답변 행 없음`(우리 인프라가 실패해
 * 물어보지도 못했다)은 <다른 사실>이다. 섞지 않는 것만으로는 부족하고
 * <따로 보여줘야> 한다 — 목록만 주면 화면이 "미답변 0건 = 문서가 충분하다"로 읽는데,
 * 실제로는 "그날 서버가 죽어서 아무것도 못 물어봤다" 일 수 있다.
 */
export interface UnansweredSummary {
  items: UnansweredQuestion[];
  /** 답변 행이 아예 없는 질문 수. 미답변이 아니라 <처리 실패>다. */
  failedTurns: number;
}

/* ───────────────────────── 위젯 (F-04, 공개) ───────────────────────── */

/**
 * GET /api/w/{publicKey}/config — 인증 없이 호출되는 공개 API.
 * 엔드유저에게 노출되므로 systemPrompt 같은 내부 설정은 절대 포함하면 안 된다.
 */
export interface WidgetConfig {
  botName: string;
  welcomeMessage: string;
  /**
   * ⚠️ PRD 와 DB 의 불일치:
   *    PRD F-04 / §8 은 "브랜드 색상 1종 커스텀"을 요구하는데
   *    db/V1__init.sql 의 bots 테이블에는 색상 컬럼이 없다.
   * TODO(W2): bots 에 theme_color 컬럼을 추가하거나, 색상 커스텀을 MVP 에서 뺄 것.
   *           지금은 없을 수도 있다는 뜻으로 optional 로 둔다.
   */
  themeColor?: string;
}

/* ───────────────────── 문서 간 사실 충돌 (진단) ───────────────────── */

/**
 * 서로 어긋나는 문서 두 조각.
 *
 * 왜 요약(topic/aSays/bSays)과 원문(aContent/bContent)을 <둘 다> 받는가:
 * 요약만 있으면 관리자가 "정말 그렇게 쓰여 있나"를 확인할 수 없고,
 * 확인할 수 없는 지적은 무시당한다. 원문만 있으면 매번 두 청크를 다 읽어야 한다.
 *
 * `distance` 가 optional 인 이유: 판정 근거가 아니라 임계값 튜닝용 기록이라
 * 없어도 화면이 성립한다. 서버가 null 을 줄 수 있다.
 */
export interface Conflict {
  id: Uuid;
  /** 무엇에 대한 충돌인가 — 예: "노트북 교체 주기" */
  topic: string;
  /** 문서 A 의 주장 — 예: "3년" */
  aSays: string;
  bSays: string;
  aFilename: string;
  bFilename: string;
  aContent: string;
  bContent: string;
  distance?: number | null;
  /** open = 아직 안 봄 · ignored = 오탐 표시 · resolved = 문서를 고침 · clear = 판정 결과 모순 아님 */
  status: "open" | "ignored" | "resolved" | "clear";
  createdAt: string;
}

/**
 * 스캔 한 번의 결과.
 *
 * 네 숫자가 <따로> 오는 이유: "깨끗해서 0건"과 "못 재서 0건"은 다른 사실이다.
 * failed 가 있으면 화면이 "일부는 판정하지 못했다"를 반드시 말해줘야 한다 —
 * 안 그러면 사용자는 문서가 깨끗하다고 믿는다.
 */
export interface ConflictScan {
  /** 판정 대상으로 고른 쌍. 서버 상한(30)과 같으면 아직 남았을 수 있다 */
  candidates: number;
  judged: number;
  conflicts: number;
  failed: number;
}

/**
 * 한 계정의 한 달 사용량. `GET /api/usage` 의 응답.
 *
 * 🔴 금액이 없다 — 이 단계는 개수만 센다. 단가·플랜·초과 계산은 다음 조각이다.
 *
 * `interface` 로 둔 이유: 백엔드 응답 <객체의 모양>을 그리는 타입이고,
 * 이 파일의 다른 응답 타입(Bot·EvalRun 등)이 전부 interface 라 맞췄다.
 * (합집합·별칭이 필요할 때만 `type` 을 쓴다 — 예: 위 EvalRunStatus)
 *
 * 필드 이름이 camelCase 인 것은 Spring 이 변환해 내려주기 때문이다.
 * Python 은 snake_case(`is_fallback`)를 쓰지만 프론트까지 오지 않는다.
 */
export interface Usage {
  /** "2026-09" */
  month: string;
  /** 위젯에서 실제로 만들어진 답변 수 (fallback·관리자 테스트 채팅 제외) */
  chatAnswers: number;
  /** 완료된 품질 평가 실행 수 (partial·failed 제외) */
  evalRuns: number;
  /** 서버가 정한 기간 경계(KST). 화면이 "9월"을 제멋대로 해석하지 않게 한다 */
  periodStart: string;
  periodEnd: string;
}

/* ───────────────────────── 요금제 (요금제 연동 2조각) ───────────────────────── */

/**
 * 계정이 고른 요금제의 <이름표>. Spring 의 `Plan` enum 이 내려주는 값과 같은 문자열이고,
 * `lib/plans.ts` 의 `Plan["id"]` 와도 같아야 한다 — 세 곳이 같은 문자열을 쓰는 것이 계약이다.
 *
 * `interface` 가 아니라 `type` 인 이유: 객체의 <모양>이 아니라 <값의 목록>이기 때문이다.
 * 이 파일의 `EvalRunStatus` 와 같은 판단이다(합집합은 type, 객체는 interface).
 *
 * 🔴 금액도 포함량도 여기 없다. 서버는 요금제의 <이름>만 알고 값은 모른다 —
 *    서버가 그 숫자로 하는 일이 아직 없기 때문이다(한도 검사·청구는 4조각 중 4번).
 *    화면에 쓰는 금액·포함량은 `lib/plans.ts` 에서 온다.
 */
export type PlanId = "free" | "pro";

/** `GET`/`PUT /api/plan` 의 응답. 필드가 하나뿐이지만 객체로 감싸 나중에 필드를 더할 자리를 남긴다. */
export interface PlanResponse {
  plan: PlanId;
}

/* ───────────────────────── 결제 수단 (요금제 연동 3조각) ───────────────────────── */

/**
 * 등록된 카드 한 장. Spring 의 `BillingMethodResponse.Card` 와 1:1 로 맞춘 모양이다.
 *
 * 🔴 `billingKey` 필드가 <없다>. 백엔드 DTO 에도 없다.
 *    타입에 자리를 만들어두면 언젠가 그 자리에 값이 실린다. 결제 열쇠는
 *    우리 DB 밖으로 한 번도 나가지 않는 것이 이 조각의 핵심 주장이다.
 *
 * 왜 `issuerCode`("61" 같은 두 자리 코드)가 아니라 `issuerName`("현대") 인가:
 * 토스는 2024-06-01 버전부터 카드사 <이름>을 안 주고 코드만 준다. 코드→이름 매핑을
 * 프론트에 두면 백엔드가 아는 것과 프론트가 아는 것이 갈라진다.
 * 표기 변환은 Spring 책임이라는 이 저장소의 규칙(snake_case → camelCase)과 같은 이유다.
 */
export interface BillingCard {
  /** 삭제·기본 지정 때 경로에 싣는 식별자 (V7, 2026-09-08 부터 카드가 여러 장이라 필요해졌다) */
  id: string;
  /**
   * 토스가 준 발급사 코드("61"). <표시용이 아니라> 카드 면 색을 고르는 키다(`lib/cardBrand.ts`).
   * 이름을 키로 쓰면 백엔드가 "현대" → "현대카드" 로 문구를 다듬는 순간 모든 현대 카드가
   * 조용히 회색이 된다. 코드는 토스가 정한 값이라 우리 사정으로 바뀌지 않는다.
   */
  issuerCode: string;
  /** "현대" · "신한" 등. 모르는 코드는 서버가 "카드" 로 내려준다 */
  issuerName: string;
  /** "43301234****123*" — 토스가 마스킹해서 준다. 우리가 자르는 게 아니다 */
  cardNumberMasked: string;
  /** 우리 DB 의 created_at. ISO-8601 문자열 */
  registeredAt: string;
  /**
   * 청구에 쓰는 카드인가. 카드가 하나라도 있으면 <정확히 하나>가 true 다 — 서버 불변식이고
   * DB 부분 유니크 인덱스가 보장한다. 프론트는 이 값을 <계산하지 않고> 그대로 그린다.
   */
  isDefault: boolean;
}

/**
 * `GET`/`POST /api/billing/methods` · `PUT /api/billing/methods/{id}/default` 의 응답.
 * 쓰기가 전부 <같은 목록>을 돌려주므로 화면에 보이는 카드의 출처가 이 타입 하나다.
 *
 * `interface` 로 둔 이유: 백엔드 응답 <객체의 모양>을 그리는 타입이고,
 * 이 파일의 다른 응답 타입(Bot·Usage·EvalRun)이 전부 interface 라 맞췄다.
 *
 * 🔴 `customerKey` 는 카드가 없어도 <항상> 있다 — 카드보다 오래 사는 값이라 users 테이블에
 *    있기 때문이다. 이 화면이 결제창을 띄우려면 카드가 없는 상태에서도 customerKey 가 필요하다.
 *    `methods` 는 카드가 없으면 <빈 배열>이다(null 이 아니다 — 목록은 비어 있음이 곧 없음이다).
 */
export interface BillingMethodsResponse {
  /** "bcus_…" — 토스에 넘기는 우리 쪽 고객 이름표. 카드를 빼도 남는다 */
  customerKey: string;
  /** 등록 순서대로. 없으면 [] */
  methods: BillingCard[];
}
