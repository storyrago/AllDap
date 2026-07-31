import Link from "next/link";
import { PageHeader } from "@/components/PageHeader";
import { Placeholder } from "@/components/Placeholder";

export const metadata = {
  title: "내 봇 — AllDap",
};

/** 로컬 시드 봇 id (db/V1__init.sql). 뼈대 단계에서 봇 화면으로 들어가보기 위한 링크용. */
const SEED_BOT_ID = "00000000-0000-0000-0000-000000000001";

/**
 * `/dashboard` — PRD §8 "봇 카드(문서 수·주간 대화 수·최근 평가 점수), 생성 / 첫 방문 시 온보딩 안내"
 *
 * 호출할 Spring API:
 *   GET  /api/bots  → BotSummary[]  (api.bots.list)
 *   POST /api/bots  { name } → Bot  (api.bots.create)
 *
 * ⚠️ BotSummary 의 documentCount / weeklyConversationCount / latestFaithfulness 는
 *    bots 테이블에 없는 집계값이다. Spring 이 documents·conversations·eval_runs 를
 *    조인해서 만들어줘야 한다. W2에서 이 집계를 한 번에 내릴지 별도 API 로 뺄지 결정할 것.
 */
export default function DashboardPage() {
  return (
    <>
      <PageHeader
        title="내 봇"
        description="봇 단위로 문서와 대화가 완전히 격리됩니다. 다른 봇의 문서는 절대 검색되지 않습니다."
        actions={
          <button
            type="button"
            disabled
            className="rounded-md border border-subtle px-3 py-1.5 text-sm text-muted"
          >
            새 봇 만들기 (미구현)
          </button>
        }
      />

      <div className="space-y-4">
        <Placeholder title="봇 카드 목록" api="GET /api/bots">
          <p>카드 1장당 표시할 값 (PRD §8):</p>
          <ul className="list-inside list-disc">
            <li>봇 이름</li>
            <li>문서 수 (documentCount)</li>
            <li>주간 대화 수 (weeklyConversationCount)</li>
            <li>최근 평가 점수 (latestFaithfulness) — 평가 이력이 없으면 &ldquo;평가 전&rdquo;</li>
          </ul>
          <p>카드를 누르면 /bot/[botId]/documents 로 이동한다.</p>
        </Placeholder>

        <Placeholder title="첫 방문 온보딩 안내" api="GET /api/bots (결과가 빈 배열일 때)">
          <p>
            봇이 하나도 없을 때만 보여준다. PRD §4 Flow A: 봇 만들기 → 문서 올리기 →
            테스트 채팅 → 위젯 설치, 4단계 안내.
          </p>
        </Placeholder>

        <Placeholder title="새 봇 만들기 모달" api="POST /api/bots">
          <p>입력값은 이름 하나. publicKey 는 서버가 생성해서 내려준다.</p>
        </Placeholder>
      </div>

      {/* 뼈대 단계 전용 이동 링크.
          아직 봇 목록을 못 불러오므로 시드 봇으로 직접 들어가 화면을 확인한다.
          TODO(W2): GET /api/bots 가 붙으면 이 블록을 지울 것. */}
      <div className="mt-8 rounded-lg border border-subtle bg-surface p-4 text-sm">
        <p className="font-medium">개발용 바로가기</p>
        <p className="mt-1 text-muted">
          아직 목록 API 가 없어서, db/V1__init.sql 의 시드 봇으로 직접 들어갑니다.
        </p>
        <Link
          href={`/bot/${SEED_BOT_ID}/documents`}
          className="mt-2 inline-block text-accent hover:underline"
        >
          테스트 봇 열기 →
        </Link>
      </div>
    </>
  );
}
