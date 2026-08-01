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
import type { Bot } from "@/lib/types";
import { PageHeader } from "@/components/PageHeader";

export default function DashboardPage() {
  /*
   * 목록 상태를 셋으로 나눈 이유.
   * 하나의 값으로 뭉치면 "불러오는 중" 과 "불러왔는데 0건" 을 구분할 수 없다.
   * 그 둘은 화면에 다르게 보여야 한다 — 후자에만 "첫 봇을 만들어보세요" 를 띄운다.
   */
  const [bots, setBots] = useState<Bot[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);

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
    /*
     * effect 안에서 async 함수를 <즉시 실행>하고 취소 플래그를 둔다.
     *
     * 왜 `void loadBots()` 이 아닌가 — 두 가지 이유가 겹친다.
     * ① 화면을 떠난 뒤 응답이 도착하면 사라진 컴포넌트의 상태를 갱신하려 든다.
     *    cancelled 플래그로 그때는 아무것도 하지 않는다.
     * ② eslint 의 react-hooks/set-state-in-effect 규칙이 "effect 에서 setState 를 하는 함수를
     *    그냥 호출하는" 모양을 막는다. 응답이 온 <뒤>에 갱신한다는 게 코드 모양에 드러나야 한다.
     */
    let cancelled = false;
    void (async () => {
      await loadBots();
      if (cancelled) return;
    })();
    return () => {
      cancelled = true;
    };
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
      setBots((prev) => [created, ...prev]);
      setNewName("");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "봇을 만들지 못했습니다.");
    } finally {
      setCreating(false);
    }
  }

  return (
    <>
      <PageHeader
        title="내 봇"
        description="봇 단위로 문서와 대화가 완전히 격리됩니다. 다른 봇의 문서는 절대 검색되지 않습니다."
      />

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
          className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {creating ? "만드는 중…" : "봇 만들기"}
        </button>
      </form>

      {error && (
        <p
          role="alert"
          className="mt-4 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300"
        >
          {error}
        </p>
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

      {/* 봇 카드의 문서 수·주간 대화 수·최근 평가 점수(PRD §8)는 아직 서버가 내려주지 않는다.
          집계를 붙이려면 group by 쿼리가 필요하다 — lib/types.ts 의 BotSummary 주석 참고. */}
    </>
  );
}
