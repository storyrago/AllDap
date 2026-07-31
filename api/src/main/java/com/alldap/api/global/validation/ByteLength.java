package com.alldap.api.global.validation;

import jakarta.validation.Constraint;
import jakarta.validation.Payload;

import java.lang.annotation.Documented;
import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * 문자열의 <b>UTF-8 바이트 길이</b> 상한을 검사하는 커스텀 검증 애너테이션.
 *
 * <p><b>왜 만들었나.</b> 표준 {@code @Size} 는 <b>문자 수</b>를 센다.
 * 그런데 우리가 지켜야 하는 제약(BCrypt 의 72바이트 한계)은 <b>바이트 수</b>다.
 * 한글은 UTF-8 에서 한 글자가 3바이트라 {@code @Size(max = 64)} 를 통과한 값이
 * 인코딩 단계에서 터지는 구멍이 생긴다 (한글 25자 = 75바이트 &gt; 72).
 * 실제로 이 구멍 때문에 가입이 500 으로 떨어졌다.
 *
 * <p><b>왜 서비스 계층이 아니라 검증 애너테이션인가.</b>
 * ① 이건 "요청 값이 규격에 맞는가"라는 <b>입력 검증</b>이지 비즈니스 규칙이 아니다.
 * ② 애너테이션으로 두면 {@code GlobalExceptionHandler} 의 기존
 * {@code MethodArgumentNotValidException} 경로를 그대로 타서
 * 다른 검증 실패와 <b>완전히 같은 모양의 400 응답</b>이 나간다.
 * 서비스에서 따로 던지면 같은 종류의 잘못에 응답 모양이 두 벌 생긴다.
 * ③ 나중에 비밀번호 변경 API 를 만들 때 한 줄만 붙이면 된다.
 *
 * <p><b>애너테이션 문법 메모</b>
 * <ul>
 *   <li>{@code @Constraint(validatedBy = ...)} — 실제 검사 로직 클래스를 연결한다.
 *       이게 있어야 Jakarta Bean Validation 이 커스텀 제약으로 인식한다.</li>
 *   <li>{@code message()}/{@code groups()}/{@code payload()} 세 개는 <b>규격상 필수</b>다.
 *       하나라도 빠지면 검증 엔진이 초기화 단계에서 예외를 던진다.</li>
 *   <li>{@code @Target} 은 표준 제약({@code @Size} 등)과 같은 목록으로 맞췄다.
 *       record 컴포넌트에 붙이려면 최소한 FIELD·PARAMETER 가 필요하다 —
 *       컴파일러가 record 컴포넌트의 애너테이션을 필드·생성자 파라미터로 복제하기 때문이다.</li>
 * </ul>
 */
@Documented
@Constraint(validatedBy = ByteLengthValidator.class)
@Target({ElementType.METHOD, ElementType.FIELD, ElementType.ANNOTATION_TYPE,
        ElementType.CONSTRUCTOR, ElementType.PARAMETER, ElementType.TYPE_USE})
@Retention(RetentionPolicy.RUNTIME)
public @interface ByteLength {

    /** 허용하는 최대 UTF-8 바이트 수(이 값 포함). */
    int max();

    /** 기본 문구. 실제로는 붙이는 쪽에서 "무엇을 어떻게 하면 되는지"를 담아 덮어쓴다. */
    String message() default "입력값이 너무 깁니다. 한글은 한 글자가 3바이트로 계산됩니다. 길이를 줄여주세요.";

    Class<?>[] groups() default {};

    Class<? extends Payload>[] payload() default {};
}
