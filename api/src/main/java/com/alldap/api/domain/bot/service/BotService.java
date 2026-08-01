package com.alldap.api.domain.bot.service;

import com.alldap.api.domain.bot.dto.BotResponse;
import com.alldap.api.domain.bot.dto.CreateBotRequest;
import com.alldap.api.domain.bot.dto.UpdateBotRequest;
import com.alldap.api.domain.bot.entity.Bot;
import com.alldap.api.domain.bot.repository.BotRepository;
import com.alldap.api.domain.user.entity.User;
import com.alldap.api.domain.user.repository.UserRepository;
import com.alldap.api.global.exception.ApiException;
import com.alldap.api.global.exception.ErrorCode;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.UUID;

/**
 * 봇 도메인 서비스.
 *
 * <p>모든 조회는 <b>반드시 소유자(userId)로 좁혀서</b> 한다.
 * botId 만으로 조회하면 남의 봇 id 를 아는 사람이 그 봇의 문서·로그를 볼 수 있다
 * (CLAUDE.md "bot_id 스코프 격리").
 */
@Slf4j
@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class BotService {

    private final BotRepository botRepository;
    private final UserRepository userRepository;

    public List<BotResponse> findMyBots(UUID userId) {
        return botRepository.findAllByUserIdOrderByCreatedAtDesc(userId).stream()
                .map(BotResponse::from)
                .toList();

        // TODO(W2 대시보드 슬라이스): PRD §8 의 봇 카드는 문서 수·주간 대화 수·최근 평가 점수까지 요구한다.
        //   지금은 붙일 화면이 없어 봇 자체만 내려준다. 집계를 넣을 때 봇마다 count 쿼리를 돌리면
        //   N+1 이 되므로 group by 한 번으로 가져와 조립할 것. (BotResponse 주석 참고)
    }

    public BotResponse findMyBot(UUID userId, UUID botId) {
        return BotResponse.from(findOwnedBot(userId, botId));
    }

    @Transactional
    public BotResponse createBot(UUID userId, CreateBotRequest request) {
        // getReferenceById(프록시)로 SELECT 를 아낄 수도 있지만 findById 로 실제 조회한다.
        // 토큰은 유효한데 그 사이 계정이 지워진 경우, 프록시를 쓰면 INSERT 단계의 FK 위반(500)이 되고
        // 여기서 걸러야 "다시 로그인하라"는 안내를 줄 수 있다.
        User owner = userRepository.findById(userId)
                .orElseThrow(() -> new ApiException(ErrorCode.INVALID_TOKEN));

        Bot bot = botRepository.save(Bot.create(owner, request.name().trim()));
        log.info("[createBot] 봇 생성 userId={} botId={}", userId, bot.getId());
        return BotResponse.from(bot);

        // publicKey UNIQUE 충돌 재시도는 넣지 않았다. 16바이트 난수라 충돌 확률이 무시할 수준이고,
        // 만에 하나 충돌하면 500 이 나가고 사용자가 다시 누르면 새 키로 성공한다.
        // 재시도 루프를 넣는 순간 "그 루프가 맞는지"를 검증할 방법이 없어진다.
    }

    @Transactional
    public BotResponse updateBot(UUID userId, UUID botId, UpdateBotRequest request) {
        Bot bot = findOwnedBot(userId, botId);
        // 변경 감지(dirty checking): 영속 상태의 엔티티를 고치면 트랜잭션 커밋 시
        // Hibernate 가 알아서 UPDATE 를 보낸다. botRepository.save() 를 부를 필요가 없다.
        bot.updateSettings(request.name(), request.systemPrompt(), request.welcomeMessage(),
                request.fallbackMessage(), request.allowedOrigins());
        return BotResponse.from(bot);
    }

    @Transactional
    public void deleteBot(UUID userId, UUID botId) {
        // ⚠️ 봇을 지우면 documents/chunks 가 DB 의 ON DELETE CASCADE 로 함께 사라진다.
        // chunks 는 Python 소유이므로, Spring 이 bots 를 지우는 것만으로 Python 데이터까지
        // 지워진다는 사실을 인지하고 있어야 한다. (별도 정리 호출은 필요 없다)
        botRepository.delete(findOwnedBot(userId, botId));
        log.info("[deleteBot] 봇 삭제 userId={} botId={}", userId, botId);
    }

    /**
     * 소유권까지 확인한 봇 조회. <b>이 클래스에서 봇을 가져오는 유일한 통로다.</b>
     *
     * <p>없는 봇과 남의 봇을 모두 404 로 답한다. 남의 봇을 403 으로 구분해주면
     * "이 id 의 봇이 존재한다"는 사실이 새어나가, 무작위 id 를 던져 남의 봇 목록을 뽑아낼 수 있다.
     * (ACCESS_DENIED 코드가 ErrorCode 에 있긴 하지만 여기서는 쓰지 않는 게 맞다)
     */
    private Bot findOwnedBot(UUID userId, UUID botId) {
        return botRepository.findByIdAndUserId(botId, userId)
                .orElseThrow(() -> new ApiException(ErrorCode.BOT_NOT_FOUND));
    }

    /**
     * 위젯 공개 API 전용 조회. 인증이 없으므로 publicKey 만으로 찾는다.
     *
     * <p>반환 타입을 엔티티로 둔 이유: 위젯 응답 DTO(WidgetConfigResponse)에는
     * systemPrompt 같은 내부 설정이 절대 들어가면 안 되는데,
     * 무엇을 노출할지 고르는 책임을 위젯 쪽 DTO 한 곳에 모으기 위해서다.
     */
    public Bot findByPublicKey(String publicKey) {
        return botRepository.findByPublicKey(publicKey)
                .orElseThrow(() -> new ApiException(ErrorCode.BOT_NOT_FOUND));
    }
}
