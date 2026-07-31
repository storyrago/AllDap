package com.alldap.api.global.common;

import org.springframework.data.domain.Page;

import java.util.List;
import java.util.function.Function;

/**
 * 페이지네이션 공통 응답 껍데기.
 *
 * <p>Spring Data 의 {@link Page} 를 그대로 내리지 않는 이유:
 * {@code Page} 의 JSON 모양(content / totalElements / number / pageable ...)은
 * Spring Data 버전에 따라 바뀌는 내부 구조라 공개 API 규격으로 삼기에 위험하다.
 * 프론트({@code web/lib/types.ts} 의 {@code Paged<T>})는
 * {@code items / page / size / totalElements / totalPages} 를 전제로 작성돼 있으므로
 * 그 모양을 여기서 고정한다.
 */
public record PageResponse<T>(
        List<T> items,
        int page,
        int size,
        long totalElements,
        int totalPages
) {

    /** 엔티티 Page 를 응답 DTO Page 로 변환한다. */
    public static <E, T> PageResponse<T> of(Page<E> page, Function<E, T> mapper) {
        return new PageResponse<>(
                page.getContent().stream().map(mapper).toList(),
                page.getNumber(),
                page.getSize(),
                page.getTotalElements(),
                page.getTotalPages()
        );
    }
}
