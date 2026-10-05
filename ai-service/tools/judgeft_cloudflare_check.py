"""tools.judgeft_cloudflare 의 점검. Cloudflare 를 부르지 않는다.

실행:  cd ai-service && python -m tools.judgeft_cloudflare_check
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest import mock

from . import judgeft_cloudflare


def check_refuses_before_gates() -> None:
    """관문 (a), (b) 의 기록이 없거나 하나라도 통과하지 못했으면 호출하기 전에 멈춘다(스펙 8-1절)."""
    with tempfile.TemporaryDirectory() as d:
        gate, gate_b = Path(d) / "gate_a.json", Path(d) / "gate_b.json"
        # mock.patch.object: with 블록 안에서만 모듈의 이름을 바꿔 끼운다. 실제 gate_a.json 을 건드리지 않는다.
        with mock.patch.object(judgeft_cloudflare, "GATE_A", gate), mock.patch.object(judgeft_cloudflare, "GATE_B", gate_b), \
             mock.patch.object(judgeft_cloudflare, "_call", side_effect=AssertionError("부르면 안 된다")):
            assert judgeft_cloudflare.run(1, None) == 1
            gate.write_text(json.dumps({"pass": False}), encoding="utf-8")
            assert judgeft_cloudflare.run(1, None) == 1
            gate.write_text(json.dumps({"pass": True}), encoding="utf-8")
            assert judgeft_cloudflare.run(1, None) == 1          # (a) 만 통과, (b) 기록 없음
            gate_b.write_text(json.dumps({"finite": False}), encoding="utf-8")
            assert not judgeft_cloudflare.gate_passed()
            gate_b.write_text(json.dumps({"finite": True}), encoding="utf-8")
            assert judgeft_cloudflare.gate_passed()


CHECKS = [check_refuses_before_gates]


def main() -> None:
    for fn in CHECKS:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(CHECKS)}가지 전부 통과.")


if __name__ == "__main__":
    main()
