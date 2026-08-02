package com.alldap.api.domain.eval.dto;

import tools.jackson.databind.JsonNode;

/**
 * 평가 실행 시점의 검색 설정. 프론트의 {@code EvalConfig}({@code web/lib/types.ts})와 맞춘다.
 *
 * <p><b>이 객체가 W4 의 축이다.</b> "벡터 검색만 vs 하이브리드+리랭커" 비교표는
 * 같은 테스트셋을 설정만 바꿔 돌린 두 실행을 나란히 놓아 만든다.
 * 실행과 함께 설정이 박제돼 있지 않으면 "이 점수는 어떤 설정이었지?"를 알 수 없어
 * 비교 자체가 성립하지 않는다(PRD §9.3).
 *
 * <p><b>왜 Python 의 JSON 을 그대로 흘리지 않는가.</b> Python 은 snake_case 로 쓰고
 * ({@code top_k}, {@code max_distance}) 프론트는 camelCase 를 본다.
 * 표기 변환은 Spring 책임이다(AGENTS.md 작업 규칙 5).
 *
 * <p><b>모든 필드가 래퍼 타입이고 null 을 허용한다.</b> 옛 실행에는 없던 키가 있을 수 있다 —
 * 예를 들어 {@code embedding_model} 은 W3 중반에 추가됐다. {@code int}/{@code boolean} 으로
 * 받으면 없는 키가 0/false 로 채워져 <b>"기록되지 않음"과 "0이었음"이 구분되지 않는다.</b>
 * 비교표에서 그건 거짓말이 된다.
 */
public record EvalConfigResponse(
        Integer topK,
        /** 검색 단계에서 잘라내는 최대 코사인 거리 (환각 억제 1차 방어선) */
        Double maxDistance,
        /** 답변 생성에 쓴 모델 */
        String model,
        /** 임베딩에 쓴 모델. 이걸 바꾸면 검색 결과가 통째로 달라지므로 비교의 필수 축이다 */
        String embeddingModel,
        /** 채점에 쓴 모델. 생성 모델과 달라야 한다(자기 편향) */
        String judgeModel,
        /** W4: 키워드+벡터 하이브리드 사용 여부 */
        Boolean hybrid,
        /** W4: 리랭커 사용 여부 */
        Boolean reranker
) {

    /**
     * DB 에 JSON 문자열로 들어 있는 config 를 파싱한다.
     *
     * <p>파싱에 실패하면 <b>예외를 던지지 않고 null 을 돌려준다.</b>
     * config 하나가 깨졌다고 실행 이력 전체가 500 이 되면 안 된다 —
     * 점수는 멀쩡히 있는데 화면이 통째로 안 뜨는 게 더 나쁘다.
     *
     * @param configJson {@code EvalRun.getConfig()} 의 원본 문자열. null 일 수 있다.
     */
    public static EvalConfigResponse from(String configJson, tools.jackson.databind.ObjectMapper mapper) {
        if (configJson == null || configJson.isBlank()) {
            return null;
        }
        try {
            JsonNode n = mapper.readTree(configJson);
            return new EvalConfigResponse(
                    intOrNull(n, "top_k"),
                    doubleOrNull(n, "max_distance"),
                    textOrNull(n, "chat_model"),
                    textOrNull(n, "embedding_model"),
                    textOrNull(n, "judge_model"),
                    boolOrNull(n, "hybrid"),
                    boolOrNull(n, "reranker")
            );
        } catch (RuntimeException e) {
            return null;
        }
    }

    // 아래 네 개가 하는 일은 같다: "키가 없으면 null". Jackson 의 asInt() 등은
    // 없는 키에 0·false·"" 를 돌려주기 때문에 그대로 쓰면 위 클래스 주석의 문제가 생긴다.
    private static Integer intOrNull(JsonNode n, String key) {
        JsonNode v = n.path(key);
        return v.isNumber() ? v.asInt() : null;
    }

    private static Double doubleOrNull(JsonNode n, String key) {
        JsonNode v = n.path(key);
        return v.isNumber() ? v.asDouble() : null;
    }

    private static String textOrNull(JsonNode n, String key) {
        JsonNode v = n.path(key);
        // Jackson 3 에서 isTextual() → isString() 으로 바뀌었다.
        return v.isString() ? v.asString() : null;
    }

    private static Boolean boolOrNull(JsonNode n, String key) {
        JsonNode v = n.path(key);
        return v.isBoolean() ? v.asBoolean() : null;
    }
}
