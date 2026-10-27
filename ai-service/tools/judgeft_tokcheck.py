"""실제 토크나이저로 학습 문항을 토큰화해, 끝 토큰이 정답 쪽 맨 뒤에 있는지 확인한다(스펙 4-5절).

실행:  cd ai-service && $PY -m tools.judgeft_tokcheck            # M3 의 토크나이저를 내려받는다(수 MB, 가중치는 받지 않는다)

CI 에서 돌지 않는다. 토크나이저를 내려받아야 하기 때문이다. CI 는 같은 함수를 가짜 토크나이저로 본다(judgeft_labels_check).
가장 긴 문항의 토큰 수도 찍는다. 학습 전 관문 (b) 가 그 문항으로 메모리를 잰다(스펙 7-2절).
"""
from __future__ import annotations

import argparse
import sys

from .judgeft_files import M3_REPO, M3_REVISION, TRAIN, VAL, read_jsonl
from .judgeft_labels import build_example

END_TOKEN = "<|im_end|>"


def check_rows(tok, rows: list[dict]) -> tuple[int, str]:
    """모든 문항을 확인하고 (가장 긴 토큰 수, 그 문항 id) 를 돌려준다. 어긋나면 AssertionError."""
    end_id = tok.convert_tokens_to_ids(END_TOKEN)
    assert isinstance(end_id, int) and end_id != tok.unk_token_id, f"{END_TOKEN} 가 어휘에 없다"

    def apply(m):
        return tok.apply_chat_template(m, add_generation_prompt=True, tokenize=False)

    def encode(s):
        return tok(s, add_special_tokens=False)["input_ids"]

    longest = (0, "")
    for r in rows:
        ids, n = build_example(apply, encode, r["messages"], r["target"], end_id)
        assert ids[-1] == end_id, f"{r['id']}: 끝 토큰이 맨 뒤가 아니다"
        tail = tok.decode(ids[-n:])
        assert tail == r["target"] + END_TOKEN, f"{r['id']}: 정답 쪽이 모범 답안과 끝 토큰이 아니다: {tail[-60:]!r}"
        assert apply(r["messages"]).startswith("<|im_start|>system\n"), f"{r['id']}: 시스템 메시지가 틀에 없다"
        longest = max(longest, (len(ids), r["id"]))
    return longest


def check_logits_to_keep() -> None:
    """학습 노트북의 loss(모범 답안 위치의 logits 만 계산)가 전체 logits 에 입력을 가린 loss 와 같은지 본다(스펙 6-2절).
    작은 무작위 Qwen2 모델로 CPU 에서 본다. 같아야 "계산 방법만 다르고 학습 결과는 같다" 는 스펙의 말이 맞다."""
    import torch
    from transformers import Qwen2Config, Qwen2ForCausalLM
    torch.manual_seed(0)
    m = Qwen2ForCausalLM(Qwen2Config(vocab_size=50, hidden_size=32, intermediate_size=64, num_hidden_layers=2,
                                     num_attention_heads=4, num_key_value_heads=2)).eval()
    ids, n = torch.randint(0, 50, (10,)), 3
    with torch.no_grad():
        ours = torch.nn.functional.cross_entropy(m(input_ids=ids[None], logits_to_keep=n + 1).logits[0, :-1], ids[-n:])
        labels = ids.clone()
        labels[:-n] = -100          # -100 은 loss 에서 빼는 자리다(transformers 의 약속)
        ref = m(input_ids=ids[None], labels=labels[None]).loss
    assert torch.allclose(ours, ref, atol=1e-6), (float(ours), float(ref))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="학습 문항의 토큰화와 끝 토큰을 확인한다")
    p.add_argument("--repo", default=M3_REPO)
    p.add_argument("--revision", default=M3_REVISION)
    args = p.parse_args(argv)
    from transformers import AutoTokenizer   # 늦은 import: CI 의 requirements.txt 만으로도 이 모듈을 불러올 수 있게
    check_logits_to_keep()
    print("모범 답안 위치만 계산한 loss 가 입력을 가린 전체 loss 와 같습니다.")
    tok = AutoTokenizer.from_pretrained(args.repo, revision=args.revision)
    rows = read_jsonl(TRAIN) + read_jsonl(VAL)
    if not rows:
        print("train.jsonl 이 비었습니다. `judgeft_export train` 을 먼저 하세요.")
        return 1
    n, rid = check_rows(tok, rows)
    print(f"{len(rows)}문항 모두 끝 토큰이 정답 쪽 맨 뒤에 있습니다. 가장 긴 문항 {rid}: {n}토큰")
    return 0


if __name__ == "__main__":
    sys.exit(main())
