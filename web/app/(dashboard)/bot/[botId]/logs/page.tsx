import { PageHeader } from "@/components/PageHeader";
import { Placeholder } from "@/components/Placeholder";

export const metadata = {
  title: "대화 로그 — AllDap",
};

/**
 * `/bot/[botId]/logs` — PRD §8 "세션별 열람, 필터(미답변/👎/기간)"
 *
 * 호출할 Spring API:
 *   GET /api/bots/{botId}/logs?onlyFallback&onlyThumbsDown&from&to&page&size
 *       → Paged<ConversationSummary>            (api.logs.list)
 *   GET /api/bots/{botId}/logs/{conversationId} → ChatMessage[]  (api.logs.messages)
 *
 * ⚠️ 두 번째 경로는 PRD §10.1 표에 없다. 세션 상세를 보려면 필요하므로
 *    W2에서 Spring 설계할 때 경로를 확정해야 한다. 여기 적은 건 제안일 뿐이다.
 *
 * 데이터 출처: conversations / messages 테이블. 둘 다 Spring 이 쓰기 소유자다.
 * (Python 은 대화 로그를 저장하지 않는다 — 아키텍처의 테이블 소유권 규칙)
 */
export default function LogsPage() {
  return (
    <>
      <PageHeader
        title="대화 로그"
        description="위젯에서 실제로 오간 대화입니다. 미답변과 👎 를 먼저 보면 무엇을 보강할지 바로 보입니다."
      />

      <div className="space-y-4">
        <Placeholder title="필터 바" api="GET /api/bots/{botId}/logs 의 쿼리 파라미터">
          <p>
            미답변만(onlyFallback) · 👎만(onlyThumbsDown) · 기간(from/to) ·
            채널(widget / test)
          </p>
          <p>
            기본값은 &ldquo;미답변만&rdquo; 을 켜두는 편이 낫다. 전체 로그를 처음부터 훑는 건
            아무도 안 한다.
          </p>
        </Placeholder>

        <Placeholder
          title="세션 목록"
          api="GET /api/bots/{botId}/logs → Paged<ConversationSummary>"
        >
          <p>행: 첫 질문 / 채널 / 메시지 수 / 미답변 포함 여부 / 시각</p>
          <p>
            ⚠️ 페이지네이션 응답 모양이 아직 미정이다. Spring Data 의 Page 를 그대로
            내리면 필드명이 content / totalElements / number 가 된다.
            lib/types.ts 의 Paged&lt;T&gt; 와 맞춰야 한다.
          </p>
        </Placeholder>

        <Placeholder
          title="세션 상세 (메시지 타임라인)"
          api="GET /api/bots/{botId}/logs/{conversationId} (경로 미확정)"
        >
          <p>
            user / assistant 를 번갈아 보여주고, assistant 메시지에는 출처(sources)와
            응답 시간(latencyMs), 피드백(👍/👎)을 함께 표시한다.
          </p>
          <p>
            fallback 된 메시지는 눈에 띄게 표시한다 — 이게 ⑤ 미답변 목록의 원재료다.
          </p>
        </Placeholder>
      </div>
    </>
  );
}
