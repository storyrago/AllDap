"use client";

/*
 * `/bot/[botId]/chat` — 관리자 테스트 채팅.
 *
 * 위젯을 공개하기 전에 관리자가 직접 물어보며 답변 품질을 확인하는 화면이다.
 * 서버는 이 대화를 channel="test" 로 기록해 품질 지표에서 제외한다
 * (관리자가 돌려본 대화가 섞이면 실사용 응답률이 왜곡되므로).
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * 이 화면이 제품의 핵심 가치를 보여주는 자리다
 * ─────────────────────────────────────────────────────────────────────────────
 * ① 답변에 <출처>가 붙는다 — 어느 문서의 어느 대목을 근거로 삼았는지 보인다
 * ② 근거가 없으면 <지어내지 않고 거절>한다 — isFallback 이 true 로 온다
 * 그래서 이 두 가지를 화면에서 눈에 띄게 다뤄야 한다. 특히 fallback 은
 * 실패가 아니라 <의도된 동작>이므로 에러처럼 보이면 안 된다.
 */

import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { ApiError, api } from "@/lib/api";
import type { Feedback, Source } from "@/lib/types";
import { PageHeader } from "@/components/PageHeader";

/** 화면에 쌓아둘 말풍선 하나. 서버 타입과 별개로 <이 화면에 필요한 것만> 담는다. */
interface Bubble {
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  isFallback?: boolean;
  latencyMs?: number | null;
  /** 피드백을 보내려면 필요하다. 서버가 답변을 저장하고 돌려주는 값이다. */
  messageId?: string;
  feedback?: Feedback;
}

export default function ChatPage() {
  const { botId } = useParams<{ botId: string }>();

  const [bubbles, setBubbles] = useState<Bubble[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /*
   * 세션 키. 같은 세션의 대화를 하나로 묶는 값이라 <화면이 살아 있는 동안 고정>되어야 한다.
   *
   * useState 에 값이 아니라 <함수>를 넘긴 이유(지연 초기화):
   * useState(crypto.randomUUID()) 로 쓰면 렌더할 때마다 새 UUID 를 만든다.
   * 결과가 버려질 뿐이라 동작은 같지만 불필요한 일이고, 무거운 초기값이면 낭비가 커진다.
   * 함수를 넘기면 React 가 <처음 한 번만> 호출한다.
   */
  const [sessionId] = useState(() => crypto.randomUUID());

  /*
   * 새 말풍선이 생기면 아래로 스크롤한다.
   * ref 는 "DOM 요소를 직접 가리키는 손잡이" 다 — 스크롤은 React 상태로 표현할 수 없는
   * 브라우저 동작이라 요소를 직접 만져야 한다.
   */
  const bottomRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [bubbles]);
  // 의존성이 bubbles 인 이유: 말풍선이 늘어날 때만 스크롤하면 된다.

  async function handleSend(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const message = input.trim();
    if (!message) return;

    // 질문은 즉시 화면에 띄운다. 서버 응답을 기다렸다 띄우면 몇 초간 아무 반응이 없어 보인다.
    setBubbles((prev) => [...prev, { role: "user", content: message }]);
    setInput("");
    setSending(true);
    setError(null);

    try {
      const response = await api.chat.send(botId, { message, sessionId });
      setBubbles((prev) => [
        ...prev,
        {
          role: "assistant",
          content: response.answer,
          sources: response.sources,
          isFallback: response.isFallback,
          latencyMs: response.latencyMs,
          messageId: response.messageId,
          feedback: null,
        },
      ]);
    } catch (e) {
      // 답변을 못 받았으므로 말풍선을 만들지 않는다. 질문만 남는 게 서버 로그와도 일치한다.
      setError(
        e instanceof ApiError ? e.message : "답변을 받지 못했습니다. 다시 시도해주세요.",
      );
    } finally {
      setSending(false);
    }
  }

  async function handleFeedback(index: number, value: 1 | -1) {
    const target = bubbles[index];
    if (!target.messageId) return;

    /*
     * 낙관적 갱신: 서버 응답을 기다리지 않고 화면을 먼저 바꾼다.
     * 👍/👎 는 실패해도 잃을 게 없고, 누르자마자 반응하는 편이 훨씬 자연스럽다.
     * 실패하면 아래 catch 에서 되돌린다.
     */
    setBubbles((prev) =>
      prev.map((b, i) => (i === index ? { ...b, feedback: value } : b)),
    );

    try {
      await api.chat.feedback(target.messageId, value);
    } catch {
      setBubbles((prev) =>
        prev.map((b, i) => (i === index ? { ...b, feedback: null } : b)),
      );
      setError("피드백을 저장하지 못했습니다. 잠시 후 다시 눌러주세요.");
    }
  }

  return (
    <>
      <PageHeader
        title="테스트 채팅"
        description="위젯을 공개하기 전에 직접 물어보세요. 이 대화는 품질 지표에서 제외됩니다."
      />

      <div className="mt-6 flex h-[60vh] flex-col rounded-lg border border-subtle bg-surface">
        <div className="flex-1 space-y-4 overflow-y-auto p-4">
          {bubbles.length === 0 && (
            <p className="py-10 text-center text-sm text-muted">
              올린 문서에 대해 질문해보세요. 문서에 없는 내용은 지어내지 않고 거절합니다.
            </p>
          )}

          {bubbles.map((bubble, index) => (
            /*
             * key 에 index 를 쓴 <드문> 경우다. 보통은 피해야 하지만 여기는 안전하다 —
             * 말풍선은 뒤에 추가만 되고 중간 삽입·삭제·정렬이 없어서 index 가 안정적이다.
             * (messageId 는 assistant 에만 있어서 key 로 쓸 수 없다)
             */
            <div key={index}>
              {bubble.role === "user" ? (
                <div className="flex justify-end">
                  <p className="max-w-[80%] rounded-lg bg-foreground px-3 py-2 text-sm text-surface">
                    {bubble.content}
                  </p>
                </div>
              ) : (
                <div className="max-w-[85%]">
                  <p
                    className={`rounded-lg px-3 py-2 text-sm ${
                      bubble.isFallback
                        ? /* fallback 은 에러가 아니라 <의도된 동작>이다. 빨강이 아니라 중립 톤으로 둔다. */
                          "border border-dashed border-subtle text-muted"
                        : "bg-foreground/5"
                    }`}
                  >
                    <RichText text={bubble.content} />
                  </p>

                  {bubble.isFallback && (
                    <p className="mt-1 text-xs text-muted">
                      근거를 찾지 못해 답하지 않았습니다 — 이 질문은 품질 대시보드의 미답변으로 집계됩니다.
                    </p>
                  )}

                  {/*
                   * 출처: 이 제품의 핵심이다. 어느 문서의 어느 대목인지 보여준다.
                   *
                   * ⚠️ fallback 일 때는 <숨긴다>. 브라우저에서 직접 보고 고친 부분이다 —
                   * "문서에서 답을 찾지 못했어요" 라고 해놓고 바로 아래에
                   * "휴학규정.md 관련도 57%" 가 붙으면 <찾았는데 왜 답을 안 해?> 로 읽힌다.
                   *
                   * 서버가 fallback 에도 근거를 함께 주는 건 버그가 아니다 —
                   * 검색 컷오프를 통과한 청크가 있는데 생성 단계에서 NO_ANSWER 가 난 경우다.
                   * 그 기록은 "무엇을 근거로 봤는데도 답을 못 했나" 를 알려주므로 DB 에는 남겨야 한다.
                   * <저장의 목적과 표시의 목적이 다르다> — 화면에서만 감춘다.
                   */}
                  {!bubble.isFallback && bubble.sources && bubble.sources.length > 0 && (
                    <Sources sources={bubble.sources} />
                  )}

                  <div className="mt-1.5 flex items-center gap-2 text-xs text-muted">
                    {bubble.latencyMs != null && <span>{bubble.latencyMs}ms</span>}
                    {bubble.messageId && (
                      <>
                        <FeedbackButton
                          active={bubble.feedback === 1}
                          onClick={() => handleFeedback(index, 1)}
                          label="도움이 됐어요"
                        >
                          👍
                        </FeedbackButton>
                        <FeedbackButton
                          active={bubble.feedback === -1}
                          onClick={() => handleFeedback(index, -1)}
                          label="도움이 안 됐어요"
                        >
                          👎
                        </FeedbackButton>
                      </>
                    )}
                  </div>
                </div>
              )}
            </div>
          ))}

          {sending && <p className="text-sm text-muted">답변을 만드는 중…</p>}

          {/* 스크롤을 맞출 기준점. 내용이 없는 빈 div 다. */}
          <div ref={bottomRef} />
        </div>

        {error && (
          <p
            role="alert"
            className="border-t border-subtle px-4 py-2 text-sm text-danger"
          >
            {error}
          </p>
        )}

        <form onSubmit={handleSend} className="flex gap-2 border-t border-subtle p-3">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            maxLength={2000}
            placeholder="문서에 대해 질문해보세요"
            className="flex-1 rounded-md border border-subtle bg-background px-3 py-2 text-sm outline-none focus:border-accent"
          />
          <button
            type="submit"
            disabled={sending || !input.trim()}
            className="rounded-md bg-foreground px-4 py-2 text-sm font-medium text-surface disabled:opacity-50"
          >
            보내기
          </button>
        </form>
      </div>
    </>
  );
}

/**
 * 답변의 최소 서식(굵게·줄바꿈)만 그린다.
 *
 * 왜 마크다운 라이브러리를 안 쓰나: 답변에 실제로 오는 서식은 `**굵게**` 와 줄바꿈뿐이다.
 * 그걸 위해 파서를 통째로 얹는 건 과하다.
 *
 * ⚠️ 왜 dangerouslySetInnerHTML 을 안 쓰나: 이건 <LLM 이 만든 문자열>이다.
 *    HTML 로 주입하면 문서 안에 섞여 들어온 것이 그대로 실행될 여지가 생긴다.
 *    React 요소로 만들면 텍스트는 항상 텍스트로만 들어간다.
 *
 * ⚠️ <사용자가 친 말풍선에는 쓰지 않는다.> 그 사람이 친 `**` 는 글자 그대로여야 한다.
 *
 * (대안은 "프롬프트에서 마크다운을 쓰지 말라고 지시하기"였다. 안 택한 이유는
 *  모델이 지시를 어기면 `**` 가 화면에 그대로 새어 나오고 그건 우리가 못 막기 때문이다.
 *  받는 쪽에서 처리하는 게 확실하다.)
 */
function RichText({ text }: { text: string }) {
  return (
    <>
      {text.split("\n").map((line, li) => (
        <span key={li}>
          {li > 0 && <br />}
          {line.split(/(\*\*[^*]+\*\*)/g).map((part, pi) =>
            /^\*\*[^*]+\*\*$/.test(part) ? (
              <strong key={pi}>{part.slice(2, -2)}</strong>
            ) : (
              part
            ),
          )}
        </span>
      ))}
    </>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
 * 출처 — 이 제품의 핵심 주장("근거를 보여준다")이 증명되는 자리
 * ─────────────────────────────────────────────────────────────────────────────
 * 예전에는 근거 5건을 각각 본문 2줄까지 펼쳐 놨는데, 답변이 한 줄인 화면에서
 * 근거 블록이 <화면 대부분을 먹었다>. 읽어야 할 것(답변)보다 훑어야 할 것(근거)이
 * 더 크게 놓인 셈이다.
 *
 * 그래서 접었다. 다만 <파일명은 접지 않는다> — 그게 이 제품의 주장 자체다.
 * 기본은 "어디서 왔나"(제목 + 관련도), 누르면 "정말 그렇게 쓰여 있나"(본문).
 *
 * 🔴 라벨에 파일명 대신 <조항 제목>을 쓴다.
 *    2026-08-03 청킹 변경으로 모든 청크가 `## 조항 제목` 으로 시작하게 됐다.
 *    "취업규칙.md" 다섯 줄보다 "제8조 경조사 지원 / 수습 기간 / 결혼" 이 훨씬 읽힌다.
 *    (제목이 없는 문서 — pdf 등 — 는 파일명으로 떨어진다)
 */
function splitSource(preview: string): { section: string | null; body: string } {
  const lines = preview.split("\n");
  const m = /^#{1,6}\s+(.+)$/.exec(lines[0]?.trim() ?? "");
  return m
    ? { section: m[1].trim(), body: lines.slice(1).join("\n").trim() }
    : { section: null, body: preview };
}

function Sources({ sources }: { sources: Source[] }) {
  // 펼침 상태를 이 컴포넌트 안에 둔다. 메시지마다 독립이라 바깥에서 관리할 이유가 없다.
  const [open, setOpen] = useState<number | null>(null);
  const shown = open !== null ? sources[open] : null;
  const parsed = shown ? splitSource(shown.preview) : null;

  return (
    <div className="mt-2">
      <p className="text-xs text-muted">근거 {sources.length}곳 · 누르면 원문이 보입니다</p>
      <ul className="mt-1 flex flex-wrap gap-1">
        {sources.map((source, i) => {
          const { section } = splitSource(source.preview);
          const on = open === i;
          return (
            <li key={source.chunkId}>
              <button
                type="button"
                onClick={() => setOpen(on ? null : i)}
                aria-expanded={on}
                className={`flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs transition ${
                  on
                    ? "border-foreground bg-foreground text-surface"
                    : "border-subtle bg-surface hover:border-foreground/30"
                }`}
              >
                <span className="tabular-nums opacity-50">{i + 1}</span>
                <span className="max-w-[16rem] truncate">{section ?? source.filename}</span>
                <span className="tabular-nums opacity-60">
                  {Math.round(source.score * 100)}%
                </span>
              </button>
            </li>
          );
        })}
      </ul>

      {shown && parsed && (
        <div className="mt-1.5 rounded-md border border-subtle bg-surface px-3 py-2 text-xs">
          <p className="text-muted">
            {shown.filename}
            {parsed.section && <> · {parsed.section}</>}
          </p>
          <p className="mt-1 leading-relaxed">{parsed.body}</p>
        </div>
      )}
    </div>
  );
}

function FeedbackButton({
  active,
  onClick,
  label,
  children,
}: {
  active: boolean;
  onClick: () => void;
  /** 아이콘만 있는 버튼이라 스크린리더가 읽을 이름을 따로 준다(접근성). */
  label: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      aria-pressed={active}
      className={`rounded px-1 transition ${active ? "opacity-100" : "opacity-40 hover:opacity-80"}`}
    >
      {children}
    </button>
  );
}
