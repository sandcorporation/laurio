#!/usr/bin/env bash
# 자동 되돌리기 리허설(#1166) — 운영 배포 스크립트를 **한 줄도 고치지 않고** 개발 머신의 실제 docker 로 돌린다.
# 운영·원격에 닿지 않는다. `post-deploy-drill.sh` 가 「확인이 깨진 이미지를 잡는다」만 본다면, 여기는
# `deploy-prod.sh` → `deploy.sh prod rollback-plan` → `post-deploy-rollback.sh` 길 전체를 진짜 컨테이너로 돈다.
#
#   bash scripts/ci/post-deploy-rehearsal.sh       # 커밋된 HEAD 를 A 로, 그 위에 깨진 B 를 만들어 A → B 를 배포한다
#   CODEMIT_REHEARSAL_KEEP=1 bash …               # 끝나도 스택·레지스트리·임시 클론을 남긴다
#   CODEMIT_REHEARSAL_BREAK=hang bash …           # 진입점을 어떻게 깨뜨리나(#1189) — 아래 B
#
# 판 둘(임시 클론 안에서만 만든다, 어디에도 push 하지 않는다):
#   A  지금 HEAD — 처음 배포(표식 없음 → 전부 받고 마이그레이션 전부)
#   B  A + `ops_metrics` 에 열 하나 더하는 마이그레이션 + backend 진입점(config/wsgi.py)이 import 때 죽는다.
#      마이그레이션(`manage.py`)은 wsgi 를 읽지 않으므로 스키마는 B 로 오르고 gunicorn 만 못 뜬다 →
#      교체 뒤 실패 → 되돌리기가 A 이미지를 **B 의 스키마 위에** 다시 띄운다(스키마는 되돌리지 않는다).
#      깨뜨리는 방식(`CODEMIT_REHEARSAL_BREAK`): `crash`(기본) — 보통 예외. gunicorn 마스터가 「Worker failed to
#      boot」로 끝나 컨테이너가 재시작에 들어가고, 겹쳐 바꾸기가 마감을 기다리지 않고 바로 실패로 본다.
#      `hang` — `SystemExit`. 워커만 exit 1 로 끝나 마스터가 끝없이 다시 띄우므로 컨테이너는 running 이고,
#      겹쳐 바꾸기의 벽시계 마감(150초)으로만 잡힌다.
#
# 운영과 다른 것은 환경 값뿐이다(스크립트에 dev 분기 없음):
#   - 이미지: 로컬 레지스트리(127.0.0.1:<포트>, `CODEMIT_IMAGE_REPO`). backend·pgbouncer·search 는 진짜로 굽고(x86,
#     태그 이름만 `-arm64`), 세 앱·agent-grader 는 대역(busybox — 앱은 httpd, 그레이더는 잠만 잔다)이다. 바뀐 것은 backend 뿐이다.
#   - preflight 의 ghcr 로그인 검사(config.json 에 `ghcr.io` 문자열) — 빈 `ghcr.io` 항목만 둔 `DOCKER_CONFIG`.
#   - `docker/.env.prod` — 임시 클론에만 두는 가짜 값(어댑터 경로는 예시 파일 그대로, 키·저장소 주소는 닿지 않는 값).
#     프로젝트 이름은 `COMPOSE_PROJECT_NAME=codemit-rehearsal-<오프셋>`, 앱 포트는 532<오프셋>0~2.
#   - 경보 주소는 이 스크립트가 띄우는 가짜 웹훅(127.0.0.1)이다 — 받은 본문을 파일로 남긴다.
#   - PATH 앞의 `docker` 감싸개가 `image prune`·`builder prune` 만 건너뛴다 — deploy.sh 의 prune 은 호스트 전역이라
#     같은 머신의 다른 작업자 캐시를 지운다. 그 밖의 명령은 진짜 docker 로 그대로 넘긴다.
#
# 결과(단계별 시각·끝 코드·로그)는 임시 디렉터리의 `deploy-A.log`·`deploy-B.log`·`alerts.log`·`timeline.txt` 에 남는다.
set -euo pipefail
src=$(cd "$(dirname "$0")/../.." && pwd)

offset="${CODEMIT_REHEARSAL_OFFSET:-2}"
break_mode="${CODEMIT_REHEARSAL_BREAK:-crash}"
case "$break_mode" in crash|hang) ;; *) echo "CODEMIT_REHEARSAL_BREAK 는 crash|hang (받은 값: $break_mode)"; exit 2 ;; esac
reg_port=$((15000 + offset))
hook_port=$((15100 + offset))
project="codemit-rehearsal-$offset"
work="${CODEMIT_REHEARSAL_DIR:-$(mktemp -d "${TMPDIR:-/tmp}/postdeploy-rehearsal.XXXXXX")}"
mkdir -p "$work"
repo_dir="$work/repo"
registry="127.0.0.1:$reg_port/codemit"
reg_name="$project-registry"
timeline="$work/timeline.txt"
: >"$timeline"

stamp() { printf '%s  %s\n' "$(date -u +%H:%M:%SZ)" "$*" | tee -a "$timeline"; }

hook_pid=""
down() {
  local code=$?
  [ -n "$hook_pid" ] && kill "$hook_pid" 2>/dev/null || true
  if [ "${CODEMIT_REHEARSAL_KEEP:-0}" = 1 ]; then
    echo "남긴다: $work (프로젝트 $project, 레지스트리 $reg_name)"
    return "$code"
  fi
  if [ -f "$repo_dir/docker/.env.prod" ]; then
    (cd "$repo_dir" && docker compose -f docker/compose.prod.yaml --env-file docker/.env.prod down -v --remove-orphans \
      >/dev/null 2>&1) || true
  fi
  docker rm -f "$reg_name" >/dev/null 2>&1 || true
  docker images --format '{{.Repository}}:{{.Tag}}' | grep "^$registry/" | xargs -r docker rmi >/dev/null 2>&1 || true
  echo "결과: $work"
  return "$code"
}
trap down EXIT

# ---------------------------------------------------------------- 판 A·B
stamp "임시 클론 — $work/repo"
git clone -q "$src" "$repo_dir"
cd "$repo_dir"
git config user.name rehearsal
git config user.email rehearsal@example.invalid
A=$(git rev-parse HEAD)
leaf=$(cd backend/ops_metrics/migrations && ls 0*.py | sort | tail -n 1)
cat >"backend/ops_metrics/migrations/9999_rehearsal_column.py" <<PY
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("ops_metrics", "${leaf%.py}")]
    operations = [
        migrations.AddField(
            model_name="alertstate", name="rehearsal_note", field=models.TextField(blank=True, null=True),
        ),
    ]
PY
case "$break_mode" in
  crash) printf '\nraise RuntimeError("rehearsal: 일부러 깨진 진입점")\n' >>backend/config/wsgi.py ;;
  hang) printf '\nraise SystemExit("rehearsal: 일부러 깨진 진입점")\n' >>backend/config/wsgi.py ;;
esac
git add -A
git commit -qm "rehearsal: 깨진 진입점 + 열 추가 마이그레이션"
B=$(git rev-parse HEAD)
git checkout -q --detach "$A"
stamp "A=${A:0:12} B=${B:0:12} (마이그레이션 ops_metrics.9999 ← ${leaf%.py}, 진입점 $break_mode)"

# ---------------------------------------------------------------- 레지스트리·이미지
docker rm -f "$reg_name" >/dev/null 2>&1 || true
docker run -d --name "$reg_name" -p "127.0.0.1:$reg_port:5000" registry:2 >/dev/null
stamp "로컬 레지스트리 $registry"

push_both() { # <서비스> <로컬 이미지>
  local tag
  for tag in "$A" "$B"; do
    docker tag "$2" "$registry/codemit-$1:$tag-arm64"
    docker push -q "$registry/codemit-$1:$tag-arm64" >/dev/null
  done
}
stamp "굽기: backend(A·B), pgbouncer, search"
docker build -q -f docker/backend.Dockerfile -t "$registry/codemit-backend:$A-arm64" . >/dev/null
docker push -q "$registry/codemit-backend:$A-arm64" >/dev/null
git checkout -q --detach "$B"
docker build -q -f docker/backend.Dockerfile -t "$registry/codemit-backend:$B-arm64" . >/dev/null
docker push -q "$registry/codemit-backend:$B-arm64" >/dev/null
git checkout -q --detach "$A"
docker build -q -f docker/pgbouncer.Dockerfile -t "$project-pgbouncer" . >/dev/null
docker build -q -f docker/search.Dockerfile -t "$project-search" . >/dev/null
push_both pgbouncer "$project-pgbouncer"
push_both search "$project-search"
mkdir -p "$work/standin"
printf 'FROM busybox:1.36\nRUN mkdir /www && echo ok >/www/index.html\nENTRYPOINT ["sh", "-c", "exec httpd -f -p 3000 -h /www", "--"]\n' \
  >"$work/standin/Dockerfile.web"
printf 'FROM busybox:1.36\nENTRYPOINT ["sh", "-c", "exec sleep 2147483647", "--"]\n' >"$work/standin/Dockerfile.idle"
docker build -q -f "$work/standin/Dockerfile.web" -t "$project-web" "$work/standin" >/dev/null
docker build -q -f "$work/standin/Dockerfile.idle" -t "$project-idle" "$work/standin" >/dev/null
for app in frontend operator classroom; do push_both "$app" "$project-web"; done
push_both agent-grader "$project-idle"
stamp "레지스트리에 일곱 이미지 × 두 판"

# ---------------------------------------------------------------- 가짜 경보·환경
cat >"$work/hook.py" <<'PY'
import http.server, sys
out = sys.argv[2]
class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        with open(out, "ab") as f:
            f.write(body + b"\n")
        self.send_response(204); self.end_headers()
    def log_message(self, *a): pass
http.server.HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
PY
: >"$work/alerts.log"
python3 -I "$work/hook.py" "$hook_port" "$work/alerts.log" &
hook_pid=$!

rand() { head -c 96 /dev/urandom | base64 | tr -d "/+=\n" | cut -c1-64; }
fernet=$(head -c 32 /dev/urandom | base64 | tr '+/' '-_')
web=$((53000 + offset * 100 + 10))
# 운영 설정은 fake 어댑터를 거부한다(CODEMIT_DEPLOYMENT_TARGET=production) — 예시 파일의 실제 어댑터 경로를 쓴다.
# 키는 닿지 않는 값이고, 어댑터는 부를 때만 바깥에 닿는다(리허설은 부르지 않는다).
adapter() { sed -n "s/^$1=//p" docker/prod.env.example; }
cat >docker/.env.prod <<ENV
COMPOSE_PROJECT_NAME=$project
CODEMIT_IMAGE_REPO=$registry
CODEMIT_WEB_PORT=$web
CODEMIT_OPERATOR_WEB_PORT=$((web + 1))
CODEMIT_CLASSROOM_WEB_PORT=$((web + 2))
DJANGO_SECRET_KEY=$(rand)
DJANGO_ALLOWED_HOSTS=localhost
POSTGRES_DB=codemit
POSTGRES_USER=codemit
POSTGRES_PASSWORD=$(rand)
STORAGE_BUCKET=rehearsal
STORAGE_ENDPOINT_URL=http://127.0.0.1:9
STORAGE_ACCESS_KEY=rehearsal
STORAGE_SECRET_KEY=rehearsal
STORAGE_IMAGES_BUCKET=rehearsal-images
STORAGE_IMAGES_BASE_URL=http://127.0.0.1:9/images
JWT_SIGNING_KEY=$(rand)
KAKAO_REST_API_KEY=rehearsal
KAKAO_SECRET_KEY=rehearsal
KAKAO_REDIRECT_URI=http://localhost:$web/auth/kakao
VERIFICATION_ADAPTER_MODE=$(adapter VERIFICATION_ADAPTER_MODE)
VERIFICATION_ENCRYPTION_KEY=$fernet
PORT_ONE_V2_STORE_ID=rehearsal
PORT_ONE_V2_SECRET_KEY=rehearsal
KG_INICIS_CHANNEL_KEY=rehearsal
PAYMENT_ADAPTER_MODE=$(adapter PAYMENT_ADAPTER_MODE)
PAYOUT_ADAPTER_MODE=$(adapter PAYOUT_ADAPTER_MODE)
SELLER_ADAPTER_MODE=$(adapter SELLER_ADAPTER_MODE)
PAYMENT_WEBHOOK_SECRET=$(rand)
PAYOUT_WEBHOOK_SECRET=$(rand)
TOSS_LIVE_CLIENT_KEY=rehearsal
SUPPORT_EMAIL=rehearsal@example.invalid
INTERNAL_API_TOKEN=$(rand)
CODEMIT_OPERATOR_ORIGIN=http://localhost:$((web + 1))
CODEMIT_WEB_ORIGIN=http://localhost:$web
CODEMIT_CLASSROOM_ORIGIN=http://localhost:$((web + 2))
CODEMIT_SESSION_COOKIE_DOMAIN=localhost
LLM_ADAPTER_MODE=$(adapter LLM_ADAPTER_MODE)
CLASSROOM_SCORING_ADAPTER_MODE=$(adapter CLASSROOM_SCORING_ADAPTER_MODE)
LLM_REQUIREMENT_CHAT_ADAPTER_MODE=$(adapter LLM_REQUIREMENT_CHAT_ADAPTER_MODE)
GITHUB_ADAPTER_MODE=$(adapter GITHUB_ADAPTER_MODE)
NOTIFICATION_ALIMTALK_ADAPTER=$(adapter NOTIFICATION_ALIMTALK_ADAPTER)
NOTIFICATION_SMS_ADAPTER=$(adapter NOTIFICATION_SMS_ADAPTER)
NOTIFICATION_LMS_ADAPTER=$(adapter NOTIFICATION_LMS_ADAPTER)
EVENT_BUS_ADAPTER_MODE=core.events_redis.RedisEventBus
SEARCH_ADAPTER_MODE=contests.search_opensearch.OpenSearchContestSearch
OPENSEARCH_URL=http://search:9200
TOSS_API_SECRET_KEY=rehearsal
TOSS_LIVE_SECRET_KEY=rehearsal
TOSS_API_SECURE_KEY=$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')
GITHUB_API_TOKEN=rehearsal
GITHUB_CLIENT_ID=rehearsal
GITHUB_CLIENT_SECRET=rehearsal
GOOGLE_CLIENT_ID=rehearsal
GOOGLE_CLIENT_SECRET=rehearsal
ALIGO_API_KEY=rehearsal
ALIGO_USER_ID=rehearsal
ALIGO_SENDER_PHONE_NUMBER=01000000000
OPEN_AI_API_KEY=rehearsal
OPS_ALERT_DISCORD_WEBHOOK_URL=http://127.0.0.1:$hook_port/webhook
CODEMIT_POSTDEPLOY=rollback
CODEMIT_POSTDEPLOY_URLS=http://127.0.0.1:$web/
ENV

mkdir -p "$work/docker-config" "$work/bin"
echo '{"auths": {"ghcr.io": {}}}' >"$work/docker-config/config.json"
real_docker=$(command -v docker)
cat >"$work/bin/docker" <<SH
#!/bin/sh
case "\$1 \$2" in
  "image prune"|"builder prune") echo "(리허설: docker \$1 \$2 건너뜀 — 호스트 전역)"; exit 0 ;;
esac
exec "$real_docker" "\$@"
SH
chmod +x "$work/bin/docker"

deploy() { # <sha> <로그>
  PATH="$work/bin:$PATH" DOCKER_CONFIG="$work/docker-config" SANDCORP_IMAGE_SHA="$1" \
    bash scripts/ci/deploy-prod.sh 2>&1 | while IFS= read -r line; do
      printf '%s %s\n' "$(date -u +%H:%M:%S)" "$line"
    done >"$2"
  return "${PIPESTATUS[0]}"
}

# ---------------------------------------------------------------- A → B
stamp "배포 A 시작(처음 — 표식 없음)"
set +e
deploy "$A" "$work/deploy-A.log"; a_code=$?
set -e
stamp "배포 A 끝 — 종료 $a_code, 표식 $(cut -c1-12 .jenkins-prod-deployed 2>/dev/null || echo 없음)"
[ "$a_code" = 0 ] || { tail -n 40 "$work/deploy-A.log"; exit 1; }

stamp "배포 B 시작(깨진 진입점 + 마이그레이션)"
set +e
deploy "$B" "$work/deploy-B.log"; b_code=$?
set -e
stamp "배포 B 끝 — 종료 $b_code, HEAD $(git rev-parse --short=12 HEAD), 표식 $(cut -c1-12 .jenkins-prod-deployed)"

C=(docker compose -f docker/compose.prod.yaml --env-file docker/.env.prod)
stamp "떠 있는 backend 이미지: $("${C[@]}" ps --format '{{.Image}}' backend | sed 's/.*://')"
col=$("${C[@]}" exec -T db psql -U codemit -d codemit -tAc \
  "select count(*) from information_schema.columns where table_name='ops_metrics_alertstate' and column_name='rehearsal_note'")
stamp "B 의 열(rehearsal_note)이 남아 있나: $col"
stamp "되돌린 뒤 확인을 다시 한 번(스키마 B 위의 A):"
set +e
bash scripts/ci/post-deploy-check.sh 2>&1 | tee -a "$timeline"; recheck=${PIPESTATUS[0]}
set -e
stamp "다시 본 확인 — 종료 $recheck"
sleep 1
stamp "경보 채널이 받은 줄: $(wc -l <"$work/alerts.log")"
cat "$work/alerts.log" | tee -a "$timeline"

ok=1
[ "$b_code" = 2 ] || ok=0
[ "$(git rev-parse HEAD)" = "$A" ] || ok=0
[ "$(cat .jenkins-prod-deployed)" = "$A" ] || ok=0
[ "$col" = 1 ] || ok=0
[ "$recheck" = 0 ] || ok=0
grep -q "${B:0:12} → ${A:0:12}" "$work/alerts.log" || ok=0
if [ "$ok" = 1 ]; then
  stamp "리허설 통과: B 실패 → A 로 되돌림(스키마 B 그대로) → 확인 통과 → 경보 한 줄"
else
  stamp "!! 리허설 실패 — $work 의 로그를 본다"
  exit 1
fi
