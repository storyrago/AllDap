package com.alldap.api.domain.eval.controller;

import com.alldap.api.domain.eval.dto.EvalQuestionResponse;
import com.alldap.api.domain.eval.dto.EvalResultResponse;
import com.alldap.api.domain.eval.dto.EvalRunResponse;
import com.alldap.api.domain.eval.dto.GenerateQuestionsRequest;
import com.alldap.api.domain.eval.dto.UnansweredSummaryResponse;
import com.alldap.api.domain.eval.service.EvalService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.UUID;

/**
 * 품질 평가 API (PRD §10.1 {@code /api/bots/{botId}/eval/*}). 인증 필요.
 *
 * <p><b>W3 이 이 프로젝트의 심장이다.</b> 평가 대시보드가 없으면 그냥 흔한 챗봇 빌더다.
 * 최종 산출물인 "검색 방식 before/after 비교표"가 이 API 위에서 만들어진다.
 *
 * <p><b>userId 는 {@code @AuthenticationPrincipal} 로만 받는다.</b> 쿼리 파라미터나 본문으로 받으면
 * 남의 id 를 적어 보내는 것만으로 격리가 무너진다. 소유권 확인은 전부 서비스가 하고,
 * <b>Python 을 부르기 전에</b> 끝난다 — Python 의 {@code /internal/*} 에는 인증이 없기 때문이다.
 */
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/bots/{botId}/eval")
public class EvalController {

    private final EvalService evalService;

    /**
     * GET /api/bots/{botId}/eval/questions — 테스트 질문 목록.
     *
     * <p>Python 을 부르지 않고 DB 를 직접 읽는다. {@code eval_questions} 는
     * "쓰기 = Python / 읽기 = Spring 도 허용" 테이블이다(AGENTS.md 테이블 소유권).
     */
    @GetMapping("/questions")
    public ResponseEntity<List<EvalQuestionResponse>> getQuestions(@AuthenticationPrincipal UUID userId,
                                                                   @PathVariable UUID botId) {
        return ResponseEntity.ok(evalService.findQuestions(userId, botId));
    }

    /**
     * POST /api/bots/{botId}/eval/questions/generate — 문서에서 테스트 질문 자동 생성.
     *
     * <p>경로 끝에 {@code /generate} 를 붙인 이유: 같은 {@code /questions} 에 POST 를 두면
     * "질문을 직접 하나 추가한다"와 구분되지 않는다. 나중에 수동 추가를 붙일 자리를 비워둔다.
     * (프론트 {@code web/lib/api.ts} 가 이미 이 경로를 가정하고 있다)
     *
     * <p>200 이다. 202 가 아닌 이유는 <b>동기 호출</b>이기 때문이다 —
     * {@code eval_questions} 에는 상태 컬럼이 없어 202 를 줘도 폴링할 대상이 없다.
     */
    @PostMapping("/questions/generate")
    public ResponseEntity<List<EvalQuestionResponse>> generateQuestions(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID botId,
            @Valid @RequestBody(required = false) GenerateQuestionsRequest request) {

        // 본문 없이 부를 수 있게 둔다. 화면에서 개수를 고르지 않고 "생성" 만 누르는 흐름이 기본이다.
        int count = request == null ? new GenerateQuestionsRequest(null).countOrDefault()
                                    : request.countOrDefault();
        return ResponseEntity.ok(evalService.generateQuestions(userId, botId, count));
    }

    /**
     * POST /api/bots/{botId}/eval/runs — 평가 실행 시작.
     *
     * <p><b>202 Accepted 다.</b> 요청을 접수했을 뿐 채점은 아직 끝나지 않았다.
     * 200 으로 답하면 프론트가 "다 됐다"고 읽고 상태 폴링을 하지 않는다(업로드와 같은 이유).
     * {@code eval_runs.status} 가 {@code running → completed|failed} 로 바뀌는 것을 폴링해야 한다.
     */
    @PostMapping("/runs")
    public ResponseEntity<EvalRunResponse> startRun(@AuthenticationPrincipal UUID userId,
                                                    @PathVariable UUID botId) {
        return ResponseEntity.accepted().body(evalService.startRun(userId, botId));
    }

    /**
     * GET /api/bots/{botId}/eval/runs — 평가 실행 이력 (최신순).
     *
     * <p>프론트가 이 목록을 폴링해 실행이 끝나는 것을 본다.
     * W4 의 before/after 비교표도 여기서 두 실행을 골라 만든다 — {@code config} 가 그 축이다.
     */
    @GetMapping("/runs")
    public ResponseEntity<List<EvalRunResponse>> getRuns(@AuthenticationPrincipal UUID userId,
                                                         @PathVariable UUID botId) {
        return ResponseEntity.ok(evalService.findRuns(userId, botId));
    }

    /**
     * GET /api/bots/{botId}/eval/runs/{runId}/results — 실행 1회의 질문별 채점 결과.
     *
     * <p>경로에 {@code botId} 가 함께 있는 이유는 <b>격리</b>다. {@code runId} 만으로 조회하면
     * 남의 실행 id 를 알아낸 사람이 그 결과를 볼 수 있다. 서비스가 두 값을 함께 쿼리에 넣는다.
     *
     * <p>점수 낮은 순 정렬은 <b>프론트가 한다</b>. 서버는 저장 순서(createdAt)로 주고,
     * 화면이 "점수 낮은 순 / 미채점 먼저" 처럼 목적에 맞게 정렬한다 —
     * 정렬 기준이 화면마다 다를 수 있어 서버에 못박지 않는다.
     */
    @GetMapping("/runs/{runId}/results")
    public ResponseEntity<List<EvalResultResponse>> getResults(@AuthenticationPrincipal UUID userId,
                                                               @PathVariable UUID botId,
                                                               @PathVariable UUID runId) {
        return ResponseEntity.ok(evalService.findResults(userId, botId, runId));
    }

    // TODO(W3): 미답변(fallback) 집계 API 경로를 확정할 것. 후보: GET /api/bots/{botId}/eval/unanswered
    //   ⚠️ 이 데이터는 eval_* 테이블에 없다. 실사용 로그(messages.is_fallback)를 집계해야 한다.
    //      즉 Python 이 아니라 Spring 이 만드는 값이다(MessageRepository TODO 참고).

    /**
     * GET /api/bots/{botId}/eval/unanswered — 봇이 거절한 질문 모음.
     *
     * <p>경로가 {@code /eval} 아래인 이유: 프론트({@code web/lib/api.ts})와 PRD 가 이미 이 주소를
     * 약속해뒀다. <b>화면은 "진단" 이지만 API 는 여기 산다</b> — 화면 배치와 API 경로가
     * 꼭 같아야 하는 것은 아니고, 굳이 옮기면 약속된 경로만 하나 깨진다.
     *
     * <p>LLM 을 부르지 않으므로 비용이 0 이고, 그래서 화면이 마음껏 다시 불러도 된다.
     *
     * @param limit 상한. 미답변이 수백 건이어도 관리자가 위에서부터 처리하므로
     *              전부 내려줄 이유가 없다. 응답 크기와 화면 렌더링을 함께 묶어둔다.
     */
    @GetMapping("/unanswered")
    public ResponseEntity<UnansweredSummaryResponse> getUnanswered(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID botId,
            @RequestParam(defaultValue = "50") int limit) {
        return ResponseEntity.ok(evalService.findUnanswered(userId, botId, Math.clamp(limit, 1, 200)));
    }
}
