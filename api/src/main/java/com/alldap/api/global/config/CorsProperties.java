package com.alldap.api.global.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.util.List;

/**
 * CORS 설정. {@code application.yaml} 의 {@code app.cors.*} 를 바인딩한다.
 *
 * <p><b>왜 설정으로 빼는가.</b> 허용 오리진은 환경마다 다르다
 * (로컬 {@code http://localhost:3000} / 운영 {@code https://…}).
 * 코드에 박아두면 배포할 때마다 코드를 고쳐야 하고, 무엇보다
 * <b>운영 도메인이 소스에 남는다</b>. 환경변수로 빼면 환경별 값이 코드 밖에 있게 된다.
 *
 * @param allowedOrigins 관리자 화면(Next.js)이 떠 있는 오리진 목록.
 *                       {@code CORS_ALLOWED_ORIGINS} 환경변수에 쉼표로 구분해 여러 개를 줄 수 있다
 *                       (스프링이 쉼표 문자열을 List 로 바인딩해준다).
 *                       ⚠️ 스킴·호스트·포트가 <b>정확히</b> 일치해야 한다.
 *                       {@code http://localhost:3000} 과 {@code http://127.0.0.1:3000} 은 다른 오리진이다.
 */
@ConfigurationProperties(prefix = "app.cors")
public record CorsProperties(
        List<String> allowedOrigins
) {

    /**
     * 치환되지 않은 스프링 플레이스홀더({@code ${...}})를 잡아내는 패턴.
     *
     * <p><b>이게 왜 필요한가 — 스프링의 함정이다.</b>
     * {@code @Value} 는 {@code ${VAR}} 를 해석하지 못하면 예외를 던지지만,
     * <b>{@code @ConfigurationProperties} 는 조용히 리터럴 문자열로 바인딩한다</b>
     * (내부적으로 {@code resolveRequiredPlaceholders} 가 아니라 {@code resolvePlaceholders} 를 쓴다).
     *
     * <p>그래서 {@code CORS_ALLOWED_ORIGINS} 없이 운영에 뜨면
     * {@code allowedOrigins = ["${CORS_ALLOWED_ORIGINS}"]} 가 되어 원소가 1개이므로
     * {@code isEmpty()} 검사를 <b>통과해버린다</b>. 기동은 성공하고, 관리자 화면만 조용히 막힌다 —
     * 이 클래스가 막으려던 바로 그 상황이 그대로 벌어진다.
     * (실제로 이 코드의 첫 버전이 그랬고, 리뷰에서 실기동으로 잡혔다.)
     */
    private static final java.util.regex.Pattern UNRESOLVED_PLACEHOLDER =
            java.util.regex.Pattern.compile("\\$\\{[^}]*}");

    /**
     * record 의 <b>compact 생성자</b>. 파라미터 목록을 다시 적지 않고 검증만 하는 문법이다
     * (마지막에 {@code this.allowedOrigins = allowedOrigins} 는 컴파일러가 자동으로 넣어준다).
     *
     * <p>값이 비어 있으면 기동을 실패시키는 이유: CORS 설정이 비면 브라우저는
     * "요청이 조용히 막히는" 상태가 된다. 서버 로그에는 아무것도 안 남고 프론트 콘솔에만 에러가 뜬다.
     * 원인을 찾는 데 몇 시간이 드는 종류의 문제라, 차라리 기동할 때 시끄럽게 죽는 편이 낫다.
     * ({@code application-prod.yaml} 의 fail-closed 원칙과 같은 결)
     */
    public CorsProperties {
        if (allowedOrigins == null || allowedOrigins.isEmpty()) {
            throw new IllegalArgumentException(
                    "app.cors.allowed-origins 가 비어 있습니다. 관리자 화면 주소를 CORS_ALLOWED_ORIGINS 환경변수에 "
                            + "설정해주세요. 예: CORS_ALLOWED_ORIGINS=https://admin.example.com (여러 개면 쉼표로 구분)");
        }

        for (String origin : allowedOrigins) {
            if (origin == null || origin.isBlank()) {
                throw new IllegalArgumentException(
                        "app.cors.allowed-origins 에 빈 항목이 있습니다. 쉼표를 연달아 쓰지 않았는지 확인해주세요.");
            }
            // ⚠️ 여기가 이 클래스에서 가장 중요한 검사다. 아래 UNRESOLVED_PLACEHOLDER 주석 참고.
            if (UNRESOLVED_PLACEHOLDER.matcher(origin).find()) {
                throw new IllegalArgumentException(
                        "CORS_ALLOWED_ORIGINS 환경변수가 설정되지 않았습니다. 값이 치환되지 않아 \"" + origin
                                + "\" 라는 문자열이 그대로 들어왔습니다. 관리자 화면 주소를 환경변수로 넣어주세요. "
                                + "예: CORS_ALLOWED_ORIGINS=https://admin.example.com");
            }
            if (!origin.startsWith("http://") && !origin.startsWith("https://")) {
                throw new IllegalArgumentException(
                        "app.cors.allowed-origins 의 \"" + origin + "\" 은 오리진 형식이 아닙니다. "
                                + "스킴을 포함해 http:// 또는 https:// 로 시작해야 합니다. 예: https://admin.example.com");
            }
        }

        // 방어적 복사. 밖에서 넘어온 리스트를 그대로 들고 있으면 나중에 누가 수정할 수 있다.
        allowedOrigins = List.copyOf(allowedOrigins);
    }
}
