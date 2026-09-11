#!/usr/bin/env bash
# 배포 뒤 "컨테이너가 <방금 받은 이미지>로 돌고 있는가" 를 확인한다. 서버에서 돈다.
#
# 왜 필요한가
# ─────────────────────────────────────────────────────────────────────────────
# /actuator/health 는 버전을 모른다. 옛 컨테이너가 그대로 떠 있어도 UP 이다.
# 2026-09-09 의 사고가 정확히 그 모양이었다: 서버 git 은 최신인데 컨테이너는
# 32시간 전 것이었다(git pull 은 했고 up -d 를 안 돌린 상태).
# 밖에서는 확인할 수 없다 - /actuator/info · /env · /metrics 가 전부 401 이고
# 열려 있는 /health 는 버전을 안 알려준다. 그래서 SSH 세션 안에서 본다.
#
# 무엇을 신호로 삼나
# ─────────────────────────────────────────────────────────────────────────────
#   기대값: compose 파일이 가리키는 <태그가 지금 가리키는 이미지>의 RootFS.Layers
#           (config --format json 에서 그 서비스의 image 를 읽는다)
#   실제값: 그 서비스의 <컨테이너가 실제로 실행 중인 이미지>의 RootFS.Layers
#           (.Image 로 이미지를 찾아 같은 필드를 읽는다)
#
# 두 값이 다르면 "pull 로 새 이미지가 왔는데 컨테이너는 옛것으로 돌고 있다" 뿐이다.
# 실패시켜야 하는 경우가 정확히 이것이다.
#
# 🔴 왜 digest(.Id) 가 아니라 레이어인가 - 그리고 그 대가가 무엇인가
#    2026-09-10 까지 이 검사는 `docker image inspect .Id` 와 컨테이너 `.Image` 를
#    비교했다. 그런데 `.Id` 는 이미지가 OCI index 로 밀리면 <index digest> 가 되고,
#    build-push-action@v6 의 provenance attestation 은 빌드마다 달라서
#    <내용물이 한 바이트도 안 바뀌어도> 그 값이 매번 새로 나온다.
#    compose 는 index 안의 플랫폼 매니페스트 digest 를 보므로 "안 바뀌었다"(옳다)고
#    판정하는데 이 검사만 "바뀌었다"고 우겨서 <정상 배포가 실패>했다.
#    당시 응급조치는 publish.yml 의 `provenance: false` 였지만, 그건 provenance 를
#    다시 켜는 순간 그대로 다시 깨진다. 그래서 기준 자체를 바꾼다.
#    RootFS.Layers 는 <내용물>이라 digest 껍데기가 어떤 형식이든 영향을 받지 않는다.
#    (실측 근거: 그때 거짓 경보를 낸 두 이미지 779b4761 / 725cabba 는 Created·크기·
#     Config 와 함께 RootFS.Layers 9개가 전부 같았다)
#
#    ⚠️ 대가를 숨기지 말 것. 검사의 뜻이 약해진다:
#         전: "컨테이너가 <받은 그 이미지>로 도는가"
#         후: "컨테이너가 <받은 이미지와 같은 내용>으로 도는가"
#       즉 태그만 갈리고 내용이 완전히 같은 이미지로 도는 경우를 이제는 통과시킨다.
#       그건 재생성해도 결과가 같으므로 배포로서는 문제가 아니다 - 실제로 2026-09-10
#       에 우리가 손으로 재생성한 것도 <아무것도 달라지지 않는> 재생성이었다.
#       반대로 이 검사가 잡아야 하는 진짜 사고(2026-09-09 의 32시간 된 컨테이너)는
#       내용이 실제로 다르므로 레이어로도 그대로 걸린다. 자체 점검 ②가 그것이다.
#
# 🔴 "이미지가 안 바뀌어서 재생성이 없었다" 를 실패로 세면 안 된다. 그건 정상이고
#    (Caddyfile 만 바뀐 배포가 그렇다), 이 검사는 그때 두 값이 <같으므로> 통과한다.
#    up -d 전후의 컨테이너 ID 를 비교하는 방식이었다면 그걸 실패로 셌을 것이다.
#
# 🔴 실패했을 때 자동으로 `--force-recreate` 하고 다시 검사하게 만들지 말 것.
#    이 검사가 잡아야 하는 진짜 사고를 자동으로 무마해버린다. 실패가 실패로 안 남으면
#    검사가 없는 것과 같다. 고치는 것은 사람이 결과를 <본 뒤에> 한다.
#
# 🔴 `config --images <svc>` 를 쓰면 안 된다. 그 서비스뿐 아니라 <depends_on 으로 딸린
#    서비스의 이미지까지> 함께 낸다. ai-service 는 depends_on: api 라 두 줄이 나오고,
#    그 두 줄짜리 문자열을 docker image inspect 에 넘기면 실패해 기대값이 비어버린다.
#    = 정상 배포인데 ai-service 가 매번 빨간불이 된다. 정상을 실패로 부르는 검사는
#    곧 무시되고, 무시되는 검사는 없는 것과 같다.
#    운영 서버(compose 5.5.1)에 붙여보고서야 나왔다. 로컬 자체 점검은 depends_on 이
#    없는 임시 compose 를 써서 못 잡았다 - 그래서 아래 check 에 의존성 있는 서비스를 넣었다.
#    (`config --no-deps` 같은 플래그는 없다. 실측: `unknown flag: --no-deps`)
#
# ⚠️ 컨테이너의 .Config.Image 를 기대값으로 쓰면 안 된다. compose 버전에 따라
#    거기에 태그가 아니라 이미지 ID 가 박히는데, 그러면 자기 자신과 비교하게 돼
#    <어떤 경우에도 통과하는 검사>가 된다. 이 저장소가 이미 두 번 겪은 부류다
#    (redirect.check.ts · rate limit 점검). compose 파일을 진실 공급원으로 삼는다.
#
# 사용:  bash scripts/verify-deploy.sh [서비스...]      (기본: api ai-service)
#        COMPOSE 를 넘기면 다른 compose 로도 돈다(자체 점검용, 아래 참고).
#
# 자체 점검: bash scripts/verify-deploy.check.sh  - 걸려야 할 것에 실제로 걸리는지 잰다.
set -euo pipefail

: "${COMPOSE:=docker compose -f docker-compose.prod.yml --env-file .env.prod}"

services=("$@")
[ ${#services[@]} -gt 0 ] || services=(api ai-service)

rc=0

# 이미지의 <내용물> 지문. 레이어 digest 목록을 그대로 쓴다.
layers() { docker image inspect -f '{{range .RootFS.Layers}}{{println .}}{{end}}' "$1"; }
# 사람이 읽을 짧은 요약 (레이어 N개 · 마지막 digest 앞 12자)
brief() { printf '%s개·%s' "$(printf '%s' "$1" | grep -c .)" "$(printf '%s' "$1" | tail -1 | cut -c8-19)"; }

for svc in "${services[@]}"; do
  cid=$($COMPOSE ps -q "$svc" | head -1)
  if [ -z "$cid" ]; then
    echo "::error::$svc 컨테이너가 없다. up -d 가 실패했는지 로그를 볼 것."
    rc=1
    continue
  fi

  tag=$($COMPOSE config --format json | jq -r --arg s "$svc" '.services[$s].image')
  want=$(layers "$tag")

  # 🔴 "컨테이너가 도는 이미지를 로컬에서 못 찾는 것" 은 "옛 이미지로 돈다" 와 다른 사실이다.
  #    같은 값으로 뭉개지 말 것(이 저장소가 반복해 낸 부류다 — AGENTS.md 의 "낸 버그" 절).
  #    판정 불가로 따로 실패시킨다.
  himg=$(docker inspect -f '{{.Image}}' "$cid")
  if ! have=$(layers "$himg" 2>/dev/null); then
    echo "::error::$svc 가 도는 이미지(${himg:0:19})를 로컬에서 찾을 수 없다. 대조 자체가 불가능하다."
    echo "  옛 이미지로 도는 것과는 다른 상태다. docker images / docker system prune 이력을 볼 것."
    rc=1
    continue
  fi

  if [ "$want" = "$have" ]; then
    echo "OK  $svc: $(brief "$want") ($tag)"
  else
    echo "::error::$svc 가 옛 이미지로 돌고 있다. 받은 것=$(brief "$want") 도는 것=$(brief "$have") ($tag)"
    echo "  손으로 고치려면: $COMPOSE up -d --force-recreate $svc"
    rc=1
  fi
done

exit $rc
