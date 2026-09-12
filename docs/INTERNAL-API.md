# Python 내부 API 컨트랙트

> README 에 있던 "Python 내부 API 컨트랙트" 절을 옮겨온 문서입니다.
> Spring 이 이 규격에 맞춰 Python AI 서비스(:8001)를 호출합니다.

🔴 **`/internal/*` 에는 인증이 없습니다.** 외부에 노출하면 무방비입니다.
운영에서 Python 은 내부망에만 열려 있고, 밖에서 :8001 로 닿을 수 없는 것을 실측으로 확인했습니다.

JSON 필드는 전부 **snake_case** 입니다.
프론트가 보는 camelCase 로의 변환은 Spring 이 DTO 로 받아서 합니다.
Python 응답을 그대로 흘려보내지 않습니다.

## 문서 · 채팅

| 메서드 | 경로 | 요청 | 응답 |
|---|---|---|---|
| GET | `/health` | — | `{"status":"ok"}` |
| POST | `/internal/bots/{bot_id}/documents` | multipart, 필드명 **`file`** | `202` + `DocumentOut` |
| GET | `/internal/bots/{bot_id}/documents` | — | `DocumentOut[]` |
| DELETE | `/internal/bots/{bot_id}/documents/{doc_id}` | — | `204` |
| POST | `/internal/chat` | `{bot_id, message(1~2000자), session_id(≤64자)}` | `ChatResponse` |

```
DocumentOut  = { id, filename, file_type, status, error_message, char_count, chunk_count }
               status ∈ pending | processing | ready | failed
ChatResponse = { answer, sources[], is_fallback, latency_ms }
Source       = { chunk_id, document_id, filename, score, preview }
               score 는 0~1 (1 - 코사인거리, 높을수록 관련성 높음), preview 는 본문 앞 200자
```

## 평가 · 문서 충돌 스캔

| 메서드 | 경로 | 하는 일 |
|---|---|---|
| POST | `/internal/bots/{bot_id}/eval/questions/generate` | 청크 표본에서 (질문, 정답) 쌍 생성 (동기 200, 재호출은 누적) |
| GET · PATCH | `/internal/bots/{bot_id}/eval/questions[/{id}]` | 테스트 질문 목록 · 부분 수정 |
| POST · GET | `/internal/bots/{bot_id}/eval/runs` | 평가 실행 (202 + 폴링) · 실행 이력 |
| POST · GET · PATCH | `/internal/bots/{bot_id}/conflicts[/scan\|/{id}]` | 문서끼리 어긋나는 곳 스캔 · 목록 · 오탐 치우기 |

정확한 요청·응답 스키마는 `ai-service/app/schemas.py` 와 자동 생성 문서(`/docs`)를 보세요.
문서에 전부 옮겨 적으면 반드시 어긋납니다.

## Spring 이 실패를 어떻게 번역하는가

**실패 변환은 `AiServiceClient` 안에서 끝냅니다.** 호출 지점마다 try-catch 를 적으면
한 곳이 빠지고, 거기서 `RestClientException` 이 그대로 올라가 500 이 나갑니다.
"Python 이 죽었다" 가 "우리 서버가 고장났다" 로 둔갑합니다.

**코드를 나누는 기준은 "누구 잘못인가" 입니다.**

| Python 쪽 사정 | Spring 이 내보내는 것 |
|---|---|
| 연결 안 됨 | 503 |
| 느림 (타임아웃) | 504 |
| Python 5xx | 503 |
| Python 4xx | 400 계열 (사용자 입력 문제) |

- ⚠️ **응답 헤더가 온 뒤** 끊기면 `ResourceAccessException` 이 아니라
  `RestClientException(cause=IOException)` 으로 옵니다. 둘 다 처리해야 합니다.
- **4xx 해석은 엔드포인트마다 다릅니다.** 업로드의 400 은 "파일이 잘못됐다"(사용자가 고칠 수 있다),
  채팅의 400·422 는 "우리가 잘못 호출했다"(사용자는 손쓸 수 없다). `call()` 에 4xx 매퍼를 넘겨
  구분합니다. 하나로 묶으면 **채팅 오류에 "지원하지 않는 파일 형식입니다" 가 나갑니다.**
- **소유권 확인은 Python 을 부르기 전에** 합니다. `/internal/*` 에는 인증이 없어서,
  요청이 거기 도달한 시점에 이미 샌 것입니다. 테스트도 "404 가 났다" 가 아니라
  **"요청이 Python 까지 가지 않았다"** 를 확인합니다.

## 재시도 · 서킷브레이커 (2026-08-17)

`AiServiceClient.call()` 안에 있습니다. resilience4j 대신 직접 만들었습니다
(Boot 4 호환 미확인 + 필요한 게 상태 3개짜리 카운터).

🔴 **재시도는 연결 실패에만 합니다.** 재시도의 전제는 "직전 시도가 아무 일도 하지 않았다" 인데,
그게 보장되는 것은 연결이 안 된 경우뿐입니다. **5xx 는 Python 이 응답했다 = 요청이 도달했다**
이므로, 재시도하면 문서 행이 중복되거나 LLM 이 두 번 과금됩니다.

🔴 **서킷은 4xx 와 DTO 불일치를 실패로 세지 않습니다.** 그건 Python 장애가 아니라 우리 잘못이라,
세면 **우리 버그로 멀쩡한 Python 을 차단**하게 됩니다.

⚠️ 상태를 가진 싱글턴이라 통합 테스트마다 `circuitBreaker.reset()` 이 필요합니다.
안 하면 5xx 테스트가 누적돼 서킷이 열리고, 실행 순서에 따라 나타났다 사라지는 실패가 납니다.

## 봇별 설정(`system_prompt` · `fallback_message`)은 이 요청에 실리지 않는다

`POST /internal/chat` 은 **둘 중 어느 것도 받지 않습니다.** 이건 지금도 사실입니다.
그런데 **둘 다 실제로 반영됩니다.** 반영 경로가 서로 다를 뿐입니다.

- `fallback_message` → Spring 이 응답의 `is_fallback == true` 를 보고 봇의 문구로 **치환**한다.
  (`ChatService.resolveAnswer`. Python 은 봇별 문구를 모른다)
- `system_prompt` → **Python 이 `bots` 테이블에서 직접 읽는다.** (2026-08-13부터, PRD F-06 충족)
  `ai-service/app/generator.py` 의 `fetch_bot_prompt` + `build_system_prompt`.

**왜 Spring 이 실어 보내지 않고 Python 이 직접 읽는가.** 성능이 아니라 **평가** 때문입니다.
`evalrun` 은 Spring 을 거치지 않으므로, Spring 이 실어 보내는 방식이면 평가만 기본 프롬프트로 돌아
"평가에서는 좋았는데 실사용은 다르다" 가 됩니다. 부수 효과로 Spring 은 한 줄도 고치지 않았습니다.

→ **`AiChatRequest` 에 `system_prompt` 필드를 추가하지 마세요.** 경로가 둘이 되면 어느 쪽이
이겼는지 알 수 없어지고, 평가와 실사용이 다시 갈라집니다.

⚠️ **한계: 봇 지침으로 `NO_ANSWER` 규칙을 뚫을 수 있다는 것이 실측됐습니다.** 결합은 대체가
아니라 덧붙임이고("충돌하면 봇 지침이 우선") 기본 규칙을 앞에 두지만, 프롬프트로 프롬프트를
막는 데는 한계가 있습니다. 막지 못하니 대신 **잽니다**:

```bash
cd ai-service && .venv/bin/python -m app.bot_prompt_check
```

봇 지침을 설정하거나 바꾼 뒤 이걸 돌려 깨지는지 보세요.

## 에러 응답 포맷 (전 계층 공통)

Spring · Python · Next.js 가 전부 같은 모양을 씁니다.

```json
{ "error": { "code": "...", "message": "무엇을 어떻게 하면 되는지까지 담은 한국어 설명" } }
```

🔴 **재시도로 안 풀리는 실패는 그렇게 안내하지 않습니다.** 2026-09-09 에 두 경로를 갈랐습니다.

| 코드 | 상태 | 왜 재시도가 안 통하는가 |
|---|---|---|
| `ANSWER_INCOMPLETE` | 422 | 답변이 잘린 것. `temperature=0` 이라 다시 물어도 같은 자리에서 잘린다 |
| `BILLING_METHOD_UNREADABLE` | 500 | 빌링키 복호화 실패. 키 분실·손상·변조 중 하나다 |

⚠️ `ANSWER_INCOMPLETE` 를 위해 **컨트랙트를 하나 바꿨습니다.** Python chat 의 503 `detail` 이
문자열에서 `{"code":"GENERATION_INCOMPLETE","message":...}` 객체가 됐습니다. 상태 코드로는
가를 수 없어서입니다(잘림도 503, Python 이 정말 아픈 것도 503).
지금은 Python 의 503 이 이 자리 하나뿐이라 우연히 신호 노릇을 하지만,
**503 이 하나만 더 생기면 조용히 뭉개집니다.**
