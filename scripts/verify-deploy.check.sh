#!/usr/bin/env bash
# verify-deploy.sh 자체 점검. "짜둔 검사가 아무 데서도 안 돌더라" 를 두 번 겪은
# 저장소라, 이 검사가 <걸려야 할 것에 실제로 걸리는지> 한 번은 재본다.
#
#   실행: bash scripts/verify-deploy.check.sh        (도커가 도는 아무 데서나)
#
# 네 가지를 본다.
#   ① 방금 올린 그대로면          -> 통과해야 한다 (정상 배포)
#   ② 태그가 <내용이 다른> 이미지로
#      갈렸는데 컨테이너는 옛것이면 -> <실패해야> 한다 (2026-09-09 사고의 모양)
#   ③ 재생성하면                  -> 다시 통과해야 한다 (고쳐졌음)
#   ④ 태그가 <내용은 같고 digest 만
#      다른> 이미지로 갈리면       -> 통과해야 한다 (2026-09-10 거짓 경보의 모양)
#
# ②가 없으면 "언제 돌려도 통과하는 검사" 인지 알 길이 없다.
# ④가 없으면 반대로 "정상을 실패로 부르는 검사" 로 돌아간 것을 알 길이 없다.
#   ④는 옛 기준(.Id 비교)에서는 반드시 실패한다 - 그게 2026-09-10 에 배포를
#   빨간불로 만든 바로 그 상황이고, 이번 변경이 없애려는 것이다.
#
# 🔴 이미지 두 개를 LABEL 로만 갈라놓으면 안 된다. LABEL 은 레이어를 만들지 않아서
#    RootFS.Layers 가 같아지고, 그러면 ②가 <원리적으로 통과해버린다>. 아래는 파일을
#    실제로 써서 레이어를 다르게 만든다. 반대로 ④는 그 성질을 일부러 이용한다.
#
set -euo pipefail

BASE_IMAGE="${BASE_IMAGE:-caddy:2-alpine}"
here=$(cd "$(dirname "$0")" && pwd)
work=$(mktemp -d)
trap 'docker compose -f "$work/docker-compose.yml" down -t 1 >/dev/null 2>&1 || true; rm -rf "$work"' EXIT

# 서로 <내용이> 다른 이미지 두 개를 만든다. 네트워크 없이 로컬 베이스 위에서.
printf 'FROM %s\nRUN echo v1 > /verifycheck\n' "$BASE_IMAGE" | docker build -q -t verifycheck:v1 - >/dev/null
printf 'FROM %s\nRUN echo v2 > /verifycheck\n' "$BASE_IMAGE" | docker build -q -t verifycheck:v2 - >/dev/null
# ④용: v2 와 <레이어는 같고 digest 만 다른> 이미지. LABEL 은 레이어를 만들지 않는다.
printf 'FROM verifycheck:v2\nLABEL rebuild=2\n' | docker build -q -t verifycheck:v2meta - >/dev/null

cat > "$work/docker-compose.yml" <<'YAML'
services:
  api:
    image: verifycheck:current
    entrypoint: ["sleep", "600"]
  # depends_on 이 걸린 서비스. 위 주석의 회귀 검사다.
  dep:
    image: verifycheck:current
    entrypoint: ["sleep", "600"]
    depends_on:
      - api
YAML

export COMPOSE="docker compose -f $work/docker-compose.yml"

run() { COMPOSE="$COMPOSE" bash "$here/verify-deploy.sh" api dep; }

docker tag verifycheck:v1 verifycheck:current
$COMPOSE up -d --force-recreate >/dev/null 2>&1

echo "① 방금 올린 그대로"
run || { echo "FAIL: 정상 배포인데 실패했다"; exit 1; }

echo "② 태그가 내용이 다른 이미지를 가리키는데 컨테이너는 옛것 (up -d 를 빠뜨린 상태)"
docker tag verifycheck:v2 verifycheck:current
if run; then echo "FAIL: 옛 컨테이너를 못 잡았다 - 이 검사는 아무것도 못 막는다"; exit 1; fi

echo "③ 재생성 뒤"
$COMPOSE up -d --force-recreate >/dev/null 2>&1
run || { echo "FAIL: 재생성했는데도 실패한다"; exit 1; }

echo "④ 태그가 내용은 같고 digest 만 다른 이미지를 가리킬 때 (provenance 재빌드의 모양)"
docker tag verifycheck:v2meta verifycheck:current
run || { echo "FAIL: 내용이 같은데 실패했다 - 정상 배포를 실패로 부르는 상태로 되돌아갔다"; exit 1; }

echo
echo "자체 점검 통과: ①통과 ②실패 ③통과 ④통과 (api + depends_on 이 걸린 dep 둘 다)"
