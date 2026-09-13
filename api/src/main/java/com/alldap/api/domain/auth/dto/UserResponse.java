package com.alldap.api.domain.auth.dto;

import com.alldap.api.domain.user.entity.User;

import java.time.Instant;

/**
 * 사용자 정보 응답. 프론트의 {@code User}({@code web/lib/types.ts})와 필드명을 맞춘다.
 *
 * <p>{@code passwordHash} 는 절대 포함하지 않는다. 엔티티를 직접 반환하지 않는 이유가 이것이다.
 */
public record UserResponse(
        Long id,
        String email,
        String name,
        Instant createdAt
) {

    public static UserResponse from(User user) {
        return new UserResponse(user.getId(), user.getEmail(), user.getName(), user.getCreatedAt());
    }
}
