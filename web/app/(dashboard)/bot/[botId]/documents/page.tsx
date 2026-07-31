import { PageHeader } from "@/components/PageHeader";
import { Placeholder } from "@/components/Placeholder";

export const metadata = {
  title: "문서 관리 — AllDap",
};

/**
 * `/bot/[botId]/documents` — PRD §8 "다중 업로드, 처리 상태(실패 시 사유), 삭제 / 상태 폴링"
 *
 * 호출할 Spring API:
 *   POST   /api/bots/{botId}/documents   multipart, 필드명 "file" → 202 DocumentItem
 *   GET    /api/bots/{botId}/documents   → DocumentItem[]
 *   DELETE /api/documents/{docId}        → 204
 *   → lib/api.ts 의 api.documents.upload / list / remove
 *
 * ★ 이 화면에서 꼭 이해해야 하는 것: 왜 폴링이 필요한가
 *   업로드 API 는 파일을 받자마자 202 로 돌아온다 (status: "pending").
 *   파싱→청킹→임베딩은 수십 초가 걸릴 수 있어서 HTTP 요청을 붙잡고 있으면 타임아웃이 난다.
 *   그래서 처리는 Python 이 백그라운드로 하고, 화면은 목록을 주기적으로 다시 불러
 *   pending → processing → ready(또는 failed) 로 바뀌는 걸 따라간다.
 *
 * TODO(W2): 이 페이지를 "use client" 로 바꾸고 아래를 구현할 것.
 *   - 드래그&드롭 + 다중 선택 업로드 (파일마다 api.documents.upload 를 따로 호출)
 *   - pending/processing 이 하나라도 있으면 2~3초 간격 폴링, 전부 끝나면 폴링 중단
 *   - failed 행은 errorMessage 를 그대로 보여준다 (한국어 안내가 이미 들어있다)
 */
export default function DocumentsPage() {
  return (
    <>
      <PageHeader
        title="문서 관리"
        description="PDF · DOCX · HWPX · TXT/MD 를 올릴 수 있습니다. 구버전 .hwp 는 지원하지 않습니다."
        actions={
          <button
            type="button"
            disabled
            className="rounded-md border border-subtle px-3 py-1.5 text-sm text-muted"
          >
            문서 올리기 (미구현)
          </button>
        }
      />

      <div className="space-y-4">
        <Placeholder
          title="업로드 영역 (드래그 앤 드롭 · 다중 선택)"
          api="POST /api/bots/{botId}/documents (multipart, 필드명 file)"
        >
          <p>
            제한: 파일당 20MB, 봇당 문서 30개 (PRD F-01 [가정]). 확장자와 MIME 을
            둘 다 검사한다 (PRD NFR 보안).
          </p>
          <p>
            응답은 202 이고 status 는 pending 이다. 즉 업로드 성공 ≠ 사용 가능.
          </p>
        </Placeholder>

        <Placeholder
          title="문서 목록 테이블"
          api="GET /api/bots/{botId}/documents (2~3초 폴링)"
        >
          <p>열: 파일명 / 형식 / 상태 / 글자 수 / 청크 수 / 삭제</p>
          <p>
            상태 배지: pending(대기) · processing(처리 중) · ready(사용 가능) ·
            failed(실패)
          </p>
          <p>
            failed 인 행은 errorMessage 를 그대로 노출한다. 예:
            &ldquo;구버전 .hwp 는 지원하지 않습니다. .hwpx 로 저장 후 올려주세요.&rdquo;
          </p>
        </Placeholder>

        <Placeholder title="삭제 확인" api="DELETE /api/documents/{docId}">
          <p>
            문서를 지우면 해당 청크도 함께 삭제된다 (DB 의 ON DELETE CASCADE).
            되돌릴 수 없으므로 확인 단계를 둔다.
          </p>
        </Placeholder>
      </div>
    </>
  );
}
