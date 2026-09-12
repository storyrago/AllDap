# 조사: DocumentController 3개 엔드포인트의 실제 에러 응답 (2026-09-13)

**왜 조사했나:** Swagger PR 2(엔드포인트별 `@ApiResponse`)를 쓰기 전에, 각 엔드포인트가
<실제로> 낼 수 있는 응답이 무엇인지 확인하려고 했다. `ErrorCode` 에 정의돼 있다고 해서
그 엔드포인트에서 난다는 뜻이 아니기 때문이다. 없는 응답을 문서에 적으면 문서가 거짓말을 한다.

🔴 **PR 2 는 하지 않기로 했다(2026-09-13).** 이 API 를 쓰는 곳이 `web/` 하나뿐이고 이미 완성돼
있어서, 엔드포인트별 에러 문서화가 "아직 없는 사용자를 위한 문서" 였다. 근거는 `docs/decisions.md`
2026-09-13 항목. **이 파일은 그때 한 조사를 보존한 것이다** - 나중에 PR 2 를 하기로 하면
같은 조사를 다시 할 필요가 없다.

📌 **PR 2 와 무관하게 값어치가 남는 것 셋.** 이 조사가 실제로 찾아낸 사실들이다.
1. **`LEGACY_HWP_NOT_SUPPORTED` 는 죽은 코드다.** 정의만 있고 사용처가 0건이다.
   구버전 `.hwp` 는 실제로 `UNSUPPORTED_FILE_TYPE` 으로 나간다.
2. **업로드와 삭제의 4xx 해석이 다르다.** 업로드는 `translateUploadClientError` 를 넘기지만
   삭제는 매퍼를 안 넘겨 4xx 가 전부 502 다. 같은 컨트롤러인데 표를 복사하면 틀린다.
3. **`GET` 목록은 Python 을 아예 안 부른다.** DB 직접 조회라 502·503·504 가 날 수 없다.

⚠️ **조사 시점은 `main` 의 `59f86e9` 다.** 코드가 바뀌면 아래 파일:줄 근거가 낡는다.
줄 번호가 안 맞으면 그 항목은 다시 확인할 것.

---

기준 커밋: main / 59f86e9. 모든 줄번호는 `api/src/main/java/com/alldap/api/...`.

## 0. 세 엔드포인트 공통으로 나갈 수 있는 것

| HTTP | ErrorCode | 언제 | 근거 | 확신 |
|---|---|---|---|---|
| 401 | AUTHENTICATION_REQUIRED | Authorization 헤더 없음 | ApiAuthenticationEntryPoint.java:40, SecurityConfig.java:135 (anyRequest().authenticated()) | 확실 |
| 401 | INVALID_TOKEN | 토큰이 있으나 만료·서명불일치·형식오류 | JwtAuthenticationFilter.java:102-103, JwtService.java:254 (필터가 기록 → EntryPoint 가 읽어 치환) | 확실 |
| 400 | INVALID_INPUT | 경로변수 UUID 자리에 비-UUID (`/api/bots/hello/documents`) | GlobalExceptionHandler.java:153-161 | 확실 |
| 405 | METHOD_NOT_ALLOWED | 주소는 맞고 메서드가 틀림 (Allow 헤더 동봉) | GlobalExceptionHandler.java:104-118 | 확실 |
| 500 | INTERNAL_ERROR | 예상 못 한 예외 (catch-all) | GlobalExceptionHandler.java:257-263 | 확실 |

> 404 RESOURCE_NOT_FOUND(NoResourceFoundException, :249)는 **매핑 자체가 없는 경로**에서만 난다. 이 세 엔드포인트는 매핑이 있으므로 해당 없음.
> 403 ACCESS_DENIED(ApiAccessDeniedHandler)는 이 경로들에 역할 기반 인가가 없어 실제로는 나가지 않는다. (추정: 높음)
> rate limit(429)은 `/api/w/**` 와 로그인에만 걸린다 - 문서 경로에는 없다. (확실)

---

## 1. POST /api/bots/{botId}/documents - 업로드

**성공: 202 Accepted, 본문 `DocumentResponse`** (DocumentController.java:51 `ResponseEntity.accepted()`).
201 이 아닌 이유가 주석에 명시돼 있다(:49-50): 문서 행은 생겼지만 처리는 안 끝났다. 201 이면 프론트가 "다 됐다"로 읽고 폴링을 안 한다.

**요청 (multipart/form-data)**
- 파트 이름: **`file`** (필수). `@RequestPart("file") MultipartFile` (:47). 이름이 `file` 인 이유는 FastAPI 의 `File(...)` 파라미터명과 맞추기 위함 (:37-39, AiServiceClient.java:100).
- 경로변수 `botId`: UUID.
- 상한: **20MB** (`application.yaml:41-42` max-file-size / max-request-size). 운영은 `application-prod.yaml:37-38` `${UPLOAD_MAX_SIZE:20MB}` 로 환경변수화. Python 쪽도 20MB (`ai-service/app/config.py:350 upload_max_bytes`).
- 확장자 검증은 **Spring 에 없다** - 단일 기준은 Python `detect_type()` (DocumentService.java:65-68).

**나갈 수 있는 에러**

| HTTP | ErrorCode | 언제 | 근거 | 확신 |
|---|---|---|---|---|
| 400 | INVALID_INPUT | multipart 에 `file` 파트가 없음 (필드명 오타 포함). 메시지: "업로드할 파일을 찾을 수 없습니다. … 'file' 로 지정해 다시 보내주세요." | GlobalExceptionHandler.java:133-140 | 확실 |
| 404 | BOT_NOT_FOUND | 없는 봇 **또는 남의 봇**. 403 이 아니다(존재 여부 탐지 방지) | DocumentService.java:141-144 | 확실 |
| 400 | EMPTY_FILE | 0바이트 파일. Python 가기 전에 Spring 이 막는다 | DocumentService.java:56-58 | 확실 |
| **413** | FILE_TOO_LARGE | 20MB 초과. **Spring multipart 단계에서 막힌다** (요청이 Python 까지 가지 않음) | GlobalExceptionHandler.java:169-175 (MaxUploadSizeExceededException) | 확실 |
| 413 | FILE_TOO_LARGE | (드묾) Python 이 413 을 준 경우. 두 상한이 어긋났을 때만 도달 | AiServiceClient.java:341-343 + ai-service/app/main.py:226-227 | 확실 |
| **400** | **LEGACY_HWP_NOT_SUPPORTED 가 아니라 UNSUPPORTED_FILE_TYPE** | 구버전 `.hwp` 및 그 밖의 미지원 확장자. **아래 🔴 참고** | AiServiceClient.java:344-346, parsers.py:23-29 | 확실 |
| 500 | INTERNAL_ERROR (문구 치환) | 업로드 본문을 읽다 IOException. "파일을 읽는 중 문제가 발생했습니다. 다시 올려주세요." | AiServiceClient.java:132-146 | 확실 |
| **503** | AI_SERVICE_UNAVAILABLE | ① Python 연결 실패(재시도 후에도) ② Python 5xx ③ 응답 도중 연결 끊김 ④ **서킷 열림** | AiServiceClient.java:238-243(서킷), :275-278(5xx), :481-494(연결), :295-301(끊김) | 확실 |
| **504** | AI_SERVICE_TIMEOUT | 읽기 타임아웃 (연결은 됐는데 응답이 늦음) | AiServiceClient.java:467-494 | 확실 |
| **502** | AI_SERVICE_ERROR | ① Python 4xx 중 400·413 이 **아닌** 것(404·422 등) ② 응답 JSON 이 DTO 와 안 맞음(decode 실패) | AiServiceClient.java:348-350, :304-312 | 확실 |
| 415 | UNSUPPORTED_MEDIA_TYPE | Content-Type 이 multipart/form-data 가 아님 | GlobalExceptionHandler.java:90-96 | **추정** (HttpMediaTypeNotSupportedException 이 이 경로에서 실제로 던져지는지 실측 안 함) |

🔴 **`.hwp` 는 `LEGACY_HWP_NOT_SUPPORTED` 로 나가지 않는다.**
경로: parsers.py:25-26 이 ParseError("구버전 .hwp는 아직 지원하지 않습니다. 한글에서 .hwpx로 저장 후 올려주세요.") → main.py:236 `HTTPException(400, str(e))` → `translateUploadClientError` 가 **400 이면 무조건 `UNSUPPORTED_FILE_TYPE`** (AiServiceClient.java:344-346), **다만 detail 문구를 그대로 실어 보낸다**(`extractDetail`, :360-).
즉 사용자가 보는 최종 응답은:
```
HTTP 400  {"error":{"code":"UNSUPPORTED_FILE_TYPE",
  "message":"구버전 .hwp는 아직 지원하지 않습니다. 한글에서 .hwpx로 저장 후 올려주세요."}}
```
→ **ErrorCode `LEGACY_HWP_NOT_SUPPORTED` 는 enum 에 정의만 돼 있고 이 경로에서 나가지 않는다.** Swagger 에 적으면 거짓말이 된다. (grep 으로 사용처 없음 확인 - 확실)
같은 이유로 암호 걸린 PDF, 미지원 확장자도 전부 `UNSUPPORTED_FILE_TYPE` + Python 한국어 문구다.

**4xx 매퍼 정리 (`translateUploadClientError`, :335-351)**
- Python 413 → `FILE_TOO_LARGE` + Python 문구
- Python 400 → `UNSUPPORTED_FILE_TYPE` + Python 문구
- 그 밖의 4xx(404·422 등) → `AI_SERVICE_ERROR`(502), **문구는 기본값**(내부 사정을 숨긴다)

**서킷브레이커** (AiServiceClient.java:238-243): 열려 있으면 호출하지 않고 즉시 **503 AI_SERVICE_UNAVAILABLE**. 사용자 응답은 연결 실패와 동일하고 구분은 지표(`AiServiceMetrics`, Outcome.CIRCUIT_OPEN)에서만 한다. 임계·지속시간은 `AiServiceProperties.circuitFailureThreshold/circuitOpenDuration`.
**4xx·DTO 불일치·ANSWER_INCOMPLETE 는 서킷 실패로 세지 않는다**(:255-273) - 우리 잘못으로 멀쩡한 Python 을 차단하지 않기 위해.

**재시도** (`attemptWithRetry`, :429-448): **연결 실패에만** 재시도. 읽기 타임아웃·5xx·4xx 는 재시도 안 함(요청이 이미 도달했으므로 중복 부작용).

**ANSWER_INCOMPLETE(422)는 업로드에 해당 없음** (추정: 매우 높음). `detail.code == GENERATION_INCOMPLETE` 는 Python 의 채팅 생성 경로에서만 실린다.

---

## 2. GET /api/bots/{botId}/documents - 목록

**성공: 200 OK, `List<DocumentResponse>`** (DocumentController.java:59).

🔴 **이 엔드포인트는 Python 을 호출하지 않는다.** `documentRepository` 로 DB 를 직접 읽는다(DocumentService.java:99-105). 근거는 :74-98 주석 - ① Python `DocumentOut` 에 `created_at` 이 없어 업로드 시각을 못 채운다 ② 폴링 대상이라 Python 이 죽어도 목록은 보여야 한다.
→ **AI_SERVICE_* (502/503/504) 는 이 엔드포인트에서 나지 않는다.** (확실)

| HTTP | ErrorCode | 언제 | 근거 |
|---|---|---|---|
| 200 | - | 성공 (문서 0건이면 빈 배열) | DocumentService.java:102 |
| 401 | AUTHENTICATION_REQUIRED / INVALID_TOKEN | 공통 | 위 §0 |
| 404 | BOT_NOT_FOUND | 없는 봇 또는 남의 봇 | DocumentService.java:141-144 |
| 400 | INVALID_INPUT | botId 가 UUID 가 아님 | GlobalExceptionHandler.java:153-161 |
| 500 | INTERNAL_ERROR | catch-all (DB 장애 등) | :257-263 |

**정렬**: `findAllByBotIdOrderByCreatedAtDesc` - 최신순.

---

## 3. DELETE /api/documents/{docId} - 삭제

**성공: 204 No Content, 본문 없음** (DocumentController.java:68 `ResponseEntity.noContent()`). 반환 타입 `ResponseEntity<Void>`.

경로에 botId 가 없어 문서 → 봇 → 소유자로 거슬러 확인한다(`findByIdAndBotUserId`, DocumentService.java:117).

| HTTP | ErrorCode | 언제 | 근거 | 확신 |
|---|---|---|---|---|
| 204 | - | 성공 (chunks 는 DB CASCADE) | :68 | 확실 |
| 401 | AUTHENTICATION_REQUIRED / INVALID_TOKEN | 공통 | §0 | 확실 |
| **404** | **DOCUMENT_NOT_FOUND** | 없는 문서 **또는 남의 문서**(403 아님) | DocumentService.java:117-118 | 확실 |
| 400 | INVALID_INPUT | docId 가 UUID 가 아님 | GlobalExceptionHandler.java:153-161 | 확실 |
| 503 | AI_SERVICE_UNAVAILABLE | Python 연결 실패 / Python 5xx / 응답 중 끊김 / **서킷 열림** | AiServiceClient.java:181-190 + call() | 확실 |
| 504 | AI_SERVICE_TIMEOUT | 읽기 타임아웃 | :467-494 | 확실 |
| **502** | AI_SERVICE_ERROR | Python 4xx **전부** (삭제는 4xx 매퍼를 넘기지 않아 기본 매퍼 사용) | AiServiceClient.java:182(매퍼 없음) + :213-216(기본 = AI_SERVICE_ERROR) | 확실 |
| 500 | INTERNAL_ERROR | catch-all | :257-263 | 확실 |

🔴 **삭제는 업로드 매퍼를 쓰지 않는다.** `deleteDocument` 는 `call(op, action)` 2인자 버전을 부르므로 4xx → 전부 **502 AI_SERVICE_ERROR**. Swagger 에 `UNSUPPORTED_FILE_TYPE` 같은 걸 적으면 안 된다.
🔴 **DOCUMENT_NOT_FOUND 는 Python 이 아니라 Spring 이 낸다.** Python 의 DELETE 는 없는 id 도 204 다(main.py:290-296). 존재 판단은 Spring 이 호출 전에 끝낸다(AiServiceClient.java:191-194 주석).
⚠️ 삭제는 **멱등이 아니다**: 두 번째 호출은 Spring DB 조회에서 404 가 난다.

---

## 4. `status` 가 가질 수 있는 값 (프론트 폴링용 - 정확)

`documents.status VARCHAR(20) NOT NULL`. **네 개뿐이고, 전부 Python 이 쓴다.**

| 값 | 뜻 | 누가 쓰는가 |
|---|---|---|
| `pending` | 업로드 접수됨, 아직 처리 시작 전 | INSERT 시 (main.py:240-243) |
| `processing` | 파싱·청킹·임베딩 진행 중 | main.py:178 |
| `ready` | 완료. `char_count`·`chunk_count` 가 채워지고 `error_message` 는 NULL 로 초기화 | main.py:208-212 |
| `failed` | 실패. `error_message` 에 한국어 사유 | main.py:170-174 (`_fail`) |

`failed` 의 `error_message` 예: 파싱 실패 시 `ParseError` 문구 그대로, 청크 0개면 "문서에서 유효한 내용을 찾지 못했습니다.", 그 외 "처리 중 오류가 발생했습니다: {예외타입}".

⚠️ **Spring 은 이 값을 enum 이 아니라 String 으로 들고 있다** (Document.java:78-87). 의도적이다 - Python 이 상태를 하나 추가해도 Spring 이 목록 조회에서 터지지 않게. 즉 **Swagger 에 enum 으로 못박으면 배포 순서에 강하게 만든 설계를 문서가 되돌리는 셈**이다. `allowableValues` 대신 description 에 나열하는 쪽을 권한다. (판단, 구현은 안 함)

**업로드 응답의 status 는 사실상 항상 `pending`** (main.py:247). 다만 `DocumentResponse.from(AiDocumentResponse)` 는 **`createdAt` 을 null 로 박는다** (DocumentResponse.java:31-44) - Python `DocumentOut` 에 `created_at` 이 없어서다. 목록(DB 조회) 경로에서만 채워진다.

**필드 (camelCase, 변환 지점은 DocumentResponse)**
`id`(UUID) · `filename`(String) · `fileType`(pdf/docx/hwpx/txt/md) · `status` · `errorMessage`(nullable) · `charCount`(nullable) · `chunkCount`(nullable) · `createdAt`(Instant, **업로드 응답에서는 항상 null**)

---

## 5. `description` 에 쓸 재료

- **왜 202 인가**: 임베딩이 수십 초 걸릴 수 있어 HTTP 요청을 붙잡으면 타임아웃이 난다. 그래서 Python 은 `documents` 행만 만들고 즉시 202(pending)로 답하고, 파싱·청킹·임베딩은 `BackgroundTasks` 로 돈다 (DocumentService.java:46-48, main.py:217-247).
- **누가 상태를 갱신하는가**: **Python 이 `documents` 의 쓰기 소유자다.** Spring 은 읽기만 한다 (AGENTS.md 테이블 소유권, DocumentService.java:91-93). 삭제도 Spring 이 직접 DELETE 하지 않고 Python 에 위임한다 (DocumentService.java:120-121).
- **프론트가 완료를 어떻게 아는가**: `GET /api/bots/{botId}/documents` 를 **폴링**해 `status` 가 `ready` 또는 `failed` 가 되는 것을 본다 (DocumentService.java:72).
- **목록이 Python 을 안 거치는 이유**: 위 §2. 폴링 경로라 Python 장애 시에도 목록이 보여야 하고, `createdAt` 을 채우려면 어차피 DB 를 읽어야 한다.
- **한계(솔직하게 적을 것)**: 백그라운드 처리가 FastAPI `BackgroundTasks` 라 **프로세스가 죽으면 작업이 유실되고 문서는 `processing` 에 멈춘다** (main.py:163-165 주석). 타임아웃도 재시도도 없다.
- **삭제 시 chunks 는 DB `ON DELETE CASCADE` 로 함께 사라진다.** 되돌릴 수 없다.

---

## 6. PR 2 에서 특히 조심할 것 (조사 중 발견)

1. **`LEGACY_HWP_NOT_SUPPORTED` 를 업로드에 달지 말 것.** enum 에 있지만 이 경로로 나가지 않는다. 실제로는 `UNSUPPORTED_FILE_TYPE` + Python 문구다.
2. **`ACCESS_DENIED`(403) 를 봇/문서 접근에 달지 말 것.** 이 저장소는 남의 리소스를 404 로 답한다(AGENTS.md 명시).
3. **`ANSWER_INCOMPLETE`(422) 는 채팅 전용.** 문서 경로에 달면 거짓이다.
4. **업로드와 삭제의 4xx 해석이 다르다.** 업로드 400 → `UNSUPPORTED_FILE_TYPE`, 삭제 400 → `AI_SERVICE_ERROR`(502). 같은 표를 복붙하면 틀린다.
5. **목록에는 AI_SERVICE_* 를 달지 말 것.** Python 을 안 부른다.
6. **413 은 대부분 Spring multipart 단계**라 요청이 Python 에 닿지 않는다. description 에 그 사실을 적으면 운영 진단에 도움이 된다.
