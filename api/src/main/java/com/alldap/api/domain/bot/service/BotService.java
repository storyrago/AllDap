package com.alldap.api.domain.bot.service;

import com.alldap.api.domain.bot.dto.BotResponse;
import com.alldap.api.domain.bot.dto.CreateBotRequest;
import com.alldap.api.domain.bot.dto.UpdateBotRequest;
import com.alldap.api.domain.bot.entity.Bot;
import com.alldap.api.domain.bot.repository.BotRepository;
import com.alldap.api.domain.user.repository.UserRepository;
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
        // TODO(W2): 구현. botRepository.findAllByUserIdOrderByCreatedAtDesc(userId) 를 DTO 로 변환.
        throw new UnsupportedOperationException("BotService.findMyBots 미구현 (W2)");
    }

    public BotResponse findMyBot(UUID userId, UUID botId) {
        // TODO(W2): 구현. findByIdAndUserId 로 조회하고 없으면 ApiException(BOT_NOT_FOUND).
        //   "남의 봇"과 "없는 봇"을 모두 404 로 답한다 —
        //   403 으로 구분해주면 봇 id 의 존재 여부가 새어나간다.
        throw new UnsupportedOperationException("BotService.findMyBot 미구현 (W2)");
    }

    @Transactional
    public BotResponse createBot(UUID userId, CreateBotRequest request) {
        // TODO(W2): 구현. userRepository 로 소유자를 찾아 Bot.create(owner, name) 로 생성.
        //   publicKey 는 랜덤이라 UNIQUE 충돌 확률이 사실상 0 이지만,
        //   충돌 시 DataIntegrityViolationException 을 잡아 재시도할지 결정할 것.
        throw new UnsupportedOperationException("BotService.createBot 미구현 (W2)");
    }

    @Transactional
    public BotResponse updateBot(UUID userId, UUID botId, UpdateBotRequest request) {
        // TODO(W2): 구현. 부분 수정이므로 null 이 아닌 필드만 반영한다.
        //   Bot 엔티티에 의도가 드러나는 도메인 메서드를 먼저 추가할 것(@Setter 금지).
        throw new UnsupportedOperationException("BotService.updateBot 미구현 (W2)");
    }

    @Transactional
    public void deleteBot(UUID userId, UUID botId) {
        // TODO(W2): 구현.
        //   ⚠️ 봇을 지우면 documents/chunks 가 DB 의 ON DELETE CASCADE 로 함께 사라진다.
        //   chunks 는 Python 소유이므로, Spring 이 bots 를 지우는 것만으로 Python 데이터까지
        //   지워진다는 사실을 인지하고 있어야 한다. (별도 정리 호출은 필요 없다)
        throw new UnsupportedOperationException("BotService.deleteBot 미구현 (W2)");
    }

    /**
     * 위젯 공개 API 전용 조회. 인증이 없으므로 publicKey 만으로 찾는다.
     *
     * <p>반환 타입을 엔티티로 둔 이유: 위젯 응답 DTO(WidgetConfigResponse)에는
     * systemPrompt 같은 내부 설정이 절대 들어가면 안 되는데,
     * 무엇을 노출할지 고르는 책임을 위젯 쪽 DTO 한 곳에 모으기 위해서다.
     */
    public Bot findByPublicKey(String publicKey) {
        // TODO(W2): 구현. 없으면 ApiException(BOT_NOT_FOUND).
        throw new UnsupportedOperationException("BotService.findByPublicKey 미구현 (W2)");
    }
}
