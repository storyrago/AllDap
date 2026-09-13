package com.alldap.api.domain.eval.controller;

import com.alldap.api.domain.eval.dto.EvalQuestionResponse;
import com.alldap.api.domain.eval.dto.EvalResultResponse;
import com.alldap.api.domain.eval.dto.EvalRunResponse;
import com.alldap.api.domain.eval.dto.GenerateQuestionsRequest;
import com.alldap.api.domain.eval.dto.UnansweredSummaryResponse;
import com.alldap.api.domain.eval.dto.UpdateEvalQuestionRequest;
import com.alldap.api.domain.eval.service.EvalService;
import com.alldap.api.global.exception.ApiException;
import com.alldap.api.global.exception.ErrorCode;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

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
@Tag(name = "품질 평가", description = "테스트 질문을 자동 생성해 답변 품질을 채점한다. 이 제품의 핵심 기능이다.")
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
    @Operation(summary = "테스트 질문 목록 조회")
    @GetMapping("/questions")
    public ResponseEntity<List<EvalQuestionResponse>> getQuestions(@AuthenticationPrincipal Long userId,
                                                                   @PathVariable Long botId) {
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
    @Operation(summary = "테스트 질문 자동 생성")
    @PostMapping("/questions/generate")
    public ResponseEntity<List<EvalQuestionResponse>> generateQuestions(
            @AuthenticationPrincipal Long userId,
            @PathVariable Long botId,
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
    @Operation(summary = "평가 실행 시작 (비동기)")
    @PostMapping("/runs")
    public ResponseEntity<EvalRunResponse> startRun(@AuthenticationPrincipal Long userId,
                                                    @PathVariable Long botId) {
        return ResponseEntity.accepted().body(evalService.startRun(userId, botId));
    }

    /**
     * GET /api/bots/{botId}/eval/runs — 평가 실행 이력 (최신순).
     *
     * <p>프론트가 이 목록을 폴링해 실행이 끝나는 것을 본다.
     * W4 의 before/after 비교표도 여기서 두 실행을 골라 만든다 — {@code config} 가 그 축이다.
     */
    @Operation(summary = "평가 실행 이력 조회")
    @GetMapping("/runs")
    public ResponseEntity<List<EvalRunResponse>> getRuns(@AuthenticationPrincipal Long userId,
                                                         @PathVariable Long botId) {
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
    @Operation(summary = "평가 실행의 질문별 채점 결과 조회")
    @GetMapping("/runs/{runId}/results")
    public ResponseEntity<List<EvalResultResponse>> getResults(@AuthenticationPrincipal Long userId,
                                                               @PathVariable Long botId,
                                                               @PathVariable Long runId) {
        return ResponseEntity.ok(evalService.findResults(userId, botId, runId));
    }

    /**
     * PATCH /api/bots/{botId}/eval/questions/{questionId} — 테스트 질문 수정.
     *
     * <p><b>왜 PUT 이 아니라 PATCH 인가.</b> PUT 은 "이 자원을 통째로 이 값으로 바꿔라" 라
     * 안 보낸 필드를 비우는 것이 맞는 해석이다. 여기서 필요한 것은 <b>부분 수정</b>이다 —
     * 질문 문장만 다듬고 정답은 그대로 두는 것이 가장 흔한 사용이다.
     *
     * <p>🔴 {@code groundTruth} 를 고치면 <b>과거 실행과 비교할 수 없게 된다</b>
     * (UpdateEvalQuestionRequest 주석 참고). 문항을 빼려면 {@code isActive=false} 가 안전하다.
     */
    @Operation(summary = "테스트 질문 수정")
    @PatchMapping("/questions/{questionId}")
    public ResponseEntity<EvalQuestionResponse> updateQuestion(
            @AuthenticationPrincipal Long userId,
            @PathVariable Long botId,
            @PathVariable Long questionId,
            @Valid @RequestBody UpdateEvalQuestionRequest request) {
        if (request.isEmpty()) {
            // 빈 요청을 200 으로 답하면 "고쳤다"는 오해를 준다.
            throw new ApiException(ErrorCode.INVALID_INPUT,
                    "고칠 항목을 하나 이상 보내주세요 (question, groundTruth, isActive).");
        }
        return ResponseEntity.ok(evalService.updateQuestion(userId, botId, questionId, request));
    }

    /**
     * GET /api/bots/{botId}/eval/unanswered — 봇이 거절한 질문 모음.
     *
     * <p><b>경로 확정 (2026-09-09).</b> 후보였던 이 주소를 그대로 굳혔다. 프론트
     * ({@code web/lib/api.ts})와 PRD 가 이미 이 주소를 약속해뒀고, 옮겨서 얻는 것이 없다.
     * <b>화면은 "진단" 이지만 API 는 {@code /eval} 아래 산다</b>: 화면 배치와 API 경로가
     * 꼭 같아야 하는 것은 아니고, 굳이 옮기면 이미 도는 경로만 하나 깨진다.
     * 데이터 출처가 {@code eval_*} 가 아니라 실사용 로그({@code messages})라는 점도 그대로 둔다.
     * 두 화면 모두 "이 봇의 품질" 을 묻는 자리이고, 출처가 다르다고 주소를 갈라야 할 이유는 없다.
     *
     * <h2>🔴 무엇이 목록에 들어가고 무엇이 빠지는가</h2>
     * 이 저장소는 <b>원인이 다른 두 사실을 같은 값으로 뭉개는</b> 버그를 반복해 냈다
     * (AGENTS.md 의 "낸 버그" 절).
     * 여기가 정확히 그 지뢰밭이라, 세 갈래를 못박아 둔다.
     * <ul>
     *   <li><b>{@code items} 에 들어간다</b>: user 질문 <b>다음</b>에 온 첫 assistant 메시지가
     *       {@code is_fallback = true} 인 것. "물어봤고 답했는데 문서에 없었다" = 진짜 미답변.
     *       같은 문장끼리 묶어 횟수를 센다(비슷한 질문 묶기는 임베딩이 필요해 Python 의 일이다).</li>
     *   <li><b>{@code failedTurns} 로 따로 센다</b>: 그 다음 assistant 메시지가 <b>아예 없는</b> 것.
     *       Python 이 죽었거나 타임아웃이라 "물어보지도 못했다" 이지 미답변이 아니다.
     *       섞으면 서버가 죽은 날이 문서가 부실한 날로 둔갑한다.</li>
     *   <li><b>어느 쪽에도 안 들어간다</b>: 정상 답변({@code is_fallback = false}),
     *       그리고 assistant 메시지 자체(집계는 {@code role = 'user'} 만 본다).</li>
     * </ul>
     * 관리자 테스트 채팅({@code channel = 'test'})은 <b>포함</b>한다. 거기서 난 fallback 도
     * "문서에 없다" 는 신호는 맞다. 화면이 그 사실을 안내한다.
     *
     * <p>LLM 을 부르지 않으므로 비용이 0 이고, 그래서 화면이 마음껏 다시 불러도 된다.
     *
     * @param limit 상한. 미답변이 수백 건이어도 관리자가 위에서부터 처리하므로
     *              전부 내려줄 이유가 없다. 응답 크기와 화면 렌더링을 함께 묶어둔다.
     */
    @Operation(summary = "미답변 질문 집계 조회")
    @GetMapping("/unanswered")
    public ResponseEntity<UnansweredSummaryResponse> getUnanswered(
            @AuthenticationPrincipal Long userId,
            @PathVariable Long botId,
            @RequestParam(defaultValue = "50") int limit) {
        return ResponseEntity.ok(evalService.findUnanswered(userId, botId, Math.clamp(limit, 1, 200)));
    }
}
