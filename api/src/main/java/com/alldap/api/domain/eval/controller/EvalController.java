package com.alldap.api.domain.eval.controller;

import com.alldap.api.domain.eval.dto.EvalQuestionResponse;
import com.alldap.api.domain.eval.dto.EvalRunResponse;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.UUID;

/**
 * 품질 평가 API (PRD §10.1 {@code /api/bots/{botId}/eval/*}). 인증 필요.
 *
 * <p><b>⚠️ 이 컨트롤러는 W3 전까지 전부 미구현이다. 스텁이다.</b>
 * 이유는 Spring 쪽 사정이 아니라 <b>Python 에 {@code /internal/eval/*} 이 아직 없기 때문</b>이다
 * (PRD §10.2 — 해당 엔드포인트는 W3 에서 구현 예정).
 * 질문 자동 생성도 LLM-as-judge 채점도 Python 파이프라인이 해야 하는 일이라
 * Spring 이 먼저 만들 수 있는 게 사실상 없다.
 *
 * <p>그런데도 경로를 미리 잡아두는 이유: W3 이 이 프로젝트의 심장이고
 * (일정이 밀리면 위젯을 버리더라도 W3 은 지킨다), 프론트 화면 배치가
 * 이 경로를 전제로 진행되기 때문이다. 서비스 클래스는 만들지 않았다 —
 * 무엇을 호출할지 정해지지 않은 상태에서 서비스를 만들면 존재하지 않는 컨트랙트를 코드로 굳히게 된다.
 *
 * <p>조회 계열(질문 목록·실행 이력)은 eval_* 테이블을 Spring 이 읽어도 되므로
 * Python 없이도 W3 초반에 먼저 붙일 수 있다.
 */
@RestController
@RequestMapping("/api/bots/{botId}/eval")
public class EvalController {

    // TODO(W3): EvalService 를 주입할 것. 지금 만들지 않는 이유는 클래스 주석 참고.

    /**
     * GET /api/bots/{botId}/eval/questions — 테스트 질문 목록.
     *
     * <p>TODO(W3): 구현. eval_questions 는 Spring 이 읽어도 되는 테이블이라
     *   EvalQuestionRepository 조회만으로 가능하다. Python 호출이 필요 없다.
     */
    @GetMapping("/questions")
    public ResponseEntity<List<EvalQuestionResponse>> getQuestions(@PathVariable UUID botId) {
        throw new UnsupportedOperationException("EvalController.getQuestions 미구현 (W3)");
    }

    /**
     * POST /api/bots/{botId}/eval/questions — 문서에서 테스트 질문 자동 생성.
     *
     * <p>TODO(W3): Python 에 {@code POST /internal/eval/questions} 를 먼저 만들어야 한다.
     *   문서 청크를 골라 LLM 으로 "질문 + 기대 답변" 쌍을 뽑는 작업이므로 Spring 이 할 수 없다.
     *   생성에 시간이 걸리므로 문서 업로드처럼 202 + 폴링 구조가 될 가능성이 높다.
     */
    @PostMapping("/questions")
    public ResponseEntity<Void> generateQuestions(@PathVariable UUID botId) {
        throw new UnsupportedOperationException("EvalController.generateQuestions 미구현 (W3, Python 선행 필요)");
    }

    /**
     * POST /api/bots/{botId}/eval/runs — 평가 실행.
     *
     * <p>TODO(W3): Python 에 {@code POST /internal/eval/runs} 를 먼저 만들어야 한다.
     *   질문 수만큼 검색·생성·채점이 돌아가 수 분 걸릴 수 있으므로 동기 호출로 두면 안 된다.
     *   eval_runs.status(running → completed/failed)가 그 비동기 처리를 전제로 만들어진 컬럼이다.
     */
    @PostMapping("/runs")
    public ResponseEntity<EvalRunResponse> startRun(@PathVariable UUID botId) {
        throw new UnsupportedOperationException("EvalController.startRun 미구현 (W3, Python 선행 필요)");
    }

    /**
     * GET /api/bots/{botId}/eval/runs — 평가 이력.
     *
     * <p>TODO(W3): 구현. eval_runs 조회만으로 가능하다(Python 호출 불필요).
     *   W4 의 before/after 비교표가 이 목록 위에서 만들어진다.
     */
    @GetMapping("/runs")
    public ResponseEntity<List<EvalRunResponse>> getRuns(@PathVariable UUID botId) {
        throw new UnsupportedOperationException("EvalController.getRuns 미구현 (W3)");
    }

    // TODO(W3): 미답변(fallback) 집계 API 경로를 확정할 것. 후보: GET /api/bots/{botId}/eval/unanswered
    //   ⚠️ 이 데이터는 eval_* 테이블에 없다. 실사용 로그(messages.is_fallback)를 집계해야 한다.
    //      즉 Python 이 아니라 Spring 이 만드는 값이다(MessageRepository TODO 참고).
}
