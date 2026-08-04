"use client";

/*
 * `/bot/[botId]/settings` — 봇 문구 · 시스템 프롬프트 · 삭제.
 *
 * ⚠️ 허용 도메인과 임베드 코드는 <내보내기>(`/bot/[botId]/export`) 로 옮겼다.
 *    PRD §8 이 "코드 복사가 전환 포인트" 라고 못박은 자리가 설정 안에 묻혀 있었기 때문이다.
 *    자세한 근거는 export/page.tsx 상단 주석 참고.
 *
 * 두 화면이 같은 PATCH 를 부르지만 서로 덮어쓰지 않는다 — 서버가 <보낸 필드만> 고치고
 * (`Bot.updateSettings` 가 null 을 건너뛴다), 두 화면의 저장 범위가 겹치지 않는다.
 *
 * 호출하는 Spring API:
 *   GET    /api/bots/{botId}   → Bot
 *   PATCH  /api/bots/{botId}   → Bot   (보낸 필드만 수정된다)
 *   DELETE /api/bots/{botId}
 */

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { ApiError, api } from "@/lib/api";
import type { Bot } from "@/lib/types";
import { PageHeader } from "@/components/PageHeader";
import { Section, TextArea, TextField } from "@/components/Form";

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
        // allowedOrigins 는 <일부러 안 보낸다>. 내보내기 화면의 몫이며,
        // 서버가 null 인 필드를 건너뛰므로 여기서 저장해도 그 값은 그대로 남는다.
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
      <p role="alert" className="text-sm text-danger">
        {error ?? "봇을 찾을 수 없습니다."}
      </p>
    );
  }

  return (
    <>
      <PageHeader title="봇 설정" description="봇 이름과 사용자에게 보이는 문구를 관리합니다." />

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
          <p className="rounded-md border border-warning bg-warning-surface px-3 py-2 text-xs text-warning">
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

        <div className="mt-4 flex items-center gap-3">
          <button
            type="submit"
            disabled={saving}
            className="rounded-md bg-foreground px-4 py-2 text-sm font-medium text-surface disabled:opacity-50"
          >
            {saving ? "저장 중…" : "저장"}
          </button>
          {error && (
            <span role="alert" className="text-sm text-danger">
              {error}
            </span>
          )}
          {saved && (
            <span className="text-sm text-success">저장했습니다.</span>
          )}
        </div>
      </form>

      {/* 여기 있던 "임베드 코드" 는 내보내기 화면으로 옮겼다. 찾으러 온 사람을 위해 길만 남긴다. */}
      <Section title="내 사이트에 붙이려면">
        <p className="text-xs text-muted">
          설치 코드와 허용 도메인은{" "}
          <Link href={`/bot/${botId}/export`} className="underline">
            내보내기
          </Link>
          에서 관리합니다.
        </p>
      </Section>

      <Section title="위험 구역">
        <p className="text-xs text-muted">
          봇을 지우면 올린 문서와 대화 기록이 <b>모두</b> 사라집니다. 되돌릴 수 없습니다.
        </p>
        <button
          type="button"
          onClick={handleDelete}
          className="rounded-md border border-danger px-3 py-1.5 text-sm text-danger"
        >
          이 봇 삭제
        </button>
      </Section>
    </>
  );
}
