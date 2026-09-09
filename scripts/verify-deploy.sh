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
#   기대값: compose 파일이 가리키는 <태그가 지금 가리키는 이미지 ID>
#           ($C config --images <svc> 로 태그를 얻고 docker image inspect 로 ID)
#   실제값: 그 서비스의 <컨테이너가 실제로 실행 중인 이미지 ID> (.Image)
#
# 두 값이 다르면 "pull 로 새 이미지가 왔는데 컨테이너는 옛것으로 돌고 있다" 뿐이다.
# 실패시켜야 하는 경우가 정확히 이것이다.
#
# 🔴 "이미지가 안 바뀌어서 재생성이 없었다" 를 실패로 세면 안 된다. 그건 정상이고
#    (Caddyfile 만 바뀐 배포가 그렇다), 이 검사는 그때 두 값이 <같으므로> 통과한다.
#    up -d 전후의 컨테이너 ID 를 비교하는 방식이었다면 그걸 실패로 셌을 것이다.
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
for svc in "${services[@]}"; do
  cid=$($COMPOSE ps -q "$svc" | head -1)
  if [ -z "$cid" ]; then
    echo "::error::$svc 컨테이너가 없다. up -d 가 실패했는지 로그를 볼 것."
    rc=1
    continue
  fi

  tag=$($COMPOSE config --images "$svc")
  want=$(docker image inspect -f '{{.Id}}' "$tag")
  have=$(docker inspect -f '{{.Image}}' "$cid")

  if [ "$want" = "$have" ]; then
    echo "OK  $svc: ${want:0:19} ($tag)"
  else
    echo "::error::$svc 가 옛 이미지로 돌고 있다. 받은 것=${want:0:19} 도는 것=${have:0:19} ($tag)"
    echo "  손으로 고치려면: $COMPOSE up -d --force-recreate $svc"
    rc=1
  fi
done

exit $rc
