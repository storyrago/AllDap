package com.alldap.api.global.config;

import com.alldap.api.support.IntegrationTest;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.web.method.HandlerMethod;
import org.springframework.web.servlet.mvc.method.annotation.RequestMappingHandlerMapping;

import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * <b>설명이 빠진 엔드포인트가 없는지</b> 재는 테스트.
 *
 * <h2>효과는 지금이 아니라 나중에 난다</h2>
 * 34번째 엔드포인트를 추가하면서 설명을 빠뜨려도 컴파일은 되고, 기존 테스트도 초록이고,
 * Swagger 화면도 뜬다. <b>그 하나만 조용히 껍데기로 남는다.</b> 이 테스트가 그 순간 CI 에서 막는다.
 *
 * <h2>🔴 한계를 분명히 한다: 이 테스트는 <b>빈칸만</b> 본다</h2>
 * {@code summary} 가 맞는 말인지는 검사하지 못한다.
 * {@code summary = "봇 목록 조회"} 라고 써놓고 실제로는 봇을 삭제하는 코드여도 통과한다.
 * 이 저장소가 반복해서 낸 "기능은 고쳤는데 그것을 설명하는 자리를 안 고쳤다" 를
 * <b>완전히 막지는 못한다.</b> 빠뜨린 것만 잡는다.
 *
 * <h2>왜 빠진 것을 <b>전부</b> 나열하는가</h2>
 * 하나만 찍으면 고칠 때마다 테스트를 다시 돌려 다음 하나를 찾아야 한다.
 * 33개를 한 번에 붙이는 작업에서는 그 왕복이 그대로 낭비다.
 *
 * <h2>{@code @Qualifier} 가 필요한 이유</h2>
 * management 포트(8081) 분리 때문에 자식 컨텍스트가 생기는데, 우리가 재려는 것은
 * <b>서비스 포트의</b> 핸들러 매핑이다. 이름을 못박아 엉뚱한 매핑을 재지 않게 한다.
 */
@IntegrationTest
@DisplayName("OpenAPI 문서화 커버리지")
class OpenApiCoverageTest {

    /** 우리가 쓴 컨트롤러만 본다. actuator·에러 핸들러·springdoc 자신의 매핑은 대상이 아니다. */
    private static final String 우리_컨트롤러_패키지 = "com.alldap.api.domain";

    @Autowired
    @Qualifier("requestMappingHandlerMapping")
    private RequestMappingHandlerMapping mapping;

    @Test
    @DisplayName("모든 엔드포인트에 @Operation(summary) 가 있다")
    void 모든_엔드포인트에_summary_가_있다() {
        List<String> 빠진것 = new ArrayList<>();

        mapping.getHandlerMethods().forEach((info, handler) -> {
            if (!우리_컨트롤러인가(handler)) {
                return;
            }
            Operation operation = handler.getMethodAnnotation(Operation.class);
            if (operation == null || operation.summary().isBlank()) {
                빠진것.add(설명(info.toString(), handler));
            }
        });

        assertThat(빠진것)
                .withFailMessage("""

                        @Operation(summary = "...") 가 없는 엔드포인트가 %d 개 있다.
                        Swagger 화면에 경로만 뜨고 설명이 비어 껍데기로 남는다. 아래 전부에 붙일 것:
                        %s
                        """, 빠진것.size(), 줄로_묶는다(빠진것))
                .isEmpty();
    }

    @Test
    @DisplayName("모든 컨트롤러에 @Tag 가 있다")
    void 모든_컨트롤러에_tag_가_있다() {
        // @Tag 가 없으면 Swagger 화면에서 33개가 "bot-controller" 같은 기계 이름으로 묶인다.
        // 문서를 여는 사람이 무엇부터 봐야 하는지 알 수 없게 된다.
        Set<String> 빠진것 = new LinkedHashSet<>();

        mapping.getHandlerMethods().forEach((info, handler) -> {
            if (!우리_컨트롤러인가(handler)) {
                return;
            }
            Tag tag = handler.getBeanType().getAnnotation(Tag.class);
            if (tag == null || tag.name().isBlank()) {
                빠진것.add(handler.getBeanType().getName());
            }
        });

        assertThat(빠진것)
                .withFailMessage("""

                        @Tag(name = "...") 가 없는 컨트롤러가 %d 개 있다:
                        %s
                        """, 빠진것.size(), 줄로_묶는다(List.copyOf(빠진것)))
                .isEmpty();
    }

    private static boolean 우리_컨트롤러인가(HandlerMethod handler) {
        return handler.getBeanType().getPackageName().startsWith(우리_컨트롤러_패키지);
    }

    /**
     * {@code RequestMappingInfo.toString()} 을 그대로 쓴다. HTTP 메서드와 경로 패턴이 이미 들어 있어
     * 조건을 하나씩 꺼내 조립하는 것보다 짧고, Spring 버전에 따라 바뀌는 API 에 덜 의존한다.
     */
    private static String 설명(String mappingInfo, HandlerMethod handler) {
        return "  · %s  →  %s#%s".formatted(
                mappingInfo, handler.getBeanType().getSimpleName(), handler.getMethod().getName());
    }

    private static String 줄로_묶는다(List<String> 줄들) {
        return 줄들.stream().sorted().collect(Collectors.joining("\n"));
    }
}
