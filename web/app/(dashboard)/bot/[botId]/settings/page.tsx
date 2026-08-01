"use client";

/*
 * `/bot/[botId]/settings` — 봇 문구 · 허용 도메인 · 임베드 코드 · 삭제.
 *
 * PRD §8 이 "코드 복사가 전환 포인트" 라고 적어둔 화면이다.
 * 여기서 허용 도메인을 넣고 스니펫을 복사해 붙이면 위젯이 실제로 뜬다.
 *
 * 호출하는 Spring API:
 *   GET    /api/bots/{botId}   → Bot
 *   PATCH  /api/bots/{botId}   → Bot   (보낸 필드만 수정된다)
 *   DELETE /api/bots/{botId}
 */

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { API_BASE_URL, ApiError, api } from "@/lib/api";
import type { Bot } from "@/lib/types";
import { PageHeader } from "@/components/PageHeader";

export default function SettingsPage() {
  const { botId } = useParams<{ botId: string }>();
  const router = useRouter();

  const [bot, setBot] = useState<Bot | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  /*
   * 폼 입력값을 봇 객체와 <따로> 들고 있는 이유.
   *
   * 서버에서 받은 bot 을 그대로 편집하면 "저장 전 원래 값"이 사라져서
   * 무엇이 바뀌었는지 알 수 없고, 저장 실패 시 되돌릴 수도 없다.
   * 서버 상태(bot)와 편집 중인 값(form)을 분리해 두는 게 폼의 기본형이다.
   */
  const [form, setForm] = useState({
    name: "",
    welcomeMessage: "",
    fallbackMessage: "",
    systemPrompt: "",
    /* 허용 도메인은 배열이지만 입력은 줄바꿈으로 받는다. 한 줄에 하나가 가장 편집하기 쉽다. */
    allowedOrigins: "",
  });

  const loadBot = useCallback(async () => {
    try {
      const loaded = await api.bots.get(botId);
      setBot(loaded);
      setForm({
        name: loaded.name,
        welcomeMessage: loaded.welcomeMessage,
        fallbackMessage: loaded.fallbackMessage,
        // 서버는 null 을 줄 수 있는데 <input value> 에 null 을 넣으면 React 가 경고한다
        // ("제어 컴포넌트가 비제어로 바뀐다"). "값 없음"을 빈 문자열로 바꿔 규칙을 지킨다.
        systemPrompt: loaded.systemPrompt ?? "",
        allowedOrigins: loaded.allowedOrigins.join("\n"),
      });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "봇 정보를 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, [botId]);

  useEffect(() => {
    /*
     * effect 안에서 async 함수를 <즉시 실행>하고 취소 플래그를 둔다.
     *
     * 왜 `void loadBot()` 이 아닌가 — 두 가지 이유가 겹친다.
     * ① 화면을 떠난 뒤 응답이 도착하면 사라진 컴포넌트의 상태를 갱신하려 든다.
     *    cancelled 플래그로 그때는 아무것도 하지 않는다.
     * ② eslint 의 react-hooks/set-state-in-effect 규칙이 "effect 에서 setState 를 하는 함수를
     *    그냥 호출하는" 모양을 막는다. 응답이 온 <뒤>에 갱신한다는 게 코드 모양에 드러나야 한다.
     */
    let cancelled = false;
    void (async () => {
      await loadBot();
      if (cancelled) return;
    })();
    return () => {
      cancelled = true;
    };
  }, [loadBot]);

  async function handleSave(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setSaved(false);

    try {
      const updated = await api.bots.update(botId, {
        name: form.name.trim(),
        welcomeMessage: form.welcomeMessage,
        fallbackMessage: form.fallbackMessage,
        systemPrompt: form.systemPrompt,
        /*
         * 줄바꿈으로 나눈 뒤 빈 줄을 걸러낸다.
         * 빈 문자열이 배열에 들어가면 서버는 "허용 도메인이 있다"고 판정하는데
         * 실제로는 아무 도메인도 못 맞춰서, 원인을 찾기 어려운 상태가 된다.
         */
        allowedOrigins: form.allowedOrigins
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

  async function handleDelete() {
    if (!bot) return;
    // 봇을 지우면 문서·청크·대화 로그가 DB 의 CASCADE 로 전부 사라진다. 되돌릴 수 없다.
    if (
      !window.confirm(
        `"${bot.name}" 봇을 삭제할까요?\n올린 문서와 대화 기록이 모두 사라지며 되돌릴 수 없습니다.`,
      )
    ) {
      return;
    }
    try {
      await api.bots.remove(botId);
      router.replace("/dashboard");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "삭제하지 못했습니다.");
    }
  }

  if (loading) return <p className="text-sm text-muted">불러오는 중…</p>;
  if (!bot) {
    return (
      <p role="alert" className="text-sm text-red-600">
        {error ?? "봇을 찾을 수 없습니다."}
      </p>
    );
  }

  /* 고객이 자기 사이트에 붙일 한 줄. publicKey 가 그대로 노출되는 게 정상이다. */
  const snippet = `<script src="${API_BASE_URL}/widget/alldap-widget.js" data-public-key="${bot.publicKey}"></script>`;

  return (
    <>
      <PageHeader title="봇 설정" description="봇 문구와 임베드 코드를 관리합니다." />

      <form onSubmit={handleSave}>
        <Section title="기본 정보">
          <TextField
            label="봇 이름"
            value={form.name}
            onChange={(v) => setForm({ ...form, name: v })}
            maxLength={100}
          />
          <TextField
            label="인사말"
            hint="위젯을 열면 먼저 보이는 문구입니다."
            value={form.welcomeMessage}
            onChange={(v) => setForm({ ...form, welcomeMessage: v })}
          />
          <TextField
            label="거절 문구"
            hint="문서에서 근거를 찾지 못했을 때 이 문구가 대신 나갑니다. 담당자 연락처를 넣어두면 좋습니다."
            value={form.fallbackMessage}
            onChange={(v) => setForm({ ...form, fallbackMessage: v })}
          />
        </Section>

        <Section title="시스템 프롬프트">
          {/*
            거짓 완성 금지 — 저장은 되지만 답변에는 <아직> 반영되지 않는다.
            Python 의 /internal/chat 요청 스키마에 자리가 없어서다.
            화면에 적어두지 않으면 사용자는 값을 넣고 "왜 안 먹지?" 하게 된다.
          */}
          <p className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300">
            ⚠️ 지금은 <b>저장만 되고 답변에는 반영되지 않습니다.</b> AI 서비스가 이 값을 받도록 고친
            뒤에 동작합니다.
          </p>
          <TextArea
            label="답변 지침"
            rows={3}
            value={form.systemPrompt}
            onChange={(v) => setForm({ ...form, systemPrompt: v })}
          />
        </Section>

        <Section title="허용 도메인">
          <TextArea
            label="위젯을 설치할 주소 (한 줄에 하나)"
            hint="예: https://example.com — 프로토콜과 포트까지 정확히 일치해야 합니다."
            rows={3}
            value={form.allowedOrigins}
            onChange={(v) => setForm({ ...form, allowedOrigins: v })}
            placeholder={"https://example.com\nhttps://www.example.com"}
          />
          {/* 빈 목록 = 전부 차단이 서버의 규칙이다. 그 사실을 화면에서 먼저 알려준다. */}
          {bot.allowedOrigins.length === 0 && (
            <p className="text-xs text-amber-700 dark:text-amber-400">
              아직 허용 도메인이 없어 <b>위젯이 어느 사이트에서도 뜨지 않습니다.</b> 설치할 주소를
              먼저 등록해주세요.
            </p>
          )}
        </Section>

        <div className="mt-4 flex items-center gap-3">
          <button
            type="submit"
            disabled={saving}
            className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {saving ? "저장 중…" : "저장"}
          </button>
          {error && (
            <span role="alert" className="text-sm text-red-600 dark:text-red-400">
              {error}
            </span>
          )}
          {saved && (
            <span className="text-sm text-green-700 dark:text-green-400">저장했습니다.</span>
          )}
        </div>
      </form>

      <Section title="임베드 코드">
        <p className="text-xs text-muted">
          고객 사이트의 <code>&lt;/body&gt;</code> 바로 앞에 이 한 줄을 붙이면 위젯이 뜹니다.
        </p>
        <pre className="overflow-x-auto rounded-md border border-subtle bg-background p-3 text-xs">
          {snippet}
        </pre>
        <button
          type="button"
          onClick={() => void navigator.clipboard.writeText(snippet)}
          className="rounded-md border border-subtle px-3 py-1.5 text-sm"
        >
          복사
        </button>
      </Section>

      <Section title="위험 구역">
        <p className="text-xs text-muted">
          봇을 지우면 올린 문서와 대화 기록이 <b>모두</b> 사라집니다. 되돌릴 수 없습니다.
        </p>
        <button
          type="button"
          onClick={handleDelete}
          className="rounded-md border border-red-300 px-3 py-1.5 text-sm text-red-600 dark:border-red-900 dark:text-red-400"
        >
          이 봇 삭제
        </button>
      </Section>
    </>
  );
}

/* ── 아래는 이 화면에서만 쓰는 작은 조각들 ────────────────────────────────
 * 별도 파일로 빼지 않은 이유: 다른 화면에서 쓸 일이 아직 없다.
 * 두 번째 사용처가 생기면 그때 components/ 로 옮긴다.
 */

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-6 space-y-3 rounded-lg border border-subtle bg-surface p-4">
      <h2 className="text-sm font-semibold">{title}</h2>
      {children}
    </section>
  );
}

function TextField({
  label,
  hint,
  value,
  onChange,
  maxLength,
}: {
  label: string;
  hint?: string;
  value: string;
  /* 이벤트가 아니라 <값>을 넘기는 시그니처로 둔다 — 호출부가 e.target.value 를 몰라도 된다. */
  onChange: (value: string) => void;
  maxLength?: number;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium">{label}</span>
      {hint && <span className="mb-1 block text-xs text-muted">{hint}</span>}
      <input
        type="text"
        value={value}
        maxLength={maxLength}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-md border border-subtle bg-background px-3 py-2 text-sm outline-none focus:border-accent"
      />
    </label>
  );
}

function TextArea({
  label,
  hint,
  value,
  onChange,
  rows,
  placeholder,
}: {
  label: string;
  hint?: string;
  value: string;
  onChange: (value: string) => void;
  rows: number;
  placeholder?: string;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium">{label}</span>
      {hint && <span className="mb-1 block text-xs text-muted">{hint}</span>}
      <textarea
        value={value}
        rows={rows}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-md border border-subtle bg-background px-3 py-2 text-sm outline-none focus:border-accent"
      />
    </label>
  );
}
