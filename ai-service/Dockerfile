# Python AI 서비스 이미지.
#
# ⚠️ 빌드 컨텍스트는 <저장소 루트>다 (api/Dockerfile 과 맞춘다).
#      docker build -f ai-service/Dockerfile -t alldap-ai .
#
# 🔴 이 서비스는 절대 외부에 노출하지 않는다.
#    /internal/* 에는 인증이 <전혀> 없다. 열리는 순간 publicKey 도 JWT 도 없이
#    누구나 남의 봇 문서와 청크를 읽는다. compose 에서 `ports:` 를 쓰지 않는 것으로
#    막는다 — 아래 0.0.0.0 바인딩은 그것과 다른 이야기다(맨 아래 주석 참고).

FROM python:3.13-slim
WORKDIR /app

# ① 의존성만 먼저. 앱 코드가 바뀌어도 pip install 을 다시 하지 않게 레이어를 나눈다.
COPY ai-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ② 앱 코드
COPY ai-service/app app

# root 로 돌리지 않는다.
RUN useradd --create-home --shell /usr/sbin/nologin app && chown -R app:app /app
USER app

# 운영에서는 설정이 빠지면 시끄럽게 죽어야 한다(config._check_prod).
ENV APP_ENV=prod

EXPOSE 8001

# --host 0.0.0.0 이 "인터넷에 공개" 라는 뜻이 아니다.
# <컨테이너 안에서> 어떤 인터페이스로 들을지를 정할 뿐이고, 127.0.0.1 로 두면
# 같은 compose 네트워크의 Spring 컨테이너조차 붙지 못한다.
# 바깥에 뚫리는지는 오직 compose 의 `ports:` 가 정한다 — 우리는 그걸 쓰지 않는다.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
