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
import { parseId } from "@/lib/ids";
import type { EvalConfig, EvalQuestion, EvalResult, EvalRun, Id } from "@/lib/types";
import { PageHeader } from "@/components/PageHeader";
import { Toggle } from "@/components/Toggle";

/** 실행이 끝나기를 기다리는 동안 목록을 다시 부르는 간격. 문서 업로드 폴링과 같은 값이다. */
const POLL_MS = 3000;

export default function QualityPage() {
  /* useParams() 가 주는 값은 URL 조각이라 언제나 <문자열>이다.
     기본키가 BIGINT 가 된 뒤로는 숫자로 바꿔야 하고, 형식 검사도 거기서 한다. */
  const { botId: rawBotId } = useParams<{ botId: string }>();
  const botId = parseId(rawBotId);

  const [questions, setQuestions] = useState<EvalQuestion[]>([]);
  const [runs, setRuns] = useState<EvalRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  /* 버튼 두 개는 각각 따로 "진행 중"을 표시해야 한다.
     하나의 boolean 으로 묶으면 질문을 만드는 동안 실행 버튼까지 잠긴다. */
  const [generating, setGenerating] = useState(false);
  const [starting, setStarting] = useState(false);

  /**
   * 질문 1건 수정. 목록을 통째로 다시 부르지 않고 <그 행만> 갈아끼운다.
   *
   * 전체 재조회를 하지 않는 이유: 이 화면은 위쪽 문항 스트립이 <목록의 순번>에 기대고 있다.
   * 다시 부르는 사이에 순서가 흔들리면 "3번을 고쳤는데 스트립의 3번이 다른 문항" 이 된다.
   * 서버가 수정된 행을 그대로 돌려주므로 그 자리에 넣으면 순서가 유지된다.
   */
  const handleSaveQuestion = useCallback(
    async (questionId: Id, payload: { question?: string; groundTruth?: string; isActive?: boolean }) => {
      const updated = await api.evaluation.updateQuestion(botId, questionId, payload);
      setQuestions((prev) => prev.map((q) => (q.id === questionId ? updated : q)));
    },
    [botId],
  );

  /* 펼쳐본 실행의 질문별 결과. 목록을 열 때만 불러온다 —
     실행마다 미리 받아두면 안 볼 데이터까지 전부 내려받게 된다. */
  /* 나란히 볼 실행 2건. 배열인 이유: 순서가 곧 <먼저 고른 것>이라
     세 번째를 고르면 가장 오래된 선택을 밀어낸다(모달 없이 계속 고를 수 있다). */
  const [compareIds, setCompareIds] = useState<Id[]>([]);

  const [openRunId, setOpenRunId] = useState<Id | null>(null);
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

      /* 최신 실행의 문항별 결과를 미리 받아둔다.
         스트립이 이 화면의 핵심 정보라 펼치기 전에도 보여야 한다.
         ⚠️ 위 MeasurementBand 는 runs[0](최신 실행, 상태 무관)을 그린다.
         여기서 "completed 인 것 중 최신"을 고르면 band 와 strip 이 <서로 다른 실행>을
         가리키게 된다 — 예를 들어 오늘 돌린 실행이 partial(문항 하나 채점 실패)이면
         band 는 오늘 점수를 보여주면서 strip 은 어제의 completed 실행을 그려,
         "어느 문항이 점수를 깎았는지"를 다른 실행에서 읽게 된다.
         running 만 예외다 — 아직 결과 행 자체가 없으므로 건너뛴다. */
      const newest = r[0]?.status === "running" ? undefined : r[0];
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
    // eslint react-hooks/set-state-in-effect 때문에 IIFE 로 감싼다 — setState 가
    // <비동기 경계 뒤>에서 일어난다는 것을 코드에 드러내는 것이다.
    // 취소 플래그는 두지 않는다: React 18+ 에서 떠난 뒤의 setState 는 무시되고,
    // 예전의 `await load(); if (cancelled) return;` 은 setState 가 이미 끝난
    // 뒤라 아무것도 막지 못했다. 근거는 app/(dashboard)/dashboard/page.tsx 첫 effect 주석.
    void (async () => {
      await load();
    })();
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

  async function toggleResults(runId: Id) {
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
            onSave={handleSaveQuestion}
          />
          <RunSection
            runs={runs}
            compareIds={compareIds}
            onToggleCompare={(id) =>
              setCompareIds((prev) =>
                prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id].slice(-2),
              )
            }
            openRunId={openRunId}
            results={results}
            resultsLoading={resultsLoading}
            onToggle={toggleResults}
          />
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
 * 그리고 큰 숫자 옆에는 <항상 분모 막대>가 붙는다. 이 프로젝트가 낸 버그 가운데
 * 둘이 "분모를 안 보고 평균을 읽은 것"이었다(AGENTS.md 의 "낸 버그" 절).
 * 숫자만 크게 그리면 같은 실수를 부른다.
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
  onSave,
}: {
  questions: EvalQuestion[];
  activeCount: number;
  generating: boolean;
  onGenerate: () => void;
  onSave: (
    questionId: Id,
    payload: { question?: string; groundTruth?: string; isActive?: boolean },
  ) => Promise<void>;
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
            <QuestionRow key={q.id} question={q} index={i} onSave={onSave} />
          ))}
        </ul>
      )}

    </section>
  );
}

/**
 * 테스트 질문 한 줄. 평소엔 읽기용이고, "수정" 을 누르면 <그 자리에서> 펼쳐진다.
 *
 * <b>왜 모달이 아닌가.</b> 테스트셋은 한 문항만 보는 게 아니라 <다른 문항과 견주며> 고친다
 * ("이 질문만 대상이 안 적혀 있네"). 모달은 그 이웃을 가린다.
 *
 * <b>왜 두 입력칸의 무게가 다른가 — 이 화면의 핵심이다.</b>
 * 질문 문장을 다듬는 것은 안전하지만, <기대 답변>을 바꾸면 채점 기준 자체가 달라져
 * 지난 실행과 점수를 나란히 놓을 수 없게 된다. 이 화면이 존재하는 이유가 실행 간 비교인데
 * 그게 조용히 깨지는 것이다(Spring EvalController 주석이 같은 말을 한다).
 * 그래서 경고를 <기대 답변이 실제로 바뀐 순간에만> 띄운다. 늘 떠 있으면 벽지가 되어
 * 아무도 안 읽는다. 그리고 그 자리에서 <안전한 대안>(비활성)을 함께 가리킨다.
 */
function QuestionRow({
  question: q,
  index,
  onSave,
}: {
  question: EvalQuestion;
  index: number;
  onSave: (
    questionId: Id,
    payload: { question?: string; groundTruth?: string; isActive?: boolean },
  ) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(q.question);
  const [truth, setTruth] = useState(q.groundTruth);
  const [active, setActive] = useState(q.isActive);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /* 서버가 돌려준 값과 비교해 <바뀐 것만> 보낸다.
     PATCH 는 부분 수정이라, 안 바뀐 필드까지 보내면 "고쳤다" 는 기록만 늘어난다. */
  const truthChanged = truth.trim() !== q.groundTruth;
  const changed = text.trim() !== q.question || truthChanged || active !== q.isActive;

  function open() {
    setText(q.question);
    setTruth(q.groundTruth);
    setActive(q.isActive);
    setError(null);
    setEditing(true);
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await onSave(q.id, {
        ...(text.trim() !== q.question ? { question: text.trim() } : {}),
        ...(truthChanged ? { groundTruth: truth.trim() } : {}),
        ...(active !== q.isActive ? { isActive: active } : {}),
      });
      setEditing(false);
    } catch (e) {
      /* 실패하면 편집 상태를 <그대로 둔다>. 닫아버리면 방금 쓴 문장이 사라진다. */
      setError(e instanceof ApiError ? e.message : "저장하지 못했습니다. 잠시 후 다시 시도해주세요.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <li className="flex gap-3 px-4 py-3">
      {/* 번호는 장식이 아니다 — 위 문항 스트립의 <같은 번호 칸>과 같은 문항이다.
          스트립에서 못 맞힌 칸을 보고 여기서 그 번호를 찾는 흐름을 위해 붙였다. */}
      <span className="w-5 shrink-0 pt-0.5 text-xs tabular-nums text-muted">{index + 1}</span>

      {editing ? (
        <div className="min-w-0 flex-1">
          <label className="block text-xs text-muted" htmlFor={`q-${q.id}`}>
            질문
          </label>
          <textarea
            id={`q-${q.id}`}
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={2}
            className="mt-1 w-full rounded-md border border-subtle bg-background px-3 py-2 text-sm"
          />

          <label className="mt-3 block text-xs text-muted" htmlFor={`t-${q.id}`}>
            기대 답변
          </label>
          <textarea
            id={`t-${q.id}`}
            value={truth}
            onChange={(e) => setTruth(e.target.value)}
            rows={2}
            className={`mt-1 w-full rounded-md border bg-background px-3 py-2 text-sm ${
              truthChanged ? "border-warning" : "border-subtle"
            }`}
          />
          {/* ★ 이 화면의 서명. 바뀐 순간에만 나타나고, 안전한 대안을 바로 아래 가리킨다. */}
          {truthChanged && (
            <p className="mt-1.5 rounded-md bg-warning-surface px-3 py-2 text-xs text-warning">
              채점 기준이 바뀝니다. 이번 문항은 <b>지난 실행과 점수를 견줄 수 없게 됩니다.</b>{" "}
              문항을 잠시 빼려는 것이라면 아래에서 평가에 포함을 꺼주세요.
            </p>
          )}

          <div className="mt-3">
            <Toggle
              checked={active}
              onChange={setActive}
              label="평가에 포함"
              description="끄면 다음 실행부터 제외됩니다. 지난 점수는 그대로 남습니다."
            />
          </div>

          <div className="mt-3 flex items-center gap-2">
            <button
              type="button"
              onClick={save}
              disabled={saving || !changed}
              className="rounded-md bg-foreground px-3 py-1.5 text-sm text-surface disabled:opacity-40"
            >
              {saving ? "저장하는 중…" : "저장"}
            </button>
            <button
              type="button"
              onClick={() => setEditing(false)}
              className="rounded-md border border-subtle px-3 py-1.5 text-sm"
            >
              취소
            </button>
            {error && (
              <span role="alert" className="text-xs text-danger">
                {error}
              </span>
            )}
          </div>
        </div>
      ) : (
        <>
          <div className="min-w-0 flex-1">
            <p className="text-sm">{q.question}</p>
            <p className="mt-1 text-xs text-muted">기대 답변: {q.groundTruth}</p>
            {!q.isActive && (
              <span className="mt-1 inline-block rounded-full bg-foreground/10 px-2 py-0.5 text-xs text-muted">
                비활성 — 평가에서 제외됨
              </span>
            )}
          </div>
          <button
            type="button"
            onClick={open}
            className="h-fit shrink-0 rounded-md border border-subtle px-2.5 py-1 text-xs text-muted"
          >
            수정
          </button>
        </>
      )}
    </li>
  );
}

/** ③ 실행 이력 + ④ 질문별 상세 */
function RunSection({
  runs,
  compareIds,
  onToggleCompare,
  openRunId,
  results,
  resultsLoading,
  onToggle,
}: {
  compareIds: Id[];
  onToggleCompare: (runId: Id) => void;
  runs: EvalRun[];
  openRunId: Id | null;
  results: EvalResult[];
  resultsLoading: boolean;
  onToggle: (runId: Id) => void;
}) {
  return (
    <section className="mb-8">
      <h2 className="mb-2 text-sm font-semibold">실행 이력</h2>

      {compareIds.length === 2 && (
        <ComparePanel
          runs={runs}
          compareIds={compareIds}
          onClear={() => compareIds.forEach(onToggleCompare)}
        />
      )}

      {runs.length === 0 ? (
        <p className="rounded-lg border border-subtle px-6 py-8 text-center text-sm text-muted">
          아직 실행 기록이 없습니다.
        </p>
      ) : (
        <ul className="divide-y divide-subtle rounded-lg border border-subtle bg-surface">
          {runs.map((run) => (
            <li key={run.id}>
              <div className="flex items-center">
                {/* 여기만 체크박스다. 고르는 즉시 무언가 바뀌는 게 아니라
                    <둘을 모아> 비교하는 것이라, 스위치가 아니라 체크가 맞다.
                    완료된 실행만 고를 수 있다 — partial 은 분모가 달라 비교하면 안 된다
                    (StatusBadge 주석과 같은 이유). */}
                <label className="flex shrink-0 cursor-pointer items-center py-3 pl-4 pr-1">
                  <input
                    type="checkbox"
                    checked={compareIds.includes(run.id)}
                    disabled={run.status !== "completed"}
                    onChange={() => onToggleCompare(run.id)}
                    aria-label="비교에 넣기"
                    className="disabled:opacity-30"
                  />
                </label>
              <button
                type="button"
                onClick={() => onToggle(run.id)}
                className="flex w-full items-center gap-3 py-3 pl-1 pr-4 text-left hover:bg-foreground/5"
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
              </div>

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
        ★ 왼쪽 칸으로 실행 두 개를 고르면 나란히 놓고 차이를 보여줍니다.
      </p>
    </section>
  );
}

/** 설정을 한 줄로 접는다. 같은 설정끼리 묶어 <측정 편차>를 재는 데 쓴다. */
function configKey(run: EvalRun): string {
  const c = run.config;
  if (!c) return "none";
  return `${c.topK}|${c.maxDistance}|${c.hybrid ? 1 : 0}|${c.reranker ? 1 : 0}|${c.model ?? ""}`;
}

/**
 * ★ 이 봇의 <측정 편차>.
 *
 * 같은 설정·같은 문항 수로 두 번 이상 돌린 실행들의 전체 충실성 폭(max − min).
 *
 * <b>왜 이걸 재는가.</b> 설정을 바꾼 뒤 점수가 0.02 올랐다고 해서 그 설정이 나은 게 아니다.
 * 아무것도 안 바꾸고 두 번 돌려도 그만큼은 흔들린다 — 생성 모델이 같은 근거에서 다른 문장을
 * 만들기 때문이다. 그래서 <차이>는 <편차>와 나란히 놓아야만 뜻이 생긴다.
 *
 * <b>왜 상수로 박지 않는가.</b> 이 값은 코퍼스와 모델에 딸려 있어 봇마다 다르다.
 * 남의 봇에서 잰 숫자를 여기 적으면 그 자체가 거짓말이다. 그래서 <이 봇의 실행 기록에서>
 * 직접 잰다. 잴 재료가 없으면 아는 척하지 않고 "모른다" 고 말한다.
 */
function measureNoise(runs: EvalRun[]): number | null {
  const groups = new Map<string, number[]>();
  for (const r of runs) {
    if (r.status !== "completed" || r.overallFaithfulness === null) continue;
    const key = `${configKey(r)}#${r.questionCount ?? "?"}`;
    groups.set(key, [...(groups.get(key) ?? []), r.overallFaithfulness]);
  }
  const spreads = [...groups.values()]
    .filter((v) => v.length >= 2)
    .map((v) => Math.max(...v) - Math.min(...v));
  return spreads.length > 0 ? Math.max(...spreads) : null;
}

/** 두 설정에서 <달라진 항목만> 뽑는다. 같은 것까지 늘어놓으면 무엇이 원인인지 안 보인다. */
function configDiff(a: EvalConfig | null, b: EvalConfig | null) {
  const rows: { label: string; before: string; after: string }[] = [];
  const on = (v?: boolean) => (v ? "켬" : "끔");
  const push = (label: string, x: string, y: string) => {
    if (x !== y) rows.push({ label, before: x, after: y });
  };
  push("topK", String(a?.topK ?? "—"), String(b?.topK ?? "—"));
  push("최대 거리", String(a?.maxDistance ?? "—"), String(b?.maxDistance ?? "—"));
  push("하이브리드", on(a?.hybrid), on(b?.hybrid));
  push("리랭커", on(a?.reranker), on(b?.reranker));
  push("모델", a?.model ?? "—", b?.model ?? "—");
  return rows;
}

/**
 * ★ W4 before/after 비교 — 이 화면의 목적지.
 *
 * <b>바닥 델타는 거짓말을 한다.</b> 이 프로젝트가 W4 에서 배운 것이 정확히 그것이라,
 * 화면이 그 함정을 다시 파지 않도록 세 겹을 건다.
 *
 *   ① <문항 수가 다르면 숫자를 아예 안 보여준다.> 테스트셋이 바뀌면 두 점수는
 *      애초에 같은 자를 쓰지 않은 것이다. 델타를 보여주는 순간 사람은 그걸 읽는다.
 *   ② <차이를 측정 편차와 나란히 놓는다.> 편차보다 작은 차이는 "개선" 이 아니라 노이즈다.
 *   ③ <기준값은 전체 충실성이다.> 충실성(avgFaithfulness)은 답을 덜 할수록 올라가므로
 *      비교에 쓰면 안 된다 — 그래도 함께 보여주되 그 사실을 딱지로 붙인다.
 */
function ComparePanel({
  runs,
  compareIds,
  onClear,
}: {
  runs: EvalRun[];
  compareIds: Id[];
  onClear: () => void;
}) {
  const picked = compareIds
    .map((id) => runs.find((r) => r.id === id))
    .filter((r): r is EvalRun => r !== undefined)
    /* 고른 순서가 아니라 <시간 순>으로 놓는다. before → after 가 사람이 읽는 방향이다. */
    .sort((a, b) => a.createdAt.localeCompare(b.createdAt));

  if (picked.length !== 2) return null;
  const [before, after] = picked;

  const sameSet =
    before.questionCount === null ||
    after.questionCount === null ||
    before.questionCount === after.questionCount;

  const noise = measureNoise(runs);
  const diff = configDiff(before.config, after.config);

  return (
    <div className="mb-3 rounded-lg border border-subtle bg-surface p-4">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h3 className="text-sm font-semibold">두 실행 비교</h3>
        <button type="button" onClick={onClear} className="text-xs text-muted underline">
          선택 해제
        </button>
      </div>

      {!sameSet ? (
        /* ① 여기서 숫자를 보여주지 않는 것이 핵심이다. */
        <p className="rounded-md bg-warning-surface px-3 py-2 text-xs text-warning">
          <b>테스트셋이 달라 비교할 수 없습니다.</b> 문항 수가 {before.questionCount} →{" "}
          {after.questionCount} 로 바뀌었습니다. 같은 질문으로 돌린 실행끼리 골라주세요.
        </p>
      ) : (
        <>
          <div className="mb-3 grid grid-cols-[1fr_auto_1fr] items-baseline gap-x-3 text-xs text-muted">
            <span>{new Date(before.createdAt).toLocaleString("ko-KR")}</span>
            <span aria-hidden>→</span>
            <span className="text-right">{new Date(after.createdAt).toLocaleString("ko-KR")}</span>
          </div>

          <MetricRow
            label="전체 충실성"
            before={before.overallFaithfulness}
            after={after.overallFaithfulness}
            noise={noise}
            headline
          />
          <MetricRow label="관련성" before={before.avgRelevancy} after={after.avgRelevancy} />
          <MetricRow label="응답률" before={before.answeredRate} after={after.answeredRate} />
          <MetricRow
            label="충실성"
            note="답을 덜 하면 올라갑니다 — 비교에 쓰지 마세요"
            before={before.avgFaithfulness}
            after={after.avgFaithfulness}
          />

          <div className="mt-3 border-t border-subtle pt-3">
            <p className="mb-1.5 text-xs text-muted">달라진 설정</p>
            {diff.length === 0 ? (
              <p className="text-xs">
                설정이 같습니다. <span className="text-muted">두 실행의 차이가 곧 <b>측정 편차</b>입니다.</span>
              </p>
            ) : (
              <ul className="space-y-1">
                {diff.map((d) => (
                  <li key={d.label} className="flex items-center gap-2 text-xs">
                    <span className="w-16 shrink-0 text-muted">{d.label}</span>
                    <ConfigChip label={d.before} />
                    <span aria-hidden className="text-muted">→</span>
                    <ConfigChip label={d.after} on />
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </div>
  );
}

/** 지표 한 줄. 차이는 <편차와 함께> 있을 때만 뜻이 생긴다(headline 인 지표에만 붙인다). */
function MetricRow({
  label,
  note,
  before,
  after,
  noise,
  headline,
}: {
  label: string;
  note?: string;
  before: number | null;
  after: number | null;
  noise?: number | null;
  headline?: boolean;
}) {
  /* null 은 0 이 아니다 — 한쪽이라도 없으면 차이를 계산하지 않는다. */
  const delta = before !== null && after !== null ? after - before : null;

  return (
    <div className="border-t border-subtle py-2 first:border-t-0">
      <div className="grid grid-cols-[1fr_auto_1fr_auto] items-baseline gap-x-3">
        <span className={headline ? "text-sm font-medium" : "text-xs text-muted"}>{label}</span>
        <span className={`tabular-nums ${headline ? "text-base" : "text-xs"}`}>{fmt(before)}</span>
        <span className={`text-right tabular-nums ${headline ? "text-base font-semibold" : "text-xs"}`}>
          {fmt(after)}
        </span>
        <span
          className={`w-16 text-right tabular-nums ${headline ? "text-sm" : "text-xs"} ${
            delta === null || delta === 0 ? "text-muted" : delta > 0 ? "text-success" : "text-danger"
          }`}
        >
          {delta === null ? "—" : `${delta > 0 ? "+" : delta < 0 ? "−" : "±"}${Math.abs(delta).toFixed(3)}`}
        </span>
      </div>
      {note && <p className="mt-0.5 text-[11px] text-warning">⚠ {note}</p>}
      {/* ② 편차 판정. 이 줄이 없으면 화면은 노이즈를 개선이라고 말하게 된다. */}
      {headline && delta !== null && (
        <p className="mt-1 text-[11px] text-muted">
          {noise === null || noise === undefined ? (
            <>
              같은 설정으로 두 번 이상 돌린 기록이 없어 <b>측정 편차를 모릅니다.</b> 설정마다 3회
              이상 돌리면 이 차이가 진짜인지 판단할 수 있습니다.
            </>
          ) : Math.abs(delta) > noise ? (
            <span className="text-success">
              이 봇의 측정 편차 ±{noise.toFixed(3)} <b>보다 큽니다.</b>
            </span>
          ) : (
            <span className="text-warning">
              이 봇의 측정 편차 ±{noise.toFixed(3)} <b>안입니다 — 노이즈와 구별되지 않습니다.</b>
            </span>
          )}
        </p>
      )}
    </div>
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
    // 🔴 "일부 실패"는 <완료>도 <실패>도 아니다. 점수는 나왔지만 분모가 달라
    //    다른 실행과 비교하면 안 된다. 그래서 색도 따로 준다(경고 톤).
    partial: "일부 실패",
    failed: "실패",
  };
  const tone: Record<string, string> = {
    completed: "bg-success-surface text-success",
    partial: "bg-warning-surface text-warning",
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

