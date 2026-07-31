import { PageHeader } from "@/components/PageHeader";
import { MetricPlaceholder, Placeholder } from "@/components/Placeholder";

export const metadata = {
  title: "품질 대시보드 — AllDap",
};

/**
 * `/bot/[botId]/quality` — ★ PRD 가 "제품의 심장"이라 부르는 화면 (F-05, §8)
 *
 * 이 화면이 없으면 AllDap 은 그냥 흔한 챗봇 빌더다.
 * "만들어준다"가 아니라 "얼마나 잘 답하는지 숫자로 보여주고 개선 루프를 돌린다"가 차별점이다.
 *
 * PRD §8 이 요구하는 다섯 영역 (아래 순서대로 자리를 잡아뒀다):
 *   ① 점수 카드
 *   ② 평가 실행 버튼
 *   ③ 실행 이력 · 설정별 비교
 *   ④ 질문별 상세 (저점 정렬)
 *   ⑤ 미답변 목록 + 보강 제안
 *
 * 호출할 Spring API (전부 W3에서 만들어질 예정 — 지금은 존재하지 않는다):
 *   GET  /api/bots/{botId}/eval/questions
 *   POST /api/bots/{botId}/eval/questions/generate  { count }
 *   POST /api/bots/{botId}/eval/runs                → EvalRun (status: running)
 *   GET  /api/bots/{botId}/eval/runs                → EvalRun[]
 *   GET  /api/bots/{botId}/eval/runs/{runId}/results→ EvalResult[]
 *   GET  /api/bots/{botId}/eval/unanswered          → UnansweredQuestion[]
 *   → lib/api.ts 의 api.evaluation.*
 *
 * ⚠️ 현재 상태를 정확히 적어둔다 (거짓 완성 금지)
 *   - Python 에 /internal/eval/* 이 아직 없다. W3에서 구현 예정.
 *   - 따라서 Spring 의 /api/bots/{botId}/eval/* 도 없다.
 *   - 위 경로 이름은 PRD §10.1 의 "POST/GET /api/bots/{botId}/eval/*" 한 줄에서
 *     추정해 붙인 것이다. W3에서 실제 구현과 반드시 대조할 것.
 *   - "미답변 목록"은 eval_* 테이블이 아니라 messages(is_fallback=true) 집계에서 나온다.
 *     즉 Python 이 아니라 Spring 이 만들어야 하는 데이터다.
 */
export default function QualityPage() {
  return (
    <>
      <PageHeader
        title="품질 대시보드"
        description="테스트 질문을 실제 파이프라인에 태워 채점합니다. 검색 설정을 바꿔가며 점수를 비교하는 것이 목적입니다."
        actions={
          <button
            type="button"
            disabled
            className="rounded-md border border-subtle px-3 py-1.5 text-sm text-muted"
          >
            평가 실행 (미구현)
          </button>
        }
      />

      {/* ① 점수 카드 ─────────────────────────────────────────── */}
      <section className="mb-6">
        <h2 className="mb-2 text-sm font-semibold">① 최근 평가 점수</h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <MetricPlaceholder
            label="충실성 (faithfulness)"
            hint="답이 근거 문서와 일치하는가 · 0~1"
          />
          <MetricPlaceholder
            label="관련성 (relevancy)"
            hint="질문에 맞는 답인가 · 0~1"
          />
          <MetricPlaceholder
            label="응답률 (answered rate)"
            hint="fallback 하지 않고 답한 비율 · 0~1"
          />
        </div>
        <p className="mt-2 text-xs text-muted">
          출처: eval_runs 의 avg_faithfulness / avg_relevancy / answered_rate ·
          GET /api/bots/{"{botId}"}/eval/runs 의 최신 1건
        </p>
        <p className="mt-1 text-xs text-muted">
          ⚠️ 응답률은 높다고 무조건 좋은 게 아니다. 근거 없이 답하면 응답률은 올라가고
          충실성은 떨어진다. 두 값을 반드시 같이 봐야 한다.
        </p>
      </section>

      {/* ② 평가 실행 ─────────────────────────────────────────── */}
      <section className="mb-6">
        <h2 className="mb-2 text-sm font-semibold">② 평가 실행</h2>
        <div className="space-y-3">
          <Placeholder
            title="테스트셋 관리 (자동 생성 · 수정 · 비활성)"
            api="GET · POST /api/bots/{botId}/eval/questions[/generate]"
          >
            <p>
              문서 청크에서 표본을 뽑아 LLM 이 질문·정답(groundTruth) 쌍을 만든다.
              관리자가 이상한 질문을 끄거나(isActive=false) 고칠 수 있어야 한다.
            </p>
            <p>문서가 하나도 ready 가 아니면 생성 자체가 불가능하다 — 안내 문구 필요.</p>
          </Placeholder>

          <Placeholder
            title="실행 버튼 + 진행 상태"
            api="POST /api/bots/{botId}/eval/runs → status: running"
          >
            <p>
              업로드와 같은 이유로 비동기다. 즉시 running 상태의 run 이 돌아오고
              채점은 백그라운드에서 진행된다. 화면은 목록을 폴링해 completed 로 바뀌는 걸 본다.
            </p>
            <p>PRD 완료 기준: 실행 후 5분 내 리포트가 표시될 것.</p>
          </Placeholder>
        </div>
      </section>

      {/* ③ 실행 이력 · 설정별 비교 ──────────────────────────── */}
      <section className="mb-6">
        <h2 className="mb-2 text-sm font-semibold">③ 실행 이력 · 설정별 비교</h2>
        <Placeholder
          title="실행 이력 표 + 두 실행 나란히 비교"
          api="GET /api/bots/{botId}/eval/runs"
        >
          <p>
            열: 실행 시각 / 설정(topK · maxDistance · hybrid · reranker · model) /
            충실성 / 관련성 / 응답률 / 상태
          </p>
          <p>
            ★ 이 영역이 W4의 전부다. eval_runs.config 에 실행 시점 검색 설정이 함께
            저장되기 때문에 &ldquo;벡터 검색만 vs 하이브리드+리랭커&rdquo; 를 같은 테스트셋으로
            비교할 수 있다. config 가 없으면 before/after 비교가 성립하지 않는다 (PRD §9.3).
          </p>
          <p>
            체크박스로 두 실행을 골라 좌우로 나란히 놓고, 점수 차이를 +/- 로 표시한다.
          </p>
        </Placeholder>
      </section>

      {/* ④ 질문별 상세 (저점 정렬) ──────────────────────────── */}
      <section className="mb-6">
        <h2 className="mb-2 text-sm font-semibold">④ 질문별 상세 (점수 낮은 순)</h2>
        <Placeholder
          title="질문 단위 채점 결과"
          api="GET /api/bots/{botId}/eval/runs/{runId}/results"
        >
          <p>
            기본 정렬은 <strong>점수가 낮은 순</strong>이다. 잘된 답을 구경하는 화면이
            아니라 <strong>못한 답을 찾아 고치는 화면</strong>이기 때문이다.
          </p>
          <p>
            행을 펼치면: 질문 / 기대 답변(groundTruth) / 실제 생성된 답변 /
            검색된 청크(retrievedChunks) / 충실성 / 관련성
          </p>
          <p>
            검색된 청크를 같이 보여주는 이유: 점수가 낮을 때 원인이 &ldquo;검색이 엉뚱한 걸
            가져왔다&rdquo;인지 &ldquo;근거는 맞는데 생성이 틀렸다&rdquo;인지 구분해야 하기 때문.
            이 구분이 W4에서 무엇을 고칠지 결정한다.
          </p>
        </Placeholder>
      </section>

      {/* ⑤ 미답변 목록 + 보강 제안 ──────────────────────────── */}
      <section>
        <h2 className="mb-2 text-sm font-semibold">⑤ 미답변 목록 + 보강 제안</h2>
        <Placeholder
          title="실사용 중 fallback 된 질문들"
          api="GET /api/bots/{botId}/eval/unanswered (경로 미확정)"
        >
          <p>
            ④가 <em>테스트셋</em> 기준이라면 ⑤는 <em>실사용</em> 기준이다.
            엔드유저가 실제로 물었는데 답하지 못한 질문 목록.
          </p>
          <p>
            열: 질문(비슷한 것끼리 묶은 대표 문장) / 횟수 / 마지막 질문 시각 / 보강 제안
          </p>
          <p>
            ⚠️ 데이터 출처가 다르다. 이 목록은 eval_* 테이블이 아니라
            messages(is_fallback = true) 에서 나온다. Spring 이 집계해야 한다.
          </p>
          <p>
            TODO(W3): 비슷한 질문 묶기(클러스터링) 방식과 &ldquo;보강 제안&rdquo; 문장을 누가
            생성할지 정할 것. 제안 생성은 LLM 호출이 필요하다.
          </p>
        </Placeholder>
      </section>
    </>
  );
}
