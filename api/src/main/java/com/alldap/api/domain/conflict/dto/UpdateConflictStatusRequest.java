package com.alldap.api.domain.conflict.dto;

import jakarta.validation.constraints.Pattern;

/**
 * 충돌 1건의 상태 변경 요청.
 *
 * <p>{@code clear}(판정 결과 모순 아님)는 <b>일부러 뺐다.</b> 그건 Python 이 스캔하면서
 * 스스로 남기는 값이지 사람이 지정할 값이 아니다. 받아주면 관리자가 실수로 넣었을 때
 * 그 쌍이 재스캔에서 조용히 건너뛰어진다.
 *
 * @param status open | ignored | resolved
 */
public record UpdateConflictStatusRequest(
        @Pattern(regexp = "open|ignored|resolved",
                message = "상태는 open, ignored, resolved 중 하나여야 합니다.")
        String status
) {
}
