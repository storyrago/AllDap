"""학습 문항 하나를 토큰으로 바꾸고, loss 를 계산할 부분의 길이를 정한다(스펙 4-5절, 6-2절).

이 파일은 torch 도 transformers 도 import 하지 않는다. 토크나이저는 함수 두 개로 받는다. 그래서 CI 에서는 가짜
토크나이저로 점검하고(judgeft_labels_check), 실제 토크나이저로는 계획 E10 의 judgeft_tokcheck 가 확인한다.
학습 노트북은 아래 build_example 의 본문을 글자 그대로 담는다(judgeft_notebooks 가 이 파일에서 옮겨 넣는다).
"""
from __future__ import annotations


def build_example(apply_template, encode, messages, target, end_id):
    """(토큰 id 목록, 정답 쪽 길이). 정답 쪽은 모범 답안의 토큰과 끝 토큰(<|im_end|>)이다. 끝 토큰은 맨 뒤에 있다.

    apply_template(messages) 는 대화 틀을 씌운 글(시스템 메시지 포함, 끝에 assistant 차례의 시작)을 돌려준다.
    채점 노트북이 generate 앞에서 만드는 글과 같아야 한다(v2 노트북의 add_generation_prompt=True).
    encode(text) 는 특수 토큰을 더하지 않고 토큰 id 목록을 돌려준다(틀이 이미 특수 토큰을 넣는다).
    입력과 정답을 따로 토큰으로 바꿔 잇는 이유: 채점할 때도 모델은 입력을 따로 토큰으로 바꾼 뒤 그 뒤를 생성한다.
    정답을 입력에 붙여 한꺼번에 바꾸면 경계의 글자가 다르게 묶여, 학습한 토큰 열과 채점 때 생성하는 토큰 열이 달라질 수 있다.
    """
    prompt_ids = list(encode(apply_template(messages)))
    target_ids = list(encode(target)) + [end_id]
    return prompt_ids + target_ids, len(target_ids)
