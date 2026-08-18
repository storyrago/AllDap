"""API 입출력 스키마."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class DocumentOut(BaseModel):
    id: UUID
    filename: str
    file_type: str
    status: str
    error_message: str | None = None
    char_count: int | None = None
    chunk_count: int | None = None


class Source(BaseModel):
    chunk_id: UUID
    document_id: UUID
    filename: str
    score: float = Field(description="0~1, 높을수록 관련성 높음")
    preview: str


class ChatRequest(BaseModel):
    bot_id: UUID
    message: str = Field(min_length=1, max_length=2000)
    session_id: str = Field(default="local-test", max_length=64)


class ChatResponse(BaseModel):
    answer: str
    sources: list[Source]
    is_fallback: bool
    latency_ms: int


# ── 품질 평가 (W3) ────────────────────────────────────────────────────

class GenerateQuestionsRequest(BaseModel):
    """테스트 질문 자동 생성 요청.

    count 에 상한을 두는 이유: 청크 1개당 LLM 을 1번 부르므로 이 숫자가 곧 비용이다.
    상한 없이 받으면 요청 하나로 문서 전체를 태울 수 있고, Spring 의 읽기 타임아웃(120초)도 넘긴다.
    실제 상한값은 설정(eval_max_questions)에 있고, 라우트에서 그 값과 대조한다.
    여기 Field 의 le 에 설정값을 못 넣는 이유는 pydantic 모델이 <클래스 정의 시점>에
    한 번 만들어지기 때문이다 — 그때는 .env 를 읽기 전일 수 있다.
    """

    count: int = Field(default=10, ge=1, description="만들 질문 수 (상한은 서버 설정)")


class UpdateEvalQuestionRequest(BaseModel):
    """테스트 질문 수정. <부분 수정>이라 셋 다 선택적이다 (PATCH).

    왜 셋을 나눠 받는가 — 고치는 이유가 서로 다르기 때문이다:
      · question      LLM 이 만든 문장이 어색하거나 모호할 때
      · ground_truth  정답이 틀렸을 때. <채점 기준>이라 이게 틀리면 점수 전체가 거짓이 된다
      · is_active     문항을 평가에서 <빼되 지우지는 않을> 때

    🔴 **`ground_truth` 를 고치면 과거 실행과 비교할 수 없게 된다.**
       `eval_results` 는 <그때의 정답>으로 채점된 값이다. 기준을 바꿔놓고 이전 숫자와
       나란히 놓으면, 설정 때문에 달라진 것인지 채점 기준이 달라진 것인지 구분할 수 없다.
       이 저장소가 반복해 낸 부류 — 원인이 다른 두 사실을 같은 값으로 뭉개는 것 — 그대로다.
       문항이 마음에 안 들면 <고치기보다 `is_active=false` 로 빼는 편>이 안전하다.
       그러면 과거 실행은 그대로 두고 앞으로만 달라진다.

    ⚠️ None 과 "값을 안 보냄" 을 구분해야 한다. pydantic 기본값 None 은 후자를 뜻하고,
       아래 update 구현이 <보낸 필드만> SET 한다. 셋 다 안 보내면 400 이다.
    """

    question: str | None = Field(default=None, min_length=1, max_length=500)
    ground_truth: str | None = Field(default=None, min_length=1, max_length=2000)
    is_active: bool | None = None


class EvalQuestionOut(BaseModel):
    """테스트 질문 1건.

    필드 이름이 snake_case 인 이유: Python 은 snake_case 로 내보내고
    Spring 이 DTO 로 받아 camelCase 로 바꿔 프론트에 준다 (AGENTS.md 작업 규칙 5).
    프론트의 EvalQuestion(web/lib/types.ts)과 필드가 1:1 로 대응한다.
    """

    id: UUID
    question: str
    ground_truth: str
    source_chunk_id: UUID | None = None
    is_active: bool
    created_at: datetime


class EvalRunOut(BaseModel):
    """평가 실행 1건.

    점수가 전부 `| None` 인 이유:
      · status='running' 이면 아직 안 나왔다
      · 채점에 전부 실패했거나 답변이 전부 fallback 이면 평균을 낼 대상이 없다
    0.0 으로 채우면 "점수가 0점"과 "아직 없음"이 구분되지 않는다.
    """

    id: UUID
    status: str
    config: dict | None = None
    avg_faithfulness: float | None = None
    avg_relevancy: float | None = None
    answered_rate: float | None = None
    created_at: datetime


class EvalResultOut(BaseModel):
    """질문 1건의 채점 결과.

    faithfulness / relevancy 가 None 이면 <채점하지 못했다>는 뜻이다. 0점이 아니다.
    (fallback 이라 채점 대상이 아니었거나, 채점 호출이 실패했거나)
    """

    question_id: UUID
    question: str
    ground_truth: str
    generated_answer: str | None = None
    retrieved_chunks: list[dict] = []
    faithfulness: float | None = None
    relevancy: float | None = None


class ConflictOut(BaseModel):
    """문서 간 사실 충돌 1건.

    화면이 <두 청크 원문을 다 읽지 않고도> 무엇이 문제인지 알 수 있어야 한다.
    그래서 판정 요약(topic/a_says/b_says)과 원문(a_content/b_content)을 함께 준다 —
    요약만 주면 관리자가 판정을 검증할 수 없고, 원문만 주면 매번 다 읽어야 한다.
    """

    id: UUID
    topic: str
    a_says: str
    b_says: str
    a_filename: str
    b_filename: str
    a_content: str
    b_content: str
    distance: float | None = None
    status: str
    created_at: datetime


class ConflictScanOut(BaseModel):
    """스캔 한 번의 결과.

    네 숫자를 <따로> 준다. "깨끗해서 0건"과 "못 재서 0건"은 다른 사실인데,
    합쳐 놓으면 구분이 안 된다 — 이 프로젝트가 그 부류의 버그를 네 번 냈다.
    """

    candidates: int
    judged: int
    conflicts: int
    failed: int


class ConflictStatusRequest(BaseModel):
    """충돌 1건의 상태 변경.

    ignored 는 <오탐 표시>다. 이걸 못 하면 헛짚은 항목이 목록에 영원히 남고,
    관리자는 화면 자체를 안 보게 된다 — 기능이 없는 것과 같아진다.
    """

    status: Literal["open", "ignored", "resolved"]
