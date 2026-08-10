package com.alldap.api.domain.conflict.dto;

import com.alldap.api.global.client.dto.AiConflictScanResponse;

/**
 * 스캔 한 번의 결과.
 *
 * <p><b>네 숫자를 따로 내려주는 이유:</b> "깨끗해서 0건"과 "못 재서 0건"은 다른 사실이다.
 * {@code conflicts} 만 주면 화면이 그 둘을 구분해 보여줄 수 없다.
 *
 * @param candidates 판정 대상으로 고른 쌍. Python 상한(기본 30)과 같으면 <b>아직 남았을 수 있다</b>
 * @param judged     실제로 판정이 돌아온 쌍
 * @param conflicts  그중 모순으로 기록된 쌍
 * @param failed     판정하지 못한 쌍 (호출 실패·응답 파싱 실패). <b>"모순 없음"이 아니다</b>
 */
public record ConflictScanResponse(
        int candidates,
        int judged,
        int conflicts,
        int failed
) {
    public static ConflictScanResponse from(AiConflictScanResponse ai) {
        return new ConflictScanResponse(ai.candidates(), ai.judged(), ai.conflicts(), ai.failed());
    }
}
