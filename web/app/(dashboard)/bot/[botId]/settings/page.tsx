import { PageHeader } from "@/components/PageHeader";
import { Placeholder } from "@/components/Placeholder";

export const metadata = {
  title: "봇 설정 — AllDap",
};

/**
 * `/bot/[botId]/settings` — PRD §8 "봇 문구·색상·허용 도메인, 임베드 코드 복사 / 코드 복사가 전환 포인트"
 *
 * 호출할 Spring API:
 *   GET    /api/bots/{botId}  → Bot           (api.bots.get)
 *   PATCH  /api/bots/{botId}  → Bot           (api.bots.update)
 *   DELETE /api/bots/{botId}                  (api.bots.remove)
 *
 * bots 테이블의 편집 가능한 컬럼: name, system_prompt, welcome_message,
 * fallback_message, allowed_origins
 */
export default function SettingsPage() {
  return (
    <>
      <PageHeader
        title="봇 설정"
        description="봇 문구와 임베드 코드를 관리합니다."
      />

      <div className="space-y-4">
        <Placeholder title="기본 정보" api="PATCH /api/bots/{botId}">
          <p>봇 이름(name)</p>
        </Placeholder>

        <Placeholder title="대화 문구" api="PATCH /api/bots/{botId}">
          <p>환영 문구(welcomeMessage) — 위젯이 열릴 때 먼저 띄우는 인사말</p>
          <p>
            거절 문구(fallbackMessage) — 근거를 못 찾았을 때 보여줄 문장.
            &ldquo;담당자에게 문의해주세요&rdquo; 처럼 다음 행동을 알려주는 문장이 좋다.
          </p>
        </Placeholder>

        {/*
          ★ 여기가 이 프로젝트에서 문서로 꼭 남겨야 하는 갭이다.
        */}
        <Placeholder title="시스템 프롬프트 (systemPrompt)" api="PATCH /api/bots/{botId}">
          <p>
            ⚠️ <strong>지금은 저장만 되고 답변에는 반영되지 않는다.</strong>
          </p>
          <p>
            이유: Python 의 POST /internal/chat 요청 본문이
            {" "}{"{ bot_id, message, session_id }"} 뿐이라 system_prompt 를 받을 자리가 없다
            (ai-service/app/schemas.py 의 ChatRequest).
          </p>
          <p>
            반면 fallbackMessage 는 반영할 수 있다. Python 이 is_fallback=true 를
            돌려주면 Spring 이 answer 를 봇의 fallbackMessage 로 치환하면 되기 때문.
          </p>
          <p>
            TODO: Python ChatRequest 에 system_prompt 를 추가하고 generator 프롬프트에
            끼워넣은 뒤, Spring 이 봇 설정을 실어 보내도록 할 것.
            그때까지 이 입력란에는 &ldquo;아직 반영되지 않습니다&rdquo; 안내를 반드시 붙일 것
            (사용자가 바꿨는데 아무 일도 안 일어나면 버그로 오해한다).
          </p>
        </Placeholder>

        <Placeholder title="허용 도메인 (allowedOrigins)" api="PATCH /api/bots/{botId}">
          <p>
            위젯을 설치할 사이트 주소 목록. 등록되지 않은 Origin 에서 온 위젯 요청은
            Spring 이 거절한다.
          </p>
          <p>
            비워두면 어디서나 호출 가능해진다 — 남이 우리 봇을 자기 사이트에 붙여
            LLM 비용을 태울 수 있다. 빈 값일 때 경고를 보여줄 것.
          </p>
        </Placeholder>

        <Placeholder title="브랜드 색상">
          <p>
            ⚠️ PRD 와 DB 의 불일치: PRD F-04 / §8 은 색상 커스텀을 요구하는데
            db/V1__init.sql 의 bots 테이블에는 색상 컬럼이 없다.
          </p>
          <p>
            TODO(W2): bots 에 theme_color 컬럼을 추가하거나, 색상 커스텀을 MVP 에서
            빼기로 결정할 것. 스키마 변경은 db/ 의 SQL 이 단일 진실 공급원이다.
          </p>
        </Placeholder>

        <Placeholder title="임베드 코드 복사 ★" api="GET /api/bots/{botId} 의 publicKey 사용">
          <p>
            PRD 는 이 버튼을 &ldquo;전환 포인트&rdquo;라고 부른다. 관리자의 기술 숙련도 상한이
            &ldquo;복사해서 붙여넣기&rdquo;이기 때문에, 설치는 스크립트 한 줄이어야 한다.
          </p>
          <p>
            보여줄 코드는 /w/{"{publicKey}"} 를 iframe 으로 띄우는 로더 스크립트다.
          </p>
          <p>
            TODO(W2): public/widget.js (플로팅 버튼 → iframe 삽입) 를 만들고,
            여기서 그 스크립트 태그 한 줄을 복사시키도록 할 것. 아직 없다.
          </p>
        </Placeholder>

        <Placeholder title="봇 삭제" api="DELETE /api/bots/{botId}">
          <p>
            봇을 지우면 문서·청크·대화·평가가 전부 연쇄 삭제된다 (ON DELETE CASCADE).
            봇 이름을 직접 입력해야 삭제되도록 할 것.
          </p>
        </Placeholder>
      </div>
    </>
  );
}
