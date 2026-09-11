"""Prometheus 텍스트 노출을 읽는 순수 함수. 부하 드라이버들이 함께 쓴다.

이 모듈에는 서버도 시계도 타지 않는 함수만 둔다. s3_check.py · s4_check.py 가
각자의 케이스로 이 파서를 시험한다.

⚠️ 2026-09-11 까지 이 함수는 loadtest/s3_context.py 와 s4_context.py 에 <두 벌>로
   있었다. 일부러 복사한 것이다 — 두 드라이버가 서로 다른 PR 로 나뉘어 있어서
   한쪽을 import 하면 그 PR 이 먼저 머지돼야만 다른 쪽 CI 가 초록불이 되는
   <스택 브랜치>가 되기 때문이다(2026-09-08 에 PR 넷을 쌓았다가 넷 다 손으로
   충돌을 푼 자리다). 둘 다 머지돼 그 이유가 없어져서 여기로 합쳤다.
"""
from __future__ import annotations

import re


def parse_prom_counter(text: str, name: str, labels: dict[str, str]) -> float | None:
    """Prometheus 텍스트 노출에서 값 하나를 꺼낸다. 없으면 None.

    🔴 못 찾았을 때 0.0 이 아니라 None 을 돌려준다. Micrometer 는 태그 조합이 <처음
       쓰일 때> 미터를 만들기 때문에, 한 번도 안 일어난 일은 시계열이 아예 없다.
       거절이 0건이면 그 시계열이 아예 없는 식이다. 0 으로 뭉개면 "안 일어났다" 와
       "계측이 안 붙었다" 가 같은 값이 된다(핸드오프 §6-ⓓ 가 지적한 부류).
       부르는 쪽이 그 둘을 갈라 다루게 하려고 None 을 남긴다.

    파이썬 메모: `re.escape` 로 이름과 값에 든 특수문자를 막는다. 라벨 순서는 노출마다
    다를 수 있어 <순서를 가정하지 않고> 라벨마다 따로 있는지를 본다.
    """
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if not line.startswith(name):
            continue
        head, _, value = line.rpartition(" ")
        if not all(re.search(rf'{re.escape(k)}="{re.escape(v)}"', head) for k, v in labels.items()):
            continue
        try:
            return float(value)
        except ValueError:
            return None
    return None
