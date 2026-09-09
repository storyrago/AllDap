# 부하테스트 PR 1: 관측 구축 (management 포트 분리 + Prometheus/Grafana)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 부하 중 Spring 내부(커넥션 풀·톰캣 스레드·힙·GC)를 숫자로 볼 수 있게 만든다. 관측 없이 k6 응답시간만 보면 병목을 추측하게 되고, 이 저장소는 리랭커 비용을 추정만 하고 켰다가 실측에서 빗나간 적이 있다.

**Architecture:** actuator 를 서비스 포트(8080)와 분리된 management 포트(8081)에 상시 켜두되, `docker-compose.prod.yml` 이 8081 을 `ports:` 에 안 열어 인터넷에서 닿지 않게 한다(`ai-service` 에 `ports:` 를 안 쓰는 것과 같은 논리). Prometheus·Grafana 는 **로컬에만** 띄운다(t3.micro 는 유휴에 이미 스왑을 쓴다). Grafana 대시보드 JSON 을 저장소에 커밋해 재현 가능하게 둔다.

**Tech Stack:** Spring Boot 4.0.7 / micrometer-registry-prometheus / Prometheus / Grafana / docker compose

## Global Constraints

- Spring Boot **4.0.7**, Java 21, Gradle-Groovy. Boot 3 예제를 그대로 붙여넣지 말 것(스타터 이름이 다르다).
- 운영 노출 규칙: `docker-compose.prod.yml` 에서 `ports:` 를 여는 서비스는 **caddy 하나뿐**이다. 이 PR 은 그 성질을 깨지 않는다.
- management 포트 값: **8081**. 서비스 포트는 8080 그대로.
- actuator 노출 엔드포인트: `health,metrics,prometheus` (로컬·운영 동일).
- 주석·문서·커밋 메시지는 한국어. **em dash 금지** — 쉼표·콜론·괄호로 대체.
- 커밋 메시지 형식: `<타입>: <한국어 요약>` (feat / fix / refactor / test / docs / chore).
- 브랜치: `feat/loadtest-observability`. PR 로 간다(설명이 필요한 변경 + 배포 파일이 함께 바뀐다).
- Prometheus·Grafana 는 **운영에 올리지 않는다.** `docker-compose.prod.yml` 을 건드리는 것은 헬스체크 포트 한 줄뿐이다.

---

## File Structure

| 파일 | 책임 |
|---|---|
| `api/build.gradle` | `micrometer-registry-prometheus` 의존성 1줄 추가 |
| `api/src/main/resources/application.yaml` | management 포트 분리 + 노출 엔드포인트 + 히스토그램 + 톰캣 MBean |
| `api/src/main/resources/application-prod.yaml` | 위와 동일 설정을 운영 프로파일에도 |
| `docker-compose.prod.yml` | 헬스체크 URL 을 8081 로 (안 고치면 배포가 영영 안 뜬다) |
| `api/Dockerfile` | `EXPOSE 8081` 추가 (문서 목적) |
| `api/src/test/java/.../ManagementPortIntegrationTest.java` | **8081 에 SecurityConfig 필터 체인이 붙는지 실측** |
| `observability/prometheus.yml` | 15초마다 Spring management 포트를 긁는 설정 |
| `observability/grafana/provisioning/datasources/prometheus.yml` | Grafana 가 Prometheus 를 자동으로 물게 |
| `observability/grafana/provisioning/dashboards/dashboards.yml` | 대시보드 파일 자동 적재 |
| `observability/grafana/dashboards/alldap-api.json` | 패널 5개 (6번째 "가짜 CF 호출 수" 는 PR 2 에서 붙는다) |
| `docker-compose.yml` | prometheus·grafana 서비스 (compose profile `obs` 로 격리) |

**Task 1 과 Task 2 를 나눈 기준:** Task 1 은 배포 산출물(`application-prod.yaml`·`docker-compose.prod.yml`·`Dockerfile`)을 건드리므로 한 덩어리여야 한다. 쪼개면 중간 커밋이 "헬스체크가 영영 실패하는" 상태가 된다. Task 2 는 로컬 전용이라 Task 1 이 없으면 긁을 대상이 없지만, 그 반대는 성립한다.

---

## Task 1: management 포트 분리 + 배포 파일 동기화

**Files:**
- Modify: `api/build.gradle` (dependencies 블록)
- Modify: `api/src/main/resources/application.yaml` (`management:` 블록 전체 교체, `server:` 블록에 tomcat 설정 추가)
- Modify: `api/src/main/resources/application-prod.yaml` (`management:` 블록 전체 교체, `server:` 블록에 tomcat 설정 추가)
- Modify: `docker-compose.prod.yml` (`api.healthcheck.test`)
- Modify: `api/Dockerfile` (`EXPOSE`)
- Test: `api/src/test/java/com/alldap/api/global/config/ManagementPortIntegrationTest.java` (신규)

**Interfaces:**
- Consumes: 없음 (이 PR 의 첫 작업)
- Produces:
  - Spring 이 `http://<host>:8081/actuator/prometheus` 로 Prometheus 텍스트 포맷을 내보낸다. Task 2 의 `observability/prometheus.yml` 이 이 주소를 긁는다.
  - `http://<host>:8081/actuator/health` 가 헬스체크 대상이다. `docker-compose.prod.yml` 이 이 주소를 부른다.
  - 8080 에서는 actuator 가 **사라진다.** 8080 의 `/actuator/health` 는 이제 404 다.

---

- [ ] **Step 1: 브랜치를 딴다**

```bash
git checkout main && git pull
git checkout -b feat/loadtest-observability
```

- [ ] **Step 2: 실패하는 테스트를 쓴다**

`api/src/test/java/com/alldap/api/global/config/ManagementPortIntegrationTest.java` 를 새로 만든다.

이 테스트가 실제로 재는 것은 **세 가지 사실**이다.
1. 8080 에서 actuator 가 사라졌는가 (분리가 실제로 일어났는가)
2. 8081 에서 `health` · `prometheus` 가 나오는가
3. **8081 에 `SecurityConfig` 의 필터 체인이 적용되는가** — 스펙이 "문서를 믿지 말고 테스트로" 라고 적어둔 자리다. management 포트를 분리하면 Boot 가 별도 자식 컨텍스트를 만드는데, 부모 컨텍스트의 `SecurityFilterChain` 빈이 자식의 서블릿 필터로 등록되는지는 버전마다 다르다.

```java
package com.alldap.api.global.config;

import com.alldap.api.support.IntegrationTest;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.boot.test.web.server.LocalManagementPort;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * management 포트(8081) 분리가 실제로 어떻게 동작하는지 <b>재는</b> 테스트.
 *
 * <h2>왜 이 테스트가 필요한가</h2>
 * management 포트를 분리하면 Spring Boot 가 <b>별도 자식 컨텍스트</b>를 만든다.
 * 부모(주 애플리케이션) 컨텍스트의 {@code SecurityFilterChain} 빈이 자식 컨텍스트의
 * 서블릿 필터로도 등록되는지는 <b>문서로 확언할 수 없다.</b>
 * 적용되지 않으면 8081 은 인증 없이 열린다.
 *
 * <p>포트를 {@code docker-compose.prod.yml} 에서 열지 않으므로 실질 위험은 없다.
 * 그래도 재는 이유는 <b>"그렇게 되어 있다는 걸 아는 것"과 "그럴 것이라 믿는 것"이 다르기</b> 때문이다.
 * 이 저장소는 짜둔 검사가 아무 데서도 안 돌아 오픈 리다이렉트가 뚫린 적이 있다.
 *
 * <h2>{@code @LocalManagementPort} 가 필요한 이유</h2>
 * {@link IntegrationTest} 는 {@code RANDOM_PORT} 다. Boot 의
 * {@code SpringBootTestRandomPortContextCustomizer} 가 서비스 포트뿐 아니라
 * {@code management.server.port} 도 함께 무작위로 바꾼다(그래서 8081 로 고정해도
 * 기존 통합 테스트들이 포트 충돌로 깨지지 않는다). 실제 포트는 이 애너테이션으로 받는다.
 */
@IntegrationTest
@DisplayName("management 포트 분리")
class ManagementPortIntegrationTest {

    @Autowired
    TestRestTemplate restTemplate;   // 서비스 포트(8080 자리)를 가리킨다

    @LocalManagementPort
    int managementPort;

    @Test
    @DisplayName("서비스 포트에서는 actuator 가 사라진다")
    void actuatorIsGoneFromServicePort() {
        ResponseEntity<String> response = restTemplate.getForEntity("/actuator/health", String.class);

        // 404 를 기대한다. actuator 가 자식 컨텍스트로 옮겨갔으므로 이 포트에는 그 경로가 없다.
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.NOT_FOUND);
    }

    @Test
    @DisplayName("management 포트에서 health 가 UP 을 준다")
    void healthIsServedOnManagementPort() {
        ResponseEntity<String> response = new TestRestTemplate()
                .getForEntity("http://localhost:" + managementPort + "/actuator/health", String.class);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(response.getBody()).contains("\"status\":\"UP\"");
    }

    @Test
    @DisplayName("management 포트에서 prometheus 스크레이프가 나온다")
    void prometheusIsServedOnManagementPort() {
        ResponseEntity<String> response = new TestRestTemplate()
                .getForEntity("http://localhost:" + managementPort + "/actuator/prometheus", String.class);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
        // Prometheus 텍스트 포맷의 첫 글자는 주석(#)이다. 지표 이름 하나로 내용을 확인한다.
        assertThat(response.getBody()).contains("jvm_memory_used_bytes");
    }

    @Test
    @DisplayName("management 포트에는 Hikari·Tomcat 지표가 실제로 실려 나온다")
    void poolAndThreadMetricsArePresent() {
        // 이 두 지표가 부하테스트의 판정 근거다. 없으면 관측을 구축한 의미가 없다.
        // 특히 tomcat_threads_busy_threads 는 server.tomcat.mbeanregistry.enabled=true 가 없으면
        // 조용히 사라진다(에러가 아니라 지표가 그냥 안 나온다).
        String body = new TestRestTemplate()
                .getForEntity("http://localhost:" + managementPort + "/actuator/prometheus", String.class)
                .getBody();

        assertThat(body).contains("hikaricp_connections_pending");
        assertThat(body).contains("tomcat_threads_busy_threads");
    }

    @Test
    @DisplayName("[실측 기록] management 포트에는 SecurityConfig 필터 체인이 붙지 않는다")
    void managementPortIsNotSecured() {
        // JWT 없이 부른다. 주 포트였다면 /actuator/metrics 는 anyRequest().authenticated() 에 걸려 401 이다.
        ResponseEntity<String> response = new TestRestTemplate()
                .getForEntity("http://localhost:" + managementPort + "/actuator/metrics", String.class);

        // 🔴 이 단언이 <200> 인 것이 이 테스트의 요점이다.
        //    자식 컨텍스트에는 부모의 SecurityFilterChain 이 서블릿 필터로 등록되지 않는다.
        //    = 8081 은 인증 없이 열린다. 방어는 "포트를 안 여는 것" 하나뿐이며,
        //      그 방어선은 docker-compose.prod.yml 이 api 에 ports: 를 안 쓰는 것이다.
        //    ⚠️ 이 테스트가 401 로 깨지면 Boot 가 동작을 바꾼 것이다. 그때는 이 주석과
        //      docker-compose.prod.yml 의 관련 주석을 함께 고칠 것(깨진 채로 두지 말 것).
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
    }
}
```

- [ ] **Step 3: 테스트를 돌려 실패를 확인한다**

Run: `cd api && ./gradlew test --tests '*ManagementPortIntegrationTest*'`

Expected: FAIL. 아직 설정을 안 바꿨으므로 5개 중 최소 4개가 깨진다.
- `actuatorIsGoneFromServicePort` → 404 를 기대했는데 **200** (아직 8080 에 있다)
- `healthIsServedOnManagementPort` → management 포트가 서비스 포트와 같아 `@LocalManagementPort` 가 서비스 포트를 주고, `/actuator/health` 는 200 이라 **통과할 수도 있다** (이건 정상이다)
- `prometheusIsServedOnManagementPort` → **404** (의존성도 노출 설정도 없다)
- `poolAndThreadMetricsArePresent` → 본문이 null 이라 NPE 또는 실패
- `managementPortIsNotSecured` → `/actuator/metrics` 가 **401** (노출도 안 됐고 SecurityConfig 가 막는다)

- [ ] **Step 4: 의존성을 추가한다**

`api/build.gradle` 의 `dependencies` 블록에서 actuator 줄 바로 아래에 넣는다.

```groovy
	implementation 'org.springframework.boot:spring-boot-starter-actuator'
	// Prometheus 스크레이프 포맷(/actuator/prometheus)을 내보낸다.
	// 버전은 Boot 의 dependency-management 가 관리하므로 적지 않는다(적으면 Boot 를 올릴 때 어긋난다).
	implementation 'io.micrometer:micrometer-registry-prometheus'
```

- [ ] **Step 5: 로컬 프로파일 설정을 고친다**

`api/src/main/resources/application.yaml` 에서 `server:` 블록을 아래로 **교체**한다.

```yaml
server:
  port: 8080
  tomcat:
    mbeanregistry:
      # 🔴 이게 없으면 tomcat.threads.* 지표가 <에러 없이 그냥 안 나온다.>
      #    부하테스트의 1순위 판정 근거가 "스레드가 몇 개 바쁜가" 라서 반드시 켠다.
      #    비용은 MBean 등록 몇 개다.
      enabled: true
```

이어서 같은 파일의 `management:` 블록 전체를 아래로 **교체**한다.

```yaml
management:
  server:
    # 🔴 서비스 포트(8080)와 <분리>한다. 이유는 두 가지다.
    #   ① 운영에서 actuator 를 껐다 켜는 편법 없이 상시 켜둘 수 있다.
    #      안전한 근거는 docker-compose.prod.yml 이 8081 을 ports: 에 안 여는 것이다.
    #      "방화벽으로 막는다" 가 아니라 애초에 호스트에 뜨지 않게 하는 쪽이 강하다.
    #      (Spring Security 규칙 한 줄의 오타에 기대는 것보다 훨씬 강하다)
    #   ② 부하테스트 중 서비스 포트가 포화돼도 지표는 계속 긁힌다.
    #      같은 포트면 톰캣 스레드가 마르는 순간 관측도 함께 멎어, 정작 알고 싶은
    #      "포화된 순간" 의 지표가 비어버린다.
    # ⚠️ 이 포트에는 SecurityConfig 의 필터 체인이 붙지 않는다(별도 자식 컨텍스트라서).
    #    실측 기록은 ManagementPortIntegrationTest 참고. 방어는 "포트를 안 여는 것" 하나뿐이다.
    port: 8081
  endpoints:
    web:
      exposure:
        # 포트가 분리돼 인터넷에서 닿지 않으므로 부하테스트에 필요한 만큼 연다.
        include: health,metrics,prometheus
  endpoint:
    health:
      show-details: never
  metrics:
    distribution:
      percentiles-histogram:
        # p95·p99 를 Grafana 에서 계산하려면 히스토그램 버킷이 필요하다.
        # 이게 없으면 count/sum 만 나와 <평균밖에> 못 그린다.
        # 평균은 느린 꼬리를 감춘다(avg_faithfulness 로 이미 데인 부류다).
        http.server.requests: true
```

- [ ] **Step 6: 운영 프로파일 설정을 고친다**

`api/src/main/resources/application-prod.yaml` 의 `server:` 블록에 tomcat 설정을 추가한다. 기존 `port:` 와 `forward-headers-strategy:` 는 그대로 두고 아래를 **덧붙인다**.

```yaml
  tomcat:
    mbeanregistry:
      # tomcat.threads.* 지표. 근거는 application.yaml 의 같은 항목 주석 참고.
      enabled: true
```

이어서 같은 파일의 `management:` 블록 전체를 아래로 **교체**한다.

```yaml
management:
  server:
    # 🔴 운영에서도 켠다. 안전한 근거는 <포트를 안 여는 것>이다 —
    #    docker-compose.prod.yml 의 api 서비스에 ports: 가 없어 이 포트는 호스트에 뜨지 않고,
    #    Caddy 는 api:8080 만 안다. ai-service 에 ports: 를 안 쓰는 것과 같은 논리다.
    # ⚠️ 이 포트에는 인증이 없다(ManagementPortIntegrationTest 실측).
    #    api 서비스에 ports: 를 추가하는 순간 지표가 인터넷에 열린다. 추가하지 말 것.
    port: ${MANAGEMENT_SERVER_PORT:8081}
  endpoints:
    web:
      exposure:
        include: health,metrics,prometheus
  endpoint:
    health:
      show-details: never
  metrics:
    distribution:
      percentiles-histogram:
        http.server.requests: true
```

- [ ] **Step 7: 테스트를 돌려 통과를 확인한다**

Run: `cd api && ./gradlew test --tests '*ManagementPortIntegrationTest*'`

Expected: PASS (5건).

⚠️ `managementPortIsNotSecured` 가 401 로 깨지면 **Boot 4 가 부모의 필터 체인을 자식에 적용한다는 뜻**이다. 그건 나쁜 소식이 아니라 더 좋은 소식이다. 그때는 ① 단언을 401 로 바꾸고 ② 테스트·`application.yaml`·`application-prod.yaml` 의 "인증이 없다" 주석 3곳을 사실에 맞게 고친 뒤 ③ Prometheus 가 긁을 수 있도록 `SecurityConfig` 에 `/actuator/prometheus` permitAll 을 추가한다. **주석을 틀린 채로 두지 말 것** — 이 저장소는 "되는 기능을 안 된다고 안내한" 적이 있다.

- [ ] **Step 8: 전체 테스트를 돌려 회귀가 없는지 본다**

Run: `cd api && ./gradlew test`

Expected: PASS. 기존 164건 + 신규 5건.

기존 통합 테스트가 깨지면 원인은 십중팔구 **`/actuator/health` 를 부르는 테스트**다. 그런 테스트가 있으면 `@LocalManagementPort` 를 쓰도록 고친다.

- [ ] **Step 9: 배포 파일을 함께 고친다 (안 고치면 배포가 영영 안 뜬다)**

`docker-compose.prod.yml` 의 `api.healthcheck.test` 를 8081 로 옮긴다.

```yaml
    healthcheck:
      # 🔴 8080 이 아니라 8081 이다. actuator 가 management 포트로 옮겨갔다.
      #    안 고치면 헬스체크가 영원히 실패하고, ai-service 가
      #    depends_on: service_healthy 에 걸려 <영영 안 뜬다.>
      test: ["CMD-SHELL", "curl -fsS http://localhost:8081/actuator/health || exit 1"]
      interval: 15s
      timeout: 5s
      retries: 40
      # t3.micro 는 느리다. 이 시간 안의 실패는 재시도 횟수로 세지 않는다.
      start_period: 180s
```

`api/Dockerfile` 의 `EXPOSE` 를 고친다.

```dockerfile
# 8081 은 management(actuator) 포트다. EXPOSE 는 문서 목적일 뿐 포트를 여는 것이 아니다 —
# 실제 노출 여부는 compose 의 ports: 가 정하고, 운영에서는 <아무도 안 연다.>
EXPOSE 8080 8081
```

- [ ] **Step 10: `docker-compose.prod.yml` 이 api 에 ports 를 안 쓰는지 눈으로 확인한다**

Run: `grep -n -A2 'ports:' docker-compose.prod.yml`

Expected: `ports:` 가 **caddy 아래에만** 나온다 (`"80:80"`, `"443:443"`). api·ai-service 아래에는 없어야 한다. 있으면 이 PR 의 안전 근거가 통째로 무너진다.

- [ ] **Step 11: 커밋한다**

```bash
git add api/build.gradle \
        api/src/main/resources/application.yaml \
        api/src/main/resources/application-prod.yaml \
        api/src/test/java/com/alldap/api/global/config/ManagementPortIntegrationTest.java \
        docker-compose.prod.yml \
        api/Dockerfile
git commit -m "feat: actuator 를 management 포트 8081 로 분리한다

부하테스트 중 서비스 포트가 포화돼도 지표를 계속 긁기 위해서다.
같은 포트면 톰캣 스레드가 마르는 순간 관측도 함께 멎어,
정작 알고 싶은 포화 순간의 지표가 비어버린다.

운영에서도 상시 켜두되 compose 에서 ports 를 안 열어 인터넷에서 닿지 않게 한다.
ai-service 에 ports 를 안 쓰는 것과 같은 논리다.

8081 에 SecurityConfig 필터 체인이 붙는지는 문서를 믿지 않고
통합 테스트로 실측했다(ManagementPortIntegrationTest).

healthcheck 를 8081 로 함께 옮겼다. 안 고치면 ai-service 가
depends_on: service_healthy 에 걸려 영영 안 뜬다."
```

---

## Task 2: 로컬 Prometheus + Grafana

**Files:**
- Create: `observability/prometheus.yml`
- Create: `observability/grafana/provisioning/datasources/prometheus.yml`
- Create: `observability/grafana/provisioning/dashboards/dashboards.yml`
- Create: `observability/grafana/dashboards/alldap-api.json`
- Modify: `docker-compose.yml` (services 에 prometheus·grafana 추가, volumes 에 grafana 볼륨 추가)
- Test: 수동 확인 (브라우저). 자동 테스트를 두지 않는 이유는 Step 6 참고.

**Interfaces:**
- Consumes: Task 1 이 만든 `http://<host>:8081/actuator/prometheus`
- Produces: `http://localhost:3001` 의 "AllDap API" 대시보드. PR 3(S2 breakpoint)이 부하 곡선과 겹쳐 볼 화면이다.

---

- [ ] **Step 1: Prometheus 스크레이프 설정을 만든다**

`observability/prometheus.yml`:

```yaml
# 로컬 부하테스트용 Prometheus. 운영에는 올리지 않는다 —
# Prometheus + Grafana 가 합쳐 200~300MB 인데 t3.micro 는 유휴에 이미 스왑을 쓴다.
# 얹으면 모니터링이 장애 원인이 된다.

global:
  # 15초. 단계당 2분 유지하는 S2 시나리오에서 단계마다 점이 8개 찍힌다.
  # 더 짧게 하면 저장 용량만 늘고, 더 길면 꺾이는 지점을 놓친다.
  scrape_interval: 15s

scrape_configs:
  - job_name: alldap-api
    metrics_path: /actuator/prometheus
    static_configs:
      # 🔴 host.docker.internal 이다. localhost 가 아니다.
      #    Spring 은 컨테이너 밖(맥 호스트)에서 gradle 로 돌리는데,
      #    Prometheus 는 컨테이너 안이라 그 안의 localhost 는 Prometheus 자기 자신이다.
      #    (Docker Desktop 이 호스트를 가리키는 이름으로 이걸 제공한다)
      - targets: ['host.docker.internal:8081']
```

- [ ] **Step 2: Grafana 프로비저닝 파일 2개를 만든다**

`observability/grafana/provisioning/datasources/prometheus.yml`:

```yaml
# Grafana 가 기동할 때 데이터소스를 자동으로 문다.
# UI 로 손수 등록하면 그 설정이 저장소에 안 남아, 다음 사람이 같은 화면을 못 만든다.
apiVersion: 1

datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    # 같은 compose 네트워크 안이라 서비스 이름으로 부른다.
    url: http://prometheus:9090
    isDefault: true
```

`observability/grafana/provisioning/dashboards/dashboards.yml`:

```yaml
# 대시보드 JSON 을 파일에서 자동으로 읽는다.
# 이것도 같은 이유다 — UI 에서 만든 대시보드는 컨테이너를 지우면 사라진다.
apiVersion: 1

providers:
  - name: alldap
    type: file
    # UI 에서 수정해도 파일이 진실이다. 재기동하면 파일 내용으로 돌아간다.
    allowUiUpdates: false
    options:
      path: /var/lib/grafana/dashboards
```

- [ ] **Step 3: 대시보드 JSON 을 만든다**

`observability/grafana/dashboards/alldap-api.json`:

```json
{
  "uid": "alldap-api",
  "title": "AllDap API",
  "tags": ["loadtest"],
  "timezone": "browser",
  "schemaVersion": 39,
  "refresh": "10s",
  "time": { "from": "now-15m", "to": "now" },
  "panels": [
    {
      "id": 1,
      "type": "timeseries",
      "title": "처리량 (2xx 만) req/s",
      "description": "429 나 500 은 세지 않는다. 초당 500건이 전부 429 인데 '빠르다' 고 읽는 것을 막는다.",
      "gridPos": { "h": 8, "w": 12, "x": 0, "y": 0 },
      "targets": [
        {
          "refId": "A",
          "expr": "sum(rate(http_server_requests_seconds_count{outcome=\"SUCCESS\"}[1m]))",
          "legendFormat": "2xx"
        },
        {
          "refId": "B",
          "expr": "sum(rate(http_server_requests_seconds_count{outcome!=\"SUCCESS\"}[1m])) by (outcome)",
          "legendFormat": "{{outcome}}"
        }
      ]
    },
    {
      "id": 2,
      "type": "timeseries",
      "title": "지연 p50 / p95 / p99 (초)",
      "description": "평균은 일부러 안 그린다. 느린 꼬리를 감춘다.",
      "gridPos": { "h": 8, "w": 12, "x": 12, "y": 0 },
      "fieldConfig": { "defaults": { "unit": "s" }, "overrides": [] },
      "targets": [
        {
          "refId": "A",
          "expr": "histogram_quantile(0.50, sum(rate(http_server_requests_seconds_bucket[1m])) by (le))",
          "legendFormat": "p50"
        },
        {
          "refId": "B",
          "expr": "histogram_quantile(0.95, sum(rate(http_server_requests_seconds_bucket[1m])) by (le))",
          "legendFormat": "p95"
        },
        {
          "refId": "C",
          "expr": "histogram_quantile(0.99, sum(rate(http_server_requests_seconds_bucket[1m])) by (le))",
          "legendFormat": "p99"
        }
      ]
    },
    {
      "id": 3,
      "type": "timeseries",
      "title": "Hikari 커넥션 풀",
      "description": "pending 이 0 보다 크면 커넥션을 기다리는 스레드가 있다는 확정 증거다. 추측이 아니라 숫자다.",
      "gridPos": { "h": 8, "w": 12, "x": 0, "y": 8 },
      "targets": [
        { "refId": "A", "expr": "hikaricp_connections_active", "legendFormat": "active" },
        { "refId": "B", "expr": "hikaricp_connections_pending", "legendFormat": "pending (대기)" },
        { "refId": "C", "expr": "hikaricp_connections_max", "legendFormat": "max" }
      ]
    },
    {
      "id": 4,
      "type": "timeseries",
      "title": "Tomcat 스레드",
      "description": "1순위 가설(Python 스레드풀 40 이 먼저 찬다)이 맞다면 busy 가 200 근처까지 안 간다.",
      "gridPos": { "h": 8, "w": 12, "x": 12, "y": 8 },
      "targets": [
        { "refId": "A", "expr": "tomcat_threads_busy_threads", "legendFormat": "busy" },
        { "refId": "B", "expr": "tomcat_threads_current_threads", "legendFormat": "current" },
        { "refId": "C", "expr": "tomcat_threads_config_max_threads", "legendFormat": "max" }
      ]
    },
    {
      "id": 5,
      "type": "timeseries",
      "title": "힙 사용률 (%) · GC 정지",
      "description": "2순위 가설. 운영은 -Xmx256m + ExitOnOutOfMemoryError 라 마르면 죽고 재시작한다. 그때 k6 가 보는 증상은 '느려진다' 가 아니라 '연결이 끊기고 30초쯤 뒤 돌아온다' 이다.",
      "gridPos": { "h": 8, "w": 24, "x": 0, "y": 16 },
      "targets": [
        {
          "refId": "A",
          "expr": "100 * sum(jvm_memory_used_bytes{area=\"heap\"}) / sum(jvm_memory_max_bytes{area=\"heap\"})",
          "legendFormat": "힙 사용률 %"
        },
        {
          "refId": "B",
          "expr": "1000 * rate(jvm_gc_pause_seconds_sum[1m]) / clamp_min(rate(jvm_gc_pause_seconds_count[1m]), 0.0001)",
          "legendFormat": "GC 평균 정지 ms"
        }
      ]
    }
  ]
}
```

**패널이 6개가 아니라 5개인 이유:** 스펙의 6번째 패널("가짜 CF 호출 수")은 PR 2 가 만드는 가짜 서버가 내주는 카운터다. 아직 그 서버가 없으므로 지금 넣으면 영원히 빈 패널이다. **PR 2 에서 추가한다.**

- [ ] **Step 4: compose 에 두 서비스를 추가한다**

`docker-compose.yml` 의 `services:` 아래, `db:` 블록 다음에 추가한다.

```yaml
  # ── 로컬 관측 스택 (부하테스트용) ───────────────────────────────────
  # 🔴 profiles 로 격리한다. `docker compose up -d` 는 예전처럼 db 만 띄우고,
  #    관측이 필요할 때만 `docker compose --profile obs up -d` 로 켠다.
  #    평소 개발에 250MB 를 상시로 물릴 이유가 없다.
  # 운영(docker-compose.prod.yml)에는 이 둘이 <없다.> t3.micro 는 유휴에 이미 스왑을 쓴다.
  prometheus:
    image: prom/prometheus:v3.1.0
    container_name: alldap-prometheus
    profiles: [obs]
    ports:
      # db 와 같은 이유로 127.0.0.1 에 묶는다. 사내망의 누구나 지표를 읽으면 안 된다.
      - "127.0.0.1:9090:9090"
    volumes:
      - ./observability/prometheus.yml:/etc/prometheus/prometheus.yml:ro
    extra_hosts:
      # 리눅스에서는 host.docker.internal 이 기본 제공되지 않는다. 이 줄이 그걸 메운다.
      # (맥 Docker Desktop 에서는 이미 되지만, 있어도 무해하다)
      - "host.docker.internal:host-gateway"

  grafana:
    image: grafana/grafana:11.5.1
    container_name: alldap-grafana
    profiles: [obs]
    depends_on:
      - prometheus
    ports:
      # 🔴 3001 이다. 3000 은 Next.js 개발 서버가 쓴다.
      - "127.0.0.1:3001:3000"
    environment:
      # 로컬 전용이라 로그인을 끈다. 부하테스트 중에 로그인 화면을 보고 싶지 않다.
      # 운영에는 이 스택 자체가 없으므로 이 설정이 새어 나갈 곳이 없다.
      GF_AUTH_ANONYMOUS_ENABLED: "true"
      GF_AUTH_ANONYMOUS_ORG_ROLE: Admin
      GF_AUTH_DISABLE_LOGIN_FORM: "true"
    volumes:
      - ./observability/grafana/provisioning:/etc/grafana/provisioning:ro
      - ./observability/grafana/dashboards:/var/lib/grafana/dashboards:ro
      - alldap-grafana:/var/lib/grafana
```

같은 파일 맨 아래 `volumes:` 블록에 한 줄 추가한다.

```yaml
volumes:
  alldap-pgdata:
  # Grafana 의 내부 SQLite. 대시보드 자체는 프로비저닝 파일이 진실이지만,
  # 이게 없으면 재기동마다 Grafana 가 초기화 로그를 잔뜩 뱉는다.
  alldap-grafana:
```

- [ ] **Step 5: 실제로 띄워서 지표가 흐르는지 본다**

```bash
docker compose --profile obs up -d
cd api && ./gradlew bootRun    # 별도 터미널. Flyway 가 돌아야 하므로 db 가 먼저 떠 있어야 한다
```

Spring 이 뜬 뒤:

```bash
# ① Spring 이 지표를 내주는가
curl -s localhost:8081/actuator/prometheus | grep -c '^hikaricp_connections_pending'
# Expected: 1

# ② Prometheus 가 그 대상을 실제로 긁고 있는가 (설정 파일이 맞아도 못 붙을 수 있다)
curl -s 'localhost:9090/api/v1/targets' | grep -o '"health":"[a-z]*"'
# Expected: "health":"up"
#   "down" 이면 host.docker.internal 이 안 풀린 것이다. 컨테이너 안에서
#   `docker compose exec prometheus wget -qO- host.docker.internal:8081/actuator/health` 로 확인한다.

# ③ 실제 값이 저장됐는가
curl -s 'localhost:9090/api/v1/query?query=tomcat_threads_busy_threads' | grep -o '"value"'
# Expected: "value" 가 한 번 이상 나온다. 아무것도 안 나오면
#   server.tomcat.mbeanregistry.enabled 가 안 켜진 것이다(Task 1 Step 5).
```

- [ ] **Step 6: 브라우저로 대시보드를 확인한다**

`http://localhost:3001/d/alldap-api` 를 연다.

Expected: 패널 5개가 모두 **값을 그린다.** 빈 패널이 있으면 그 지표가 안 나오는 것이고, 그 상태로 PR 3 을 시작하면 부하 중에 알게 된다.

빈 패널을 흔들어 값이 나오게 하려면 API 를 몇 번 부른다:

```bash
for i in $(seq 1 20); do curl -s -o /dev/null localhost:8080/api/auth/login -X POST \
  -H 'Content-Type: application/json' -d '{"email":"x@x.com","password":"nope12345"}'; done
```

Expected: "처리량" 패널에 `CLIENT_ERROR` 선이 뜨고, "지연" 패널에 p50/p95/p99 가 그려진다.

**자동 테스트를 두지 않는 이유:** 검증 대상이 "Grafana 가 이 JSON 을 읽어 화면을 그리는가" 인데, 그걸 자동으로 재려면 Grafana API 를 호출하는 테스트 하니스가 필요하다. 그 하니스가 대시보드 JSON 보다 커진다. 대신 위 Step 5 의 curl 3개가 **진짜 위험한 부분**(지표가 아예 안 나오는 것)을 잡는다.

- [ ] **Step 7: 컨테이너를 내리고 커밋한다**

```bash
docker compose --profile obs down
git add observability docker-compose.yml
git commit -m "chore: 로컬 관측 스택(Prometheus + Grafana)을 붙인다

부하테스트 중 커넥션 풀·톰캣 스레드·힙을 부하 곡선과 같은 시간축에
겹쳐 보기 위해서다. 관측이 없으면 k6 응답시간만 보고
'아마 풀이 말랐겠지' 라고 추측하게 된다.

profiles: obs 로 격리해 평소 docker compose up 은 예전처럼 db 만 띄운다.
운영에는 올리지 않는다. t3.micro 는 유휴에 이미 스왑을 써서
얹으면 모니터링이 장애 원인이 된다.

대시보드 JSON 을 저장소에 커밋해 재현 가능하게 뒀다.
패널은 5개다. 6번째 '가짜 CF 호출 수' 는 그 서버를 만드는 PR 2 에서 붙인다."
```

- [ ] **Step 8: PR 을 연다**

```bash
cd api && ./gradlew test    # 마지막으로 한 번 더
git push -u origin feat/loadtest-observability
gh pr create --title "feat: 부하테스트 PR 1 - 관측 구축(management 포트 분리 + Grafana)" --body "$(cat <<'BODY'
## 무엇을 왜 바꿨나요

부하테스트(`docs/superpowers/specs/2026-09-10-loadtest-design.md`)의 첫 조각이다.
측정보다 **먼저** 관측을 붙인다. 없으면 k6 의 응답시간만 보고 "아마 풀이 말랐겠지" 라고
추측하게 되는데, 이 저장소는 리랭커 비용을 추정하고 켰다가 실측(13.6 뉴런)에서 빗나간 적이 있다.

- actuator 를 서비스 포트(8080)와 분리해 **management 포트 8081** 로 옮겼다
- Prometheus 스크레이프 엔드포인트를 열었다 (`micrometer-registry-prometheus`)
- 로컬에만 Prometheus + Grafana 를 붙였다 (compose profile `obs`)

## 어떻게 해결했나요

**포트를 나눈 이유가 두 가지다.**
① 운영에서 actuator 를 껐다 켜는 편법 없이 상시 켜둘 수 있다. 안전한 근거는
`docker-compose.prod.yml` 이 `api` 에 `ports:` 를 안 쓰는 것이다. Spring Security 규칙
한 줄의 오타에 기대는 것보다 강하다.
② 부하 중 서비스 포트가 포화돼도 지표가 계속 긁힌다. 같은 포트면 톰캣 스레드가 마르는
순간 관측도 함께 멎어, 정작 알고 싶은 포화 순간의 지표가 비어버린다.

**8081 의 보안을 문서로 믿지 않고 쟀다.** `ManagementPortIntegrationTest` 5건.

```
$ ./gradlew test --tests '*ManagementPortIntegrationTest*'
(여기에 실제 실행 결과를 붙일 것)
```

**같이 고쳐야 했던 것:** `docker-compose.prod.yml` 의 헬스체크가 `localhost:8080/actuator/health`
를 부르고 있었다. 안 고쳤으면 헬스체크가 영원히 실패하고 `ai-service` 가
`depends_on: service_healthy` 에 걸려 영영 안 뜬다.

## 한계 & 트레이드오프

- 🔴 **8081 에는 인증이 없다.** management 는 별도 자식 컨텍스트라 부모의
  `SecurityFilterChain` 이 붙지 않는다(추측이 아니라 테스트로 확인). 방어는 **포트를 안 여는 것**
  하나뿐이다. `api` 서비스에 `ports:` 를 추가하는 순간 지표가 인터넷에 열린다.
- 🔴 **운영에 관측 스택이 없다.** t3.micro 는 유휴에 이미 스왑 506Mi 라 Prometheus + Grafana
  200~300MB 를 얹으면 모니터링이 장애 원인이 된다. 그래서 운영의 절대 수치는
  `docker stats` / `free -m` / 로그로만 본다. 서버를 키우면 Prometheus 가 그 8081 을
  가리키게만 하면 된다.
- **Grafana 대시보드에 자동 테스트가 없다.** 하니스가 대시보드 JSON 보다 커진다.
  대신 "지표가 아예 안 나오는" 진짜 위험은 통합 테스트 4번째 케이스가 잡는다.
- **패널이 5개다.** 6번째 "가짜 CF 호출 수" 는 PR 2 에서 붙는다.
- **재보지 않은 것:** 8081 이 붙으면서 늘어난 메모리. 자식 컨텍스트 하나 + 톰캣 커넥터 하나라
  수십 MB 로 짐작하지만 **재지 않았다.** 운영 배포 뒤 `docker stats` 로 볼 것.

## 검토한 대안과 선택 이유

| 대안 | 기각 이유 |
|---|---|
| 같은 포트(8080)에 actuator 를 두고 `SecurityConfig` 로 막기 | 부하 중 포화되면 관측도 함께 멎는다. 그리고 방어가 `permitAll` 한 줄의 정확성에 걸린다 |
| 부하테스트 때만 환경변수로 임시 노출 | 껐다 켜는 것을 잊는다. 이 저장소가 "짜둔 검사가 안 도는" 부류로 이미 두 번 데였다 |
| 운영에도 Prometheus + Grafana 설치 | 메모리가 없다. 모니터링이 장애 원인이 된다 |
| Grafana 대시보드를 UI 에서 만들기 | 컨테이너를 지우면 사라지고 저장소에 안 남아 재현이 안 된다 |
BODY
)"
```

⚠️ `gh pr create` 까지가 이 계획의 끝이다. **CI 결과를 폴링하지 않는다.**

---

## Self-Review

**스펙 대비 커버리지**

| 스펙 항목 | 담당 |
|---|---|
| `micrometer-registry-prometheus` 의존성 1개 추가 | Task 1 Step 4 |
| `management.server.port: 8081` + 노출 3개 | Task 1 Step 5·6 |
| 운영에서도 그대로 켠다 | Task 1 Step 6 (`application-prod.yaml`) |
| prod 헬스체크를 8081 로 | Task 1 Step 9 |
| `Dockerfile` EXPOSE 8081 | Task 1 Step 9 |
| management 포트의 보안을 통합 테스트로 확인 | Task 1 Step 2·7 |
| Prometheus :9090 / Grafana :3001 | Task 2 Step 4 |
| 대시보드 JSON 을 저장소에 커밋 | Task 2 Step 3 |
| Grafana 패널 6개 | **5개.** 6번째는 PR 2 소관 (근거 명시) |
| 운영에는 관측 스택 없음 | Task 2 Step 4 주석 + PR 본문 |

**스펙에 없는데 넣은 것 2개 (근거 있음)**
- `server.tomcat.mbeanregistry.enabled: true` — 없으면 스펙이 요구한 "Tomcat 스레드" 패널의 지표가 **에러 없이 그냥 안 나온다.** 스펙의 요구를 만족시키기 위해 필요한 값이다.
- `management.metrics.distribution.percentiles-histogram` — 없으면 스펙이 요구한 p95·p99 를 Grafana 가 계산할 수 없고 **평균밖에** 못 그린다. 스펙 결정 7번("평균은 참고만")과 정면으로 충돌한다.

**타입·이름 일관성**: `alldap-api` 라는 uid 가 대시보드 JSON(Task 2 Step 3)과 확인 URL(Step 6)에서 일치한다. `host.docker.internal:8081` 이 `prometheus.yml`(Step 1)과 `extra_hosts`(Step 4)에서 일치한다. management 포트 8081 이 `application.yaml` · `application-prod.yaml` · `docker-compose.prod.yml` · `Dockerfile` · `prometheus.yml` 다섯 곳에서 일치한다.
