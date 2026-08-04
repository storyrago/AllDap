# Spring API 이미지.
#
# ⚠️ 빌드 컨텍스트는 <저장소 루트>다. `api/` 가 아니다.
#    build.gradle 의 processResources 가 `${projectDir}/../widget` 을 읽어
#    위젯 로더를 정적 리소스로 담기 때문이다. 컨텍스트를 api/ 로 두면
#    그 복사가 조용히 빈 채로 지나가고, 배포 후에야
#    `GET /widget/alldap-widget.js → 404` 로 드러난다.
#
#      docker build -f api/Dockerfile -t alldap-api .
#
# 멀티스테이지인 이유: JDK+Gradle+소스는 300MB 를 훌쩍 넘는데 실행에는 JAR 과 JRE 만 있으면 된다.

# ── 빌드 ─────────────────────────────────────────────────────────────
FROM eclipse-temurin:21-jdk AS build
WORKDIR /src/api

# ① 의존성 목록만 먼저 복사한다.
#    소스만 고쳤을 때 Gradle 의존성을 다시 내려받지 않도록 레이어를 나누는 것이다.
#    (도커는 COPY 한 파일이 안 바뀌면 그 아래 RUN 결과를 캐시에서 꺼내 쓴다)
COPY api/gradle gradle
COPY api/gradlew api/build.gradle api/settings.gradle ./
RUN chmod +x gradlew && ./gradlew --no-daemon -q dependencies || true

# ② 소스. widget/ 도 함께 넣어야 processResources 의 ../widget 이 맞는다.
COPY widget /src/widget
COPY api/src src

# 테스트는 CI 가 돌린다. 이미지 빌드에서 Testcontainers 를 띄우면
# 도커 안에서 도커가 필요해지고 빌드 시간이 몇 배가 된다.
RUN ./gradlew --no-daemon -x test bootJar \
 && cp build/libs/$(ls build/libs | grep -v -- '-plain' | head -1) /app.jar

# ── 실행 ─────────────────────────────────────────────────────────────
FROM eclipse-temurin:21-jre
WORKDIR /app

# healthcheck 용. compose 에서 ai-service 가 <Spring 이 뜬 뒤에> 시작해야 한다
# (Flyway 가 Spring 기동 때 돌아서 테이블을 만든다 — AGENTS.md 참고).
RUN apt-get update && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

# root 로 돌리지 않는다. 컨테이너가 뚫렸을 때 할 수 있는 일을 줄인다.
RUN useradd --create-home --shell /usr/sbin/nologin app
USER app

COPY --from=build /app.jar app.jar

# 컨테이너 메모리 기준으로 힙을 잡는다. 기본값(1/4)은 12GB VM 에 3개를 띄울 때
# 서로 눈치를 못 봐서, compose 에서 준 제한에 맞춰 비율로 지정한다.
ENV JAVA_OPTS="-XX:MaxRAMPercentage=70"

EXPOSE 8080
ENTRYPOINT ["sh", "-c", "exec java $JAVA_OPTS -jar /app/app.jar"]
