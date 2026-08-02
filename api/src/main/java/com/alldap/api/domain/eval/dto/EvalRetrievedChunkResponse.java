package com.alldap.api.domain.eval.dto;

import com.fasterxml.jackson.annotation.JsonAlias;

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
 * <h2>⚠️ {@code @JsonProperty} 가 아니라 {@code @JsonAlias} 인 이유 (실제로 낸 버그)</h2>
 * 이 record 는 <b>읽기와 쓰기에 모두 쓰인다</b> — DB 의 JSONB(Python 이 만든 snake_case)를 읽고,
 * 그대로 프론트 응답으로도 나간다.
 *
 * <p>처음에 {@code @JsonProperty("chunk_id")} 를 붙였더니 Jackson 이 그 이름을
 * <b>직렬화에도</b> 적용해 <b>응답에 {@code chunk_id} 가 그대로 실려 나갔다.</b>
 * "공개 API 응답은 camelCase"(AGENTS.md 작업 규칙 5)를 정면으로 어긴 것이고,
 * 프론트 타입({@code EvalRetrievedChunk.chunkId})은 영원히 undefined 를 받는다.
 *
 * <p>브라우저로 화면을 확인했을 때는 <b>안 보였다</b> — 화면이 마침 {@code filename} 만 썼기 때문이다.
 * 통합 테스트가 응답 본문에서 {@code chunk_id} 를 찾아보고서야 드러났다.
 *
 * <p>{@code @JsonAlias} 는 <b>읽을 때만</b> 추가 이름을 인정한다. 쓸 때는 record 필드명
 * ({@code chunkId})이 그대로 나간다. 읽기·쓰기가 갈리는 지점이라 이게 맞다.
 */
public record EvalRetrievedChunkResponse(
        @JsonAlias("chunk_id") UUID chunkId,
        String filename,
        /** 0~1. 1에 가까울수록 관련성 높음 (1 - 코사인거리) */
        Double score
) {
}
