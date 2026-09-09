package com.alldap.api.global.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 위젯 공개 API 설정. {@code application.yaml} 의 {@code app.widget.*} 를 바인딩한다.
 *
 * <p>숫자를 코드에 박지 않고 설정으로 뺀 이유: 이 값들은 <b>운영하면서 조정하게 되는</b> 종류다.
 * 실제 사용량을 보기 전까지는 어떤 값이 맞는지 알 수 없고, 값을 바꾸려고 재빌드하고 싶지 않다.
 *
 * @param chatPerMinute   같은 IP·같은 봇 기준 분당 채팅 허용 횟수.
 *                        채팅은 건당 LLM 비용이 들어 낮게 잡는다
 * @param configPerMinute 설정 조회 허용 횟수. 비용은 없지만 무제한이면
 *                        publicKey 를 무작위로 넣어 <b>존재하는 봇을 훑을 수</b> 있다
 * @param loginPerMinute  같은 IP 기준 분당 로그인 시도 허용 횟수.
 *                        <p>여기 있는 이유: 이 record 가 이미 "요청 수 제한 값들" 을 담고 있고,
 *                        값 하나 때문에 새 프로퍼티 클래스를 만들 이유가 없다.
 *                        (이름이 {@code app.widget} 인 것은 어색하지만, 프리픽스를 바꾸면
 *                        배포 환경변수까지 함께 바꿔야 해서 그 대가가 더 크다)
 * @param loginFailureLimit 같은 IP·같은 이메일 기준으로 허용하는 <b>연속 로그인 실패</b> 횟수.
 *                        <p>{@code loginPerMinute} 와 <b>세는 대상이 다르다.</b>
 *                        저쪽은 성공·실패를 가리지 않는 <b>요청 수</b>를, 이쪽은 <b>실패만</b> 센다.
 *                        저쪽만 있으면 한 IP 가 분당 한도만큼 <b>영원히</b> 추측을 이어갈 수 있다.
 *                        <p>윈도우(15분)는 설정이 아니라 {@code AuthService.FAILURE_WINDOW} 상수다.
 *                        {@code ErrorCode.TOO_MANY_LOGIN_FAILURES} 안내 문구가 그 값을 글자로 담고 있어,
 *                        설정으로 빼면 <b>안내와 실제가 어긋난 채 배포될 수 있다.</b>
 */
@ConfigurationProperties(prefix = "app.widget")
public record WidgetProperties(
        int chatPerMinute,
        int configPerMinute,
        int loginPerMinute,
        int loginFailureLimit
) {
}
