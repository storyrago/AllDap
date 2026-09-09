"use client";

/*
 * `/dashboard` — 내 봇 목록 · 봇 생성.
 *
 * 데이터를 서버가 아니라 브라우저에서 가져오는 이유는 상위 레이아웃 주석에 적어두었다
 * (한 줄 요약: JWT 가 localStorage 에 있어 서버가 대신 호출해줄 수 없다).
 *
 * 호출하는 Spring API:
 *   GET  /api/bots          → Bot[]
 *   POST /api/bots {name}   → Bot
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ApiError, api } from "@/lib/api";
import type { BotSummary, Usage } from "@/lib/types";
import { PageHeader } from "@/components/PageHeader";

export default function DashboardPage() {
  /*
   * 목록 상태를 셋으로 나눈 이유.
   * 하나의 값으로 뭉치면 "불러오는 중" 과 "불러왔는데 0건" 을 구분할 수 없다.
   * 그 둘은 화면에 다르게 보여야 한다 — 후자에만 "첫 봇을 만들어보세요" 를 띄운다.
   */
  const [bots, setBots] = useState<BotSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);

  const [usage, setUsage] = useState<Usage | null>(null);
  /*
   * usage 하나만으로는 "아직 안 불러옴 / 실패함 / 사용량이 0건임"을 구분할 수 없다.
   * 셋 다 usage 가 null 이거나 { chatAnswers: 0, ... } 이 되기 때문이다.
   * 특히 실패와 "0건"은 화면에 다르게 보여야 한다 — 실패를 0건처럼 보여주면
   * 사용자가 "과금 안 됐네" 로 착각하고, 반대로 실패를 아예 숨기면
   * "이 기능이 원래 없다"로 착각한다. 그래서 실패 여부만 별도 불리언으로 둔다.
   */
  const [usageFailed, setUsageFailed] = useState(false);

  /**
   * 사용량을 불러온다.
   *
   * 왜 클라이언트에서 가져오는가: 인증 토큰이 <브라우저에만> 있어서 서버 컴포넌트가
   * 이 요청을 대신 보낼 수 없다. 이 파일이 이미 "use client" 인 이유와 같고,
   * 바로 위 봇 목록도 같은 이유로 여기서 부른다.
   *
   * useCallback 으로 감싸는 이유: 아래 useEffect 의 의존성 배열에 이 함수를 넣어야 하는데,
   * 매 렌더마다 새 함수가 만들어지면 effect 가 매번 다시 돌아 요청이 무한히 나간다.
   *
   * 실패해도 화면을 막지 않는다 — 사용량은 <보조 정보>다. 여기서 에러를 띄우면
   * 봇 목록이라는 주 기능이 부수 기능 때문에 가려진다. 다만 완전히 숨기지도 않는다 —
   * 아래 usageFailed 참고.
   */
  const loadUsage = useCallback(async () => {
    try {
      setUsage(await api.usage.current());
      setUsageFailed(false);
    } catch {
      setUsage(null);
      setUsageFailed(true);
    }
  }, []);

  useEffect(() => {
    /*
     * effect 안에서 async 함수를 <즉시 실행>한다. 이 저장소의 표준 모양이고,
     * 다른 화면들이 여기를 가리키므로 근거를 여기에 모아둔다.
     *
     * 왜 `void loadUsage()` 가 아닌가 — eslint 의 react-hooks/set-state-in-effect 가
     * "effect 에서 setState 하는 함수를 그냥 호출하는" 모양을 막는다(실측 확인).
     * IIFE 는 그 규칙의 <우회>가 아니라, setState 가 <비동기 경계 뒤>에서 일어난다는 것을
     * 코드 모양에 드러내는 것이다. 규칙이 잡으려는 건 렌더 중 동기 setState 다.
     *
     * 🔴 취소(cancelled) 플래그는 두지 않는다 — 2026-09-07 에 걷어냈다.
     *    예전에는 `await loadUsage(); if (cancelled) return;` 이 있었는데
     *    <아무것도 막지 못했다>: setState 는 이미 loadUsage() 안에서 끝나 있고
     *    그 뒤의 return 은 빈 return 이다. 그런데 주석은 "플래그로 그때는 아무것도
     *    하지 않는다" 고 단언하고 있어서, 읽는 사람이 <이미 처리돼 있다>고 믿게 만들었다.
     *
     *    애초에 막을 필요도 없다. 화면을 떠난 뒤 setState 가 불리는 것은 React 18+ 에서
     *    무시된다(경고도 없다) — billing 화면 주석이 이미 그렇게 적고 있었다.
     *    저장소 안에 상충하는 두 서술이 있었고 그쪽이 맞았다.
     *
     * ⚠️ 정말로 취소가 필요한 경우(예: 응답이 오래 걸리고 그 사이 다른 대상으로 바뀌는 화면)
     *    에는 <setState 바로 앞>에서 검사해야 한다. components/BotName.tsx 가 그 예다.
     */
    void (async () => {
      await loadUsage();
    })();
  }, [loadUsage]);

  /*
   * useCallback 으로 감싼 이유: 이 함수를 아래 useEffect 의 의존성 배열에 넣어야 하는데,
   * 감싸지 않으면 렌더할 때마다 <새 함수>가 만들어져 의존성이 매번 바뀐 것으로 보이고,
   * 그러면 effect 가 무한히 다시 실행된다. useCallback 은 "의존성이 그대로면 같은 함수를
   * 계속 쓰라" 는 뜻이다. 여기서는 바깥 값을 쓰지 않으므로 의존성이 빈 배열이다.
   */
  const loadBots = useCallback(async () => {
    setError(null);
    try {
      setBots(await api.bots.list());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "봇 목록을 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // 위 loadUsage effect 와 같은 모양이다 — 근거는 그쪽 주석에 모아두었다.
    void (async () => {
      await loadBots();
    })();
  }, [loadBots]);

  async function handleCreate(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!newName.trim()) return;

    setCreating(true);
    setError(null);
    try {
      const created = await api.bots.create({ name: newName.trim() });
      /*
       * 목록을 다시 부르지 않고 응답으로 받은 봇을 앞에 붙인다(서버가 최신순으로 주므로).
       * 왕복 한 번을 아끼고 화면이 즉시 반응한다.
       *
       * setBots(prev => ...) 형태로 쓰는 이유: 지금 화면에 그려진 bots 가 아니라
       * <가장 최신 값>을 기준으로 계산하기 위해서다. 연달아 만들 때 하나가 사라지는 사고를 막는다.
       */
      /*
       * POST 응답은 집계가 없는 Bot 이라 카드 타입(BotSummary)으로 맞춰준다.
       * 0 과 null 을 여기서 채워도 거짓이 아니다. 방금 만든 봇은 문서도 대화도 있을 수 없고,
       * 평가는 돌린 적이 없다. 목록을 다시 부르면 서버가 같은 값을 돌려줄 뿐이다.
       */
      setBots((prev) => [
        {
          ...created,
          documentCount: 0,
          weeklyConversationCount: 0,
          latestOverallFaithfulness: null,
        },
        ...prev,
      ]);
      setNewName("");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "봇을 만들지 못했습니다.");
    } finally {
      setCreating(false);
    }
  }

  return (
    <>
      <PageHeader title="내 봇" />

      <form onSubmit={handleCreate} className="mt-6 flex gap-2">
        <input
          type="text"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          maxLength={100}
          placeholder="새 봇 이름 (예: 학사 규정 봇)"
          className="flex-1 rounded-md border border-subtle bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
        />
        <button
          type="submit"
          /* 이름이 비었으면 눌러도 서버가 400 을 줄 뿐이다. 미리 막아 왕복을 아낀다. */
          disabled={creating || !newName.trim()}
          className="rounded-md bg-foreground px-4 py-2 text-sm font-medium text-surface disabled:opacity-50"
        >
          {creating ? "만드는 중…" : "봇 만들기"}
        </button>
      </form>

      {error && (
        <p
          role="alert"
          className="mt-4 rounded-md border border-danger bg-danger-surface px-3 py-2 text-sm text-danger"
        >
          {error}
        </p>
      )}

      {usage && (
        <section aria-labelledby="usage-heading" className="mt-6">
          <h2 id="usage-heading" className="text-sm font-medium">
            이번 달 사용량 ({usage.month})
          </h2>
          <dl className="mt-2 grid gap-3 sm:grid-cols-2">
            <div className="rounded-lg border border-subtle bg-surface p-4">
              <dt className="text-xs text-muted">답변</dt>
              <dd className="mt-1 text-lg font-medium">
                {usage.chatAnswers.toLocaleString("ko-KR")}건
              </dd>
            </div>
            <div className="rounded-lg border border-subtle bg-surface p-4">
              <dt className="text-xs text-muted">품질 평가 실행</dt>
              <dd className="mt-1 text-lg font-medium">
                {usage.evalRuns.toLocaleString("ko-KR")}회
              </dd>
            </div>
          </dl>
          {/* 🔴 금액은 /pricing 에 있지만(2026-09-07, 가정값) 플랜 테이블·한도·청구는 아직 없다
              (요금제 연동 4조각 중 2·4번 미구현). 여기서 금액을 <계산해> 보여주면
              청구되지 않을 금액을 청구될 것처럼 보이게 한다. 개수만 보여준다. */}
          <p className="mt-2 text-xs text-muted">
            답하지 못한 질문과 관리자 테스트 채팅은 세지 않습니다. 요금제별 한도와 청구는 아직
            연결되지 않았습니다.
          </p>
        </section>
      )}

      {/* usage 가 null 인 두 경우(아직 안 옴 / 실패함) 중 실패했을 때만 보인다.
          "아직 안 옴"은 로딩 중이라 아무것도 안 보이는 게 맞고, 실패는 알려야
          "사용량 기능이 아예 없다"로 착각하지 않는다. */}
      {usageFailed && (
        <p className="mt-6 text-xs text-muted">사용량을 불러오지 못했습니다.</p>
      )}

      <div className="mt-6">
        {loading ? (
          <p className="text-sm text-muted">불러오는 중…</p>
        ) : bots.length === 0 ? (
          <div className="rounded-lg border border-dashed border-subtle px-6 py-12 text-center">
            <p className="text-sm font-medium">아직 봇이 없습니다.</p>
            <p className="mt-1 text-sm text-muted">
              위에서 봇을 만든 뒤 문서를 올리면 그 문서만 근거로 답하는 챗봇이 됩니다.
            </p>
          </div>
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2">
            {bots.map((bot) => (
              /*
               * key 에 배열 인덱스가 아니라 bot.id 를 쓰는 이유:
               * React 는 key 로 "이전 목록의 어느 항목이 지금의 어느 항목인지" 를 맞춘다.
               * 인덱스를 쓰면 앞에 새 봇을 추가했을 때 전부 다른 항목으로 인식돼
               * 불필요한 다시 그리기와 상태 뒤섞임이 생긴다.
               */
              <li key={bot.id}>
                <Link
                  href={`/bot/${bot.id}`}
                  className="block rounded-lg border border-subtle bg-surface p-4 transition hover:border-accent"
                >
                  <p className="font-medium">{bot.name}</p>
                  <p className="mt-1 font-mono text-xs text-muted">
                    {bot.publicKey}
                  </p>

                  {/*
                   * PRD §8 의 봇 카드 세 숫자. dl 로 쓰는 이유는 "이름표 + 값" 이 정확히
                   * 정의 목록의 뜻이라서다. div 로 쌓으면 화면은 같아 보여도 스크린 리더에는
                   * 숫자만 흩어져 읽힌다.
                   */}
                  <dl className="mt-3 grid grid-cols-3 gap-2 border-t border-subtle pt-3">
                    <div>
                      <dt className="text-xs text-muted">문서</dt>
                      <dd className="mt-0.5 text-sm font-medium">
                        {bot.documentCount.toLocaleString("ko-KR")}개
                      </dd>
                    </div>
                    <div>
                      <dt className="text-xs text-muted">최근 7일 대화</dt>
                      <dd className="mt-0.5 text-sm font-medium">
                        {bot.weeklyConversationCount.toLocaleString("ko-KR")}건
                      </dd>
                    </div>
                    <div>
                      <dt className="text-xs text-muted">전체 충실성</dt>
                      {/*
                       * null 은 "0점" 이 아니라 "아직 잰 적이 없다" 이다. 0 으로 채워 보여주면
                       * 멀쩡한 봇이 최악의 점수를 받은 것처럼 보인다. 그래서 문구로 가른다.
                       * toFixed(3) 인 이유: 이 프로젝트의 개선 폭(측정 편차 0.032)이
                       * 소수 셋째 자리에서 갈린다. 반올림해 두 자리로 보여주면 그 차이가 사라진다.
                       */}
                      <dd className="mt-0.5 text-sm font-medium">
                        {bot.latestOverallFaithfulness === null ? (
                          <span className="text-muted">평가 전</span>
                        ) : (
                          bot.latestOverallFaithfulness.toFixed(3)
                        )}
                      </dd>
                    </div>
                  </dl>

                  <p className="mt-3 text-xs text-muted">
                    {bot.allowedOrigins.length === 0
                      ? "허용 도메인 미설정 — 위젯이 아직 동작하지 않습니다"
                      : `허용 도메인 ${bot.allowedOrigins.length}개`}
                  </p>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* 카드 숫자의 기준을 화면에도 적는다. 특히 "전체 충실성" 은 품질 대시보드가 쓰는 것과
          같은 지표라는 사실이 보여야, 카드와 대시보드의 숫자가 달라 보일 때 헷갈리지 않는다. */}
      {bots.length > 0 && (
        <p className="mt-4 text-xs text-muted">
          대화 수는 지금으로부터 최근 7일치이며 관리자 테스트 채팅도 포함합니다. 전체 충실성은
          가장 최근 완료된 평가 실행의 값으로, 답하지 못한 질문까지 분모에 넣은 지표입니다.
        </p>
      )}
    </>
  );
}
