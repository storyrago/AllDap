package com.alldap.api.global.client;

import com.alldap.api.global.client.dto.AiChatRequest;
import com.alldap.api.global.client.dto.AiChatResponse;
import com.alldap.api.global.client.dto.AiConflictResponse;
import com.alldap.api.global.client.dto.AiConflictScanResponse;
import com.alldap.api.global.client.dto.AiDocumentResponse;
import com.alldap.api.global.client.dto.AiEvalQuestionResponse;
import com.alldap.api.global.client.dto.AiEvalRunResponse;
import com.alldap.api.global.client.dto.AiGenerateQuestionsRequest;
import com.alldap.api.global.client.dto.AiUpdateConflictStatusRequest;
import com.alldap.api.global.config.AiServiceProperties;
import com.alldap.api.global.exception.ApiException;
import com.alldap.api.global.exception.ErrorCode;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.http.HttpStatus;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestClientResponseException;
import org.springframework.web.multipart.MultipartFile;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.net.ConnectException;
import java.net.http.HttpConnectTimeoutException;
import java.net.http.HttpTimeoutException;
import java.util.List;
import java.util.UUID;
import java.util.function.Function;
import java.util.function.Supplier;

/**
 * Python AI 서비스(:8001) 호출 담당.
 *
 * <p><b>이 클래스가 존재하는 이유.</b> Python 컨트랙트를 아는 코드를 여기 한 곳에 가둔다.
 * 서비스 계층은 {@code snake_case} 도 HTTP 도 모른 채 도메인 언어로만 대화한다.
 * 나중에 Python 컨트랙트가 바뀌어도 고칠 곳이 이 파일과 {@code client/dto} 뿐이다.
 *
 * <p><b>실제 컨트랙트</b> (ai-service/app/main.py 를 읽어 확인한 것):
 * <pre>
 * GET    /health                             -> {"status":"ok"}
 * POST   /internal/bots/{bot_id}/documents   multipart 필드명 "file" -> 202 + DocumentOut
 * GET    /internal/bots/{bot_id}/documents   -> DocumentOut[]
 * DELETE /internal/documents/{doc_id}        -> 204 (본문 없음)
 * POST   /internal/chat                      {bot_id, message, session_id} -> ChatResponse
 * POST   /internal/bots/{bot_id}/eval/questions/generate  {count} -> EvalQuestionOut[]  (동기)
 * POST   /internal/bots/{bot_id}/eval/runs   -> 202 + EvalRunOut(status=running)
 * GET    /internal/bots/{bot_id}/eval/questions           -> EvalQuestionOut[]  (Spring 은 DB 직접 조회)
 * GET    /internal/bots/{bot_id}/eval/runs                -> EvalRunOut[]       (Spring 은 DB 직접 조회)
 * </pre>
 *
 * <p><b>주의:</b> {@code /internal/*} 에는 인증이 없다. Spring 이 앞단에서 막아준다는 전제다.
 * 이 서비스를 외부에 노출하면 누구나 남의 봇 문서를 조회할 수 있다.
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class AiServiceClient {

    /** RestClientConfig 의 {@code aiServiceRestClient} 빈. baseUrl 과 타임아웃이 이미 박혀 있다. */
    private final RestClient aiServiceRestClient;

    /** FastAPI 의 에러 본문 {@code {"detail":"..."}} 을 읽는 데만 쓴다. Boot 4 가 자동 구성하는 Jackson 3 매퍼다. */
    private final ObjectMapper objectMapper;

    /** 실패 로그에 "어디로 못 붙었는지"를 남기기 위해 주입한다. 주소를 모르면 로그만 보고 원인을 못 좁힌다. */
    private final AiServiceProperties aiServiceProperties;

    /**
     * 문서 업로드. Python 은 documents 행만 만들고 202 로 즉시 응답한 뒤
     * 파싱·청킹·임베딩은 백그라운드로 처리한다. 따라서 반환되는 status 는 보통 {@code pending} 이다.
     *
     * <p>multipart 필드명은 반드시 {@code "file"} 이어야 한다 (FastAPI 의 {@code File(...)} 파라미터명).
     *
     * @param botId 문서를 붙일 봇. 호출 전에 <b>반드시 소유권을 검증</b>해야 한다
     *              (Python 에는 인증이 없어 여기서 막지 않으면 남의 봇에 문서를 넣을 수 있다).
     */
    public AiDocumentResponse uploadDocument(UUID botId, MultipartFile file) {
        MultiValueMap<String, Object> body = new LinkedMultiValueMap<>();
        body.add("file", toFilePart(file));

        return call("문서 업로드", () -> aiServiceRestClient.post()
                .uri("/internal/bots/{botId}/documents", botId)
                .contentType(MediaType.MULTIPART_FORM_DATA)
                .body(body)
                .retrieve()
                .body(AiDocumentResponse.class),
                this::translateUploadClientError);
    }

    /**
     * {@link MultipartFile} → multipart 파트로 변환.
     *
     * <p><b>{@code getFilename()} 을 오버라이드하는 게 이 메서드의 존재 이유다.</b>
     * Spring 은 {@code Resource} 의 파일명을 보고 {@code Content-Disposition} 의 {@code filename=} 을 채우는데,
     * 평범한 {@code ByteArrayResource} 는 파일명을 모른다(null). 그러면 Python 에 파일명이 안 넘어가고,
     * {@code detect_type()} 이 확장자를 못 읽어 <b>멀쩡한 PDF 도 "지원하지 않는 형식"으로 거절된다.</b>
     * 여기서 익명 클래스로 한 줄 덮어쓰는 이유가 그것이다.
     *
     * <p>파일 전체를 메모리에 올리는 것은 의도적이다. multipart 상한이 20MB
     * ({@code application.yaml})라 상한이 있는 데다, 스트리밍으로 넘기려면
     * {@code InputStreamResource} 를 써야 하는데 그건 길이를 모르는 스트림이라
     * 재시도·리다이렉트에서 한 번 읽고 나면 다시 읽을 수 없다.
     */
    private ByteArrayResource toFilePart(MultipartFile file) {
        byte[] bytes;
        try {
            bytes = file.getBytes();
        } catch (IOException e) {
            // 업로드 도중 연결이 끊기는 등 파일을 읽지 못한 경우. 우리 잘못도 Python 잘못도 아니라
            // 재시도를 안내한다.
            log.warn("[AI 호출] 업로드 파일을 읽지 못했다. filename={}", file.getOriginalFilename(), e);
            throw new ApiException(ErrorCode.INTERNAL_ERROR,
                    "파일을 읽는 중 문제가 발생했습니다. 다시 올려주세요.");
        }

        String filename = file.getOriginalFilename();
        return new ByteArrayResource(bytes) {
            @Override
            public String getFilename() {
                return filename;
            }
        };
    }

    /**
     * 봇의 문서 목록 조회. <b>현재 호출자가 없다 — 미구현으로 남겨둔 것이 의도다.</b>
     *
     * <p>문서 목록은 이 메서드가 아니라 {@code DocumentService.findDocuments} 가
     * <b>DB 를 직접 읽어</b> 처리한다. 그 이유(업로드 시각을 채울 수 있다 / Python 이 죽어도
     * 목록은 보인다)는 그쪽 주석에 적어두었다.
     *
     * <p>그럼 왜 지우지 않는가: Python 에 이 엔드포인트가 실제로 있고
     * ({@code GET /internal/bots/{bot_id}/documents}), 나중에 "Spring 이 모르는 상태 값을
     * Python 이 판단해줘야 하는" 상황이 오면 이쪽으로 갈아탈 수 있다.
     * 다만 <b>지금은 죽은 코드이므로 구현하지 않는다</b> — 호출자 없는 코드를 미리 만들면
     * 검증되지 않은 채 "동작한다"는 인상만 남는다.
     */
    public List<AiDocumentResponse> listDocuments(UUID botId) {
        throw new UnsupportedOperationException(
                "AiServiceClient.listDocuments 는 의도적으로 미구현이다 — 문서 목록은 DocumentService 가 DB 에서 읽는다");
    }

    /**
     * 문서 삭제. chunks 는 DB 의 ON DELETE CASCADE 로 함께 지워진다.
     *
     * <p>Spring 이 documents 를 직접 DELETE 하지 않는 이유: 쓰기 소유자가 Python 이기 때문이다.
     * 양쪽이 같은 테이블에 쓰기 시작하면 누가 무엇을 바꿨는지 추적이 불가능해진다.
     */
    public void deleteDocument(UUID documentId) {
        call("문서 삭제", () -> aiServiceRestClient.delete()
                .uri("/internal/documents/{documentId}", documentId)
                .retrieve()
                .toBodilessEntity());

        // Python 의 DELETE 는 없는 id 를 지워도 204 다(SQL DELETE 가 0행을 지운 것뿐).
        // 그래서 "없는 문서" 판단은 Spring 이 이 호출 <전에> DB 조회로 끝낸다(DocumentService).
        // 여기서 다시 확인하려 들면 Python 컨트랙트에 없는 의미를 우리가 지어내는 셈이다.
    }

    // ── 실패 변환 ────────────────────────────────────────────────────────

    /**
     * Python 호출을 감싸 <b>모든 실패를 {@link ApiException} 으로 바꾼다.</b>
     *
     * <p><b>왜 한 곳에 모으는가.</b> 이 변환을 호출 지점마다 적으면 반드시 한 군데가 빠지고,
     * 빠진 곳에서는 {@code RestClientException} 이 그대로 올라가
     * {@code GlobalExceptionHandler} 의 마지막 그물에 걸려 <b>500 INTERNAL_ERROR</b> 가 나간다.
     * 그러면 "Python 이 죽었다"가 "우리 서버가 고장났다"로 둔갑한다 —
     * 프론트는 재시도 로직을 잘못 짜고, 로그에는 가짜 ERROR 가 쌓여 진짜 장애가 묻힌다.
     *
     * <p><b>상태 코드를 나누는 기준은 "누구 잘못인가"다.</b>
     * <ul>
     *   <li>연결 자체가 안 됨 → 503 {@code AI_SERVICE_UNAVAILABLE} ("잠시 후 재시도")</li>
     *   <li>연결은 됐는데 응답이 늦음 → 504 {@code AI_SERVICE_TIMEOUT} ("질문을 줄여서 재시도")</li>
     *   <li>Python 이 5xx → 503. Python 이 스스로 고장났다고 말한 것이다</li>
     *   <li>Python 이 4xx → 사용자 입력 문제. {@link #translateClientError} 가 구체적인 코드로 바꾼다</li>
     * </ul>
     */
    private <T> T call(String what, Supplier<T> action) {
        // 기본 4xx 처리: 사용자가 고칠 수 있는 게 아니라 <우리가 Python 을 잘못 호출한> 것이다.
        // 내부 사정을 사용자에게 설명하지 않고 502 로 답한다.
        return call(what, action, e -> new ApiException(ErrorCode.AI_SERVICE_ERROR));
    }

    /**
     * 4xx 해석을 호출자가 정할 수 있는 형태.
     *
     * <p><b>왜 필요한가.</b> 같은 400 이라도 의미가 엔드포인트마다 다르다.
     * 업로드의 400 은 "파일 형식이 잘못됐다"(사용자가 고칠 수 있다)지만,
     * 채팅의 400·422 는 "Spring 이 스키마에 안 맞는 요청을 보냈다"(사용자는 손쓸 수 없다)이다.
     * 이걸 한 매퍼로 묶어두면 <b>채팅 오류에 "지원하지 않는 파일 형식입니다"가 나간다.</b>
     * (실제로 업로드 슬라이스의 매퍼를 그대로 두면 그렇게 된다 — 채팅을 붙이며 발견했다)
     */
    private <T> T call(String what, Supplier<T> action,
                       Function<RestClientResponseException, ApiException> on4xx) {
        try {
            return action.get();

        } catch (RestClientResponseException e) {
            // Python 이 HTTP 응답은 돌려준 경우 (4xx / 5xx)
            HttpStatusCode status = e.getStatusCode();
            if (status.is4xxClientError()) {
                log.warn("[AI 호출] {} — Python 이 {} 로 거절. body={}",
                        what, status, e.getResponseBodyAsString());
                throw on4xx.apply(e);
            }
            log.error("[AI 호출] {} 실패 — Python 이 {} 응답. body={}", what, status, e.getResponseBodyAsString());
            throw new ApiException(ErrorCode.AI_SERVICE_UNAVAILABLE);

        } catch (ResourceAccessException e) {
            // 아예 응답을 받지 못한 경우 (연결 거부·타임아웃·중간 끊김)
            throw translateIoFailure(what, e);

        } catch (RestClientException e) {
            // ⚠️ 여기 두 가지가 섞여 들어온다. 구분하지 않으면 "Python 이 죽었다"가
            // "우리가 응답을 못 읽었다"로 둔갑해, 운영자를 엉뚱한 조사(DTO·컨트랙트 대조)로 보낸다.
            //
            // 응답 <헤더가 온 뒤> 연결이 끊기거나 본문이 늦으면 ResourceAccessException 이 아니라
            // RestClientException(cause = IOException) 으로 온다.
            // DefaultRestClient 가 본문을 읽다 만난 IOException 을 여기로 감싸 던지기 때문이다.
            // 즉 위의 catch(ResourceAccessException) 는 "헤더도 못 받은" 실패만 잡는다.
            if (e.getCause() instanceof IOException io) {
                log.error("[AI 호출] {} 실패 — 응답을 받는 도중 Python 과의 통신이 끊겼다.", what, io);
                throw new ApiException(ErrorCode.AI_SERVICE_UNAVAILABLE);
            }

            // 진짜로 응답은 멀쩡히 받았는데 해석에 실패한 경우 — JSON 구조가 DTO 와 안 맞는다.
            // Python 컨트랙트가 바뀌었는데 우리 DTO 를 안 고친 상황이라
            // 502(게이트웨이가 받은 응답이 이상함)가 맞다.
            log.error("[AI 호출] {} 실패 — 응답을 해석하지 못했다. DTO 와 Python 스키마가 어긋났을 수 있다.", what, e);
            throw new ApiException(ErrorCode.AI_SERVICE_ERROR);
        }
    }

    /**
     * <b>업로드 전용</b> 4xx 변환. 다른 엔드포인트에 재사용하지 말 것 — 위 {@link #call} 주석 참고.
     *
     * <p><b>Python 의 메시지를 그대로 사용자에게 내려보낸다.</b> 보통은 내부 서비스의 에러 문구를
     * 밖으로 흘리면 안 되지만, 여기 오는 문구는 {@code parsers.py} 의 {@code ParseError} 가
     * <b>애초에 사용자에게 보여주려고 쓴 한국어</b>다.
     * 예: "구버전 .hwp는 아직 지원하지 않습니다. 한글에서 .hwpx로 저장 후 올려주세요."
     * Spring 이 이걸 버리고 "지원하지 않는 파일 형식입니다"로 뭉개면
     * <b>사용자가 다음에 뭘 해야 하는지를 잃는다</b>(AGENTS.md 작업 규칙 4).
     *
     * <p>그래서 지원 확장자 목록을 Spring 에 복제하지 않는다.
     * 목록을 양쪽에 두면 반드시 어긋나고, 그때 "Spring 은 통과시켰는데 Python 이 거절"이 된다.
     * <b>형식 판단의 단일 기준은 Python 의 {@code detect_type()} 하나다.</b>
     */
    private ApiException translateUploadClientError(RestClientResponseException e) {
        String detail = extractDetail(e);

        // 413: Spring 의 multipart 상한(20MB)과 Python 의 upload_max_bytes(20MB)가 같아서
        // 보통은 Spring 에서 먼저 걸린다. 두 값이 어긋나면 여기로 오므로 대비해 둔다.
        // (Spring 7 에서 PAYLOAD_TOO_LARGE 는 CONTENT_TOO_LARGE 로 이름이 바뀌었다. 숫자는 413 그대로다)
        if (e.getStatusCode().isSameCodeAs(HttpStatus.CONTENT_TOO_LARGE)) {
            return new ApiException(ErrorCode.FILE_TOO_LARGE, detail);
        }
        if (e.getStatusCode().isSameCodeAs(HttpStatus.BAD_REQUEST)) {
            return new ApiException(ErrorCode.UNSUPPORTED_FILE_TYPE, detail);
        }

        // 그 밖의 4xx(404·422 등)는 사용자가 고칠 수 있는 게 아니라
        // 우리가 Python 을 잘못 호출한 것이다. 사용자에게는 내부 사정을 설명하지 않는다.
        return new ApiException(ErrorCode.AI_SERVICE_ERROR);
    }

    /**
     * FastAPI 의 에러 본문 {@code {"detail":"..."}} 에서 메시지만 꺼낸다.
     *
     * <p>꺼내지 못하면 null 을 돌려주고, 그러면 {@link ApiException} 이
     * {@link ErrorCode} 의 기본 문구를 쓴다 — 즉 실패해도 사용자 응답은 여전히 온전하다.
     * 파싱 실패로 예외를 던지면 "에러를 만들다가 에러가 나는" 최악의 모양이 된다.
     */
    private String extractDetail(RestClientResponseException e) {
        try {
            JsonNode detail = objectMapper.readTree(e.getResponseBodyAsString()).path("detail");
            // Jackson 3 에서 isTextual() 이 isString() 으로 바뀌었다 (2.x 예제를 그대로 쓰면 deprecated 경고).
            return detail.isString() ? detail.asString() : null;
        } catch (RuntimeException ignored) {
            return null;
        }
    }

    /**
     * 응답을 아예 못 받은 실패 → "연결 안 됨(503)" 과 "너무 느림(504)" 을 구분한다.
     *
     * <p>구분하는 이유는 <b>사용자가 할 수 있는 행동이 다르기 때문</b>이다.
     * 연결이 안 되는 건 서비스가 내려간 것이라 기다리는 수밖에 없지만,
     * 느린 건 질문을 줄이면 성공할 수도 있다. 둘을 하나로 뭉개면 그 안내를 못 한다.
     *
     * <p>{@code HttpConnectTimeoutException} 을 먼저 보는 게 중요하다 —
     * 이 클래스가 {@code HttpTimeoutException} 을 상속하므로 순서를 바꾸면
     * <b>연결 실패가 읽기 타임아웃으로 잘못 분류된다.</b>
     */
    private ApiException translateIoFailure(String what, ResourceAccessException e) {
        Throwable cause = e.getCause();

        if (cause instanceof HttpConnectTimeoutException || cause instanceof ConnectException) {
            log.error("[AI 호출] {} 실패 — Python({}) 에 연결할 수 없다. 서비스가 떠 있는지 확인할 것.",
                    what, aiServiceProperties.baseUrl());
            return new ApiException(ErrorCode.AI_SERVICE_UNAVAILABLE);
        }
        if (cause instanceof HttpTimeoutException) {
            log.error("[AI 호출] {} 실패 — 읽기 타임아웃({}) 초과.", what, aiServiceProperties.readTimeout());
            return new ApiException(ErrorCode.AI_SERVICE_TIMEOUT);
        }

        // 그 외 I/O 실패(응답 도중 연결 끊김 등). Python 이 처리 중 죽은 경우가 여기 온다.
        log.error("[AI 호출] {} 실패 — Python 과의 통신이 끊겼다.", what, e);
        return new ApiException(ErrorCode.AI_SERVICE_UNAVAILABLE);
    }

    /**
     * 질문 → 답변. 이 프로젝트에서 유일하게 오래 걸리는(수십 초) 동기 호출이다.
     *
     * <p>응답의 {@code isFallback} 이 true 면 근거를 못 찾은 것이다.
     * 봇별 문구 치환은 여기가 아니라 ChatService 에서 한다(클라이언트는 Python 응답을 그대로 전달).
     */
    public AiChatResponse chat(AiChatRequest request) {
        // 4xx 매퍼를 넘기지 않는다 = 기본 처리(502). 채팅의 4xx·422 는 사용자가 고칠 수 있는 게 아니라
        // Spring 이 Python 스키마에 안 맞는 요청을 보낸 것이다. 길이 제한 같은 사용자 입력 문제는
        // ChatRequest 의 @Valid 가 이미 컨트롤러 진입 시점에 한국어 안내로 걸러낸다.
        return call("채팅", () -> aiServiceRestClient.post()
                .uri("/internal/chat")
                .contentType(MediaType.APPLICATION_JSON)
                .body(request)
                .retrieve()
                .body(AiChatResponse.class));
    }

    // ── 품질 평가 (W3) ──────────────────────────────────────────────────

    /**
     * 문서 청크에서 테스트 질문·정답 쌍을 자동 생성한다. <b>동기</b> 호출이다.
     *
     * <p>업로드·평가실행과 달리 202 가 아닌 이유는 Python 쪽 사정이다 —
     * {@code eval_questions} 에 상태 컬럼이 없어 202 를 줘도 프론트가 폴링할 대상이 없다.
     * 대신 Python 이 {@code count} 상한(기본 20)으로 응답 시간을 통제한다.
     *
     * <p>청크 1개당 LLM 을 1번 부르므로 {@code count} 가 곧 비용이자 지연이다.
     * 실측 기준 1건당 약 1.2초라 20건이면 25초 안팎 — 읽기 타임아웃(120초) 안이다.
     *
     * @param botId 호출 전에 <b>반드시 소유권을 검증</b>할 것. Python 에는 인증이 없다.
     */
    public List<AiEvalQuestionResponse> generateEvalQuestions(UUID botId, int count) {
        return call("평가 질문 생성", () -> aiServiceRestClient.post()
                        .uri("/internal/bots/{botId}/eval/questions/generate", botId)
                        .contentType(MediaType.APPLICATION_JSON)
                        .body(new AiGenerateQuestionsRequest(count))
                        .retrieve()
                        .body(new ParameterizedTypeReference<List<AiEvalQuestionResponse>>() {}),
                this::translateEvalClientError);
    }

    /**
     * 평가 실행 시작. Python 이 {@code running} 상태의 실행을 즉시 돌려주고 채점은 백그라운드로 돈다.
     *
     * <p>여기는 202 가 성립한다 — {@code eval_runs.status} 라는 <b>폴링할 대상</b>이 있기 때문이다.
     * 질문 수만큼 (검색 + 생성 + 채점)이 돌아 반드시 수십 초를 넘기므로 동기로 둘 수 없다.
     */
    public AiEvalRunResponse startEvalRun(UUID botId) {
        return call("평가 실행 시작", () -> aiServiceRestClient.post()
                        .uri("/internal/bots/{botId}/eval/runs", botId)
                        .retrieve()
                        .body(AiEvalRunResponse.class),
                this::translateEvalClientError);
    }

    // ── 문서 간 모순 진단 ────────────────────────────────────────────────

    /**
     * 문서끼리 어긋나는 곳을 훑는다. <b>동기</b> 호출이다.
     *
     * <p>평가 실행(202)과 다른 이유는 Python 쪽 사정이다 — {@code doc_conflicts} 에는
     * "스캔 한 번"을 가리키는 행이 없어 202 를 줘도 프론트가 폴링할 대상이 없다.
     * 대신 Python 이 판정할 쌍 수를 상한(기본 30)으로 묶어 응답 시간을 통제한다.
     * 판정 1건이 1~2초라 30쌍이면 읽기 타임아웃(120초) 안에 들어온다.
     *
     * <p>후보가 상한보다 많으면 가까운 쌍부터 처리하고 나머지는 남는다.
     * Python 이 "모순 아님"도 기록하므로 다시 부르면 <b>남은 것부터 이어서</b> 한다.
     *
     * @param botId 호출 전에 <b>반드시 소유권을 검증</b>할 것. Python 에는 인증이 없다.
     */
    public AiConflictScanResponse scanConflicts(UUID botId) {
        return call("문서 모순 스캔", () -> aiServiceRestClient.post()
                        .uri("/internal/bots/{botId}/conflicts/scan", botId)
                        .retrieve()
                        .body(AiConflictScanResponse.class),
                this::translateEvalClientError);
    }

    /**
     * 충돌 목록. {@code status} 기본값은 Python 쪽에서 {@code open} 이다.
     *
     * <p>Spring 이 DB 를 직접 읽지 않고 Python 을 부르는 이유: 이 목록은 단순 조회가 아니라
     * <b>청크 원문 4중 JOIN</b> 이다(충돌 → 청크A/B → 문서A/B). {@code chunks} 는
     * AGENTS.md 테이블 소유권상 <b>Spring 이 아예 건드리지 않는</b> 테이블이라,
     * 여기서 조인하면 그 규칙이 무너진다.
     */
    public List<AiConflictResponse> listConflicts(UUID botId, String status) {
        return call("문서 모순 목록", () -> aiServiceRestClient.get()
                        .uri(uriBuilder -> uriBuilder
                                .path("/internal/bots/{botId}/conflicts")
                                .queryParam("status", status)
                                .build(botId))
                        .retrieve()
                        .body(new ParameterizedTypeReference<List<AiConflictResponse>>() {}),
                this::translateEvalClientError);
    }

    /**
     * 충돌 1건의 상태 변경 (주로 오탐을 {@code ignored} 로 치우는 용도).
     *
     * <p><b>경로에 botId 가 반드시 들어간다.</b> conflictId 만 보내면 Python 의 UPDATE 가
     * 봇으로 좁혀지지 않아, id 만 알아내면 남의 봇 충돌을 치울 수 있다.
     * Python 쪽도 {@code WHERE id=? AND bot_id=?} 로 함께 좁힌다 — 두 겹이다.
     */
    public AiConflictResponse updateConflictStatus(UUID botId, UUID conflictId, String status) {
        return call("문서 모순 상태 변경", () -> aiServiceRestClient.patch()
                        .uri("/internal/bots/{botId}/conflicts/{conflictId}", botId, conflictId)
                        .contentType(MediaType.APPLICATION_JSON)
                        .body(new AiUpdateConflictStatusRequest(status))
                        .retrieve()
                        .body(AiConflictResponse.class),
                this::translateEvalClientError);
    }

    /**
     * <b>평가 전용</b> 4xx 변환. 업로드용({@link #translateUploadClientError})을 재사용하지 말 것.
     *
     * <p>재사용하면 어떻게 되는가 — 업로드 매퍼는 400 을 {@code UNSUPPORTED_FILE_TYPE} 으로 바꾼다.
     * 그러면 <b>"질문을 만들 문서가 없습니다" 상황에 "지원하지 않는 파일 형식입니다"가 나간다.</b>
     * 사용자는 멀쩡한 파일을 의심하며 엉뚱한 곳을 고치게 된다.
     *
     * <p>평가의 400 은 전부 <b>사용자가 고칠 수 있는</b> 상태다. Python 이 이미
     * "무엇을 어떻게 하면 되는지"까지 담은 한국어로 답한다:
     * <ul>
     *   <li>"처리가 끝난 문서가 없습니다. 문서를 올린 뒤 상태가 '준비됨'이 되면…"</li>
     *   <li>"이미 모든 문서 조각으로 질문을 만들었습니다. 새 문서를 올리거나…"</li>
     *   <li>"평가할 테스트 질문이 없습니다. 먼저 문서에서 질문을 생성한 뒤…"</li>
     *   <li>"한 번에 만들 수 있는 질문은 최대 20개입니다…"</li>
     * </ul>
     * 그래서 문구를 뭉개지 않고 <b>그대로 내려보낸다</b>(AGENTS.md 작업 규칙 4).
     * 상태 코드만 400 으로 맞추면 프론트가 "사용자가 고칠 수 있는 문제"로 읽는다.
     */
    private ApiException translateEvalClientError(RestClientResponseException e) {
        if (e.getStatusCode().isSameCodeAs(HttpStatus.BAD_REQUEST)) {
            return new ApiException(ErrorCode.EVAL_NOT_READY, extractDetail(e));
        }

        // 422 는 FastAPI 의 요청 검증 실패다 — Spring 이 스키마에 안 맞는 요청을 보낸 것이므로
        // 사용자 잘못이 아니다. 502 로 답하고 내부 사정을 설명하지 않는다.
        // 502(=AI_SERVICE_ERROR)는 Python 이 5xx 를 준 503 과 다르다: 여기는 "우리가 잘못 불렀다"이다.
        return new ApiException(ErrorCode.AI_SERVICE_ERROR);
    }

    /**
     * Python 서비스 헬스체크.
     *
     * <p>TODO(W2): Spring 의 {@code /actuator/health} 에 커스텀 HealthIndicator 로 물릴 것.
     *   Python 이 죽으면 채팅이 죽으므로, Spring 만 살아있고 health 가 UP 이면 거짓 신호가 된다.
     */
    public boolean isHealthy() {
        // TODO(W2): 구현. GET /health -> {"status":"ok"}
        throw new UnsupportedOperationException("AiServiceClient.isHealthy 미구현 (W2)");
    }

    // TODO(W3): /internal/eval/* 호출 메서드.
    //   Python 에 아직 해당 엔드포인트가 없다. W3 에서 Python 을 먼저 만든 뒤 여기에 추가한다.
    //   지금 시그니처를 미리 만들어두면 존재하지 않는 컨트랙트를 코드로 굳히게 되므로 두지 않는다.
}
