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

  /* 맨 위 문항 스트립이 쓰는 <최신 실행>의 질문별 결과.
     아코디언용 results 와 <일부러 분리했다> — 이력에서 옛 실행을 펼치면
     results 가 그걸로 바뀌는데, 그때 위쪽 스트립까지 옛 실행으로 바뀌면 안 된다. */
  const [latestResults, setLatestResults] = useState<EvalResult[]>([]);

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

      /* 최신 <완료된> 실행의 문항별 결과를 미리 받아둔다.
         스트립이 이 화면의 핵심 정보라 펼치기 전에도 보여야 한다.
         running 인 실행은 아직 결과가 없으므로 건너뛴다. */
      const newest = r.find((x) => x.status === "completed");
      if (newest) {
        setLatestResults(await api.evaluation.getRunResults(botId, newest.id));
      } else {
        setLatestResults([]);
      }
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
            className="rounded-md bg-foreground px-3 py-1.5 text-sm font-medium text-surface disabled:opacity-50"
          >
            {starting ? "시작하는 중…" : "평가 실행"}
          </button>
        }
      />

      {error && (
        <p
          role="alert"
          className="mt-4 rounded-md border border-danger bg-danger-surface px-3 py-2 text-sm text-danger"
        >
          {error}
        </p>
      )}

      {loading ? (
        <p className="mt-6 text-sm text-muted">불러오는 중…</p>
      ) : (
        <>
          <MeasurementBand run={latest} results={latestResults} />
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

/* ─────────────────────────────────────────────────────────────────────────────
 * ① 계측 밴드 — 이 화면의 뼈대
 * ─────────────────────────────────────────────────────────────────────────────
 * 흔한 대시보드는 지표 4개를 <같은 크기 카드 4장>으로 늘어놓는다. 여기서는
 * 일부러 그러지 않았다. 이 화면의 지표 넷 중 <셋은 혼자 보면 속는 값>이기 때문이다:
 *   · 충실성  — 답을 덜 할수록 저절로 올라간다(생존 편향)
 *   · 응답률  — 근거 없이 마구 답해도 올라간다
 *   · 관련성  — 위 둘과 같은 분모를 쓴다
 * 넷을 같은 크기로 그리면 "아무거나 봐도 된다"는 <설계상의 거짓말>이 된다.
 * 그래서 믿을 수 있는 하나만 크게 두고 나머지는 한 줄로 낮췄다.
 *
 * 그리고 큰 숫자 옆에는 <항상 분모 막대>가 붙는다. 이 프로젝트가 낸 버그 셋 중
 * 둘이 "분모를 안 보고 평균을 읽은 것"이었다. 숫자만 크게 그리면 같은 실수를 부른다.
 */
function MeasurementBand({ run, results }: { run: EvalRun | null; results: EvalResult[] }) {
  const scored = run?.scoredCount ?? null;
  const total = run?.questionCount ?? null;
  const ratio = scored !== null && total ? scored / total : null;

  return (
    <section className="mb-10 mt-6">
      <p className="text-[11px] font-medium tracking-[0.01em] text-muted">측정 기준값</p>

      <div className="mt-3 rounded-2xl bg-foreground px-6 py-7 text-surface sm:px-8">
        <div className="flex flex-wrap items-end gap-x-10 gap-y-6">
          <div>
            <p className="text-[11px] font-medium tracking-[0.01em] text-surface/60">
              전체 충실성
            </p>
            {/* Pretendard 는 100~900 가변이다. 굵기 대비를 크게 벌려 <숫자가 주인공>이 되게 한다. */}
            <p className="mt-1 text-6xl font-extrabold leading-none tracking-tight tabular-nums sm:text-7xl">
              {fmt(run?.overallFaithfulness)}
            </p>
          </div>

          {/* 분모 막대. 이 화면의 규칙: <숫자는 분모 없이 읽지 않는다.> */}
          <div className="min-w-[200px] flex-1 pb-1">
            <div className="flex items-baseline justify-between text-[11px] text-surface/60">
              <span className="tracking-[0.01em]">채점된 문항</span>
              <span className="tabular-nums">
                {scored ?? "—"} / {total ?? "—"}
              </span>
            </div>
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-surface/15">
              <div
                className="h-full rounded-full bg-accent transition-[width] duration-500"
                style={{ width: ratio !== null ? `${ratio * 100}%` : "0%" }}
              />
            </div>
            <p className="mt-2 text-[11px] leading-relaxed text-surface/55">
              막대가 덜 차 있으면 그만큼 표본이 줄어든 것입니다. 점수가 정직해도 표본이 줄었다는
              사실은 따로 봐야 합니다.
            </p>
          </div>
        </div>

        {/* 보조 지표 — 카드로 나란히 놓지 않는다. 위 주석 참고. */}
        <dl className="mt-7 flex flex-wrap gap-x-10 gap-y-4 border-t border-surface/15 pt-5">
          <SecondaryMetric
            label="충실성"
            value={run?.avgFaithfulness}
            caution="답을 덜 하면 올라갑니다"
          />
          <SecondaryMetric label="관련성" value={run?.avgRelevancy} />
          <SecondaryMetric
            label="응답률"
            value={run?.answeredRate}
            caution="높다고 좋은 게 아닙니다"
          />
        </dl>
      </div>

      {run ? (
        <p className="mt-3 text-xs text-muted">
          {new Date(run.createdAt).toLocaleString("ko-KR")} 실행 · 상태 {run.status}
        </p>
      ) : (
        <p className="mt-3 text-xs text-muted">아직 실행한 평가가 없습니다.</p>
      )}

      <QuestionStrip results={results} />

      {/* ⚠️ 아래 두 문단은 <제품의 핵심 경고>다. 디자인을 이유로 줄이지 말 것. */}
      <div className="mt-6 space-y-1.5 border-l-2 border-warning pl-4 text-xs leading-relaxed text-muted">
        <p>
          <strong className="text-warning">응답률이 높다고 좋은 게 아닙니다.</strong> 근거 없이
          답하면 응답률은 올라가고 충실성은 떨어집니다.
        </p>
        <p>
          <strong className="text-warning">반대 방향이 더 위험합니다.</strong>{" "}
          &ldquo;충실성&rdquo;은 답한 것들만의 평균이라{" "}
          <strong>답을 덜 할수록 저절로 올라갑니다.</strong> 그래서 설정을 비교할 때는 분모를
          전체 질문으로 되돌린 <strong>&ldquo;전체 충실성&rdquo;</strong>을 봐야 합니다.
          (리랭커 실험에서 충실성은 0.714→0.789 로 올랐지만 전체 충실성은 0.714 로 변화가
          없었습니다)
        </p>
      </div>
    </section>
  );
}

function SecondaryMetric({
  label,
  value,
  caution,
}: {
  label: string;
  value: number | null | undefined;
  caution?: string;
}) {
  return (
    <div>
      <dt className="text-[11px] tracking-[0.01em] text-surface/50">{label}</dt>
      <dd className="mt-0.5 text-xl font-semibold tabular-nums">{fmt(value)}</dd>
      {caution && <p className="mt-0.5 text-[11px] text-surface/45">⚠ {caution}</p>}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
 * 문항 스트립 — 이 화면의 시그니처
 * ─────────────────────────────────────────────────────────────────────────────
 * 평가 한 번은 <시험 한 회차>다. 평균 하나로 뭉개면 "어디가 약한가"가 사라진다.
 * 그래서 문항을 하나씩 칸으로 세워 <한눈에> 보게 했다. 칸을 누르면 그 문항이 아래 뜬다.
 *
 * 🔴 네 상태를 <반드시> 구분한다. 특히 뒤 둘을 섞으면 안 된다:
 *      거절(fallback) = 근거가 없어 답하지 않은 것 → <제품이 제대로 동작한 것이다>
 *      측정 실패      = 호출 자체가 실패한 것       → 우리 인프라 문제이지 품질이 아니다
 *    이 둘을 같은 색으로 칠하면 "쿼터가 모자란 날"이 "품질이 나쁜 날"로 읽힌다.
 *    실제로 그 구분을 놓쳐 응답률이 거짓말을 한 적이 있다(docs/decisions.md).
 */
type Outcome = "ok" | "weak" | "declined" | "unmeasured";

function classify(r: EvalResult): Outcome {
  if (r.generatedAnswer === null) return "unmeasured";
  if (r.faithfulness === null) return "declined";
  return r.faithfulness >= 0.8 ? "ok" : "weak";
}

const OUTCOME: Record<Outcome, { cell: string; dot: string; label: string }> = {
  ok: { cell: "bg-foreground", dot: "bg-foreground", label: "근거대로 답함" },
  weak: { cell: "bg-warning", dot: "bg-warning", label: "근거에서 벗어남" },
  declined: {
    cell: "border border-subtle bg-surface",
    dot: "border border-subtle bg-surface",
    label: "거절 — 근거 없음(정상 동작)",
  },
  unmeasured: {
    cell: "border border-dashed border-danger/60 bg-danger-surface",
    dot: "border border-dashed border-danger/60 bg-danger-surface",
    label: "측정 실패 — 품질과 무관",
  },
};

function QuestionStrip({ results }: { results: EvalResult[] }) {
  const [picked, setPicked] = useState<number | null>(null);
  if (results.length === 0) return null;

  const shown = picked !== null ? results[picked] : null;

  return (
    <div className="mt-7">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-[11px] font-medium tracking-[0.01em] text-muted">문항별 결과</p>
        <p className="text-[11px] text-muted">칸을 누르면 그 문항이 아래에 나옵니다</p>
      </div>

      {/* 칸 하나 = 문항 하나. 순서는 테스트셋의 실제 순서다(장식용 번호가 아니다). */}
      <div className="mt-2 flex flex-wrap gap-1.5">
        {results.map((r, i) => {
          const o = OUTCOME[classify(r)];
          const on = picked === i;
          return (
            <button
              key={r.id}
              type="button"
              onClick={() => setPicked(on ? null : i)}
              title={`${i + 1}. ${r.question}`}
              aria-label={`${i + 1}번 문항 — ${o.label}`}
              aria-pressed={on}
              className={`h-8 w-6 rounded-[3px] transition ${o.cell} ${
                on ? "ring-2 ring-accent ring-offset-2 ring-offset-background" : "hover:opacity-70"
              }`}
            />
          );
        })}
      </div>

      <ul className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5 text-[11px] text-muted">
        {(Object.keys(OUTCOME) as Outcome[]).map((k) => (
          <li key={k} className="flex items-center gap-1.5">
            <span className={`h-2.5 w-2 rounded-[2px] ${OUTCOME[k].dot}`} />
            {OUTCOME[k].label}
          </li>
        ))}
      </ul>

      {shown && (
        <div className="mt-3 rounded-lg border border-subtle bg-surface px-4 py-3">
          <p className="text-sm font-medium">
            <span className="mr-2 tabular-nums text-muted">{(picked ?? 0) + 1}</span>
            {shown.question}
          </p>
          <p className="mt-1.5 text-xs text-muted">기대: {shown.groundTruth}</p>
          <p className="mt-1 text-xs">실제: {shown.generatedAnswer ?? "(답변 없음)"}</p>
          <p className="mt-2 text-xs tabular-nums text-muted">
            충실성 {fmt(shown.faithfulness)} · 관련성 {fmt(shown.relevancy)}
          </p>
        </div>
      )}
    </div>
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
        <ul className="divide-y divide-subtle overflow-hidden rounded-lg border border-subtle bg-surface">
          {questions.map((q, i) => (
            <li key={q.id} className="flex gap-3 px-4 py-3">
              {/* 번호는 장식이 아니다 — 위 문항 스트립의 <같은 번호 칸>과 같은 문항이다.
                  스트립에서 못 맞힌 칸을 보고 여기서 그 번호를 찾는 흐름을 위해 붙였다. */}
              <span className="w-5 shrink-0 pt-0.5 text-xs tabular-nums text-muted">{i + 1}</span>
              <div className="min-w-0 flex-1">
                <p className="text-sm">{q.question}</p>
                <p className="mt-1 text-xs text-muted">기대 답변: {q.groundTruth}</p>
                {!q.isActive && (
                  <span className="mt-1 inline-block rounded-full bg-foreground/10 px-2 py-0.5 text-xs text-muted">
                    비활성 — 평가에서 제외됨
                  </span>
                )}
              </div>
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
                  <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                    {/* 비교의 기준값을 크게. 나머지 셋은 같은 줄에 작게 —
                        위 계측 밴드와 <같은 위계>를 유지해야 화면이 한 가지 말을 한다. */}
                    <span className="text-lg font-semibold tabular-nums">
                      {fmt(run.overallFaithfulness)}
                    </span>
                    <span className="text-xs tabular-nums text-muted">
                      충실성 {fmt(run.avgFaithfulness)} · 관련성 {fmt(run.avgRelevancy)} · 응답률{" "}
                      {fmt(run.answeredRate)}
                    </span>
                    {run.questionCount !== null && (
                      <span className="text-xs tabular-nums text-muted">
                        {run.scoredCount}/{run.questionCount} 채점
                      </span>
                    )}
                  </div>
                  {/* 설정을 칩으로 떼어놓는다. W4 비교는 <어느 설정이 달랐나>를 눈으로
                      훑는 일이라, 문장 안에 섞여 있으면 두 실행을 비교할 수가 없다. */}
                  <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                    <span className="text-xs text-muted">
                      {new Date(run.createdAt).toLocaleString("ko-KR")}
                    </span>
                    {run.config && (
                      <>
                        <ConfigChip label={`topK ${run.config.topK}`} />
                        <ConfigChip label={`거리 ${run.config.maxDistance}`} />
                        {run.config.hybrid && <ConfigChip label="하이브리드" on />}
                        {run.config.reranker && <ConfigChip label="리랭커" on />}
                      </>
                    )}
                  </div>
                </div>
                <StatusBadge status={run.status} />
              </button>

              {openRunId === run.id && (
                <div className="border-t border-subtle px-4 py-3">
                  {resultsLoading ? (
                    <p className="text-xs text-muted">불러오는 중…</p>
                  ) : (
                    <>
                      <RunSummary results={results} />
                      <ResultTable results={results} />
                    </>
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

/** 실행 설정 칩. 켜진 것(하이브리드·리랭커)은 강조해서 <무엇이 달랐는지>가 먼저 보이게 한다. */
function ConfigChip({ label, on }: { label: string; on?: boolean }) {
  return (
    <span
      className={`rounded px-1.5 py-0.5 text-[11px] tabular-nums ${
        on ? "bg-foreground text-surface" : "bg-foreground/8 text-muted"
      }`}
    >
      {label}
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  const label: Record<string, string> = {
    running: "실행 중",
    completed: "완료",
    failed: "실패",
  };
  const tone: Record<string, string> = {
    completed: "bg-success-surface text-success",
    failed: "bg-danger-surface text-danger",
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
 * 실행 한 건의 구성 요약.
 *
 * <b>측정 실패가 몇 건인지 반드시 보여야 한다.</b> 그 숫자를 모르면
 * "응답률 1.0" 이 21문항 중 16문항만 돌린 결과라는 걸 알 수 없다.
 * 점수는 정직해도 <표본이 줄었다>는 사실은 따로 알려야 한다.
 */
function RunSummary({ results }: { results: EvalResult[] }) {
  const total = results.length;
  // 질문을 물어보지도 못한 건(호출 실패). 응답률 분모에서 빠진 것들이다.
  const notMeasured = results.filter((r) => r.generatedAnswer === null).length;
  // 답은 했는데 채점이 없는 건 = fallback 이거나 채점 실패.
  const notScored = results.filter(
    (r) => r.generatedAnswer !== null && r.faithfulness === null,
  ).length;

  return (
    <p className="mb-3 text-xs text-muted">
      질문 {total}건 · 채점됨 {total - notMeasured - notScored}건
      {notScored > 0 && <> · 미채점 {notScored}건</>}
      {notMeasured > 0 && (
        <span className="text-warning">
          {" "}
          · <strong>측정 실패 {notMeasured}건</strong> (점수 계산에서 제외됨)
        </span>
      )}
    </p>
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

          {/*
            점수가 없는 이유가 두 가지이고 <성격이 완전히 다르다>. 반드시 갈라서 보여준다.
              · generatedAnswer 가 null  → 질문을 <물어보지도 못했다> (호출 실패·쿼터 초과).
                                           우리 인프라 문제이지 챗봇 품질이 아니다.
                                           그래서 응답률 분모에서도 빠진다.
              · generatedAnswer 는 있는데 점수가 null → 답은 했다. fallback 이라 채점 대상이
                                           아니었거나 채점 호출이 실패했다.
            한 문구로 뭉개면 "쿼터가 모자란 날"이 "품질이 나쁜 날"로 읽힌다.
          */}
          {r.faithfulness === null &&
            (r.generatedAnswer === null ? (
              <p className="mt-2 text-xs text-warning">
                ⚠️ 측정하지 못했습니다 — 검색·생성 호출이 실패했습니다(쿼터 초과 등).
                <strong> 챗봇 품질과 무관하며 응답률 계산에서도 제외됩니다.</strong>
              </p>
            ) : (
              <p className="mt-2 text-xs text-muted">
                채점하지 않았습니다 — 답변이 fallback 이었거나 채점에 실패했습니다.
                <strong> 0점이라는 뜻이 아닙니다.</strong>
              </p>
            ))}
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
