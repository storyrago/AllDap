"use client";

/*
 * `/w/[publicKey]` — 엔드유저 임베드 위젯의 <채팅 화면 본체>.
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * 이 화면이 어디서 도는가
 * ─────────────────────────────────────────────────────────────────────────────
 * 고객 사이트에 붙인 로더(widget/alldap-widget.js)가 이 페이지를 <iframe> 으로 띄운다.
 * 즉 이 코드는 "남의 사이트 안의 창" 에서 실행된다. 그래서 두 가지가 특별하다.
 *
 *   ① <인증이 없다.> URL 의 publicKey 가 곧 봇 식별자다.
 *      JWT 를 여기서 쓰면 남의 사이트에 우리 토큰을 심는 꼴이 된다.
 *      보호는 Spring 이 한다 — publicKey + Origin 검증 + rate limit.
 *
 *   ② <로더와 postMessage 로 대화한다.> 규약은 로더가 정해뒀다.
 *        이 페이지 → 로더 : { source: 'alldap-widget',      type: 'ready' | 'close' | 'unread' }
 *        로더 → 이 페이지 : { source: 'alldap-widget-host', type: 'host-info' | 'visibility' }
 *      특히 'ready' 를 보내지 않으면 로더가 10초 뒤 "불러오지 못했습니다" 오버레이를 띄운다.
 *      <이 신호가 이 화면의 가장 중요한 계약이다.>
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { ApiError, api } from "@/lib/api";
import type { Source, WidgetConfig } from "@/lib/types";

/** 로더가 쓰는 메시지 표식. 이 값이 아니면 남이 보낸 것이므로 무시한다. */
const HOST_SOURCE = "alldap-widget-host";
const SELF_SOURCE = "alldap-widget";

interface Bubble {
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  isFallback?: boolean;
}

export default function WidgetChatPage() {
  const { publicKey } = useParams<{ publicKey: string }>();

  const [config, setConfig] = useState<WidgetConfig | null>(null);
  const [configError, setConfigError] = useState<string | null>(null);
  const [bubbles, setBubbles] = useState<Bubble[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /*
   * 세션 키.
   *
   * 원칙적으로는 <로더가 만든 값>을 써야 한다. 로더는 호스트 사이트와 같은 origin 이라
   * localStorage 가 "제1자 저장소"로 살아남지만, 이 iframe 의 localStorage 는
   * "제3자 저장소"라 사파리 등에서 자주 차단되기 때문이다.
   * 그래서 로더가 host-info 로 sessionId 를 내려주면 그것으로 <교체>한다.
   *
   * 그 전까지 쓸 임시값을 여기서 만들어 둔다 — iframe 을 직접 열어봤을 때도(개발 중)
   * 채팅이 되어야 하고, host-info 가 늦게 와도 첫 질문이 실패하면 안 되기 때문이다.
   */
  const [sessionId, setSessionId] = useState(() => crypto.randomUUID());

  const bottomRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [bubbles]);

  /* ── 로더와의 handshake ─────────────────────────────────────────────── */

  useEffect(() => {
    function handleMessage(event: MessageEvent) {
      /*
       * origin 을 검사하지 않고 source 표식만 보는 이유.
       *
       * 이 페이지는 <어느 고객 사이트에 심겼는지 미리 알 수 없다>. 그래서 "이 origin 만 허용"
       * 이라는 목록을 만들 수가 없다. 대신 받는 값의 <용도>를 최소로 제한해 위험을 없앤다 —
       * 여기서 받는 건 sessionId(대화를 묶는 키)뿐이고, 이 값으로는 남의 대화를 읽거나
       * 권한을 얻을 수 없다. 봇 식별자는 URL 에서 오고 실제 인가는 Spring 이 publicKey 로 한다.
       */
      const data = event.data;
      if (!data || data.source !== HOST_SOURCE) return;

      if (data.type === "host-info" && typeof data.sessionId === "string") {
        setSessionId(data.sessionId);
      }
    }

    window.addEventListener("message", handleMessage);

    /*
     * 로더에게 "준비됐다" 를 알린다. 이걸 보내야 로더가 로딩 오버레이를 걷는다.
     * 보내지 않으면 10초 뒤 "채팅 화면을 불러오지 못했습니다" 가 뜬다.
     *
     * target 을 '*' 로 두는 이유: 부모(호스트 사이트)의 origin 을 우리는 모른다.
     * 이 메시지에는 비밀이 없고(타입 문자열뿐) 새어도 문제가 없다.
     * 반대로 로더가 우리에게 보낼 때는 origin 을 정확히 지정한다 — 그쪽은 sessionId 를 싣기 때문이다.
     */
    window.parent?.postMessage({ source: SELF_SOURCE, type: "ready" }, "*");

    // 화면이 사라지면 리스너를 떼어낸다. 안 하면 리스너가 쌓인다.
    return () => window.removeEventListener("message", handleMessage);
  }, []);
  /*
   * 의존성이 빈 배열인 이유: 이 effect 는 <처음 한 번만> 실행되어야 한다.
   * 안에서 쓰는 바깥 값이 없고(setSessionId 는 React 가 안정성을 보장한다),
   * 다시 실행되면 ready 신호를 여러 번 보내게 된다.
   */

  /* ── 봇 설정 ────────────────────────────────────────────────────────── */

  const loadConfig = useCallback(async () => {
    try {
      setConfig(await api.widget.config(publicKey));
    } catch (e) {
      // 설정을 못 받아도 화면은 유지한다. 다만 이유는 보여준다 —
      // 대부분 "허용 도메인에 이 주소가 없다" 이고, 그건 관리자가 고칠 수 있는 문제다.
      setConfigError(
        e instanceof ApiError ? e.message : "봇 설정을 불러오지 못했습니다.",
      );
    }
  }, [publicKey]);

  useEffect(() => {
    /*
     * effect 안에서 async 함수를 <즉시 실행>하고 취소 플래그를 둔다.
     *
     * 왜 `void loadConfig()` 이 아닌가 — 두 가지 이유가 겹친다.
     * ① 화면을 떠난 뒤 응답이 도착하면 사라진 컴포넌트의 상태를 갱신하려 든다.
     *    cancelled 플래그로 그때는 아무것도 하지 않는다.
     * ② eslint 의 react-hooks/set-state-in-effect 규칙이 "effect 에서 setState 를 하는 함수를
     *    그냥 호출하는" 모양을 막는다. 응답이 온 <뒤>에 갱신한다는 게 코드 모양에 드러나야 한다.
     */
    let cancelled = false;
    void (async () => {
      await loadConfig();
      if (cancelled) return;
    })();
    return () => {
      cancelled = true;
    };
  }, [loadConfig]);

  /* ── 대화 ───────────────────────────────────────────────────────────── */

  async function handleSend(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const message = input.trim();
    if (!message) return;

    setBubbles((prev) => [...prev, { role: "user", content: message }]);
    setInput("");
    setSending(true);
    setError(null);

    try {
      const response = await api.widget.chat(publicKey, { message, sessionId });
      setBubbles((prev) => [
        ...prev,
        {
          role: "assistant",
          content: response.answer,
          sources: response.sources,
          isFallback: response.isFallback,
        },
      ]);

      /*
       * 닫힌 상태에서 답이 오면 로더가 뱃지를 띄우도록 알린다.
       * "지금 열려 있는가" 는 로더만 아는 정보라, 우리는 신호만 보내고 판단은 로더가 한다.
       */
      window.parent?.postMessage(
        { source: SELF_SOURCE, type: "unread", count: 1 },
        "*",
      );
    } catch (e) {
      setError(
        e instanceof ApiError
          ? e.message
          : "답변을 받지 못했습니다. 잠시 후 다시 시도해주세요.",
      );
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="flex h-dvh flex-col bg-surface">
      <div className="flex-1 space-y-3 overflow-y-auto p-3">
        {/* 인사말은 봇 설정에서 온다. 로더가 아니라 여기서 그린다 — 같은 UI 를 두 곳에서 만들지 않으려고. */}
        {config && bubbles.length === 0 && (
          <Assistant>{config.welcomeMessage}</Assistant>
        )}

        {configError && (
          <p className="rounded-md border border-dashed border-subtle px-3 py-2 text-xs text-muted">
            {configError}
          </p>
        )}

        {bubbles.map((bubble, index) => (
          // 말풍선은 뒤에 추가만 되고 중간 삽입·삭제가 없어 index 가 안정적이다.
          <div key={index}>
            {bubble.role === "user" ? (
              <div className="flex justify-end">
                <p className="max-w-[85%] rounded-lg bg-accent px-3 py-2 text-sm text-white">
                  {bubble.content}
                </p>
              </div>
            ) : (
              <Assistant isFallback={bubble.isFallback} sources={bubble.sources}>
                {bubble.content}
              </Assistant>
            )}
          </div>
        ))}

        {sending && <p className="text-xs text-muted">답변을 찾는 중…</p>}
        {error && (
          <p role="alert" className="text-xs text-red-600 dark:text-red-400">
            {error}
          </p>
        )}

        <div ref={bottomRef} />
      </div>

      <form onSubmit={handleSend} className="flex gap-2 border-t border-subtle p-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          maxLength={2000}
          placeholder="궁금한 점을 물어보세요"
          className="flex-1 rounded-md border border-subtle bg-background px-3 py-2 text-sm outline-none focus:border-accent"
        />
        <button
          type="submit"
          disabled={sending || !input.trim()}
          className="rounded-md bg-accent px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          전송
        </button>
      </form>
    </div>
  );
}

/** 봇 쪽 말풍선. 출처 표시 규칙이 관리자 채팅과 같아야 해서 한 군데로 모았다. */
function Assistant({
  children,
  isFallback,
  sources,
}: {
  children: React.ReactNode;
  isFallback?: boolean;
  sources?: Source[];
}) {
  return (
    <div className="max-w-[90%]">
      <p
        className={`rounded-lg px-3 py-2 text-sm ${
          isFallback
            ? /* fallback 은 에러가 아니라 의도된 동작이다. 경고색을 쓰지 않는다. */
              "border border-dashed border-subtle text-muted"
            : "bg-foreground/5"
        }`}
      >
        {children}
      </p>

      {/* fallback 이면 근거를 숨긴다 — "못 찾았다" 면서 출처를 보여주면 모순으로 읽힌다. */}
      {!isFallback && sources && sources.length > 0 && (
        <p className="mt-1 text-xs text-muted">
          근거: {sources.map((s) => s.filename).join(", ")}
        </p>
      )}
    </div>
  );
}
