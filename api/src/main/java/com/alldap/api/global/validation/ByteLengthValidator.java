package com.alldap.api.global.validation;

import jakarta.validation.ConstraintValidator;
import jakarta.validation.ConstraintValidatorContext;

import java.nio.charset.StandardCharsets;

/**
 * {@link ByteLength} 의 실제 검사 로직.
 *
 * <p>{@code ConstraintValidator<검증할애너테이션, 검증할타입>} 형태로 두 타입을 알려주면
 * 검증 엔진이 String 필드에만 이 검사를 적용한다.
 */
public class ByteLengthValidator implements ConstraintValidator<ByteLength, String> {

    private int max;

    /** 애너테이션에 적힌 설정값({@code max})을 꺼내 보관한다. 요청마다 애너테이션을 다시 읽지 않기 위해서다. */
    @Override
    public void initialize(ByteLength constraintAnnotation) {
        this.max = constraintAnnotation.max();
    }

    @Override
    public boolean isValid(String value, ConstraintValidatorContext context) {
        // null 은 통과시킨다. "값이 있어야 하는가"는 @NotBlank 의 책임이고,
        // 한 필드의 규칙을 두 애너테이션이 겹쳐 검사하면 메시지가 두 개 나가 사용자만 혼란스럽다.
        // (Bean Validation 표준 제약들도 모두 이 관례를 따른다)
        if (value == null) {
            return true;
        }
        // UTF-8 을 명시한다. 기본 charset 에 맡기면 실행 환경에 따라 바이트 수가 달라져
        // "내 노트북에선 되는데 서버에선 안 되는" 검증이 된다.
        return value.getBytes(StandardCharsets.UTF_8).length <= max;
    }
}
