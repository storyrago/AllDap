package com.alldap.api.domain.conflict.controller;

import com.alldap.api.domain.conflict.dto.ConflictResponse;
import com.alldap.api.domain.conflict.dto.ConflictScanResponse;
import com.alldap.api.domain.conflict.dto.UpdateConflictStatusRequest;
import com.alldap.api.domain.conflict.service.ConflictService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;

import java.util.List;
import java.util.UUID;

/**
 * 문서 간 사실 충돌 진단 API. 인증 필요.
 *
 * <p><b>userId 는 {@code @AuthenticationPrincipal} 로만 받는다.</b> 쿼리 파라미터나 본문으로
 * 받으면 남의 id 를 적어 보내는 것만으로 격리가 무너진다. 소유권 확인은 서비스가 하고,
 * <b>Python 을 부르기 전에</b> 끝난다 — Python 의 {@code /internal/*} 에는 인증이 없기 때문이다.
 */
@Tag(name = "문서 충돌", description = "서로 다른 값을 말하는 문서 쌍을 찾아 알려준다.")
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/bots/{botId}/conflicts")
public class ConflictController {

    private final ConflictService conflictService;

    /**
     * GET /api/bots/{botId}/conflicts?status=open — 충돌 목록.
     *
     * <p>기본이 {@code open} 인 이유: 화면이 보여줄 것은 "아직 안 본 것"뿐이다.
     * {@code ignored}(오탐 표시)와 {@code clear}(판정 결과 모순 아님)까지 섞어 보여주면
     * 목록이 금세 노이즈로 덮인다. 지난 판정을 되짚고 싶을 때만 status 를 바꿔 부른다.
     */
    @Operation(summary = "충돌 목록 조회")
    @GetMapping
    public ResponseEntity<List<ConflictResponse>> getConflicts(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID botId,
            @RequestParam(defaultValue = "open") String status) {
        return ResponseEntity.ok(conflictService.findAll(userId, botId, status));
    }

    /**
     * POST /api/bots/{botId}/conflicts/scan — 문서끼리 어긋나는 곳을 훑는다.
     *
     * <p>200 이다. 202 가 아닌 이유는 <b>동기 호출</b>이기 때문이다 —
     * {@code doc_conflicts} 에는 "스캔 한 번"을 가리키는 행이 없어 202 를 줘도 폴링할 대상이 없다.
     * (평가 실행은 {@code eval_runs.status} 가 있어서 202 가 성립한다)
     *
     * <p>경로 끝에 {@code /scan} 을 붙인 이유: 같은 {@code /conflicts} 에 POST 를 두면
     * "충돌을 직접 하나 등록한다"와 구분되지 않는다.
     */
    @Operation(summary = "충돌 진단 실행")
    @PostMapping("/scan")
    public ResponseEntity<ConflictScanResponse> scan(@AuthenticationPrincipal UUID userId,
                                                     @PathVariable UUID botId) {
        return ResponseEntity.ok(conflictService.scan(userId, botId));
    }

    /**
     * PATCH /api/bots/{botId}/conflicts/{conflictId} — 상태 변경 (오탐 치우기).
     *
     * <p><b>경로에 botId 가 반드시 들어간다.</b> conflictId 만 받으면 소유권을 확인할 대상이
     * 없어서, id 만 알아내면 남의 봇 충돌을 치울 수 있다.
     */
    @Operation(summary = "충돌 처리 상태 변경")
    @PatchMapping("/{conflictId}")
    public ResponseEntity<ConflictResponse> updateStatus(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID botId,
            @PathVariable UUID conflictId,
            @Valid @RequestBody UpdateConflictStatusRequest request) {
        return ResponseEntity.ok(
                conflictService.updateStatus(userId, botId, conflictId, request.status()));
    }
}
