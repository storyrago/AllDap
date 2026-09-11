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

import math
import re


class MetricUnreadable(RuntimeError):
    """줄은 찾았는데 값을 숫자로 못 읽었다. <시계열이 없다>(None) 와 <다른 사실>이다.

    🔴 왜 None 으로 뭉개면 안 되나. 부르는 쪽이 두 사실에 서로 <반대로> 대응한다.
       - 시계열이 없다 = 그 태그 조합이 한 번도 안 쓰였다 = 카운터라면 0 이다.
         s4_context.judge_fault_round 의 delta 가 after 의 None 을 실제로 0.0 으로 읽는다.
       - 값이 NaN 이다 = 계측이 죽었다. 0 이 아니고, 그 판은 <잴 수 없다>.
       None 으로 뭉개면 죽은 계측이 "그 일이 0번 일어났다" 로 둔갑한다.

    🔴 왜 값(nan)으로 흘려보내도 안 되나. 파이썬 float("NaN") 은 예외를 내지 않아
       그대로 통과하고, 그러면 "계측이 살아 있는가" 를 `is None` 으로 묻는 가드들이
       (s3_context.cmd_before 의 keys 게이지 가드가 그렇다) 전부 통과해버린다.
       = 계측이 죽은 채로 측정 한 판이 돈다. AGENTS.md "낸 버그" 절이 모은 부류 그대로다.

    그래서 셋째 값으로 가른다. 예외로 만든 이유는 <무시할 수 없게> 하려는 것이다.
    표식 객체를 돌려주면 분기를 빠뜨린 호출부가 조용히 지나갈 수 있지만, 예외는 안 잡으면
    그 자리에서 멈춘다. 그리고 NaN 을 만난 판은 어차피 계속 돌 값어치가 없다.
    """


def parse_prom_counter(text: str, name: str, labels: dict[str, str]) -> float | None:
    """Prometheus 텍스트 노출에서 값 하나를 꺼낸다. 없으면 None, 못 읽으면 예외.

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
        # 🔴 이름 경계. startswith 만으로는 <접두사가 같은 다른 메트릭>이 함께 걸린다.
        #    실례: alldap_ratelimit_keys(게이지)로 물으면
        #    alldap_ratelimit_keys_cleared_total(카운터) 줄도 통과한다. 그 조회는 라벨이
        #    {} 라 아래 라벨 검사가 빈 시퀀스의 all()=True 로 통과해 버려, 결국 <먼저
        #    나오는 줄이 이긴다>. 지금까지 값이 맞았던 것은 파서 덕이 아니라
        #    prometheus-metrics 1.x 가 알파벳 순으로 뱉기 때문이었다(기대도 안 한 보증이다).
        #    Prometheus 노출 형식에서 메트릭 이름 뒤에 올 수 있는 것은 라벨을 여는 '{'
        #    아니면 값 앞의 공백뿐이므로, 그 둘만 경계로 인정하면 위험이 원리적으로 닫힌다.
        #    회귀 검사는 loadtest/s3_check.py · s4_check.py 에 있다(줄 순서를 뒤집어도
        #    같은 값이 나오는지까지 단언한다).
        if line[len(name):len(name) + 1] not in ("{", " "):
            continue
        head, _, value = line.rpartition(" ")
        if not all(re.search(rf'{re.escape(k)}="{re.escape(v)}"', head) for k, v in labels.items()):
            continue
        # 🔴 여기서 NaN·+Inf·-Inf 를 갈라낸다. float("NaN") 은 <예외를 내지 않는다>.
        #    그래서 아래 try 만으로는 안 걸리고 nan 이 정상 값처럼 흘러나간다.
        #    Micrometer 의 DefaultGauge.value() 는 약한 참조가 끊겼을 때뿐 아니라
        #    <값 함수가 Throwable 을 던졌을 때도> NaN 을 돌려주고(1.16.4 바이트코드 확인),
        #    prometheus-metrics 의 TextFormatUtil.writeDouble 이 그것을 Double.toString 으로
        #    흘려 "NaN" 이라는 글자로 노출한다(1.4.3 확인). +Inf·-Inf 는 아예 그 이름으로 쓴다.
        #    ⚠️ 지금 이 저장소가 가진 게이지 둘(alldap_ratelimit_keys · alldap_ai_circuit_state)은
        #       참조를 @Component 싱글턴이 계속 들고 있고 값 함수도 던지지 않아 NaN 이 나올 수
        #       없다. 즉 이 분기는 <지금 나는 일>이 아니라 다음 게이지를 위한 것이다.
        try:
            parsed = float(value)
        except ValueError as exc:
            raise MetricUnreadable(
                f"{name}{labels or ''} 줄은 찾았는데 값을 숫자로 못 읽었다: {value!r}"
            ) from exc
        if not math.isfinite(parsed):
            raise MetricUnreadable(
                f"{name}{labels or ''} 의 값이 {value} 다. 시계열은 <있는데> 계측이 죽은 것이다. "
                f"게이지라면 값 함수가 예외를 던졌거나(Micrometer 가 그때 NaN 을 낸다) "
                f"참조가 끊긴 것이다. 0 으로도 <없음>으로도 읽으면 안 된다."
            )
        return parsed
    return None
