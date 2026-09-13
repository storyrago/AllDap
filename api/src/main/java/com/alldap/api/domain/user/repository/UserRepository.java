package com.alldap.api.domain.user.repository;

import com.alldap.api.domain.user.entity.User;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface UserRepository extends JpaRepository<User, Long> {

    /** 로그인에서 사용. 없으면 INVALID_CREDENTIALS 로 처리한다. */
    Optional<User> findByEmail(String email);

    /**
     * 가입 시 중복 검사.
     *
     * <p>이 검사만으로 완전하지는 않다. 동시에 같은 이메일로 가입 요청이 오면 둘 다 통과할 수 있다.
     * 최종 방어선은 DB 의 {@code email UNIQUE} 제약이므로,
     * 서비스에서 DataIntegrityViolationException 도 함께 처리해야 한다.
     *
     * <p>✅ <b>그 처리는 이미 있다</b>(옛 TODO 를 지운 자리다). {@code AuthService.signup} 이
     * {@code catch (DataIntegrityViolationException)} 으로 받아 1차 검사와 <b>같은</b>
     * {@code EMAIL_ALREADY_EXISTS} 로 답한다. 거기서 {@code save} 가 아니라
     * {@code saveAndFlush} 를 쓰는 이유도 이것이다: INSERT 가 커밋 시점까지 미뤄지면
     * 그 catch 가 제약 위반을 잡지 못하고 500 이 나간다.
     */
    boolean existsByEmail(String email);
}
