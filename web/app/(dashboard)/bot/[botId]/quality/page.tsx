"use client";

/*
 * `/bot/[botId]/quality` — ★ PRD 가 "제품의 심장"이라 부르는 화면 (F-05, §8)
 *
 * 이 화면이 없으면 AllDap 은 그냥 흔한 챗봇 빌더다.
 * "만들어준다"가 아니라 "얼마나 잘 답하는지 숫자로 보여주고 개선 루프를 돌린다"가 차별점이다.
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * 왜 이 파일이 "use client" 인가 — 이 프로젝트에서 반복되는 질문이라 여기 한 번 더 적는다
 * ─────────────────────────────────────────────────────────────────────────────
 * Next.js 는 기본적으로 서버 컴포넌트다. 서버에서 데이터를 미리 가져와 HTML 로 내려주면
 * 더 빠르고 자바스크립트도 적게 간다. 그런데 이 화면은 그럴 수가 없다. 이유가 셋이다.
 *
 *   ① <토큰이 브라우저에만 있다.> JWT 를 localStorage 에 보관하므로(lib/api.ts)
 *      서버는 "이 요청을 보낸 사람이 누구인지" 자체를 모른다. 대신 가져와 줄 수가 없다.
 *   ② <폴링이 필요하다.> 평가 실행은 백그라운드로 돌아 status 가 running → completed 로
 *      바뀐다. 그걸 지켜보려면 setInterval 과 useEffect 가 필요하고, 둘 다 클라이언트 전용이다.
 *   ③ <버튼이 있다.> onClick 은 서버 컴포넌트에 붙일 수 없다.
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * 이 화면이 지켜야 하는 규칙 하나 — 숫자를 거짓말하지 않기
 * ─────────────────────────────────────────────────────────────────────────────
 * 점수는 전부 null 이 될 수 있고, <null 은 0 이 아니다.>
 *   · 실행이 아직 running 이라 점수가 없다
 *   · 답변이 전부 fallback 이라 채점할 대상이 없었다
 *   · 채점 호출 자체가 실패했다
 * 이걸 0 으로 그리면 "품질이 0점"으로 읽힌다. 그래서 없는 값은 "—" 로 그린다.
 * (아래 fmt 함수가 그 한 곳이다)
 */

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { ApiError, api } from "@/lib/api";
import type { EvalQuestion, EvalResult, EvalRun } from "@/lib/types";
import { PageHeader } from "@/components/PageHeader";
import { Placeholder } from "@/components/Placeholder";

/** 실행이 끝나기를 기다리는 동안 목록을 다시 부르는 간격. 문서 업로드 폴링과 같은 값이다. */
const POLL_MS = 3000;

export default function QualityPage() {
  const { botId } = useParams<{ botId: string }>();

  const [questions, setQuestions] = useState<EvalQuestion[]>([]);
  const [runs, setRuns] = useState<EvalRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  /* 버튼 두 개는 각각 따로 "진행 중"을 표시해야 한다.
     하나의 boolean 으로 묶으면 질문을 만드는 동안 실행 버튼까지 잠긴다. */
  const [generating, setGenerating] = useState(false);
  const [starting, setStarting] = useState(false);

  /* 펼쳐본 실행의 질문별 결과. 목록을 열 때만 불러온다 —
     실행마다 미리 받아두면 안 볼 데이터까지 전부 내려받게 된다. */
  const [openRunId, setOpenRunId] = useState<string | null>(null);
  const [results, setResults] = useState<EvalResult[]>([]);
  const [resultsLoading, setResultsLoading] = useState(false);

  const load = useCallback(async () => {
    try {
      // 두 요청은 서로를 기다릴 이유가 없다. Promise.all 로 동시에 보낸다.
      const [q, r] = await Promise.all([
        api.evaluation.listQuestions(botId),
        api.evaluation.listRuns(botId),
      ]);
      setQuestions(q);
      setRuns(r);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "평가 정보를 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, [botId]);
  // botId 가 의존성인 이유: 다른 봇 화면으로 이동하면 <그 봇의> 데이터를 불러야 한다.
  // 빼먹으면 봇을 바꿔도 이전 봇의 점수가 계속 보인다.

  useEffect(() => {
    /* effect 안에서 async 를 즉시 실행하고 취소 플래그를 둔다.
       ① 화면을 떠난 뒤 응답이 오면 사라진 컴포넌트의 상태를 갱신하려 든다.
       ② eslint 의 react-hooks/set-state-in-effect 가 "effect 에서 setState 하는 함수를
          그냥 호출하는" 모양을 막는다. 응답이 온 <뒤>에 갱신한다는 게 코드에 드러나야 한다.
       (프로젝트 전반에서 같은 모양을 쓴다 — docs/decisions.md 2026-08-02 참고) */
    let cancelled = false;
    void (async () => {
      await load();
      if (cancelled) return;
    })();
    return () => {
      cancelled = true;
    };
  }, [load]);

  /* ── 실행 상태 폴링 ──────────────────────────────────────────────────
   * running 인 실행이 있을 때만 3초마다 다시 부른다.
   *   ① 다 끝나면 멈춘다. 안 그러면 아무 일도 안 일어나는데 영원히 서버를 두드린다.
   *   ② 화면을 떠나면 반드시 정리한다(clearInterval). 안 하면 타이머가 쌓인다.
   * 의존성에 runs 가 들어간 이유: "돌고 있는 게 남았는가"는 목록이 바뀔 때마다 다시 판단해야 한다.
   * 목록이 갱신될 때마다 이 effect 가 새로 돌면서 조건이 깨지면 타이머를 안 걸어 자연스럽게 멈춘다.
   */
  useEffect(() => {
    if (!runs.some((r) => r.status === "running")) return;
    const timer = setInterval(() => void load(), POLL_MS);
    return () => clearInterval(timer);
  }, [runs, load]);

  const latest = runs[0] ?? null;
  const activeCount = questions.filter((q) => q.isActive).length;

  async function handleGenerate() {
    setGenerating(true);
    setError(null);
    try {
      await api.evaluation.generateQuestions(botId, 10);
      await load();
    } catch (e) {
      // 서버가 "무엇을 어떻게 하면 되는지"까지 담은 한국어를 준다. 그대로 보여준다.
      // (예: "처리가 끝난 문서가 없습니다. 문서를 올린 뒤 상태가 '준비됨'이 되면…")
      setError(e instanceof ApiError ? e.message : "질문을 생성하지 못했습니다.");
    } finally {
      setGenerating(false);
    }
  }

  async function handleStartRun() {
    setStarting(true);
    setError(null);
    try {
      await api.evaluation.startRun(botId);
      await load(); // 목록에 running 이 들어가면 위 폴링 effect 가 저절로 켜진다
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "평가를 시작하지 못했습니다.");
    } finally {
      setStarting(false);
    }
  }

  async function toggleResults(runId: string) {
    if (openRunId === runId) {
      setOpenRunId(null);
      return;
    }
    setOpenRunId(runId);
    setResultsLoading(true);
    try {
      setResults(await api.evaluation.getRunResults(botId, runId));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "채점 결과를 불러오지 못했습니다.");
      setResults([]);
    } finally {
      setResultsLoading(false);
    }
  }

  return (
    <>
      <PageHeader
        title="품질 대시보드"
        description="테스트 질문을 실제 파이프라인에 태워 채점합니다. 검색 설정을 바꿔가며 점수를 비교하는 것이 목적입니다."
        actions={
          <button
            type="button"
            onClick={handleStartRun}
            disabled={starting || activeCount === 0}
            className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
          >
            {starting ? "시작하는 중…" : "평가 실행"}
          </button>
        }
      />

      {error && (
        <p
          role="alert"
          className="mt-4 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300"
        >
          {error}
        </p>
      )}

      {loading ? (
        <p className="mt-6 text-sm text-muted">불러오는 중…</p>
      ) : (
        <>
          <ScoreCards run={latest} />
          <QuestionSection
            questions={questions}
            activeCount={activeCount}
            generating={generating}
            onGenerate={handleGenerate}
          />
          <RunSection
            runs={runs}
            openRunId={openRunId}
            results={results}
            resultsLoading={resultsLoading}
            onToggle={toggleResults}
          />
          <UnansweredSection />
        </>
      )}
    </>
  );
}

/**
 * 점수를 화면 문자열로. <없는 값을 0 으로 그리지 않는 것>이 이 함수의 존재 이유다.
 *
 * null 이 오는 경우가 여럿이고(running / 채점 대상 없음 / 채점 실패) 전부 "0점"과 다르다.
 * 한 곳에 모아두면 화면 어디서도 이 규칙이 깨지지 않는다.
 */
function fmt(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : v.toFixed(3);
}

/** ① 점수 카드 — 최근 실행의 세 숫자 */
function ScoreCards({ run }: { run: EvalRun | null }) {
  const cards = [
    { label: "충실성", hint: "답이 근거 문서와 일치하는가", value: run?.avgFaithfulness },
    { label: "관련성", hint: "질문에 맞는 답인가", value: run?.avgRelevancy },
    { label: "응답률", hint: "fallback 하지 않고 답한 비율", value: run?.answeredRate },
  ];

  return (
    <section className="mb-8 mt-6">
      <h2 className="mb-2 text-sm font-semibold">최근 평가 점수</h2>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {cards.map((c) => (
          <div key={c.label} className="rounded-lg border border-subtle bg-surface px-4 py-3">
            <p className="text-xs text-muted">{c.label}</p>
            <p className="mt-1 text-2xl font-semibold tabular-nums">{fmt(c.value)}</p>
            <p className="mt-1 text-xs text-muted">{c.hint}</p>
          </div>
        ))}
      </div>

      {run ? (
        <p className="mt-2 text-xs text-muted">
          {new Date(run.createdAt).toLocaleString("ko-KR")} 실행 · 상태 {run.status}
        </p>
      ) : (
        <p className="mt-2 text-xs text-muted">아직 실행한 평가가 없습니다.</p>
      )}

      <p className="mt-2 text-xs text-muted">
        ⚠️ 응답률은 높다고 무조건 좋은 게 아닙니다. 근거 없이 답하면 응답률은 올라가고 충실성은
        떨어집니다. <strong>두 값을 반드시 같이 보세요.</strong>
      </p>
    </section>
  );
}

/** ② 테스트셋 */
function QuestionSection({
  questions,
  activeCount,
  generating,
  onGenerate,
}: {
  questions: EvalQuestion[];
  activeCount: number;
  generating: boolean;
  onGenerate: () => void;
}) {
  return (
    <section className="mb-8">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-sm font-semibold">
          테스트 질문 <span className="text-muted">({activeCount}/{questions.length} 활성)</span>
        </h2>
        <button
          type="button"
          onClick={onGenerate}
          disabled={generating}
          className="rounded-md border border-subtle px-3 py-1.5 text-sm disabled:opacity-50"
        >
          {generating ? "만드는 중…" : "문서에서 질문 생성"}
        </button>
      </div>

      {questions.length === 0 ? (
        <p className="rounded-lg border border-subtle px-6 py-8 text-center text-sm text-muted">
          아직 테스트 질문이 없습니다. 문서를 올린 뒤 &ldquo;문서에서 질문 생성&rdquo;을 눌러주세요.
        </p>
      ) : (
        <ul className="divide-y divide-subtle rounded-lg border border-subtle bg-surface">
          {questions.map((q) => (
            <li key={q.id} className="px-4 py-3">
              <p className="text-sm">{q.question}</p>
              <p className="mt-1 text-xs text-muted">기대 답변: {q.groundTruth}</p>
              {!q.isActive && (
                <span className="mt-1 inline-block rounded-full bg-foreground/10 px-2 py-0.5 text-xs text-muted">
                  비활성 — 평가에서 제외됨
                </span>
              )}
            </li>
          ))}
        </ul>
      )}

      {/* 켜고 끄기는 아직 서버에 없다. 없는 기능을 있는 것처럼 그리지 않는다. */}
      <p className="mt-2 text-xs text-muted">
        TODO(W3): 질문 수정·비활성 토글은 아직 API 가 없습니다 (PATCH 미구현).
      </p>
    </section>
  );
}

/** ③ 실행 이력 + ④ 질문별 상세 */
function RunSection({
  runs,
  openRunId,
  results,
  resultsLoading,
  onToggle,
}: {
  runs: EvalRun[];
  openRunId: string | null;
  results: EvalResult[];
  resultsLoading: boolean;
  onToggle: (runId: string) => void;
}) {
  return (
    <section className="mb-8">
      <h2 className="mb-2 text-sm font-semibold">실행 이력</h2>

      {runs.length === 0 ? (
        <p className="rounded-lg border border-subtle px-6 py-8 text-center text-sm text-muted">
          아직 실행 기록이 없습니다.
        </p>
      ) : (
        <ul className="divide-y divide-subtle rounded-lg border border-subtle bg-surface">
          {runs.map((run) => (
            <li key={run.id}>
              <button
                type="button"
                onClick={() => onToggle(run.id)}
                className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-foreground/5"
              >
                <div className="min-w-0 flex-1">
                  <p className="text-sm tabular-nums">
                    충실성 {fmt(run.avgFaithfulness)} · 관련성 {fmt(run.avgRelevancy)} · 응답률{" "}
                    {fmt(run.answeredRate)}
                  </p>
                  <p className="mt-0.5 text-xs text-muted">
                    {new Date(run.createdAt).toLocaleString("ko-KR")}
                    {run.config && (
                      <>
                        {" · "}topK {run.config.topK} · maxDistance {run.config.maxDistance}
                        {run.config.hybrid ? " · 하이브리드" : ""}
                        {run.config.reranker ? " · 리랭커" : ""}
                      </>
                    )}
                  </p>
                </div>
                <StatusBadge status={run.status} />
              </button>

              {openRunId === run.id && (
                <div className="border-t border-subtle px-4 py-3">
                  {resultsLoading ? (
                    <p className="text-xs text-muted">불러오는 중…</p>
                  ) : (
                    <ResultTable results={results} />
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      <p className="mt-2 text-xs text-muted">
        ★ W4 의 before/after 비교가 이 목록 위에서 만들어집니다. 각 실행이 그때의 검색 설정을 함께
        저장하고 있어서, 같은 테스트셋으로 &ldquo;벡터 검색만 vs 하이브리드+리랭커&rdquo;를 비교할 수 있습니다.
      </p>
      <p className="mt-1 text-xs text-muted">
        TODO(W4): 두 실행을 체크박스로 골라 좌우로 나란히 놓고 점수 차이를 +/- 로 표시할 것.
      </p>
    </section>
  );
}

function StatusBadge({ status }: { status: string }) {
  const label: Record<string, string> = {
    running: "실행 중",
    completed: "완료",
    failed: "실패",
  };
  const tone: Record<string, string> = {
    completed: "bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-300",
    failed: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
  };
  return (
    <span
      className={`shrink-0 rounded-full px-2 py-0.5 text-xs ${
        tone[status] ?? "bg-foreground/10 text-muted"
      }`}
    >
      {label[status] ?? status}
    </span>
  );
}

/**
 * ④ 질문별 채점 결과.
 *
 * <점수 낮은 순>이 기본 정렬이다. 잘된 답을 구경하는 화면이 아니라
 * <못한 답을 찾아 고치는 화면>이기 때문이다. 채점 못 한 것(null)을 맨 위에 둔다 —
 * 그것도 들여다봐야 할 대상이다.
 *
 * 정렬을 서버가 아니라 여기서 하는 이유: 정렬 기준이 화면마다 다를 수 있어
 * 서버에 못박으면 다른 화면이 생길 때 API 를 또 늘려야 한다.
 */
function ResultTable({ results }: { results: EvalResult[] }) {
  if (results.length === 0) {
    return <p className="text-xs text-muted">채점 결과가 없습니다.</p>;
  }

  // toSorted 는 원본을 건드리지 않고 정렬된 <새 배열>을 준다.
  // sort 를 쓰면 props 로 받은 배열을 그 자리에서 뒤집어 React 가 예상 못 한 변경이 된다.
  const sorted = results.toSorted((a, b) => {
    // null(채점 못 함)을 맨 앞으로. -1 로 치환하면 0점보다도 앞에 온다.
    const av = a.faithfulness ?? -1;
    const bv = b.faithfulness ?? -1;
    return av - bv;
  });

  return (
    <ul className="space-y-3">
      {sorted.map((r) => (
        <li key={r.id} className="rounded-md border border-subtle px-3 py-2">
          <div className="flex items-start gap-3">
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium">{r.question}</p>
              <p className="mt-1 text-xs text-muted">기대: {r.groundTruth}</p>
              <p className="mt-1 text-xs">실제: {r.generatedAnswer ?? "(답변 없음)"}</p>
              {r.retrievedChunks.length > 0 && (
                <p className="mt-1 text-xs text-muted">
                  검색된 근거: {r.retrievedChunks.map((c) => c.filename).join(", ")}
                </p>
              )}
            </div>
            <div className="shrink-0 text-right text-xs tabular-nums">
              <p>충실성 {fmt(r.faithfulness)}</p>
              <p className="text-muted">관련성 {fmt(r.relevancy)}</p>
            </div>
          </div>

          {r.faithfulness === null && (
            <p className="mt-2 text-xs text-muted">
              채점하지 않았습니다 — 답변이 fallback 이었거나 채점에 실패했습니다.
              <strong> 0점이라는 뜻이 아닙니다.</strong>
            </p>
          )}
        </li>
      ))}
    </ul>
  );
}

/** ⑤ 미답변 목록 — 아직 API 가 없다. 없는 걸 있는 것처럼 그리지 않는다. */
function UnansweredSection() {
  return (
    <section>
      <h2 className="mb-2 text-sm font-semibold">미답변 목록 + 보강 제안</h2>
      <Placeholder
        title="실사용 중 fallback 된 질문들"
        api="GET /api/bots/{botId}/eval/unanswered (미구현)"
      >
        <p>
          위 ④가 <em>테스트셋</em> 기준이라면 여기는 <em>실사용</em> 기준입니다. 엔드유저가 실제로
          물었는데 답하지 못한 질문 목록입니다.
        </p>
        <p>
          ⚠️ 데이터 출처가 다릅니다. 이 목록은 eval_* 테이블이 아니라 messages(is_fallback = true)
          에서 나옵니다. Python 이 아니라 <strong>Spring 이 집계</strong>해야 합니다.
        </p>
        <p>TODO(W3): 비슷한 질문 묶기 방식과 &ldquo;보강 제안&rdquo; 문장을 누가 생성할지 정할 것.</p>
      </Placeholder>
    </section>
  );
}
