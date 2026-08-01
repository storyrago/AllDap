"use client";

/*
 * `/bot/[botId]/documents` — 문서 업로드 · 목록 · 삭제.
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * 이 화면의 핵심은 "업로드가 즉시 끝나지 않는다" 는 것이다.
 * ─────────────────────────────────────────────────────────────────────────────
 * 서버는 파일을 받자마자 202 로 답하고(status: "pending"), 파싱·청킹·임베딩은
 * 백그라운드에서 이어진다. 임베딩은 외부 LLM API 호출이라 수십 초가 걸릴 수 있어서,
 * 응답을 붙잡아두면 타임아웃이 나기 때문이다.
 *
 * 그래서 화면은 <상태를 따라가야 한다>: pending → processing → ready | failed.
 * 아래 useEffect 가 그 폴링을 담당한다.
 *
 * params 를 useParams() 로 읽는 이유:
 *   서버 컴포넌트라면 `const { botId } = await params` 로 받는다(상위 layout.tsx 가 그렇다).
 *   그런데 이 파일은 "use client" 라 서버에서 실행되지 않으므로 그 방법을 쓸 수 없다.
 *   클라이언트에서는 useParams() 훅으로 현재 URL 의 동적 구간을 읽는다.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { ApiError, api } from "@/lib/api";
import type { DocumentItem, DocumentStatus } from "@/lib/types";
import { PageHeader } from "@/components/PageHeader";

/** 아직 처리 중인 상태들. 이 중 하나라도 있으면 폴링을 계속한다. */
const IN_PROGRESS: DocumentStatus[] = ["pending", "processing"];

export default function DocumentsPage() {
  const { botId } = useParams<{ botId: string }>();

  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  /*
   * useRef 로 <input type="file"> 을 직접 붙잡는 이유.
   *
   * 다른 입력들은 value/onChange 로 React 가 값을 관리한다(제어 컴포넌트).
   * 그런데 파일 입력은 보안상 값을 코드로 지정할 수 없어 그 방식이 통하지 않는다.
   * 업로드 후 "선택된 파일" 표시를 지우려면 DOM 요소를 직접 만져야 해서 ref 를 쓴다.
   */
  const fileInputRef = useRef<HTMLInputElement>(null);

  const loadDocuments = useCallback(async () => {
    try {
      setDocuments(await api.documents.list(botId));
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "문서 목록을 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, [botId]);
  // botId 가 의존성인 이유: 다른 봇 화면으로 이동하면 이 함수는 <다른 봇의 목록>을 불러야 한다.
  // 빼먹으면 봇을 바꿔도 이전 봇의 문서가 계속 보인다.

  useEffect(() => {
    void loadDocuments();
  }, [loadDocuments]);

  /*
   * ── 상태 폴링 ────────────────────────────────────────────────────────────
   * 처리 중인 문서가 있을 때만 2초마다 다시 불러온다.
   *
   * 두 가지를 지켜야 한다.
   *   ① 처리가 다 끝나면 멈춘다. 안 그러면 아무 일도 안 일어나는데 영원히 서버를 두드린다.
   *   ② 화면을 떠나면 반드시 정리한다(return 의 clearInterval).
   *      정리하지 않으면 타이머가 계속 살아서 사라진 화면의 상태를 갱신하려 들고,
   *      화면을 오갈 때마다 타이머가 하나씩 쌓인다.
   *
   * 의존성에 documents 가 들어간 이유: "처리 중인 게 남았는가" 는 목록이 바뀔 때마다
   * 다시 판단해야 한다. 목록이 갱신될 때마다 이 effect 가 새로 돌면서
   * 조건이 깨지면 타이머를 걸지 않는 식으로 자연스럽게 멈춘다.
   */
  useEffect(() => {
    const hasInProgress = documents.some((d) => IN_PROGRESS.includes(d.status));
    if (!hasInProgress) return;

    const timer = setInterval(() => void loadDocuments(), 2000);
    return () => clearInterval(timer);
  }, [documents, loadDocuments]);

  async function handleUpload(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;

    setUploading(true);
    setError(null);
    try {
      const created = await api.documents.upload(botId, file);
      // 업로드 직후 목록 앞에 붙인다 → 위 폴링 effect 가 pending 을 보고 자동으로 켜진다.
      setDocuments((prev) => [created, ...prev]);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "업로드하지 못했습니다.");
    } finally {
      setUploading(false);
      // 같은 파일을 다시 고를 수 있게 입력을 비운다.
      // 안 비우면 브라우저가 "값이 그대로" 라고 보고 onChange 를 안 쏜다.
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function handleDelete(documentId: string, filename: string) {
    // 되돌릴 수 없는 작업이라 확인을 받는다(문서를 지우면 청크도 함께 사라진다).
    if (!window.confirm(`"${filename}" 을(를) 삭제할까요? 되돌릴 수 없습니다.`)) return;

    setError(null);
    try {
      await api.documents.remove(documentId);
      setDocuments((prev) => prev.filter((d) => d.id !== documentId));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "삭제하지 못했습니다.");
    }
  }

  return (
    <>
      <PageHeader
        title="문서 관리"
        description="올린 문서만 답변의 근거가 됩니다. 문서에 없는 내용은 지어내지 않고 거절합니다."
      />

      <div className="mt-6 rounded-lg border border-dashed border-subtle p-6 text-center">
        <input
          ref={fileInputRef}
          type="file"
          onChange={handleUpload}
          disabled={uploading}
          accept=".pdf,.docx,.hwpx,.txt,.md"
          className="block w-full text-sm file:mr-3 file:rounded-md file:border-0 file:bg-accent file:px-4 file:py-2 file:text-sm file:font-medium file:text-white"
        />
        <p className="mt-3 text-xs text-muted">
          pdf · docx · hwpx · txt · md (20MB 이하) — 구버전 .hwp 는 .hwpx 로 저장한 뒤 올려주세요.
        </p>
        {uploading && <p className="mt-2 text-sm text-muted">올리는 중…</p>}
      </div>

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
        ) : documents.length === 0 ? (
          <p className="rounded-lg border border-subtle px-6 py-10 text-center text-sm text-muted">
            아직 올린 문서가 없습니다. 문서를 올려야 챗봇이 답할 수 있습니다.
          </p>
        ) : (
          <ul className="divide-y divide-subtle rounded-lg border border-subtle bg-surface">
            {documents.map((doc) => (
              <li key={doc.id} className="flex items-center gap-3 px-4 py-3">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{doc.filename}</p>
                  <p className="mt-0.5 text-xs text-muted">
                    {doc.status === "ready"
                      ? `${doc.charCount?.toLocaleString() ?? "?"}자 · ${doc.chunkCount ?? "?"}개 조각`
                      : /* 실패 사유는 서버가 한국어로 주므로 그대로 보여준다 */
                        doc.errorMessage ?? "처리 중입니다…"}
                  </p>
                </div>

                <StatusBadge status={doc.status} />

                <button
                  type="button"
                  onClick={() => handleDelete(doc.id, doc.filename)}
                  className="shrink-0 text-xs text-muted hover:text-red-600"
                >
                  삭제
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}

/**
 * 상태 뱃지.
 *
 * status 를 그대로 쓰지 않고 한국어로 바꾸는 이유: "pending" 은 개발자 언어다.
 * 서버가 나중에 새 상태를 추가하면 여기 없는 값이 올 수 있으므로,
 * 매핑에 없으면 원문을 그대로 띄운다 — 화면이 깨지는 것보다 낫다.
 */
function StatusBadge({ status }: { status: string }) {
  const label: Record<string, string> = {
    pending: "대기 중",
    processing: "처리 중",
    ready: "준비됨",
    failed: "실패",
  };
  const tone: Record<string, string> = {
    ready: "bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-300",
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
