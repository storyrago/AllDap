package com.alldap.api.domain.eval.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.UUID;

/**
 * 평가 실행 중 검색된 청크 하나 (스냅샷).
 *
 * <p><b>{@code SourceResponse} 를 재사용하지 않은 이유:</b> 필드가 다르다.
 * 채팅의 {@code sources} 는 {@code documentId} 와 {@code preview} 까지 담지만,
 * Python 이 평가 결과에 남기는 건 {@code chunk_id / filename / score} 셋뿐이다
 * ({@code evalrun.py}). 없는 필드를 null 로 채워 같은 타입인 척하면
 * 화면이 "왜 여기만 preview 가 비지?" 를 계속 묻게 된다.
 *
 * <p>{@code @JsonProperty} 가 붙은 이유: 이 JSON 을 만든 건 <b>Python</b> 이라 snake_case 다
 * ({@code chunk_id}). DB(JSONB)에 그 모양 그대로 저장돼 있으므로 읽을 때 매핑해야 한다.
 * 반대로 프론트에 나갈 때는 record 필드명(camelCase)이 그대로 쓰인다 — 그게 변환 지점이다.
 */
public record EvalRetrievedChunkResponse(
        @JsonProperty("chunk_id") UUID chunkId,
        @JsonProperty("filename") String filename,
        /** 0~1. 1에 가까울수록 관련성 높음 (1 - 코사인거리) */
        @JsonProperty("score") Double score
) {
}
