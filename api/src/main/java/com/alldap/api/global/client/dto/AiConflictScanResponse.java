package com.alldap.api.global.client.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Python 의 {@code ConflictScanOut} — 스캔 한 번의 결과.
 *
 * <p><b>네 숫자를 따로 받는 이유:</b> "깨끗해서 0건"과 "못 재서 0건"은 다른 사실이다.
 * 합쳐 놓으면 구분이 안 되는데, 이 프로젝트는 그 부류의 버그를 이미 네 번 냈다
 * (answered_rate 분모 · 생존 편향 · 채점자 200자 · 잘린 답변).
 *
 * <p>{@code candidates} 가 Python 의 상한(기본 30)과 같으면 <b>아직 판정하지 않은 쌍이
 * 남았을 수 있다</b>는 신호다. 화면이 "다시 스캔"을 권해야 한다.
 */
public record AiConflictScanResponse(
        @JsonProperty("candidates") int candidates,
        @JsonProperty("judged") int judged,
        @JsonProperty("conflicts") int conflicts,
        @JsonProperty("failed") int failed
) {
}
