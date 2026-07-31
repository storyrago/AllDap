import { Placeholder } from "@/components/Placeholder";

export const metadata = {
  title: "문의하기",
  // 위젯은 검색엔진에 노출될 이유가 없다. 고객사 사이트 안에서만 쓰인다.
  robots: { index: false, follow: false },
};

/**
 * `/w/[publicKey]` — 엔드유저 임베드 위젯 (PRD F-04, §8 "익명 대화, 출처 표시, 피드백 / 모바일 최적화")
 *
 * ★ 이 화면만 인증이 없다.
 *   URL 의 publicKey(예: pk_local_dev)가 곧 봇 식별자다.
 *   대신 Spring 이 ① 허용 도메인(Origin) 검증 ② rate limit 으로 막는다.
 *   JWT 를 여기서 쓰면 안 된다 — 남의 사이트에 우리 토큰을 심는 꼴이 된다.
 *
 * 호출할 Spring API:
 *   GET  /api/w/{publicKey}/config → WidgetConfig  (api.widget.config)
 *   POST /api/w/{publicKey}/chat   { message, sessionId } → ChatResponse (api.widget.chat)
 *   POST /api/messages/{msgId}/feedback
 *   ※ 셋 다 인증 헤더 없이 호출한다.
 *
 * ⚠️ config 응답에는 내부 설정(systemPrompt 등)이 절대 포함되면 안 된다.
 *    이 화면은 누구나 볼 수 있으므로, 응답에 들어간 값은 곧 공개된 값이다.
 *
 * TODO(W2): 실제 대화 UI 구현 ("use client" 필요).
 *   - sessionId: 처음 열 때 crypto.randomUUID() 로 만들고 sessionStorage 에 보관
 *     (새로고침해도 같은 세션으로 이어지게. 최대 64자 제한 있음)
 *   - 모바일 우선 레이아웃. 위젯은 대부분 좁은 화면에서 열린다.
 *   - public/widget.js (플로팅 버튼 → 이 페이지를 iframe 으로 삽입) 는 아직 없다.
 */
export default async function WidgetPage({
  params,
}: {
  params: Promise<{ publicKey: string }>;
}) {
  // Next.js 16 에서 params 는 Promise 다. await 하지 않으면 값이 아니라 Promise 가 잡힌다.
  const { publicKey } = await params;

  return (
    <div className="mx-auto flex w-full max-w-md flex-1 flex-col px-4 py-6">
      <header className="border-b border-subtle pb-3">
        {/* TODO(W2): GET /api/w/{publicKey}/config 로 봇 이름·환영 문구를 가져와 채울 것.
            없는 publicKey 면 notFound() 로 404. */}
        <h1 className="text-base font-semibold">문의하기</h1>
        <p className="mt-1 font-mono text-[11px] text-muted">
          publicKey: {publicKey}
        </p>
      </header>

      <div className="mt-4 flex-1 space-y-3">
        <Placeholder title="환영 메시지" api="GET /api/w/{publicKey}/config">
          <p>WidgetConfig = {"{ botName, welcomeMessage, themeColor? }"}</p>
          <p>
            themeColor 는 아직 DB 에 컬럼이 없다 (settings 페이지 주석 참고).
          </p>
        </Placeholder>

        <Placeholder
          title="대화 영역 + 입력창"
          api="POST /api/w/{publicKey}/chat (인증 없음)"
        >
          <p>익명 사용자가 질문한다. 답변에는 출처(파일명)를 함께 표시한다.</p>
          <p>
            근거가 없으면 봇의 fallbackMessage 가 내려온다. 지어내지 않는 것이 이
            제품의 약속이다.
          </p>
        </Placeholder>

        <Placeholder title="👍 / 👎 피드백" api="POST /api/messages/{msgId}/feedback">
          <p>
            여기서 모인 👎 가 대화 로그와 품질 대시보드의 개선 재료가 된다.
          </p>
        </Placeholder>
      </div>

      <footer className="mt-4 border-t border-subtle pt-3 text-[11px] text-muted">
        AllDap 으로 만든 챗봇입니다.
      </footer>
    </div>
  );
}
