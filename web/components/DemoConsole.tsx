"use client";

/*
 * DemoConsole — `/demo` 의 본체. 왼쪽에 학습한 문서, 오른쪽에 채팅.
 *
 * ── 왜 "use client" 인가 ────────────────────────────────────────────────────
 * 문서를 고르는 것도, 질문을 보내는 것도 <사용자 입력에 따라 화면이 바뀌는> 일이다.
 * 서버 컴포넌트에는 useState 도 onClick 도 없다. 반대로 파일을 읽는 일은 서버만 할 수
 * 있어서, 페이지(서버 컴포넌트)가 읽어 props 로 내려주고 여기서는 받기만 한다.
 *
 * ── 왜 문서 본문을 통째로 props 로 받나 ────────────────────────────────────
 * 코퍼스 50개가 다 합쳐 200KB 다(이미지 한 장보다 작다). 문서를 고를 때마다 서버에
 * 다시 요청하면 그 한 번의 왕복이 화면 반응을 늦추는데, 얻는 게 없다. 처음에 다 받아두면
 * 문서 전환이 즉시다. 코퍼스가 수십 MB 로 커지면 그때 나눠 받는 방식으로 바꿔야 한다.
 */

import { useEffect, useMemo, useRef, useState } from "react";

import { ApiError, api } from "@/lib/api";
import type { Source } from "@/lib/types";

import type { CorpusDoc } from "@/app/(site)/demo/page";

/** 랜딩과 같은 데모 봇을 본다. 위젯 공개 API 라 로그인 없이 부를 수 있다. */
const DEMO_PUBLIC_KEY = process.env.NEXT_PUBLIC_DEMO_PUBLIC_KEY ?? "pk_local_dev";

/**
 * 제안 질문. <답이 있는 것 하나, 없는 것 하나>를 반드시 같이 둔다.
 *
 * 🔴 이게 이 페이지의 핵심이다. 답이 되는 질문만 제안하면 "잘 답하는 챗봇"만 보여주게 되고,
 *    그건 어느 챗봇이나 한다. 이 제품이 다른 지점은 <답할 수 없을 때 거절하는 것>이라,
 *    그 장면을 방문자가 한 번 클릭으로 볼 수 있어야 한다.
 *    (`grounded: false` 질문은 W1 fallback 시험에서 실제로 쓰는 것들이다 —
 *     `ai-service/app/fallback_e2e_check.py`)
 */
const SUGGESTIONS = [
  { text: "정규직 연차는 며칠인가요?", grounded: true },
  { text: "정규직 수습 기간은 얼마인가요?", grounded: true },
  { text: "사내 헬스장 있나요?", grounded: false },
  { text: "주차 지원되나요?", grounded: false },
] as const;

type Msg =
  | { role: "me"; text: string }
  /* isError 는 <서버가 답을 못 준 것>이고 isFallback 은 <근거가 없어 답하지 않은 것>이다.
     원인이 다른 두 사실이라 한 모양으로 뭉개면 안 된다 — 이 저장소가 지표에서 같은
     부류의 실수를 네 번 냈다(AGENTS.md "낸 버그 4건"). 화면에서도 갈라 보여준다. */
  | { role: "bot"; text: string; sources: Source[]; isFallback: boolean; isError?: boolean };

/**
 * 마크다운을 통째로 렌더하는 라이브러리를 넣지 않는다. 코퍼스가 쓰는 문법이
 * `# 제목` 과 문단뿐이라, 그 둘만 처리하면 된다. 의존성 하나를 아끼는 것보다
 * <읽을 수 있게 만드는 것>이 목적이고 그건 이 열 줄로 충분하다.
 */
function DocBody({ body }: { body: string }) {
  const blocks = useMemo(
    () =>
      body
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean),
    [body],
  );

  return (
    <div className="space-y-3">
      {blocks.map((line, i) => {
        if (line.startsWith("## ")) {
          return (
            <h3 key={i} className="pt-2 text-sm font-bold tracking-[-0.01em]">
              {line.slice(3)}
            </h3>
          );
        }
        if (line.startsWith("# ")) {
          return (
            <h2 key={i} className="text-base font-bold tracking-[-0.02em]">
              {line.slice(2)}
            </h2>
          );
        }
        return (
          <p key={i} className="text-sm leading-relaxed text-muted">
            {line}
          </p>
        );
      })}
    </div>
  );
}

export function DemoConsole({ docs }: { docs: CorpusDoc[] }) {
  /** 지금 펼쳐 놓은 문서의 파일명. null 이면 목록만 보여준다. */
  const [openDoc, setOpenDoc] = useState<string | null>(null);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [pending, setPending] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  /*
   * 대화 로그 영역. 새 말풍선이 생기면 맨 아래로 내린다.
   * ref 는 "DOM 요소를 직접 가리키는 손잡이"다 — 스크롤 위치는 React 상태로 표현할 수 없는
   * 브라우저 동작이라 요소를 직접 만져야 한다.
   *
   * ⚠️ 이 화면에서는 sentinel + scrollIntoView 를 쓰면 안 된다.
   * 위젯(/w/[publicKey])과 대시보드 채팅은 그 방식을 쓰는데, 두 화면은 h-dvh 라
   * <페이지 자체가 스크롤되지 않아서> scrollIntoView 가 컨테이너만 움직인다.
   * /demo 는 왼쪽 문서 목록 때문에 페이지가 스크롤되고, scrollIntoView 는
   * <스크롤 가능한 조상을 전부> 움직인다 — 답변이 올 때마다 창이 통째로 아래로 튄다
   * (실측 664px, 설계 문서의 대조표 참고). 그래서 컨테이너만 직접 민다.
   */
  const logRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
    /*
     * 의존성이 둘인 이유.
     * msgs — 말풍선이 늘어날 때 내려야 한다.
     * pending — "문서를 찾아보는 중…" 줄이 생겼다 사라지며 로그 높이가 바뀐다.
     *           msgs 만 넣으면 그 로딩 문구가 스크롤 아래에 숨어, 보낸 직후 화면이
     *           아무 반응 없는 것처럼 보인다.
     */
  }, [msgs, pending]);

  /* 같은 대화를 묶는 키. 서버가 conversations 행을 이걸로 이어 붙인다.
     첫 질문 때 한 번 만들고 새로고침 전까지 유지한다. */
  const sessionRef = useRef<string | null>(null);
  const sessionId = () => (sessionRef.current ??= crypto.randomUUID());

  /* 파일명 → 문서. 출처를 눌렀을 때 그 문서를 바로 여는 데 쓴다.
     docs 는 서버가 준 뒤 바뀌지 않으므로 한 번만 만든다. */
  const byFilename = useMemo(() => new Map(docs.map((d) => [d.filename, d])), [docs]);
  const current = openDoc ? byFilename.get(openDoc) : undefined;

  const send = (preset?: string) => {
    const value = (preset ?? inputRef.current?.value ?? "").trim();
    // 답을 기다리는 중이면 무시한다. 없으면 Enter 연타로 요청이 겹쳐
    // 답변 순서가 뒤섞이고 rate limit 만 깎인다.
    if (!value || pending) return;
    if (inputRef.current) inputRef.current.value = "";
    setMsgs((s) => [...s, { role: "me", text: value }]);
    setPending(true);

    api.widget
      .chat(DEMO_PUBLIC_KEY, { message: value, sessionId: sessionId() })
      .then((res) => {
        setMsgs((s) => [
          ...s,
          { role: "bot", text: res.answer, sources: res.sources, isFallback: res.isFallback },
        ]);
      })
      .catch((e) => {
        /* 실패를 조용히 삼키면 안 된다. 답이 안 오는 것과 "모른다"는 답은 다른 상태인데,
           화면에 아무것도 안 뜨면 방문자는 챗봇이 고장난 줄 안다.
           서버가 "무엇을 어떻게 하면 되는지"까지 담은 한국어를 주므로 그대로 보여준다. */
        setMsgs((s) => [
          ...s,
          {
            role: "bot",
            text:
              e instanceof ApiError
                ? e.message
                : "지금은 답변을 가져오지 못했습니다. 잠시 후 다시 시도해 주세요.",
            sources: [],
            isFallback: false,
            isError: true,
          },
        ]);
      })
      .finally(() => setPending(false));
  };

  return (
    <div className="mt-10 grid gap-8 lg:grid-cols-[1fr_22rem]">
      {/* ── 왼쪽: 학습한 문서 ────────────────────────────────────────────── */}
      <section className="min-w-0">
        <h2 className="text-sm font-bold tracking-[0.14em] text-muted">학습한 문서</h2>

        <ul className="mt-4 flex flex-wrap gap-2">
          {docs.map((d) => {
            const active = d.filename === openDoc;
            return (
              <li key={d.filename}>
                <button
                  type="button"
                  // 같은 문서를 다시 누르면 닫힌다. 목록으로 돌아갈 길을 따로 만들 필요가 없다.
                  onClick={() => setOpenDoc(active ? null : d.filename)}
                  aria-pressed={active}
                  className={`rounded-lg border px-3 py-2 text-left text-xs leading-tight transition ${
                    active
                      ? "border-foreground bg-foreground text-surface"
                      : "border-subtle bg-surface text-foreground hover:border-foreground/40"
                  }`}
                >
                  {d.title}
                </button>
              </li>
            );
          })}
        </ul>

        {current ? (
          <article className="mt-6 rounded-xl border border-subtle bg-surface p-6">
            <p className="text-xs tracking-[0.14em] text-muted">{current.filename}</p>
            <div className="mt-4">
              <DocBody body={current.body} />
            </div>
          </article>
        ) : (
          <p className="mt-6 rounded-xl border border-dashed border-subtle p-6 text-sm text-muted">
            문서를 누르면 전문이 열립니다. 답변에 붙은 출처를 눌러도 그 문서가 열립니다.
          </p>
        )}
      </section>

      {/* ── 오른쪽: 채팅 ─────────────────────────────────────────────────── */}
      <aside className="lg:sticky lg:top-8 lg:self-start">
        <h2 className="text-sm font-bold tracking-[0.14em] text-muted">물어보기</h2>

        <div className="mt-4 rounded-xl border border-subtle bg-surface p-4">
          <div
            ref={logRef}
            /*
             * 대화가 쌓여도 패널이 세로로 자라지 않게 <고정 높이 + 안쪽 스크롤>.
             * 높이를 막지 않으면 패널이 화면보다 커지고, 그 순간 위 <aside> 의
             * lg:sticky 가 무력해진다 — sticky 는 붙은 요소가 화면보다 작을 때만 동작한다.
             *
             * 28rem(448px)은 눈대중이 아니라 브라우저에서 잰 값이다.
             * 질문 36px + 답변 177px + 질문 36px + 답변 132px + 간격 36px = 417px (2쌍).
             *
             * max-h 는 낮은 화면에서만 줄어드는 안전장치다. 이 패널에서 로그를 뺀 나머지
             * (제목·제안 버튼·입력창·안내문)가 285px 이고 top-8 이 32px 이라 20rem 을 뺀다.
             * 이게 없으면 세로가 짧은 화면에서 방금 고친 문제가 그대로 재현된다.
             */
            className="flex h-[28rem] max-h-[calc(100vh-20rem)] flex-col gap-3 overflow-y-auto"
            /*
             * 스크롤되는 영역은 포커스를 받을 수 없으면 키보드로 굴릴 방법이 아예 없다.
             * role="log" 은 새로 추가되는 답변을 스크린리더가 읽어주게 한다(암묵적 aria-live).
             */
            tabIndex={0}
            role="log"
          >
            {/* m-auto: flex 컨테이너에서 margin:auto 는 남는 공간을 사방으로 나눠 가진다.
                자식이 이것 하나뿐인 빈 상태에서만 효과가 있고, 말풍선이 생기면 사라진다. */}
            {msgs.length === 0 && (
              <p className="m-auto text-sm leading-relaxed text-muted">
                왼쪽 문서에 있는 것과 <b className="font-semibold text-foreground">없는 것</b>을
                하나씩 물어보세요. 두 답이 어떻게 다른지가 이 제품의 전부입니다.
              </p>
            )}

            {msgs.map((m, i) =>
              m.role === "me" ? (
                <p
                  key={i}
                  className="self-end rounded-xl rounded-br-sm bg-foreground px-3 py-2 text-sm text-surface"
                >
                  {m.text}
                </p>
              ) : (
                <div
                  key={i}
                  /* 오류는 답변과 <같은 모양이면 안 된다.> 그러면 방문자가 서버 장애 문구를
                     봇의 답변으로 읽는다. 색은 이 저장소의 danger 토큰을 그대로 쓴다. */
                  className={
                    m.isError
                      ? "rounded-xl rounded-bl-sm border border-danger bg-danger-surface px-3 py-2"
                      : "rounded-xl rounded-bl-sm bg-background px-3 py-2"
                  }
                >
                  {/* role="alert" 로 스크린리더가 즉시 읽게 한다. 놓치면 안 되는 정보다. */}
                  <p
                    className={m.isError ? "text-sm leading-relaxed text-danger" : "text-sm leading-relaxed"}
                    role={m.isError ? "alert" : undefined}
                  >
                    {m.text}
                  </p>

                  {/* 거절한 답변에는 <근거가 없다는 사실 자체>를 표시한다.
                      출처가 비어 있는 것을 눈으로 확인하는 게 이 화면의 목적이다. */}
                  {m.isFallback ? (
                    <p className="mt-2 border-t border-subtle pt-2 text-xs font-medium text-muted">
                      근거를 찾지 못해 답하지 않았습니다
                    </p>
                  ) : (
                    m.sources.length > 0 && (
                      <div className="mt-2 border-t border-subtle pt-2">
                        <p className="text-xs text-muted">출처 · 눌러서 대조해 보세요</p>
                        <div className="mt-1 flex flex-wrap gap-1">
                          {/* 같은 문서에서 청크를 여러 개 가져오면 파일명이 중복된다. Set 으로 접는다. */}
                          {[...new Set(m.sources.map((s) => s.filename))].map((filename) => (
                            <button
                              key={filename}
                              type="button"
                              onClick={() => setOpenDoc(filename)}
                              // 코퍼스에 없는 파일명이면 열 문서가 없다(DB 와 파일이 어긋난 경우)
                              disabled={!byFilename.has(filename)}
                              className="rounded-md border border-subtle px-2 py-1 text-xs hover:border-foreground/40 disabled:opacity-50"
                            >
                              {byFilename.get(filename)?.title ?? filename}
                            </button>
                          ))}
                        </div>
                      </div>
                    )
                  )}
                </div>
              ),
            )}

            {pending && <p className="text-sm text-muted">문서를 찾아보는 중…</p>}
          </div>

          <div className="mt-4 flex flex-wrap gap-1">
            {SUGGESTIONS.map((s) => (
              <button
                key={s.text}
                type="button"
                onClick={() => send(s.text)}
                disabled={pending}
                /* 답이 없는 질문을 <시각적으로 구분하지 않는다.> 미리 표시해두면
                   "거절하도록 준비된 질문"으로 읽혀서, 정작 보여주려는 것이 연출로 보인다. */
                className="rounded-full border border-subtle px-3 py-1.5 text-xs hover:border-foreground/40 disabled:opacity-50"
              >
                {s.text}
              </button>
            ))}
          </div>

          <div className="mt-3 flex gap-2">
            <input
              ref={inputRef}
              onKeyDown={(e) => {
                if (e.key !== "Enter") return;
                /*
                 * 🐛 한글 입력에서 <반드시> 필요한 검사다.
                 * 한글은 자모를 모아 한 글자를 만든다. 마지막 글자가 아직 조합 중일 때
                 * Enter 를 누르면, send() 가 값을 읽고 입력창을 비운 <뒤에> IME 가 그 글자를
                 * 확정해 빈 입력창에 다시 넣는다. 그 글자가 다음 전송에 딸려 간다.
                 * isComposing 이 true 면 이 Enter 는 "조합을 확정하라"는 뜻이다.
                 */
                if (e.nativeEvent.isComposing) return;
                e.preventDefault();
                send();
              }}
              placeholder="문서에 대해 물어보세요"
              aria-label="질문 입력"
              /* 서버가 2000자를 넘기면 거절한다. 여기서 미리 막으면 왕복 한 번과
                 "왜 안 되지" 를 아낀다(잘라내는 게 아니라 더 못 치게 한다). */
              maxLength={2000}
              className="min-w-0 flex-1 rounded-lg border border-subtle bg-background px-3 py-2 text-sm outline-none focus:border-accent"
            />
            <button
              type="button"
              onClick={() => send()}
              disabled={pending}
              className="rounded-lg bg-foreground px-4 py-2 text-sm font-semibold text-surface disabled:opacity-50"
            >
              보내기
            </button>
          </div>
        </div>

        <p className="mt-3 text-xs leading-relaxed text-muted">
          답변은 실제 서비스와 같은 경로로 만들어집니다. 검색·생성·거절 판정이 모두 그대로
          동작합니다.
        </p>
      </aside>
    </div>
  );
}
