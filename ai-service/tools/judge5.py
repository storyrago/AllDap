"""채점 모델 비교 실험(2026-10-02)의 공통 채점 모듈.

설계: docs/superpowers/specs/2026-10-02-judge-selfhost-design.md

이 파일 하나가 쥐고 있는 것
─────────────────────────────────────────────────────────────────────────────
1. 채점표(1~5 각 점수의 뜻). 사람 라벨링 화면과 네 모델의 지시문이 모두 여기서 읽는다.
2. 공통 지시문. 네 모델이 글자 하나까지 같은 입력을 받게 하려고 한 곳에서만 만든다.
3. 모델 출력에서 점수를 읽는 함수. 코랩 노트북은 원문만 저장하고 점수는 여기서 읽는다.
   읽는 규칙이 노트북과 로컬에 두 벌 있으면 언젠가 갈라진다.
4. 대조 수치(거리, 후함 박함, 부호 검정, 교체 후보 기준). 스펙 §4 를 그대로 옮겼다.

외부 API 도 DB 도 부르지 않는다. 그래서 CI 의 tools.judge5_check 로 전부 검사한다.
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from pathlib import Path

SCALE: tuple[int, ...] = (1, 2, 3, 4, 5)

# 스펙 §2 의 네 모델. 결과 파일과 보고서가 이 키(M1~M4)로 모델을 부른다.
MODELS: dict[str, str] = {
    "M1": "@cf/mistralai/mistral-small-3.1-24b-instruct",
    "M2": "mistralai/Mistral-Small-3.1-24B-Instruct-2503",
    "M3": "Unbabel/M-Prometheus-14B",
    "M4": "Qwen/Qwen2.5-14B-Instruct",
}

# 이유를 먼저 쓰고 끝에 점수를 쓰는 양식이라 짧으면 점수가 잘린다(스펙 §3-3).
MAX_NEW_TOKENS = 512

CRITERIA = (
    "충실성: 답변의 모든 주장이 근거에 실제로 적혀 있는가. "
    "답변이 세상의 상식에 맞는지는 보지 않는다. 사실이더라도 근거에 없으면 점수를 낮춘다."
)

# 스펙 §3-1 의 채점표. dict 의 키가 점수, 값이 그 점수의 뜻이다.
RUBRIC: dict[int, str] = {
    1: "답변이 근거와 관계없는 내용을 지어냈거나, 근거와 반대되는 내용을 말한다",
    2: "답변의 주장 대부분이 근거에 없다",
    3: "근거에 있는 주장과 근거에 없는 주장이 비슷한 정도로 섞여 있다",
    4: "답변의 핵심 답은 근거와 일치한다. 다만 근거에 없는 사소한 주장이 하나 있다",
    5: "답변의 모든 주장이 근거에 적혀 있다",
}

# M3(M-Prometheus)가 학습한 절대 평가 양식이다(Prometheus 2 의 기대 답변 없는 판).
# 틀은 영어 그대로 두고 내용(근거, 질문, 답변, 채점표)만 한국어로 넣는다(스펙 §3-2).
SYSTEM_PROMPT = (
    "You are a fair judge assistant tasked with providing clear, objective feedback based on "
    "specific criteria, ensuring each assessment reflects the absolute standards set for performance."
)

_USER_TEMPLATE = """###Task Description:
An instruction (might include an Input inside it), a response to evaluate, and a score rubric representing a evaluation criteria are given.
1. Write a detailed feedback that assess the quality of the response strictly based on the given score rubric, not evaluating in general.
2. After writing a feedback, write a score that is an integer between 1 and 5. You should refer to the score rubric.
3. The output format should look as follows: "Feedback: (write a feedback for criteria) [RESULT] (an integer number between 1 and 5)"
4. Please do not generate any other opening, closing, and explanations.

###The instruction to evaluate:
{instruction}

###Response to evaluate:
{response}

###Score Rubrics:
[{criteria}]
Score 1: {s1}
Score 2: {s2}
Score 3: {s3}
Score 4: {s4}
Score 5: {s5}

###Feedback: """


def prompt_sha256() -> str:
    """공통 지시문 본문(시스템 프롬프트, 틀, 기준, 채점표)의 SHA-256. 스펙 §3-2 가 시험지와 함께 적으라는 값이다.

    시험지 파일에는 완성된 messages 가 들어 있어 파일 해시가 지시문까지 덮는다. 그래도 따로 적는 이유:
    결과 문서를 읽는 사람이 "지시문이 바뀌었는가" 를 시험지 전체 해시와 분리해서 볼 수 있게 하려는 것이다.
    """
    # "\x00".join: 조각 사이에 본문에 나올 수 없는 글자를 끼워, 경계가 옮겨 간 다른 본문이 같은 해시가 되지 않게 한다.
    body = "\x00".join([SYSTEM_PROMPT, _USER_TEMPLATE, CRITERIA, *(RUBRIC[k] for k in SCALE)])
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def build_instruction(question: str, sources: list[dict]) -> str:
    """채점 대상이 받은 과제를 다시 쓴다: 근거 전문과 질문.

    근거 머리표 `[근거 i] (출처: 파일명)` 는 생성 모델이 받은 모양
    (`app/generator.py` 의 `_build_context`)과 같게 둔다. 채점 모델은 생성 모델이 본 것과
    같은 것을 봐야 한다(`app/judge.py` 의 2026-08-02 버그 주석).
    """
    # enumerate(xs, 1) 은 번호를 1 부터 매긴다. "\n\n".join 은 블록 사이에 빈 줄을 하나 둔다.
    blocks = "\n\n".join(
        f"[근거 {i}] (출처: {s['filename']})\n{s['content']}" for i, s in enumerate(sources, 1)
    )
    return f"아래 근거만 사용해서 질문에 답하세요.\n\n<근거>\n{blocks}\n</근거>\n\n<질문>\n{question}"


def build_messages(question: str, sources: list[dict], answer: str) -> list[dict[str, str]]:
    """네 모델에 똑같이 줄 대화(messages)를 만든다. 기대 답변은 받지도 않는다."""
    # **{...} 는 dict 를 키워드 인자로 펼친다. s1=RUBRIC[1], ..., s5=RUBRIC[5] 와 같다.
    user = _USER_TEMPLATE.format(
        instruction=build_instruction(question, sources),
        response=answer,
        criteria=CRITERIA,
        **{f"s{k}": v for k, v in RUBRIC.items()},
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


# 점수 읽기 규칙(스펙 §4-7, 2026-10-02 사용자 결정): 꾸밈은 너그럽게, 값은 엄격하게.
#   너그럽게: [RESULT] 앞뒤의 마크다운 굵게(**), 뒤의 콜론 하나, 괄호. 일반 지시 모델이 흔히 붙이는 버릇이라
#             이것 때문에 못 읽음이 되면 실력과 무관하게 §4-4 의 "못 읽음 0건" 에서 떨어진다.
#   엄격하게: 값은 부호와 소수점까지 통째로 잡는다(-?\d+(?:\.\d+)?). 4.5 를 4 로 읽으면 근거 없는 점수를 만들고,
#             -1 을 못 잡으면 out_of_range 가 아니라 missing 으로 섞인다. 정수가 아니면 아래에서 out_of_range 다.
#   분수: "4/5" 는 5점 만점의 4 라 4 로 읽지만, "4/10" 은 10점 만점의 4 라 우리 4점이 아니다. 그래서 분모도
#             잡아 두고(두 번째 괄호), 분모가 5 가 아니면 아래에서 out_of_range 다.
# (?:\*\*)? 는 "** 가 있어도 되고 없어도 된다", :? 는 "콜론 하나가 있어도 된다" 는 뜻이다.
# 괄호가 두 개라 findall 은 (값, 분모) 튜플 목록을 돌려준다. 분모가 없으면 빈 글자 "" 다.
_RESULT_RE = re.compile(
    r"(?:\*\*)?\[RESULT\](?:\*\*)?\s*:?\s*(?:\*\*)?\s*\(?\s*(?:\*\*)?\s*(-?\d+(?:\.\d+)?)(?:\s*/\s*(\d+))?"
)


# 동작 확인용 가짜 사례. 44건과 무관하다(순서 규칙, 스펙 §4-1). M1 의 --smoke 와 코랩 노트북이 모두 이것을 쓴다.
# 답변의 "창립기념일" 은 근거에 없는 사소한 주장 하나라, 채점표대로면 4 가 나와야 한다.
SMOKE_CASE: dict = {
    "question": "연차는 며칠인가요?",
    "sources": [{"filename": "가짜.md", "content": "정규직 직원의 연차는 15일이다."}],
    "answer": "연차는 15일이고, 회사 창립기념일에는 하루 더 쉽니다.",
}


def smoke_messages() -> list[dict[str, str]]:
    return build_messages(SMOKE_CASE["question"], SMOKE_CASE["sources"], SMOKE_CASE["answer"])


def parse_result(text: str | None) -> tuple[int | None, str]:
    """모델 출력에서 점수를 읽는다. (점수, 상태) 를 돌려준다.

    상태는 넷이다. 앞의 하나만 점수가 있고 나머지 셋은 서로 다른 실패다.
      ok            점수 하나를 읽었다
      missing       [RESULT] 가 없다(출력이 잘렸거나 양식을 안 지켰다)
      out_of_range  [RESULT] 는 있는데 뒤의 값이 1~5 정수가 아니다(소수, 음수, 범위 밖, 숫자를 못 찾음)
      conflict      [RESULT] 를 여러 번 쓰고 값이 서로 다르다
    셋을 "못 읽음" 하나로 뭉개지 않는 이유: 원인이 다르면 고칠 곳도 다르다.
    규칙(꾸밈은 너그럽게, 값은 엄격하게)은 스펙 §4-7 에 측정 전에 고정돼 있다.
    """
    if not text:
        return None, "missing"
    pairs = _RESULT_RE.findall(text)   # (값, 분모) 목록. 예: [("4", "")], [("4.5", "")], [("4", "10")]
    if not pairs:
        # [RESULT] 는 썼는데 뒤에서 값을 못 찾은 것("[RESULT] Score: 4")은 missing 이 아니다.
        # 스펙 §4-7 표의 missing 은 "[RESULT] 가 없다" 이고, 이 경우는 "값을 읽을 수 없다" 쪽이다.
        # 잘려서 [RESULT] 까지 못 쓴 것과 [RESULT] 까지 쓰고 값 모양이 틀린 것은 고칠 곳이 다르다.
        return None, ("out_of_range" if "[RESULT]" in text else "missing")
    # 분모가 있는데 5 가 아니면(4/10) 다른 척도의 점수라 읽지 않는다.
    if any(den and int(den) != 5 for _, den in pairs):
        return None, "out_of_range"
    raw = [x for x, _ in pairs]
    # str.isdigit(): 숫자 글자로만 된 글자인지. "4.5" 와 "-1" 은 False 라 정수로 바꾸지 않고 바로 out_of_range 다.
    # 전각 숫자("４")도 숫자 글자라 True 이고 int("４") 는 4 다(꾸밈 허용, 스펙 §4-7).
    if any(not x.isdigit() or int(x) not in SCALE for x in raw):
        return None, "out_of_range"
    found = [int(x) for x in raw]
    if len(set(found)) > 1:
        return None, "conflict"
    return found[0], "ok"


@dataclass(frozen=True)  # frozen=True: 만든 뒤 값을 못 바꾼다. 집계 결과가 도중에 변하지 않게 한다.
class Summary:
    total: int
    unread: int
    exact: int
    within1: int
    mean_distance: float | None   # 읽은 사례가 0건이면 None (0.0 이 아니다)
    generous: int                 # 모델 점수 > 사람 점수
    harsh: int                    # 모델 점수 < 사람 점수
    confusion: dict[tuple[int, int], int]  # 키는 (사람, 모델) 순서


def summarize(pairs: list[tuple[int, int | None]]) -> Summary:
    """(사람 점수, 모델 점수 또는 None) 목록을 스펙 §4-2 의 수치로 정리한다."""
    read = [(h, m) for h, m in pairs if m is not None]
    dists = [abs(h - m) for h, m in read]
    conf = {(h, m): 0 for h in SCALE for m in SCALE}
    for h, m in read:
        conf[(h, m)] += 1
    return Summary(
        total=len(pairs),
        unread=len(pairs) - len(read),
        exact=sum(1 for d in dists if d == 0),
        within1=sum(1 for d in dists if d <= 1),
        mean_distance=(sum(dists) / len(dists)) if dists else None,
        generous=sum(1 for h, m in read if m > h),
        harsh=sum(1 for h, m in read if m < h),
        confusion=conf,
    )


def sign_test_p(k: int, n: int) -> float:
    """양측 부호 검정의 정확한 p 값. n 번 중 한쪽이 k 번 이겼을 때.

    공정한 동전을 n 번 던져 k 번 이하(또는 n-k 번 이상)가 나올 확률의 두 배다.
    math.comb(n, i) 는 n 개 중 i 개를 고르는 경우의 수다.
    """
    if n == 0:
        return 1.0
    tail = min(k, n - k)
    p = 2 * sum(math.comb(n, i) for i in range(tail + 1)) / 2**n
    return min(1.0, p)


@dataclass(frozen=True)
class Comparison:
    excluded: int   # 둘 중 하나라도 못 읽어 뺀 사례 수
    a_closer: int
    b_closer: int
    ties: int
    p_value: float

    def verdict(self, a: str, b: str) -> str:
        """스펙 §4-3 의 판정 문장. p < 0.05 일 때만 더 가까운 쪽을 말한다."""
        if self.p_value < 0.05 and self.a_closer != self.b_closer:
            closer = a if self.a_closer > self.b_closer else b
            return f"{closer} 가 사람에 더 가깝다"
        return "구별되지 않음"


def compare(human: dict[str, int], a: dict[str, int | None], b: dict[str, int | None]) -> Comparison:
    """두 모델 중 사례마다 누가 사람에 더 가까운지 세고 부호 검정을 한다(스펙 §4-3)."""
    excluded = a_closer = b_closer = ties = 0
    for cid, h in human.items():
        x, y = a.get(cid), b.get(cid)
        if x is None or y is None:
            excluded += 1
            continue
        dx, dy = abs(x - h), abs(y - h)
        if dx < dy:
            a_closer += 1
        elif dy < dx:
            b_closer += 1
        else:
            ties += 1
    return Comparison(excluded, a_closer, b_closer, ties, sign_test_p(a_closer, a_closer + b_closer))


def linear_weighted_kappa(pairs: list[tuple[int, int]]) -> float | None:
    """선형 가중 카파(보조 지표). 정의되지 않으면 None.

    한 칸에 사례가 몰리면 우연 일치가 1 에 가까워져 분모가 0 이 된다. 그때 0.0 을 돌려주면
    "일치하지 않는다" 로 읽히므로, 계산할 수 없다는 뜻으로 None 을 돌려준다.
    """
    n = len(pairs)
    if n == 0:
        return None
    k = len(SCALE)
    idx = {v: i for i, v in enumerate(SCALE)}

    def w(a: int, b: int) -> float:
        return 1.0 - abs(a - b) / (k - 1)

    obs = sum(w(idx[h], idx[m]) for h, m in pairs) / n
    hc = [sum(1 for h, _ in pairs if h == v) / n for v in SCALE]
    mc = [sum(1 for _, m in pairs if m == v) / n for v in SCALE]
    exp = sum(w(a, b) * hc[a] * mc[b] for a in range(k) for b in range(k))
    if abs(1.0 - exp) < 1e-12:
        return None
    return (obs - exp) / (1.0 - exp)


def pick_best(summaries: dict[str, Summary]) -> str | None:
    """M2~M4 중 가장 나은 후보(스펙 §4-3). 거리 1 이하가 많은 순, 같으면 평균 거리가 작은 순,
    그래도 같으면 못 읽음이 적은 순, 그래도 같으면 이름 순서."""
    if not summaries:
        return None

    def key(name: str) -> tuple:
        s = summaries[name]
        mean = s.mean_distance if s.mean_distance is not None else math.inf
        # sorted 는 작은 값이 앞이므로 "많을수록 좋은" 값에는 음수를 붙인다.
        return (-s.within1, mean, s.unread, name)

    return sorted(summaries, key=key)[0]


def replacement_failures(cand: Summary, m1: Summary, vs_m1: Comparison) -> list[str]:
    """교체 후보 기준(스펙 §4-4)에서 어긋난 항목을 돌려준다. 빈 목록이면 교체 후보다.

    vs_m1 은 compare(사람, 후보, M1) 의 결과여야 한다(a 가 후보, b 가 M1).
    """
    out = []
    if cand.within1 < m1.within1:
        out.append(f"거리 1 이하 사례가 M1 보다 적다({cand.within1} < {m1.within1})")
    if cand.unread > 0:
        out.append(f"못 읽음 사례가 {cand.unread}건 있다")
    if vs_m1.p_value < 0.05 and vs_m1.b_closer > vs_m1.a_closer:
        out.append(f"부호 검정에서 M1 이 사람에 더 가깝다(p = {vs_m1.p_value:.4f})")
    return out


def to_three(v: int) -> float:
    """새 라벨을 옛 세 칸으로 옮긴다(스펙 §4-6). 5 만 1.0, 1 만 0.0, 나머지는 0.5."""
    return 1.0 if v == 5 else 0.0 if v == 1 else 0.5


def sha256_file(path: str | Path) -> str:
    """파일 내용의 SHA-256. 코랩과 로컬이 같은 시험지를 읽었는지 확인하는 데 쓴다."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
