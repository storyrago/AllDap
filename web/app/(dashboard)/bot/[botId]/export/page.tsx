"use client";

/*
 * `/bot/[botId]/export` — 내보내기. 허용 도메인 + 임베드 코드.
 *
 * 왜 "설정" 에서 갈라져 나왔나
 * ─────────────────────────────────────────────────────────────────────────
 * PRD §8 이 "코드 복사가 전환 포인트" 라고 못박은 자리인데, 그게 <설정> 안에 있었다.
 * 설정은 다 만들고 나서 한 번 들어가는 곳이라, 제품의 목적지가 가장 안 눌리는 자리에
 * 놓여 있던 셈이다. 사용자의 흐름은 <문서 먹이기 → 테스트 → 내보내기> 이고
 * 마지막 칸에는 그 이름이 붙어 있어야 한다.
 *
 * 허용 도메인을 설정이 아니라 여기 둔 이유: 스니펫만 붙여서는 위젯이 안 뜬다.
 * 빈 목록은 "전부 허용" 이 아니라 <전부 차단> 이기 때문이다(서버 규칙).
 * 두 가지를 갈라 놓으면 "코드는 붙였는데 왜 안 뜨지" 가 반드시 나온다.
 *
 * 호출하는 Spring API:
 *   GET   /api/bots/{botId}             → Bot
 *   PATCH /api/bots/{botId}             → Bot  (보낸 필드만 수정된다 — Bot.updateSettings 가 null 을 건너뛴다)
 *   GET   /api/bots/{botId}/documents   → Document[]  (준비 상태 확인용)
 *
 * ⚠️ PATCH 에 allowedOrigins 만 보낸다. 설정 화면과 저장 범위가 겹치지 않아야
 *    한쪽을 저장할 때 다른 쪽이 덮이지 않는다. 부분 수정이라는 서버 동작에 기대는 부분이라
 *    Bot.updateSettings 가 바뀌면 여기도 같이 검토해야 한다.
 */

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { API_BASE_URL, ApiError, api } from "@/lib/api";
import type { Bot } from "@/lib/types";
import { PageHeader } from "@/components/PageHeader";
import { Section, TextArea } from "@/components/Form";

export default function ExportPage() {
  const { botId } = useParams<{ botId: string }>();

  const [bot, setBot] = useState<Bot | null>(null);
  /* 문서는 "준비됐나" 판단에만 쓴다. 목록을 그리지 않으므로 개수만 들고 있는다. */
  const [readyDocs, setReadyDocs] = useState<number | null>(null);
  const [origins, setOrigins] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [copied, setCopied] = useState(false);

  const load = useCallback(async () => {
    try {
      /*
       * 두 요청이 서로를 기다릴 이유가 없어 Promise.all 로 <동시에> 보낸다.
       * 순서대로 await 하면 왕복 시간이 그냥 두 배가 된다.
       */
      const [loaded, docs] = await Promise.all([
        api.bots.get(botId),
        api.documents.list(botId),
      ]);
      setBot(loaded);
      setOrigins(loaded.allowedOrigins.join("\n"));
      setReadyDocs(docs.filter((d) => d.status === "ready").length);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "봇 정보를 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, [botId]);

  useEffect(() => {
    // settings 화면과 같은 형태다. 화면을 떠난 뒤 응답이 와도 상태를 건드리지 않는다.
    let cancelled = false;
    void (async () => {
      await load();
      if (cancelled) return;
    })();
    return () => {
      cancelled = true;
    };
  }, [load]);

  async function handleSave(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const updated = await api.bots.update(botId, {
        /*
         * 빈 줄을 걸러낸다. 빈 문자열이 배열에 들어가면 서버는 "허용 도메인이 있다"고
         * 판정하는데 실제로는 아무 도메인도 못 맞춰서, 원인을 찾기 어려운 상태가 된다.
         */
        allowedOrigins: origins
          .split("\n")
          .map((line) => line.trim())
          .filter((line) => line.length > 0),
      });
      setBot(updated);
      setSaved(true);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "저장하지 못했습니다.");
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <p className="text-sm text-muted">불러오는 중…</p>;
  if (!bot) {
    return (
      <p role="alert" className="text-sm text-danger">
        {error ?? "봇을 찾을 수 없습니다."}
      </p>
    );
  }

  /*
   * 고객이 자기 사이트에 붙일 한 줄. publicKey 가 그대로 노출되는 게 정상이다.
   *
   * 🔴 data-app-base 가 왜 필요한가 (2026-08-05 PoC 에서 잡은 버그)
   * ───────────────────────────────────────────────────────────────────────
   * 위젯 JS 는 <Spring(:8080)> 이 서빙하고, 로더는 스크립트 src 의 origin 을
   * API 주소로 삼는다. 그런데 정작 iframe 에 띄울 채팅 화면(`/w/[publicKey]`)은
   * <Next.js(:3000)> 에 있다. 이 속성이 없으면 로더가 iframe 도 :8080 으로 열어
   * `GET :8080/w/{key}?embed=1 → 401` 로 <채팅 화면을 불러오는 중입니다…> 에서 멎는다.
   * (버튼과 인사말까지는 정상이라 더 헷갈린다 — config 는 Spring 이 맞게 주기 때문이다)
   *
   * window.location.origin 을 쓰는 이유: `/w/[publicKey]` 는 <바로 이 앱>이 서빙한다.
   * 그래서 이 화면이 떠 있는 주소가 곧 정답이고, 로컬이든 운영이든 자동으로 맞는다.
   * (환경변수로 따로 받으면 배포할 때 하나 더 틀릴 자리가 생긴다)
   *
   * typeof window 검사는 서버 렌더 대비다. 이 줄까지 오려면 loading 이 false 여야 하고
   * 그건 브라우저에서만 일어나지만, 규칙을 코드에 남겨두는 편이 안전하다.
   */
  const appBase = typeof window === "undefined" ? "" : window.location.origin;
  const snippet =
    `<script src="${API_BASE_URL}/widget/alldap-widget.js"` +
    ` data-public-key="${bot.publicKey}"` +
    ` data-app-base="${appBase}"></script>`;

  const hasDocs = (readyDocs ?? 0) > 0;
  const hasOrigins = bot.allowedOrigins.length > 0;

  return (
    <>
      <PageHeader
        title="내보내기"
        description="이 봇을 내 사이트에 붙입니다. 아래 두 가지가 준비돼야 위젯이 뜹니다."
      />

      {/*
        체크리스트를 <실제 상태>로 그린다. 고정 문구로 "1. 문서를 올리세요" 만 적어두면
        사용자는 자기가 어디까지 했는지를 스스로 대조해야 한다.
        특히 아래 두 조건은 하나라도 빠지면 위젯이 <조용히> 안 뜬다 —
        오류가 아니라 "아무 일도 일어나지 않음" 이라 원인을 찾기가 가장 어렵다.
      */}
      <Section title="준비 상태">
        <ul className="space-y-2 text-sm">
          <Check done={hasDocs}>
            {hasDocs ? (
              <>답변에 쓸 문서 {readyDocs}개가 준비됐습니다.</>
            ) : (
              <>
                아직 <b>준비된 문서가 없습니다.</b> 문서가 없으면 봇은 모든 질문에 거절 문구로
                답합니다.{" "}
                <Link href={`/bot/${botId}/documents`} className="underline">
                  문서 관리로 이동
                </Link>
              </>
            )}
          </Check>
          <Check done={hasOrigins}>
            {hasOrigins ? (
              <>설치할 주소 {bot.allowedOrigins.length}개가 등록됐습니다.</>
            ) : (
              <>
                설치할 주소가 없습니다. <b>빈 목록은 전부 허용이 아니라 전부 차단입니다</b> —
                아래에서 먼저 등록해주세요.
              </>
            )}
          </Check>
        </ul>
      </Section>

      <form onSubmit={handleSave}>
        <Section title="설치할 주소">
          <TextArea
            label="위젯을 설치할 주소 (한 줄에 하나)"
            hint="예: https://example.com — 프로토콜과 포트까지 정확히 일치해야 합니다. www 를 쓴다면 그 주소도 따로 넣어주세요."
            rows={3}
            value={origins}
            onChange={setOrigins}
            placeholder={"https://example.com\nhttps://www.example.com"}
          />
          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={saving}
              className="rounded-md bg-foreground px-4 py-2 text-sm font-medium text-surface disabled:opacity-50"
            >
              {saving ? "저장 중…" : "주소 저장"}
            </button>
            {error && (
              <span role="alert" className="text-sm text-danger">
                {error}
              </span>
            )}
            {saved && <span className="text-sm text-success">저장했습니다.</span>}
          </div>
        </Section>
      </form>

      <Section title="붙여넣을 코드">
        <p className="text-xs text-muted">
          내 사이트의 <code>&lt;/body&gt;</code> 바로 앞에 이 한 줄을 붙이면 오른쪽 아래에 상담
          버튼이 생깁니다.
        </p>
        <pre className="overflow-x-auto rounded-md border border-subtle bg-background p-3 text-xs">
          {snippet}
        </pre>
        <button
          type="button"
          onClick={() => {
            void navigator.clipboard.writeText(snippet);
            // 눌렀는데 화면이 그대로면 복사가 됐는지 알 수 없다. 잠깐 문구를 바꿔 알려준다.
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
          }}
          className="rounded-md border border-subtle px-3 py-1.5 text-sm"
        >
          {copied ? "복사했습니다" : "복사"}
        </button>
      </Section>
    </>
  );
}

/* 체크리스트 한 줄. 이 화면에서만 쓰므로 여기 둔다(공용으로 뺄 두 번째 사용처가 없다). */
function Check({ done, children }: { done: boolean; children: React.ReactNode }) {
  return (
    <li className="flex gap-2">
      <span aria-hidden className={done ? "text-success" : "text-warning"}>
        {done ? "✓" : "!"}
      </span>
      {/* 아이콘은 aria-hidden 이므로 상태를 글자로도 남긴다 — 스크린리더가 ✓ 를 못 읽는다. */}
      <span className="sr-only">{done ? "완료:" : "필요:"}</span>
      <span className={done ? "text-muted" : ""}>{children}</span>
    </li>
  );
}
