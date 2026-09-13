package com.alldap.api.domain.conflict.service;

import com.alldap.api.domain.bot.repository.BotRepository;
import com.alldap.api.domain.conflict.dto.ConflictResponse;
import com.alldap.api.domain.conflict.dto.ConflictScanResponse;
import com.alldap.api.global.client.AiServiceClient;
import com.alldap.api.global.exception.ApiException;
import com.alldap.api.global.exception.ErrorCode;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * 문서 간 사실 충돌 진단 서비스.
 *
 * <p><b>왜 이 기능이 있나:</b> RAG 는 "문서가 진리"라고 가정한다. 그런데 실제 사내 문서는
 * 서로 모순된다 — 구버전과 신버전이 같이 올라가 있으면 챗봇은 둘 중 하나를 골라
 * <b>자신 있게</b> 답하고 관리자는 틀린 줄도 모른다. 근거를 표시해도 소용없다:
 * 표시된 그 근거가 틀린 쪽일 수 있다. 환각 억제({@code NO_ANSWER}·{@code max_distance})는
 * "문서에 없는 것"을 막지만 <b>"문서에 둘 다 있는 것"</b>은 못 막는다.
 *
 * <h2>Spring 의 역할은 문지기 + 번역기다</h2>
 * 후보 선별도 판정도 전부 Python 이 한다. 여기서 하는 일은 (1) 요청자가 이 봇의 주인이
 * 맞는지 확인하고 (2) Python 에 넘기고 (3) snake_case 를 camelCase 로 바꿔 내려주는 것뿐이다.
 *
 * <h2>왜 DB 를 직접 읽지 않고 Python 을 부르나</h2>
 * {@code eval_*} 은 Spring 이 직접 SELECT 하지만 여기는 다르다. 충돌 목록은 단순 조회가 아니라
 * <b>청크 원문까지 끌어오는 4중 조인</b>이다(충돌 → 청크 A/B → 문서 A/B).
 * {@code chunks} 는 AGENTS.md 테이블 소유권상 <b>Spring 이 아예 건드리지 않는</b> 테이블이라,
 * 여기서 조인하면 그 규칙이 무너진다. 조인은 소유자인 Python 이 한다.
 *
 * <p>클래스에 {@code @Transactional} 을 걸지 않은 이유는 EvalService 와 같다 —
 * 주 작업이 DB 트랜잭션이 아니라 <b>수십 초 걸리는 외부 HTTP 호출</b>이다.
 * 트랜잭션 안에 넣으면 커넥션 풀(기본 10)이 말라 채팅·업로드까지 멈춘다.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ConflictService {

    private final BotRepository botRepository;
    private final AiServiceClient aiServiceClient;

    /** 문서끼리 어긋나는 곳을 훑는다. 동기이며 Python 이 판정 쌍 수를 상한으로 묶어 시간을 통제한다. */
    public ConflictScanResponse scan(Long userId, Long botId) {
        requireOwnedBot(userId, botId);
        ConflictScanResponse result = ConflictScanResponse.from(aiServiceClient.scanConflicts(botId));
        log.info("[scanConflicts] botId={} 후보={} 판정={} 모순={} 실패={}",
                botId, result.candidates(), result.judged(), result.conflicts(), result.failed());
        return result;
    }

    /** 충돌 목록. 기본은 관리자가 아직 안 본 것({@code open})만. */
    public List<ConflictResponse> findAll(Long userId, Long botId, String status) {
        requireOwnedBot(userId, botId);
        return aiServiceClient.listConflicts(botId, status).stream()
                .map(ConflictResponse::from)
                .toList();
    }

    /**
     * 충돌 1건의 상태 변경 (주로 오탐을 {@code ignored} 로 치우는 용도).
     *
     * <p>이 기능이 없으면 헛짚은 항목이 목록에 영원히 남고, 관리자는 화면 자체를 안 보게 된다 —
     * <b>기능이 없는 것과 같아진다.</b> 그래서 탐지와 함께 만들었다.
     */
    public ConflictResponse updateStatus(Long userId, Long botId, Long conflictId, String status) {
        requireOwnedBot(userId, botId);
        return ConflictResponse.from(aiServiceClient.updateConflictStatus(botId, conflictId, status));
    }

    /**
     * 이 봇이 요청자의 것인지 확인한다. <b>Python 을 부르기 전에 반드시 통과해야 하는 관문이다.</b>
     *
     * <p>Python 의 {@code /internal/*} 에는 인증이 없다. 요청이 거기 도달한 시점에 이미 샌 것이다.
     * 없는 봇과 남의 봇을 <b>모두 404</b> 로 답한다 — 403 으로 구분해주면 무작위 id 를 던져
     * 남의 봇 존재 여부를 훑을 수 있다.
     */
    private void requireOwnedBot(Long userId, Long botId) {
        botRepository.findByIdAndUserId(botId, userId)
                .orElseThrow(() -> new ApiException(ErrorCode.BOT_NOT_FOUND));
    }
}
