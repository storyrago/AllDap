"use client";

/*
 * `/bot/[botId]/diagnostics` — 진단. 문서끼리 어긋나는 곳을 보여준다.
 *
 * 품질 대시보드와 짝이다:
 *   품질 = 지금 얼마나 좋은가 (측정)
 *   진단 = 뭘 고치면 좋아지나 (처방)
 *
 * 왜 이 화면이 필요한가
 * ─────────────────────────────────────────────────────────────────────────
 * 환각 억제(NO_ANSWER·max_distance)는 "문서에 없는 것" 을 막는다.
 * 그런데 "문서에 <둘 다> 있는 것" 은 못 막는다 — 구버전 규정과 신버전이 같이 올라가 있으면
 * 챗봇은 둘 중 하나를 골라 <자신 있게> 답하고, 근거까지 붙여서 보여준다.
 * 관리자는 틀린 줄도 모른다. 표시된 그 근거가 틀린 쪽일 수 있기 때문이다.
 *
 * "use client" 인 이유: 스캔 버튼·펼치기·무시가 전부 상태를 바꾸는 상호작용이고,
 * 데이터도 JWT 로 부른다(토큰이 브라우저에만 있어 서버 컴포넌트가 못 가져온다).
 *
 * 호출하는 Spring API:
 *   GET   /api/bots/{botId}/conflicts?status=open
 *   POST  /api/bots/{botId}/conflicts/scan
 *   PATCH /api/bots/{botId}/conflicts/{conflictId}
 */

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { ApiError, api } from "@/lib/api";
import type { Conflict, ConflictScan } from "@/lib/types";
import { PageHeader } from "@/components/PageHeader";
import { Section } from "@/components/Form";

/** 서버(config.py conflict_max_pairs)의 상한. 이 값과 candidates 가 같으면 아직 남았을 수 있다. */
const SCAN_LIMIT = 30;

export default function DiagnosticsPage() {
  const { botId } = useParams<{ botId: string }>();

  const [conflicts, setConflicts] = useState<Conflict[] | null>(null);
  const [scanning, setScanning] = useState(false);
  const [lastScan, setLastScan] = useState<ConflictScan | null>(null);
  const [error, setError] = useState<string | null>(null);
  /* 어떤 항목이 펼쳐져 있는지. 기본은 전부 접힘 — 원문까지 펼치면 목록을 훑을 수가 없다. */
  const [opened, setOpened] = useState<Set<string>>(new Set());

  const load = useCallback(async () => {
    try {
      setConflicts(await api.conflicts.list(botId));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "목록을 불러오지 못했습니다.");
    }
  }, [botId]);

  useEffect(() => {
    // 다른 화면들과 같은 형태. 떠난 뒤 응답이 와도 상태를 건드리지 않는다.
    let cancelled = false;
    void (async () => {
      await load();
      if (cancelled) return;
    })();
    return () => {
      cancelled = true;
    };
  }, [load]);

  async function handleScan() {
    setScanning(true);
    setError(null);
    setLastScan(null);
    try {
      const result = await api.conflicts.scan(botId);
      setLastScan(result);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "스캔에 실패했습니다.");
    } finally {
      setScanning(false);
    }
  }

  async function handleIgnore(id: string) {
    try {
      await api.conflicts.updateStatus(botId, id, "ignored");
      /* 목록을 다시 부르지 않고 그 항목만 지운다.
         재조회하면 스크롤이 튀고, 서버 상태는 이미 확정됐다. */
      setConflicts((prev) => (prev ?? []).filter((c) => c.id !== id));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "처리하지 못했습니다.");
    }
  }

  function toggle(id: string) {
    setOpened((prev) => {
      // Set 을 그대로 mutate 하면 참조가 같아 React 가 리렌더하지 않는다. 새 Set 을 만든다.
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <>
      <PageHeader
        title="진단"
        description="문서끼리 서로 다른 말을 하는 곳을 찾습니다. 챗봇은 그중 하나를 골라 자신 있게 답하므로, 관리자가 먼저 알아야 합니다."
      />

      <Section title="문서 모순 검사">
        <p className="text-xs text-muted">
          비슷한 주제를 다루는 문서 조각을 짝지어, 같은 항목에 <b>서로 다른 값</b>을 말하는지
          확인합니다. 한 번에 최대 {SCAN_LIMIT}쌍을 검사하며 1~2분 걸릴 수 있습니다.
        </p>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={handleScan}
            disabled={scanning}
            className="rounded-md bg-foreground px-4 py-2 text-sm font-medium text-surface disabled:opacity-50"
          >
            {scanning ? "검사 중… (1~2분)" : "문서 검사"}
          </button>
          {error && (
            <span role="alert" className="text-sm text-danger">
              {error}
            </span>
          )}
        </div>

        {/*
          스캔 결과를 <네 숫자 그대로> 보여준다.
          "모순 0건"만 말하면 "깨끗해서 0건"과 "못 재서 0건"이 구분되지 않는다.
          이 프로젝트가 그 부류의 버그를 네 번 냈다.
        */}
        {lastScan && (
          <div className="rounded-md border border-subtle bg-background p-3 text-xs">
            검사한 쌍 <b>{lastScan.judged}</b> · 모순 <b>{lastScan.conflicts}</b>건
            {lastScan.failed > 0 && (
              <span className="text-warning">
                {" "}
                · ⚠️ {lastScan.failed}쌍은 <b>판정하지 못했습니다</b>(모순 없음이 아닙니다). 잠시
                후 다시 검사해주세요.
              </span>
            )}
            {lastScan.candidates >= SCAN_LIMIT && (
              <span className="text-warning">
                {" "}
                · 한 번에 검사할 수 있는 최대치를 채웠습니다. <b>아직 남은 쌍이 있을 수 있으니</b>{" "}
                한 번 더 눌러주세요.
              </span>
            )}
          </div>
        )}
      </Section>

      <Section title={`어긋나는 곳 ${conflicts ? `${conflicts.length}건` : ""}`}>
        {/*
          🐛 여기서 실제로 버그를 냈다(2026-08-10 브라우저 확인).
             목록 조회가 실패해도 conflicts 가 null 로 남아 <"불러오는 중…" 에서 영원히 멈췄다.>
             없는 봇 주소로 들어갔을 때 드러났는데, 사용자는 "느린 건가" 하며 계속 기다리게 된다.
             "아직 안 왔다" 와 "못 가져왔다" 는 다른 상태다 — 같은 화면으로 뭉개면 안 된다.
        */}
        {conflicts === null && error ? (
          <p role="alert" className="text-sm text-danger">
            {error}
          </p>
        ) : conflicts === null ? (
          <p className="text-sm text-muted">불러오는 중…</p>
        ) : conflicts.length === 0 ? (
          <p className="text-sm text-muted">
            아직 찾은 것이 없습니다. 위에서 <b>문서 검사</b>를 눌러보세요.
          </p>
        ) : (
          <ul className="space-y-3">
            {conflicts.map((c) => (
              <li key={c.id} className="rounded-md border border-warning bg-warning-surface p-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-sm font-semibold">⚠️ {c.topic}</p>
                    {/* 두 주장을 <나란히> 놓는다. 이게 이 화면의 핵심 정보다. */}
                    <dl className="mt-2 space-y-1 text-sm">
                      <div className="flex gap-2">
                        <dt className="shrink-0 text-muted">{c.aFilename}</dt>
                        <dd className="font-medium">{c.aSays}</dd>
                      </div>
                      <div className="flex gap-2">
                        <dt className="shrink-0 text-muted">{c.bFilename}</dt>
                        <dd className="font-medium">{c.bSays}</dd>
                      </div>
                    </dl>
                  </div>
                  <div className="flex shrink-0 gap-2">
                    <button
                      type="button"
                      onClick={() => toggle(c.id)}
                      className="rounded-md border border-subtle px-2 py-1 text-xs"
                    >
                      {opened.has(c.id) ? "원문 접기" : "원문 보기"}
                    </button>
                    {/*
                      "무시" 가 <반드시> 있어야 한다. 헛짚은 항목을 치울 수 없으면
                      관리자는 이 화면을 두 번 다시 보지 않는다 — 기능이 없는 것과 같아진다.
                    */}
                    <button
                      type="button"
                      onClick={() => void handleIgnore(c.id)}
                      className="rounded-md border border-subtle px-2 py-1 text-xs text-muted"
                      title="모순이 아니라고 표시합니다. 다시 검사해도 올라오지 않습니다."
                    >
                      무시
                    </button>
                  </div>
                </div>

                {/*
                  원문은 접어둔다. 판정을 <검증>하려면 필요하지만, 기본으로 펼치면
                  목록을 훑을 수가 없다. (테스트 채팅의 근거 칩과 같은 이유·같은 방식)
                */}
                {opened.has(c.id) && (
                  <div className="mt-3 grid gap-2 sm:grid-cols-2">
                    <pre className="overflow-x-auto whitespace-pre-wrap rounded-md border border-subtle bg-surface p-2 text-xs">
                      {c.aContent}
                    </pre>
                    <pre className="overflow-x-auto whitespace-pre-wrap rounded-md border border-subtle bg-surface p-2 text-xs">
                      {c.bContent}
                    </pre>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </Section>
    </>
  );
}
