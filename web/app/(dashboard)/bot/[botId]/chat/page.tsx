import { PageHeader } from "@/components/PageHeader";
import { Placeholder } from "@/components/Placeholder";

export const metadata = {
  title: "테스트 채팅 — AllDap",
};

/**
 * `/bot/[botId]/chat` — PRD §8 "답변 + 출처 카드(클릭 → 근거 미리보기), 피드백 / 위젯 공개 전 검수용"
 *
 * 호출할 Spring API:
 *   POST /api/bots/{botId}/chat  { message, sessionId } → ChatResponse
 *   POST /api/messages/{msgId}/feedback  { value: 1 | -1 }
 *   → lib/api.ts 의 api.chat.send / api.chat.feedback
 *
 * ★ 이 화면의 존재 이유 (PRD F-03)
 *   위젯을 외부에 공개하기 전에 관리자가 직접 물어보며 검수하는 자리다.
 *   특히 "문서에 없는 질문"을 던졌을 때 isFallback 이 true 로 오는지 확인하는 게 핵심이다.
 *   W1 완료 조건: 문서에 없는 질문 10개 중 8개 이상이 fallback 되어야 한다.
 *
 * ⚠️ 알려진 갭 (숨기지 말 것)
 *   Python 의 POST /internal/chat 은 봇의 systemPrompt / fallbackMessage 를 받지 않는다.
 *   따라서:
 *     - fallbackMessage : Spring 이 isFallback=true 를 받은 뒤 answer 를 봇 문구로 치환한다 (가능)
 *     - systemPrompt    : Python 을 고치기 전까지 답변에 반영되지 않는다 (불가)
 *   설정 화면에서 시스템 프롬프트를 바꿔도 이 화면의 답변은 달라지지 않는다.
 *
 * TODO(W2): "use client" 로 바꾸고 아래를 구현할 것.
 *   - 메시지 목록 상태(useState) + 입력창. sessionId 는 페이지 진입 시 crypto.randomUUID() 로 한 번 만든다.
 *   - 전송 중 로딩 표시. p95 5초까지 걸릴 수 있으므로(PRD NFR) 대기 UI 가 반드시 필요하다.
 *   - 답변 아래에 출처 카드(filename + score) 를 깔고, 클릭하면 preview(앞 200자)를 펼친다.
 */
export default function ChatPage() {
  return (
    <>
      <PageHeader
        title="테스트 채팅"
        description="위젯을 공개하기 전, 문서에 없는 질문을 던져 봇이 제대로 '모른다'고 답하는지 확인하세요."
      />

      <div className="space-y-4">
        <Placeholder
          title="대화 영역 (질문 · 답변 말풍선)"
          api="POST /api/bots/{botId}/chat { message, sessionId }"
        >
          <p>message 는 1~2000자 (Python 쪽 제약), sessionId 는 최대 64자.</p>
          <p>
            응답: {"{ answer, sources[], isFallback, latencyMs }"} — latencyMs 는
            개발 중 성능 감을 잡는 데 쓰이므로 화면 구석에 작게 표시한다.
          </p>
        </Placeholder>

        <Placeholder title="출처 카드 (클릭 시 근거 원문 미리보기)">
          <p>
            Source = {"{ chunkId, documentId, filename, score, preview }"}. score 는
            0~1 이며 1에 가까울수록 관련성이 높다(1 − 코사인거리).
          </p>
          <p>preview 는 청크 본문 앞 200자다. 전체 원문 조회 API 는 아직 없다.</p>
        </Placeholder>

        <Placeholder
          title="fallback(미답변) 표시"
          api="응답의 isFallback === true"
        >
          <p>
            근거를 못 찾은 답변은 일반 답변과 시각적으로 구분한다. 이게 제품의 핵심
            가치이므로 &ldquo;실패&rdquo;처럼 보이게 하지 말고 &ldquo;정직하게 거절함&rdquo;으로 보이게 할 것.
          </p>
        </Placeholder>

        <Placeholder
          title="👍 / 👎 피드백 버튼"
          api="POST /api/messages/{msgId}/feedback"
        >
          <p>
            ⚠️ 이걸 붙이려면 채팅 응답에 messageId 가 있어야 한다. Python 은 이 값을
            모르고, messages 행을 만드는 건 Spring 이다.
          </p>
          <p>TODO(W2): Spring ChatResponse DTO 에 messageId 를 포함시킬 것.</p>
        </Placeholder>
      </div>
    </>
  );
}
