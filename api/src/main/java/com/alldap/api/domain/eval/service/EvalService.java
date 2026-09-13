package com.alldap.api.domain.eval.service;

import com.alldap.api.domain.bot.repository.BotRepository;
import com.alldap.api.domain.chat.repository.MessageRepository;
import com.alldap.api.domain.eval.dto.EvalQuestionResponse;
import com.alldap.api.domain.eval.dto.EvalResultResponse;
import com.alldap.api.domain.eval.dto.EvalRetrievedChunkResponse;
import com.alldap.api.domain.eval.dto.EvalRunResponse;
import com.alldap.api.domain.eval.dto.UpdateEvalQuestionRequest;
import com.alldap.api.domain.eval.dto.UnansweredQuestionResponse;
import com.alldap.api.domain.eval.dto.UnansweredSummaryResponse;
import com.alldap.api.domain.eval.repository.EvalQuestionRepository;
import com.alldap.api.domain.eval.entity.EvalResult;
import com.alldap.api.domain.eval.repository.EvalResultRepository;
import com.alldap.api.domain.eval.repository.EvalRunRepository;
import com.alldap.api.global.client.AiServiceClient;
import com.alldap.api.global.client.dto.AiUpdateEvalQuestionRequest;
import com.alldap.api.global.client.dto.AiEvalRunResponse;
import com.alldap.api.global.exception.ApiException;
import com.alldap.api.global.exception.ErrorCode;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.ObjectMapper;

import java.util.List;

/**
 * 품질 평가 서비스 (W3).
 *
 * <p><b>Spring 의 역할은 문지기 + 번역기다.</b> 질문 생성도 채점도 전부 Python 이 한다.
 * 여기서 하는 일은 (1) 요청자가 이 봇의 주인이 맞는지 확인하고 (2) Python 에 넘기거나
 * DB 를 읽고 (3) snake_case 를 camelCase 로 바꿔 내려주는 것뿐이다.
 *
 * <h2>쓰기는 Python, 읽기는 Spring</h2>
 * {@code eval_*} 테이블의 쓰기 소유자는 Python 이다(AGENTS.md 테이블 소유권).
 * 그래서 이 서비스는 리포지토리로 <b>SELECT 만</b> 한다. save/delete 를 부르지 않는다.
 *
 * <p>조회를 Python 호출이 아니라 DB 직접 읽기로 한 이유는 문서 목록과 같다:
 * <ul>
 *   <li>실행 이력·질문 목록은 <b>폴링 대상</b>이라 호출이 잦다. Python 이 죽었다고
 *       목록까지 503 이 되면 사용자는 "내 평가 기록이 사라졌나" 싶고, 죽은 서비스를 계속 두드린다.</li>
 *   <li>한 번 저장된 뒤로는 Python 이 다시 손대지 않는 값이라 DB 가 곧 최신이다.</li>
 * </ul>
 *
 * <p>클래스에 {@code @Transactional} 을 걸지 않은 이유: 주 작업이 DB 트랜잭션이 아니라
 * <b>외부 HTTP 호출</b>이다. 질문 생성은 수십 초 걸릴 수 있는데 트랜잭션 안에 넣으면
 * 그동안 DB 커넥션이 묶여 풀이 마른다. 조회 메서드에만 개별로 붙인다.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class EvalService {

    private final AiServiceClient aiServiceClient;
    private final BotRepository botRepository;
    private final MessageRepository messageRepository;
    private final EvalQuestionRepository evalQuestionRepository;
    private final EvalRunRepository evalRunRepository;
    private final EvalResultRepository evalResultRepository;

    /** config(JSONB 문자열)를 camelCase 객체로 바꾸는 데만 쓴다. Boot 4 가 자동 구성하는 Jackson 3 매퍼다. */
    private final ObjectMapper objectMapper;

    /**
     * 테스트 질문 목록. <b>비활성(isActive=false)도 함께 준다</b> —
     * 관리자가 화면에서 껐다 켜야 하므로 꺼진 질문이 안 보이면 다시 켤 방법이 없다.
     */
    @Transactional(readOnly = true)
    public List<EvalQuestionResponse> findQuestions(Long userId, Long botId) {
        requireOwnedBot(userId, botId);
        return evalQuestionRepository.findAllByBotIdOrderByCreatedAtDesc(botId).stream()
                .map(EvalQuestionResponse::from)
                .toList();
    }

    /**
     * 문서 청크에서 테스트 질문·정답 쌍을 자동 생성 → Python 에 위임.
     *
     * <p>동기 호출이다. Python 이 {@code count} 상한으로 응답 시간을 통제한다
     * (자세한 이유는 {@code AiServiceClient.generateEvalQuestions} 주석).
     *
     * <p>재호출하면 <b>기존 질문은 그대로 두고 새 것만 더한다.</b> 관리자가 고쳐둔 질문을
     * 날리지 않기 위해서다. 중복 방지는 Python 의 표본 SQL 이 한다.
     */
    public List<EvalQuestionResponse> generateQuestions(Long userId, Long botId, int count) {
        requireOwnedBot(userId, botId);

        List<EvalQuestionResponse> created = aiServiceClient.generateEvalQuestions(botId, count).stream()
                .map(EvalQuestionResponse::from)
                .toList();

        log.info("[eval] 테스트 질문 생성 userId={} botId={} 요청={} 생성={}",
                userId, botId, count, created.size());
        return created;
    }

    /**
     * 평가 실행 시작 → Python 에 위임. 즉시 {@code running} 상태의 실행이 돌아온다.
     *
     * <p>채점은 백그라운드에서 돌아가므로 프론트는 {@link #findRuns} 를 폴링해
     * {@code status} 가 {@code completed} 로 바뀌는 것을 봐야 한다.
     * {@code eval_runs.status} 가 있어서 이 구조가 성립한다 —
     * 질문 생성이 동기인 것도 같은 이유(거긴 상태 컬럼이 없다)의 뒷면이다.
     */
    public EvalRunResponse startRun(Long userId, Long botId) {
        requireOwnedBot(userId, botId);

        AiEvalRunResponse run = aiServiceClient.startEvalRun(botId);
        log.info("[eval] 평가 실행 시작 userId={} botId={} runId={} status={}",
                userId, botId, run.id(), run.status());
        return EvalRunResponse.from(run, objectMapper);
    }

    /**
     * 평가 실행 이력 (최신순). <b>W4 의 before/after 비교표가 이 목록 위에서 만들어진다.</b>
     * 두 실행을 골라 나란히 놓을 수 있는 건 각 실행이 {@code config} 를 함께 들고 있기 때문이다.
     */
    @Transactional(readOnly = true)
    public List<EvalRunResponse> findRuns(Long userId, Long botId) {
        requireOwnedBot(userId, botId);
        return evalRunRepository.findAllByBotIdOrderByCreatedAtDesc(botId).stream()
                .map(run -> EvalRunResponse.from(run, objectMapper))
                .toList();
    }

    /**
     * 실행 1회의 질문별 채점 결과.
     *
     * <p><b>runId 를 botId 와 함께 조회하는 것이 격리의 핵심이다.</b>
     * {@code findById(runId)} 로 찾고 나서 소유자를 비교하는 방식이면,
     * 검사를 빠뜨려도 컴파일이 통과한다. 쿼리에 못박으면 빠뜨릴 수가 없다
     * (봇 조회의 {@code findByIdAndUserId} 와 같은 방식).
     *
     * <p>남의 실행은 403 이 아니라 <b>404</b> 다. 403 은 "그 실행은 존재한다"를 알려주는 셈이라
     * 아무 번호나 던져 남의 데이터 존재 여부를 훑을 수 있다.
     */
    @Transactional(readOnly = true)
    public List<EvalResultResponse> findResults(Long userId, Long botId, Long runId) {
        requireOwnedBot(userId, botId);

        evalRunRepository.findByIdAndBotId(runId, botId)
                .orElseThrow(() -> new ApiException(ErrorCode.RESOURCE_NOT_FOUND,
                        "해당 평가 실행을 찾을 수 없습니다."));

        return evalResultRepository.findAllByRunIdOrderByCreatedAtAsc(runId).stream()
                .map(r -> EvalResultResponse.from(r, parseChunks(r)))
                .toList();
    }

    /**
     * {@code eval_results.retrieved_chunks}(JSONB 문자열) → DTO 목록.
     *
     * <p><b>실패해도 예외를 던지지 않는다.</b> 결과 한 건의 JSON 이 깨졌다고
     * 리포트 전체가 500 이 되면 안 된다 — 점수는 멀쩡히 있는데 화면이 통째로 안 뜨는 게 더 나쁘다.
     * 빈 목록을 돌려주면 "근거를 못 보여줄 뿐" 나머지는 다 보인다.
     * ({@code ConversationLogService.parseSources} 와 같은 판단)
     */
    private List<EvalRetrievedChunkResponse> parseChunks(EvalResult result) {
        String json = result.getRetrievedChunks();
        if (json == null || json.isBlank()) {
            return List.of();
        }
        try {
            return objectMapper.readValue(json, new TypeReference<List<EvalRetrievedChunkResponse>>() {
            });
        } catch (RuntimeException e) {
            log.warn("[eval] retrieved_chunks JSON 파싱 실패 — resultId={} 는 근거 없이 내려보낸다.",
                    result.getId(), e);
            return List.of();
        }
    }

    /**
     * 테스트 질문 1건 수정. 보낸 필드만 바뀐다.
     *
     * <p>Python 으로 위임한다 — {@code eval_*} 는 Python 소유 테이블이다(AiServiceClient 주석).
     * 소유권 확인은 <b>Python 을 부르기 전에</b> 한다. {@code /internal/*} 에는 인증이 없어서,
     * 요청이 거기 도달한 시점에 이미 샌 것이다.
     */
    public EvalQuestionResponse updateQuestion(Long userId, Long botId, Long questionId,
                                               UpdateEvalQuestionRequest request) {
        requireOwnedBot(userId, botId);

        EvalQuestionResponse updated = EvalQuestionResponse.from(
                aiServiceClient.updateEvalQuestion(botId, questionId,
                        new AiUpdateEvalQuestionRequest(
                                request.question(), request.groundTruth(), request.isActive())));

        log.info("[eval] 테스트 질문 수정 userId={} botId={} questionId={} 바꾼항목={}",
                userId, botId, questionId,
                (request.question() != null ? "question " : "")
                        + (request.groundTruth() != null ? "ground_truth " : "")
                        + (request.isActive() != null ? "is_active" : ""));
        return updated;
    }

    /**
     * <b>미답변 질문 집계.</b> 봇이 근거를 못 찾아 거절한 질문들을 자주 물어본 순으로 준다.
     *
     * <p>Python 을 부르지 않는다 — {@code conversations}·{@code messages} 는
     * <b>Spring 소유</b> 테이블이다(AGENTS.md 테이블 소유권). 문서 모순 진단이 Python 을
     * 거치는 것과 정반대인데, 이유도 정반대다: 거기는 {@code chunks} 가 Python 소유였다.
     *
     * <p>🔴 <b>fallback 과 "답변 행 없음" 을 갈라서 센다.</b>
     * 전자는 "물어봤는데 문서에 없었다"(진짜 미답변), 후자는 "우리 인프라가 실패해
     * 물어보지도 못했다" 이다. 합치면 <b>서버가 죽은 날이 문서가 부실한 날로 둔갑한다.</b>
     *
     * <p>LLM 을 부르지 않으므로 <b>비용이 0</b> 이다. 목록을 여는 것만으로 돈이 나가면 안 된다.
     * ({@code suggestion} 이 항상 null 인 이유이기도 하다)
     */
    public UnansweredSummaryResponse findUnanswered(Long userId, Long botId, int limit) {
        requireOwnedBot(userId, botId);
        List<UnansweredQuestionResponse> items = messageRepository.aggregateUnanswered(botId, limit)
                .stream()
                .map(UnansweredQuestionResponse::from)
                .toList();
        return new UnansweredSummaryResponse(items, messageRepository.countFailedTurns(botId));
    }

    /**
     * 이 봇이 요청자의 것인지 확인한다. <b>Python 을 부르기 전에 반드시 통과해야 하는 관문이다.</b>
     *
     * <p>Python 의 {@code /internal/*} 에는 인증이 없다. 요청이 거기 도달한 시점에 이미 샌 것이므로,
     * 테스트도 "404 가 났다"가 아니라 <b>"요청이 Python 까지 가지 않았다"</b>를 확인해야 한다.
     *
     * <p>없는 봇과 남의 봇을 <b>모두 404</b> 로 답한다. 403 으로 구분해주면
     * 무작위 id 를 던져 남의 봇 존재 여부를 알아낼 수 있다.
     */
    private void requireOwnedBot(Long userId, Long botId) {
        botRepository.findByIdAndUserId(botId, userId)
                .orElseThrow(() -> new ApiException(ErrorCode.BOT_NOT_FOUND));
    }
}
