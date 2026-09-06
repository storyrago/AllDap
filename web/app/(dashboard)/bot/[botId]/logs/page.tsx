"use client";

/*
 * `/bot/[botId]/logs` — 대화 로그 목록 · 상세.
 *
 * W3(품질 대시보드)의 "미답변 목록"이 결국 이 데이터에서 나온다.
 * 그래서 이 화면의 핵심 필터는 <미답변만 보기>다 — 봇이 무엇에 답하지 못했는지가
 * 곧 "어떤 문서를 더 올려야 하는가"의 답이기 때문이다.
 *
 * 호출하는 Spring API:
 *   GET /api/bots/{botId}/logs?onlyFallback&onlyThumbsDown&page&size
 *   GET /api/bots/{botId}/logs/{conversationId}
 */

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { ApiError, api } from "@/lib/api";
import type { ChatMessage, ConversationSummary, Paged } from "@/lib/types";
import { PageHeader } from "@/components/PageHeader";

const PAGE_SIZE = 20;

export default function LogsPage() {
  const { botId } = useParams<{ botId: string }>();

  const [page, setPage] = useState(0);
  const [onlyFallback, setOnlyFallback] = useState(false);
  const [onlyThumbsDown, setOnlyThumbsDown] = useState(false);

  const [logs, setLogs] = useState<Paged<ConversationSummary> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  /** 펼쳐 놓은 대화. null 이면 아무것도 안 펼친 상태. */
  const [openId, setOpenId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [messagesLoading, setMessagesLoading] = useState(false);

  const loadLogs = useCallback(async () => {
    setLoading(true);
    try {
      setLogs(
        await api.logs.list(botId, {
          onlyFallback,
          onlyThumbsDown,
          page,
          size: PAGE_SIZE,
        }),
      );
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "대화 로그를 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, [botId, onlyFallback, onlyThumbsDown, page]);
  /*
   * 의존성이 네 개인 이유: 이 중 무엇이 바뀌어도 <다른 목록>을 불러야 한다.
   * 하나라도 빠뜨리면 필터를 눌렀는데 목록이 그대로인 버그가 된다.
   */

  useEffect(() => {
    // eslint react-hooks/set-state-in-effect 때문에 IIFE 로 감싼다 — setState 가
    // <비동기 경계 뒤>에서 일어난다는 것을 코드에 드러내는 것이다.
    // 취소 플래그는 두지 않는다: React 18+ 에서 떠난 뒤의 setState 는 무시되고,
    // 예전의 `await loadLogs(); if (cancelled) return;` 은 setState 가 이미 끝난
    // 뒤라 아무것도 막지 못했다. 근거는 app/(dashboard)/dashboard/page.tsx 첫 effect 주석.
    void (async () => {
      await loadLogs();
    })();
  }, [loadLogs]);

  /**
   * 필터를 바꿀 때 페이지를 0으로 되돌린다.
   *
   * 이걸 빼먹는 게 페이지네이션의 가장 흔한 버그다 —
   * 3페이지를 보다가 필터를 켜면 결과가 5건뿐인데 3페이지를 요청해서
   * <빈 화면>이 나오고, 사용자는 "필터에 해당하는 게 없다"고 오해한다.
   */
  function changeFilter(next: { onlyFallback?: boolean; onlyThumbsDown?: boolean }) {
    if (next.onlyFallback !== undefined) setOnlyFallback(next.onlyFallback);
    if (next.onlyThumbsDown !== undefined) setOnlyThumbsDown(next.onlyThumbsDown);
    setPage(0);
    setOpenId(null);
  }

  async function toggleConversation(conversationId: string) {
    // 같은 것을 다시 누르면 접는다.
    if (openId === conversationId) {
      setOpenId(null);
      return;
    }
    setOpenId(conversationId);
    setMessages([]);
    setMessagesLoading(true);
    try {
      setMessages(await api.logs.messages(botId, conversationId));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "대화 내용을 불러오지 못했습니다.");
    } finally {
      setMessagesLoading(false);
    }
  }

  return (
    <>
      <PageHeader
        title="대화 로그"
        description="실제로 오간 대화입니다. 답하지 못한 질문은 무엇을 보강해야 하는지 알려줍니다."
      />

      <div className="mt-4 flex flex-wrap gap-4 text-sm">
        <Checkbox
          checked={onlyFallback}
          onChange={(v) => changeFilter({ onlyFallback: v })}
          label="미답변만"
        />
        <Checkbox
          checked={onlyThumbsDown}
          onChange={(v) => changeFilter({ onlyThumbsDown: v })}
          label="👎 받은 것만"
        />
      </div>

      {error && (
        <p role="alert" className="mt-4 text-sm text-danger">
          {error}
        </p>
      )}

      <div className="mt-4">
        {loading ? (
          <p className="text-sm text-muted">불러오는 중…</p>
        ) : !logs || logs.items.length === 0 ? (
          <p className="rounded-lg border border-subtle px-6 py-10 text-center text-sm text-muted">
            {onlyFallback || onlyThumbsDown
              ? "조건에 맞는 대화가 없습니다."
              : "아직 대화가 없습니다. 테스트 채팅이나 위젯으로 질문해보세요."}
          </p>
        ) : (
          <>
            <ul className="divide-y divide-subtle rounded-lg border border-subtle bg-surface">
              {logs.items.map((conversation) => (
                <li key={conversation.id}>
                  <button
                    type="button"
                    onClick={() => void toggleConversation(conversation.id)}
                    /* aria-expanded 는 "이 버튼이 무언가를 펼친다"를 스크린리더에 알려준다. */
                    aria-expanded={openId === conversation.id}
                    className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-foreground/5"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm">
                        {conversation.firstUserMessage ?? "(질문 없음)"}
                      </p>
                      <p className="mt-0.5 text-xs text-muted">
                        {formatDateTime(conversation.createdAt)} · 메시지{" "}
                        {conversation.messageCount}개
                      </p>
                    </div>

                    {/* 관리자 테스트 대화와 실사용을 구분해 보여준다 — 지표 해석이 달라진다. */}
                    <span className="shrink-0 rounded-full bg-foreground/10 px-2 py-0.5 text-xs text-muted">
                      {conversation.channel === "test" ? "테스트" : "위젯"}
                    </span>
                    {conversation.hasFallback && (
                      <span className="shrink-0 rounded-full bg-warning-surface px-2 py-0.5 text-xs text-warning">
                        미답변 포함
                      </span>
                    )}
                  </button>

                  {openId === conversation.id && (
                    <div className="space-y-3 border-t border-subtle bg-background/50 px-4 py-3">
                      {messagesLoading ? (
                        <p className="text-sm text-muted">불러오는 중…</p>
                      ) : (
                        messages.map((message) => (
                          <MessageRow key={message.id} message={message} />
                        ))
                      )}
                    </div>
                  )}
                </li>
              ))}
            </ul>

            <div className="mt-4 flex items-center justify-between text-sm">
              <span className="text-muted">
                총 {logs.totalElements}건 · {logs.page + 1}/{Math.max(logs.totalPages, 1)} 페이지
              </span>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setPage((p) => p - 1)}
                  disabled={logs.page === 0}
                  className="rounded-md border border-subtle px-3 py-1.5 disabled:opacity-40"
                >
                  이전
                </button>
                <button
                  type="button"
                  onClick={() => setPage((p) => p + 1)}
                  disabled={logs.page + 1 >= logs.totalPages}
                  className="rounded-md border border-subtle px-3 py-1.5 disabled:opacity-40"
                >
                  다음
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </>
  );
}

/** 대화 상세의 메시지 한 줄. 채팅 화면과 달리 <읽기 전용>이라 피드백 버튼이 없다. */
function MessageRow({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  return (
    <div className={isUser ? "flex justify-end" : ""}>
      <div className={isUser ? "max-w-[80%]" : "max-w-[85%]"}>
        <p
          className={`rounded-lg px-3 py-2 text-sm ${
            isUser
              ? "bg-foreground text-surface"
              : message.isFallback
                ? "border border-dashed border-subtle text-muted"
                : "bg-foreground/5"
          }`}
        >
          {message.content}
        </p>

        {/* 근거는 fallback 이 아닐 때만 보여준다 — 채팅 화면과 같은 이유다. */}
        {!message.isFallback && message.sources && message.sources.length > 0 && (
          <p className="mt-1 text-xs text-muted">
            근거: {message.sources.map((s) => s.filename).join(", ")}
          </p>
        )}

        {message.feedback !== null && message.feedback !== undefined && (
          <p className="mt-1 text-xs">{message.feedback === 1 ? "👍" : "👎"}</p>
        )}
      </div>
    </div>
  );
}

function Checkbox({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  label: string;
}) {
  return (
    <label className="flex items-center gap-2">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span>{label}</span>
    </label>
  );
}

/**
 * 서버가 주는 ISO 시각을 한국어로.
 *
 * 브라우저의 시간대를 그대로 쓴다(toLocaleString 기본 동작).
 * 서버의 로그 <필터>는 KST 고정인데 여기는 브라우저 기준이라 엄밀히는 어긋날 수 있다.
 * 지금은 사용자가 전부 한국에 있어 차이가 없다.
 * TODO(W3 이후): 해외 사용자가 생기면 표시 기준을 서버와 맞출 것.
 */
function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("ko-KR", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
