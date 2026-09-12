package com.alldap.api.global.config;

import com.alldap.api.global.exception.ErrorCode;
import io.swagger.v3.oas.annotations.security.SecurityRequirements;
import io.swagger.v3.oas.models.Components;
import io.swagger.v3.oas.models.OpenAPI;
import io.swagger.v3.oas.models.media.Content;
import io.swagger.v3.oas.models.media.MediaType;
import io.swagger.v3.oas.models.media.ObjectSchema;
import io.swagger.v3.oas.models.media.Schema;
import io.swagger.v3.oas.models.media.StringSchema;
import io.swagger.v3.oas.models.info.Info;
import io.swagger.v3.oas.models.responses.ApiResponse;
import io.swagger.v3.oas.models.responses.ApiResponses;
import io.swagger.v3.oas.models.security.SecurityRequirement;
import io.swagger.v3.oas.models.security.SecurityScheme;
import org.springdoc.core.customizers.OperationCustomizer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * OpenAPI 공통 설정. 컨트롤러 33곳에 반복될 것을 여기 한 곳에 모은다.
 *
 * <h2>여기서 정하는 것 세 가지</h2>
 * <ol>
 *   <li><b>Info</b> : 문서를 여는 사람이 가장 먼저 알아야 할 사실(외부에 열린 API 는 Spring 뿐이다)을 설명에 넣는다.</li>
 *   <li><b>JWT 보안 스킴을 전역 기본으로</b> : Swagger UI 의 Authorize 에 토큰을 한 번 넣으면 전부 시험할 수 있다.
 *       인증이 없는 엔드포인트는 {@code @SecurityRequirements} 로 개별 해제한다.</li>
 *   <li><b>공통 에러 응답</b> : {@code ErrorCode} 가 36개인데 엔드포인트마다 나열하면 문서를 못 읽는다.
 *       모든 엔드포인트에 참인 것만 일괄로 붙이고, 나머지는 엔드포인트별로 단다.</li>
 * </ol>
 *
 * <h2>🔴 401 을 <b>전부에</b> 달지 않는다</h2>
 * 401 은 모든 엔드포인트에 공통이 아니다. {@code /api/auth/signup} 은 401 을 낼 수 없고,
 * 위젯 API 는 인증이 없어 401 이 나갈 일이 없다. 일괄로 달면 <b>문서가 없는 응답을 있다고 말한다.</b>
 * 그래서 500 만 전부에 달고, 401 은 "전역 JWT 요구를 해제하지 않은 엔드포인트" 에만 단다.
 * 판정 신호는 {@code @SecurityRequirements} 의 유무 하나다. 보안 요구와 401 표기가 <b>자동으로 맞는다.</b>
 *
 * <p>⚠️ 로그인의 401({@code INVALID_CREDENTIALS})은 "토큰이 없어서" 가 아니라 "비밀번호가 틀려서" 다.
 * 별개 사실이므로 여기서 다루지 않고 엔드포인트별로 단다.
 *
 * <h2>🔴 에러 스키마를 클래스 참조가 아니라 손으로 정의하는 이유</h2>
 * {@code @Schema(implementation = ErrorResponse.class)} 는 springdoc 이 타입을 뒤져 스키마를 만들게 한다.
 * Boot 4 는 Jackson 3({@code tools.jackson})을 쓰는데 swagger-core 2.2.29 는 Jackson 2 를 쓴다.
 * 두 Jackson 이 한 클래스패스에 있는 상태에서 모델 introspection 에 의존하지 않는 쪽이 안전하고,
 * 필드가 {@code code}·{@code message} 둘뿐이라 손으로 적는 비용이 거의 없다. 결과가 결정적이다.
 */
@Configuration
public class OpenApiConfig {

    /** 보안 스킴 이름. 엔드포인트별 보안 표기를 적을 때 이 상수를 쓴다(문자열을 다시 적지 않는다). */
    public static final String BEARER_SCHEME = "bearerAuth";

    /** 공통 에러 응답 스키마 이름. 엔드포인트별 {@code @ApiResponse} 가 이 이름을 참조한다. */
    public static final String ERROR_SCHEMA_NAME = "ErrorResponse";

    private static final String ERROR_SCHEMA_REF = "#/components/schemas/" + ERROR_SCHEMA_NAME;

    @Bean
    public OpenAPI alldapOpenApi() {
        return new OpenAPI()
                .info(new Info()
                        .title("AllDap API")
                        .version("v0.4")
                        .description("""
                                문서를 올리면 출처가 표시되는 한국어 RAG 챗봇 서비스의 API.

                                외부에 노출되는 API 는 이 Spring 서비스뿐입니다. 파싱·청킹·임베딩·검색·생성·평가를 \
                                담당하는 Python AI 서비스(:8001)는 내부망 전용이고 인증이 없습니다. \
                                브라우저에서 직접 호출하지 마세요.

                                에러 응답은 전 계층 공통으로 {"error":{"code","message"}} 모양이고, \
                                message 는 "무엇을 어떻게 하면 되는지" 까지 담은 한국어 문장입니다.

                                이 문서는 로컬에서만 열립니다(운영에서는 생성 자체를 끕니다).
                                """))
                .components(new Components()
                        .addSchemas(ERROR_SCHEMA_NAME, 공통_에러_스키마())
                        .addSecuritySchemes(BEARER_SCHEME, new SecurityScheme()
                                .type(SecurityScheme.Type.HTTP)
                                .scheme("bearer")
                                .bearerFormat("JWT")
                                .description("""
                                        로그인(POST /api/auth/login) 응답의 token 값을 그대로 넣으세요. \
                                        가입·로그인과 위젯 API(/api/w/**)는 토큰이 필요 없습니다.""")))
                // 전역 기본. 인증이 없는 엔드포인트는 @SecurityRequirements 로 개별 해제한다.
                .addSecurityItem(new SecurityRequirement().addList(BEARER_SCHEME));
    }

    /**
     * 모든 엔드포인트에 <b>참인</b> 응답만 붙인다.
     *
     * <p>{@code OperationCustomizer} 는 springdoc 이 엔드포인트 하나를 모델로 만든 <b>뒤</b> 불러주는 훅이다.
     * 이미 적힌 응답이 있으면 덮지 않는다({@code containsKey} 검사). 엔드포인트별 설명이 공통 문구보다 정확하다.
     */
    @Bean
    public OperationCustomizer 공통_에러_응답() {
        return (operation, handlerMethod) -> {
            ApiResponses responses = operation.getResponses();

            // 500 은 어디서든 날 수 있다(GlobalExceptionHandler 의 마지막 그물).
            응답을_없을_때만_붙인다(responses, "500", ErrorCode.INTERNAL_ERROR);

            // 401 은 토큰을 받는 엔드포인트에만 있다. 판정 신호는 개별 해제 애노테이션의 유무다.
            boolean 토큰을_받는다 = handlerMethod.getMethodAnnotation(SecurityRequirements.class) == null;
            if (토큰을_받는다) {
                응답을_없을_때만_붙인다(responses, "401", ErrorCode.AUTHENTICATION_REQUIRED);
            }

            return operation;
        };
    }

    private static void 응답을_없을_때만_붙인다(ApiResponses responses, String status, ErrorCode errorCode) {
        if (responses.containsKey(status)) {
            return;
        }
        responses.addApiResponse(status, new ApiResponse()
                .description(errorCode.getCode() + " : " + errorCode.getMessage())
                .content(new Content().addMediaType("application/json", new MediaType()
                        .schema(new Schema<>().$ref(ERROR_SCHEMA_REF))
                        .example("""
                                {"error":{"code":"%s","message":"%s"}}"""
                                .formatted(errorCode.getCode(), errorCode.getMessage())))));
    }

    /**
     * 전 계층 공통 에러 응답. <b>중첩 구조가 핵심이다.</b>
     * 평평하게 만들면 프론트({@code web/lib/types.ts} 의 {@code ApiErrorBody})·Python·위젯이 모두 어긋난다.
     */
    private static Schema<?> 공통_에러_스키마() {
        Schema<?> 내부 = new ObjectSchema()
                .addProperty("code", new StringSchema()
                        .description("기계가 분기할 식별자(영문 대문자 스네이크). 문구가 바뀌어도 이 값은 유지된다.")
                        .example(ErrorCode.BOT_NOT_FOUND.getCode()))
                .addProperty("message", new StringSchema()
                        .description("사용자에게 그대로 보여줄 한국어 문장. 무엇을 어떻게 하면 되는지까지 담는다.")
                        .example(ErrorCode.BOT_NOT_FOUND.getMessage()));

        return new ObjectSchema()
                .description("전 계층(Spring·Python·Next.js) 공통 에러 응답")
                .addProperty("error", 내부);
    }
}
