"""부하테스트 <측정 전용 계정>을 만들고, 측정 봇이 그 계정 것이 되게 맞춘다.

실행:
    cd ai-service && LOADTEST_PASSWORD='...' .venv/bin/python -m loadtest.account

    # 이메일을 바꾸고 싶으면
    cd ai-service && LOADTEST_EMAIL='loadtest2@example.com' LOADTEST_PASSWORD='...' \\
        .venv/bin/python -m loadtest.account

왜 이 파일이 있는가
─────────────────────────────────────────────────────────────────────────────
🔴 S1·S2·S4 세 판 내내 <같은 손작업>을 했다. 측정에 쓰던 `w2check@example.com` 은
   측정 전용 계정이 아니라 W2 검증에 쓰던 계정이라, 측정이 끝날 때마다 비밀번호를
   원래대로 되돌렸다. 그래서 다음 측정에서 계획서에 적힌 비밀번호가 매번 401 이었고,
   그때마다 `password_hash` 를 임시로 갈아끼운 뒤 실행하고 되돌렸다
   (docs/superpowers/2026-09-10-loadtest-s2-result.md "실행 중에 드러난 절차 문제" 2번,
   docs/HANDOFF-2026-09-11-3.md §5 가 "세 번째다" 라고 적은 자리).

   손으로 해시를 만지는 절차는 그 자체가 사고 경로다. 실행 전에 바꾸고 실행 뒤에
   되돌리는 두 걸음 중 하나만 빠져도 <계정의 비밀번호가 조용히 달라진 채> 남는다.

   → 아무도 되돌리지 않는 <측정 전용 계정>을 하나 두면 그 절차가 통째로 없어진다.

🔴 해시를 이 스크립트가 만들지 않는다. 가입 API(`POST /api/auth/signup`)를 부른다.
   Spring 의 `PasswordEncoder` 가 유일한 해시 생산자로 남아야 한다. 여기서 bcrypt 를
   직접 돌리면 인코더 설정(비용·알고리즘)이 바뀌는 날 <이 파일만 조용히 낡는다>.
   2026-09-11 의 손작업도 같은 이유로 임시 계정을 가입시켜 해시를 복사해 썼다.

🔴 비밀번호는 환경변수로만 받는다. 기본값을 코드에 박지 않는다.
   박아두면 그 값이 곧 저장소에 커밋된 비밀번호다. 측정 계정은 로컬 전용이지만,
   "로컬 전용이니까 괜찮다" 는 판단이 한 번 서면 다음에도 같은 판단을 하게 된다.

봇 소유권을 왜 여기서 옮기는가
─────────────────────────────────────────────────────────────────────────────
드라이버는 로그인한 계정의 봇 중 <문서가 가장 많은 것>을 고른다(`_pick_bot`).
그런데 갓 가입한 계정에는 봇이 없어 거기서 바로 중단된다. 그렇다고 코퍼스를 API 로
새로 올릴 수도 없다: 진짜 임베딩을 태우면 하루 한도를 쓰고, 가짜 CF 로 태우면
벡터가 가짜라 검색 경로를 재는 측정 자체가 뜻을 잃는다.

그래서 <이미 코퍼스를 가진 봇>(fake_cf.BOT_ID)의 주인을 측정 계정으로 옮긴다.
`bots` 는 Spring 이 쓰는 테이블이지만(AGENTS.md 테이블 소유권), 소유자를 바꾸는
API 가 없어 SQL 말고는 길이 없다. 제품 코드가 아니라 <로컬 측정 픽스처>이므로
여기에 둔다. 운영 DB 에서는 절대 돌리지 말 것(아래에서 호스트를 검사한다).

🔴 Flyway 마이그레이션(V9)으로 심지 않는다. 한 번 적용하면 되돌리기가 어렵고
   (체크섬), 무엇보다 <운영 DB 에 측정 계정을 심는> 셈이 된다.
"""
from __future__ import annotations

import os
import sys

import httpx

DEFAULT_EMAIL = "loadtest@example.com"
DEFAULT_API = "http://localhost:8080"

# 측정 계정의 표시 이름. 대시보드에서 이게 무슨 계정인지 한눈에 보이게 한다.
DISPLAY_NAME = "부하테스트"


def env_email() -> str:
    """측정 계정의 이메일. 드라이버들이 기본값으로 이 값을 쓴다.

    한 자리에 모아두는 이유: 드라이버 네 개가 각자 이메일을 박아두면, 계정을 바꾸는 날
    한 개를 빠뜨리고 그 드라이버만 옛 계정으로 돈다. 그러면 <같은 측정> 안에서 서로 다른
    봇을 두드리게 되는데, 결과 파일만 봐서는 그 사실이 드러나지 않는다.
    """
    return os.environ.get("LOADTEST_EMAIL", DEFAULT_EMAIL)


def env_password() -> str | None:
    """측정 계정의 비밀번호. 없으면 None. 부르는 쪽이 안내하고 중단한다.

    🔴 기본값을 두지 않는다. 기본값을 두면 그 문자열이 곧 저장소에 커밋된 비밀번호다.
    """
    return os.environ.get("LOADTEST_PASSWORD")


def _fail(message: str) -> int:
    print(f"중단: {message}")
    return 1


def _assert_local_db() -> str:
    """운영 DB 를 향하고 있으면 아무것도 하지 않는다.

    이 스크립트가 하는 일 중 하나는 `bots.user_id` 를 바꾸는 UPDATE 다.
    운영에서 돌면 남의 봇 주인이 바뀐다. 되돌릴 수 있는 종류의 사고가 아니라,
    <실행 전에> 막는다.
    """
    from app.config import get_settings

    url = get_settings().database_url
    # 접속 문자열에 비밀번호가 들어 있어 통째로 찍지 않는다. 호스트만 본다.
    host = url.split("@")[-1].split("/")[0]
    if not host.startswith(("localhost", "127.0.0.1")):
        raise SystemExit(
            f"중단: DATABASE_URL 이 로컬이 아니다({host}). "
            f"이 스크립트는 로컬 측정 환경 전용이다."
        )
    return host


def _user_id(email: str) -> str | None:
    from app.db import cursor

    with cursor() as cur:
        cur.execute("SELECT id FROM users WHERE email=%s", (email,))
        row = cur.fetchone()
    return str(row[0]) if row else None


def _bot_owner_email(bot_id: str) -> tuple[str | None, str | None]:
    """(봇 이름, 현재 주인 이메일). 주인이 없으면 이메일이 None."""
    from app.db import cursor

    with cursor() as cur:
        cur.execute(
            "SELECT b.name, u.email FROM bots b LEFT JOIN users u ON u.id = b.user_id "
            "WHERE b.id=%s",
            (bot_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None, None
    return row[0], row[1]


def _move_bot(bot_id: str, user_id: str) -> None:
    from app.db import cursor

    with cursor(commit=True) as cur:
        cur.execute("UPDATE bots SET user_id=%s WHERE id=%s", (user_id, bot_id))


def _close_pool() -> None:
    """psycopg 커넥션 풀을 닫는다. 안 닫으면 종료할 때 "couldn't stop thread" 가
    네 줄 찍혀 <스크립트가 실패한 것처럼> 보인다. 마지막 줄이 성공/실패를 말해야 한다."""
    from app import db

    if db._pool is not None:
        db._pool.close()
        db._pool = None


def main() -> int:
    from .fake_cf import BOT_ID  # app.config 를 끌고 오므로 필요할 때만 부른다

    email = env_email()
    password = env_password()
    api = os.environ.get("LOADTEST_API", DEFAULT_API)

    if not password:
        return _fail(
            "LOADTEST_PASSWORD 가 없다. 측정 계정의 비밀번호를 환경변수로 넘겨줘야 한다.\n"
            "  예: LOADTEST_PASSWORD='...' .venv/bin/python -m loadtest.account\n"
            "  (8자 이상 64자 이하 · UTF-8 72바이트 이하, Spring 의 가입 검증 조건이다)"
        )

    host = _assert_local_db()
    print(f"DB: {host} · API: {api} · 계정: {email}")

    client = httpx.Client(timeout=30.0)

    # ① 가입. 이미 있으면 409 다. 그건 정상이고, 이 스크립트를 두 번째로 돌린 것뿐이다.
    resp = client.post(
        f"{api}/api/auth/signup",
        json={"email": email, "password": password, "name": DISPLAY_NAME},
    )
    if resp.status_code == 201:
        print("가입: 새로 만들었다.")
    elif resp.status_code == 409:
        print("가입: 이미 있다(건너뛴다).")
    else:
        return _fail(f"가입이 {resp.status_code} 로 실패했다: {resp.text}")

    # ② 로그인이 <실제로> 되는지 확인한다. 여기까지 와야 "계정을 만들어뒀다" 가 아니라
    #    "그 비밀번호로 들어가진다" 가 된다.
    resp = client.post(f"{api}/api/auth/login", json={"email": email, "password": password})
    if resp.status_code != 200:
        return _fail(
            f"로그인이 {resp.status_code} 다: {resp.text}\n"
            f"  이 계정은 이미 있는데 LOADTEST_PASSWORD 가 DB 의 것과 다르다는 뜻이다.\n"
            f"  해시를 손으로 갈아끼우지 말 것(그 손작업을 없애려고 만든 파일이다).\n"
            f"  맞는 값을 넣거나, LOADTEST_EMAIL 로 다른 주소를 써서 새로 만들 것.\n"
            f"  ⚠️ 연속 실패가 쌓이면 Spring 이 잠그므로 값을 찍어 맞히려 하지 말 것."
        )
    token = resp.json()["token"]
    print("로그인: 통과.")

    # ③ 측정 봇을 이 계정 것으로 맞춘다.
    user_id = _user_id(email)
    if user_id is None:
        return _fail(f"가입도 로그인도 됐는데 users 에 {email} 이 없다. DB 가 다른 곳인가?")

    bot_name, owner = _bot_owner_email(BOT_ID)
    if bot_name is None:
        return _fail(
            f"측정 봇 {BOT_ID} 가 DB 에 없다. 코퍼스를 먼저 적재할 것 "
            f"(ai-service/testdata/corpus)."
        )
    if owner == email:
        print(f"봇: '{bot_name}' 은 이미 이 계정 것이다.")
    else:
        _move_bot(BOT_ID, user_id)
        print(f"봇: '{bot_name}' 의 주인을 {owner or '(없음)'} → {email} 로 옮겼다.")

    # ④ Spring 을 통해 다시 확인한다. SQL 로 바꿔놓고 SQL 로 확인하면 <같은 자리를 두 번>
    #    보는 것이라, 드라이버가 실제로 쓰는 경로(JWT + GET /api/bots)가 되는지는 모른다.
    resp = client.get(f"{api}/api/bots", headers={"Authorization": f"Bearer {token}"})
    resp.raise_for_status()
    bots = resp.json()
    mine = [b for b in bots if b["id"] == BOT_ID]
    if not mine:
        return _fail(f"주인을 옮겼는데도 GET /api/bots 에 {BOT_ID} 가 없다.")
    bot = mine[0]
    print(f"확인: GET /api/bots 에 '{bot['name']}' (문서 {bot['documentCount']}건) 이 보인다.")

    print("\n다음 측정은 이 두 줄을 쓴다(비밀번호는 셸에서 넘긴다):")
    print(f"  export LOADTEST_EMAIL='{email}'")
    print("  export LOADTEST_PASSWORD='...'")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        _close_pool()
    sys.exit(code)
