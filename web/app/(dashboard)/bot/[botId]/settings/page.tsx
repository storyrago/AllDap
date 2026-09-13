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
import { parseId } from "@/lib/ids";
import type { Bot } from "@/lib/types";
import { PageHeader } from "@/components/PageHeader";
import { Section, TextArea, TextField } from "@/components/Form";

export default function SettingsPage() {
  /* useParams() 가 주는 값은 URL 조각이라 언제나 <문자열>이다.
     기본키가 BIGINT 가 된 뒤로는 숫자로 바꿔야 하고, 형식 검사도 거기서 한다. */
  const { botId: rawBotId } = useParams<{ botId: string }>();
  const botId = parseId(rawBotId);
  const router = useRouter();

  const [bot, setBot] = useState<Bot | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  /* 삭제 확인 패널이 열렸는가. window.confirm 을 대신한다(handleDelete 주석 참고). */
  const [armed, setArmed] = useState(false);
  /* 삭제 요청이 도는 중. 버튼을 잠가 연타로 같은 요청이 두 번 나가는 것을 막는다. */
  const [deleting, setDeleting] = useState(false);

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
    // eslint react-hooks/set-state-in-effect 때문에 IIFE 로 감싼다 — setState 가
    // <비동기 경계 뒤>에서 일어난다는 것을 코드에 드러내는 것이다.
    // 취소 플래그는 두지 않는다: React 18+ 에서 떠난 뒤의 setState 는 무시되고,
    // 예전의 `await loadBot(); if (cancelled) return;` 은 setState 가 이미 끝난
    // 뒤라 아무것도 막지 못했다. 근거는 app/(dashboard)/dashboard/page.tsx 첫 effect 주석.
    void (async () => {
      await loadBot();
    })();
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

  /*
   * 봇을 지우면 문서·청크·대화 로그가 DB 의 CASCADE 로 전부 사라진다. 되돌릴 수 없다.
   *
   * 🔴 window.confirm 을 쓰지 않는 이유 (2026-08-10, 문서 삭제에서 먼저 겪었다)
   * ─────────────────────────────────────────────────────────────────────────
   * 크롬은 같은 페이지에서 대화상자가 반복되면 "추가 대화상자를 만들지 않도록 차단"
   * 체크박스를 띄운다. 켜지면 confirm() 은 <항상 false> 를 돌려주고,
   * 이 함수는 조용히 return 하고, 요청조차 안 나가고, 오류도 안 뜬다.
   * 밖에서 보면 "버튼이 고장났다" 와 구별할 수 없다 — 실제로 그렇게 보였다.
   *
   * 즉 <파괴적 작업일수록 안전장치가 브라우저 설정 하나로 사라지면 안 된다.>
   * 문서 삭제보다 여기가 더 위험하다: 문서는 다시 올릴 수 있지만 대화 기록은 못 되살린다.
   *
   * 문서 삭제는 버튼 라벨만 바꾸는 2단계인데 여기는 <패널>인 이유:
   * confirm 이 보여주던 정보(봇 이름 + 무엇이 사라지는지)를 잃지 않으려면 자리가 필요하고,
   * 취소 버튼이 따로 있어야 오클릭으로 지워지지 않는다. 위험이 다르면 마찰도 달라야 한다.
   */
  async function handleDelete() {
    if (!bot) return;
    setDeleting(true);
    setError(null);
    try {
      await api.bots.remove(botId);
      // 성공하면 화면을 떠나므로 deleting 을 되돌리지 않는다(되돌리면 잠깐 깜빡인다).
      router.replace("/dashboard");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "삭제하지 못했습니다.");
      setDeleting(false);
      setArmed(false);
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
      <PageHeader title="봇 설정" />

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
            🔴 2026-09-07 정정. 예전엔 "저장만 되고 답변에는 반영되지 않습니다" 라고 안내했는데
               <이미 반영된다.> 2026-08-13 에 Python 의 fetch_bot_prompt 가 bots.system_prompt 를
               직접 읽도록 붙었다(Spring 이 요청에 싣지 않는다 — evalrun 이 Spring 을 거치지 않아
               그러면 평가만 기본 프롬프트로 돌기 때문이다). 기능이 붙은 뒤 이 화면을 안 고쳐서
               <되는 기능을 안 된다고 안내>하고 있었다.

               경고 자리는 없애지 않고 <진짜 한계>로 바꾼다. 결합은 대체가 아니라 덧붙임이고
               "충돌하면 위 규칙이 우선" 을 명시하지만(generator.build_system_prompt),
               프롬프트로 프롬프트를 막는 데는 한계가 있어 실측으로 뚫렸다.
               재는 도구는 ai-service/app/bot_prompt_check.py 다.
          */}
          <p className="rounded-md border border-warning bg-warning-surface px-3 py-2 text-xs text-warning">
            {/* {" "} 가 필요하다 — 없으면 "있습니다.“모르는" 처럼 <붙어서> 렌더된다.
                JSX 는 태그와 엔티티 사이의 공백을 그대로 지켜주지 않는다.
                lint·tsc 로는 안 잡히고 브라우저로 봐야만 보이는 부류다. */}
            ⚠️ 이 지침으로 <b>거절 판정이 약해질 수 있습니다.</b>{" "}
            &ldquo;모르는 것도 아는 척 답해&rdquo; 처럼 기본 규칙을 거스르는 문장을 넣으면 근거가
            없는 질문에도 답하는 경우가 확인됐습니다. 말투와 답변 범위를 정하는 데만 쓰시길 권합니다.
          </p>
          <TextArea
            label="답변 지침"
            hint="답변에 반영됩니다. 기본 규칙(문서에 근거가 없으면 답하지 않기) 뒤에 덧붙는 형태이고, 충돌하면 기본 규칙이 우선합니다."
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

        {!armed ? (
          <button
            type="button"
            onClick={() => setArmed(true)}
            className="rounded-md border border-danger px-3 py-1.5 text-sm text-danger"
          >
            이 봇 삭제
          </button>
        ) : (
          /*
            confirm 이 보여주던 것을 그대로 화면에 옮겼다 — <봇 이름>과 <무엇이 사라지는지>.
            이름을 다시 적는 이유: 봇을 여러 개 쓰면 "지금 어느 봇 설정 화면인지"를
            착각하기 쉽다. 지우기 직전에 한 번 더 눈으로 확인시킨다.
          */
          <div className="rounded-md border border-danger bg-danger-surface p-3">
            <p className="text-sm">
              <b>{bot.name}</b> 을(를) 정말 삭제할까요?
            </p>
            <p className="mt-1 text-xs">
              올린 문서와 대화 기록이 함께 사라지며 <b>되돌릴 수 없습니다.</b>
            </p>
            <div className="mt-3 flex gap-2">
              {/* 취소를 <먼저> 둔다. 습관적으로 왼쪽을 누르는 사람이 실수로 지우지 않도록. */}
              <button
                type="button"
                onClick={() => setArmed(false)}
                disabled={deleting}
                className="rounded-md border border-subtle bg-surface px-3 py-1.5 text-sm disabled:opacity-50"
              >
                취소
              </button>
              <button
                type="button"
                onClick={() => void handleDelete()}
                disabled={deleting}
                className="rounded-md bg-danger px-3 py-1.5 text-sm font-medium text-surface disabled:opacity-50"
              >
                {deleting ? "삭제 중…" : "삭제합니다"}
              </button>
            </div>
          </div>
        )}
      </Section>
    </>
  );
}
