package com.alldap.api.global.client;

/**
 * Python AI 서비스 호출의 <b>종류</b>. 로그 문구와 지표 태그를 한 곳에 묶어둔다.
 *
 * <p><b>왜 enum 인가.</b> 그전에는 {@code call("채팅", ...)} 처럼 한국어 문자열을 그대로 넘겼다.
 * 로그만 볼 때는 그게 제일 읽기 좋지만, 같은 문자열을 지표 태그로 쓰면 PromQL 이
 * {@code alldap_ai_call_seconds_count{operation="문서 모순 상태 변경"}} 이 된다.
 * 공백과 한글이 섞인 라벨은 쿼리에서 다루기 나쁘고, 무엇보다 <b>오타를 아무도 못 잡는다</b> —
 * 호출부에서 한 글자만 달라져도 지표가 조용히 두 시계열로 갈라진다.
 * enum 으로 두면 컴파일러가 그걸 막고, 사람이 읽는 {@link #label} 과 기계가 읽는 {@link #tag} 를
 * 따로 둘 수 있다.
 *
 * <p>{@code tag} 는 ASCII 소문자·언더스코어로만 쓴다(Prometheus 라벨 관례).
 */
public enum AiOperation {

    DOCUMENT_UPLOAD("문서 업로드", "document_upload"),
    DOCUMENT_DELETE("문서 삭제", "document_delete"),
    CHAT("채팅", "chat"),
    EVAL_QUESTIONS_GENERATE("평가 질문 생성", "eval_questions_generate"),
    EVAL_QUESTION_UPDATE("평가 질문 수정", "eval_question_update"),
    EVAL_RUN_START("평가 실행 시작", "eval_run_start"),
    CONFLICT_SCAN("문서 모순 스캔", "conflict_scan"),
    CONFLICT_LIST("문서 모순 목록", "conflict_list"),
    CONFLICT_STATUS_UPDATE("문서 모순 상태 변경", "conflict_status_update");

    private final String label;
    private final String tag;

    AiOperation(String label, String tag) {
        this.label = label;
        this.tag = tag;
    }

    /** 로그에 찍는 한국어 이름. */
    public String label() {
        return label;
    }

    /** 지표 태그 값. */
    public String tag() {
        return tag;
    }

    /** 로그 포맷({@code {}})에 그대로 넣어도 한국어가 나오도록. */
    @Override
    public String toString() {
        return label;
    }
}
