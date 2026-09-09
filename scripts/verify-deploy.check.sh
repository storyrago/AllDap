#!/usr/bin/env bash
# verify-deploy.sh 자체 점검. "짜둔 검사가 아무 데서도 안 돌더라" 를 두 번 겪은
# 저장소라, 이 검사가 <걸려야 할 것에 실제로 걸리는지> 한 번은 재본다.
#
#   실행: bash scripts/verify-deploy.check.sh        (도커가 도는 아무 데서나)
#
# 세 가지를 본다.
#   ① 방금 올린 그대로면          -> 통과해야 한다 (정상 배포)
#   ② 태그만 새 이미지로 갈리고
#      컨테이너는 옛것이면        -> <실패해야> 한다 (이번 사고의 모양)
#   ③ 재생성하면                  -> 다시 통과해야 한다 (고쳐졌음)
#
# ②가 없으면 "언제 돌려도 통과하는 검사" 인지 알 길이 없다.
set -euo pipefail

BASE_IMAGE="${BASE_IMAGE:-caddy:2-alpine}"
here=$(cd "$(dirname "$0")" && pwd)
work=$(mktemp -d)
trap 'docker compose -f "$work/docker-compose.yml" down -t 1 >/dev/null 2>&1 || true; rm -rf "$work"' EXIT

# 서로 다른 이미지 두 개를 만든다. 네트워크 없이 로컬 베이스에 라벨만 얹는다.
printf 'FROM %s\nLABEL verifycheck=v1\n' "$BASE_IMAGE" | docker build -q -t verifycheck:v1 - >/dev/null
printf 'FROM %s\nLABEL verifycheck=v2\n' "$BASE_IMAGE" | docker build -q -t verifycheck:v2 - >/dev/null

cat > "$work/docker-compose.yml" <<'YAML'
services:
  api:
    image: verifycheck:current
    entrypoint: ["sleep", "600"]
YAML

export COMPOSE="docker compose -f $work/docker-compose.yml"

run() { COMPOSE="$COMPOSE" bash "$here/verify-deploy.sh" api; }

docker tag verifycheck:v1 verifycheck:current
$COMPOSE up -d --force-recreate >/dev/null 2>&1

echo "① 방금 올린 그대로"
run || { echo "FAIL: 정상 배포인데 실패했다"; exit 1; }

echo "② 태그가 새 이미지를 가리키는데 컨테이너는 옛것 (up -d 를 빠뜨린 상태)"
docker tag verifycheck:v2 verifycheck:current
if run; then echo "FAIL: 옛 컨테이너를 못 잡았다 - 이 검사는 아무것도 못 막는다"; exit 1; fi

echo "③ 재생성 뒤"
$COMPOSE up -d --force-recreate >/dev/null 2>&1
run || { echo "FAIL: 재생성했는데도 실패한다"; exit 1; }

echo
echo "자체 점검 통과: ①통과 ②실패 ③통과"
