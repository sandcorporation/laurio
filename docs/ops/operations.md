# 운영 — admin 없음·백업·감시·로그·오류 수집·GlitchTip 자동 진단

`CLAUDE.md` 의 부록이다 — 거기서 앵커로 가리키고, 같은 「지금」을 말한다.

**Django admin 은 없다**(#46, ADR-0019). `/admin/` 은 마운트되지 않고 각 앱의
`admin.py` 도 없다.

사람이 판단하는 행위는 `/api/operator/*` 로만 한다. 그 API 에는 이제 화면이 있다
(`operator/`, #63) — 이의 심판·지급·정책·산출물 종류·카테고리(#231)·무료 공모전
개최 권한(#414, ADR-0048)·운영자 계정이 각각 한 화면씩이다. 화면이 없는 조작만
운영자가 HTTP 로 직접 친다.

데이터는 이렇게 훑는다:

```bash
cd backend && uv run python manage.py shell      # ORM 으로 조회
docker compose -f docker/compose.dev.yaml exec db psql -U codemit -d codemit
```

**DB 는 매일 새벽 2시(서울) 오브젝트 스토리지로 백업된다.** beat 의 `backup:database` 가
워커에서 `pg_dump --format=custom` 을 돌려 비공개 버킷 `db-backups/YYYY/MM/DD/` 에 올리고,
14일(`DB_BACKUP_RETENTION_DAYS`)이 지난 것은 지운다(`core/backups.py`). 스캔 등록부 밖에서
**손으로 쓰는 beat 항목은 `config/celery.py` 의 `SCHEDULED_JOBS` 한 자리뿐이다.** DB 가
`postgres:17` 이라 pg_dump 도 17 이어야 해서 backend 이미지가 PGDG 에서 `postgresql-client-17` 을
설치한다 — 서버 메이저를 올리면 이 줄도 같이 올린다. **Celery 가 없는 dev 기본 스택에서는 돌지
않는다.** 복원은 이렇게 한다:

```bash
pg_restore --clean --if-exists --no-owner -h <host> -U codemit -d codemit codemit-YYYYMMDD-HHMMSS.dump
```

첫 Operator 는 관리 명령으로 만든다 — `createsuperuser` 는 쓰지 않는다(ADR-0018·0019):

```bash
cd backend && uv run python manage.py create_operator <아이디> --superuser
```

**살아 있는지는 oracle 의 Prometheus 가 본다**(2026-09-21). 그 전에는 **prod 가 죽어도
아무도 몰랐다** — GlitchTip 은 오류가 **도착해야** 아는 장치라 프로세스가 죽거나 디스크가
차서 응답을 못 하면 조용하다. 감시 스택은 **이 저장소 밖**이다: oracle 의
`/server/prometheus`(별도 compose — Prometheus 30일·Grafana·node-exporter·cadvisor, sub2 같은
다른 호스트도 같이 보는 공용 스택)에 사람이 손으로 둔다. Jenkins·GlitchTip 과 같은 취급이다.

- **무엇을 보나**: blackbox 프로브 6개(prod·staging × 공개 앱 `/contests`·강의실 `/login`·
  운영자 앱) — `/contests` 는 서버 렌더링이 백엔드를 불러야 200 이라 **백엔드·DB 생존까지**
  본다. 호스트 지표는 세 호스트(oracle·sub·sub2)의 node-exporter, 컨테이너 재시작은 oracle
  의 cadvisor(**prod 만** — sub 는 CI 러너와 배포가 컨테이너를 늘 만들고 지워 재시작이
  정상이다).
- **언제 울리나**(`prometheus/alerts.yml`, 7개): 응답 없음 2분 · sub 호스트 다운 2분 ·
  루트 디스크 85%(경고)/95%(위험) · 가용 메모리 10% 미만 5분 · 스왑 90% 이상 · prod 컨테이너
  15분에 3회 재시작. prod 는 `critical`, staging 은 `warning` 이다.
- **어디로**: Alertmanager 가 **빌드 알림과 같은 Discord 채널**로 보낸다(채널을 늘리면 안
  보는 채널이 생긴다). 웹훅은 `alertmanager/discord_webhook`(chmod 600)에만 있고 설정
  파일에는 없다 — 바꾸려면 그 파일 한 줄을 고친다(재시작 불필요, 보낼 때마다 읽는다).
- **감시자가 prod 위에 있다는 사각지대**는 GlitchTip(sub) 의 uptime 모니터가 교차로 본다 —
  oracle 이 통째로 죽으면 Prometheus 도 같이 죽기 때문이다. 반대로 sub 가 죽으면 위
  `HostDown` 이 잡는다. 서로가 서로를 본다.
- **한 화면에서 본다** — Grafana 대시보드 **「Codemit prod」**(`/d/codemit-prod`, 저장소 밖
  `/server/prometheus/grafana/dashboards/codemit-prod.json` 을 프로비저닝이 30초마다 다시 읽는다).
  줄 다섯이다: 서비스 생존(프로브·지금 울리는 경보) · prod 백엔드 요청(초당·상태코드·지연
  p50/95/99·5xx 비율·경로별 상위) · 호스트 자원 · prod 컨테이너(메모리·재시작) · prod 로그(서비스별
  줄 수·오류·**요청 id 로 찾기** — GlitchTip 오류의 `request_id` 태그 값을 맨 위 입력칸에 넣는다).
  호스트 일반 지표는 원래 있던 node-exporter·cadvisor 대시보드가 맡으므로 여기에는 codemit 에만
  있는 것을 둔다. **오류 패널은 우리 서비스만 본다** — 처음에 「exception」으로 넓게 걸었더니
  OpenSearch 의 JVM 기동 인자(`-XX:+ShowCodeDetailsInExceptionMessages`)가 걸려, Django JSON 의
  ERROR 이상·파이썬 `Traceback`·Celery `: ERROR/` 로 좁혔다.
- **닿는지 확인하는 법**: Alertmanager 에 시험 경보를 넣는다(`POST /api/v2/alerts`, 3분 뒤
  해소 메시지가 한 번 더 온다). 2026-09-21 에 그렇게 확인했다 — 발송 1·실패 0.

**컨테이너 로그는 무제한으로 쌓이지 않는다**(2026-09-21). 도커 기본 json-file 은 크기
제한이 없어 sub 에는 이 저장소 밖의 컨테이너 로그가 319M·106M 쌓여 있었다. 두 배포
compose 의 서비스 11개 전부에 `x-logging`(20MB × 5개)을 걸었다 — **다음 배포의 컨테이너
교체부터** 적용된다. 두 호스트의 `/etc/docker/daemon.json` 에도 같은 기본값을 써 두었지만
**데몬이 다시 떠야 읽힌다** — 두 호스트 모두 `live-restore` 가 꺼져 있어 데몬 재시작이 곧
전 컨테이너 재시작이라 일부러 하지 않았다(다음 재부팅·도커 업그레이드 때 적용된다).
**prod 로그는 배포해도 남는다 — 30일**(2026-09-21). 컨테이너를 바꿔 끼우면 그 로그
파일도 지워지므로, 예전에는 배포 한 번이 사후 진단을 끊었다. 지금은 oracle 의 같은 감시
스택에 **Loki**(30일, 메모리 상한 1GB)와 수집기 **Alloy**(도커 소켓으로 `codemit-prod-*`
컨테이너만 따라간다)가 있어, 로그가 나오는 대로 Loki 로 간다. Grafana 의 Loki 데이터소스에서
`{service="backend"}`·`{container="codemit-prod-events-1"}` 처럼 찾는다(라벨은 `container`·
`service`·`env`). **staging 은 모으지 않는다** — sub 는 CI 러너와 배포가 컨테이너를 늘 만들고
지워 거기서는 `docker logs` 로 본다(그래서 staging 은 여전히 배포하면 이전 로그가 사라진다).

**배포 환경에서 Django 가 찍는 로그는 한 줄 JSON 이고, 요청마다 id 가 붙는다**(2026-09-21).
gunicorn 자신의 줄(워커 기동 등)과 Celery 자신의 줄은 각자 포맷 그대로다 — 그 둘은 Django 의
LOGGING 을 지나지 않는다.
`config/settings.py` 의 LOGGING 이 배포 여부(`IS_DEPLOYED_ENVIRONMENT`)로 포매터를 고른다 —
staging·prod 는 `core.json_logging.JsonFormatter`(`time`·`level`·`logger`·`message`·
`request_id`, 예외는 같은 줄의 `exc`), dev 는 지금처럼 사람이 읽는 한 줄 포맷이다. Loki 에서는
`{service="backend"} | json | request_id="…"` 로 한 요청의 줄만 뽑는다.

- **요청 id 는 세 곳에 같은 값이다**(`core/request_id.py`): 그 요청 동안의 **모든 로그 레코드**
  (필터가 아니라 레코드 팩토리가 붙여 어느 핸들러로 가든 빠지지 않는다), **GlitchTip 태그**
  `request_id`, **응답 헤더** `X-Request-ID`. 그래서 GlitchTip 오류 하나에서 태그 값을 복사해
  Loki 로 그 요청의 앞뒤 로그를 찾는다. 앞단이 모양이 맞는 `X-Request-ID`(영숫자·`._-`, 64자
  이하)를 주면 그대로 잇고, 아니면 새로 만든다 — 모양만 막아 로그 주입을 끊는다.
- **id 는 요청이 완전히 끝날 때(`request_finished`) 지운다** — 미들웨어가 돌아올 때 지우면,
  Django 가 4xx·5xx 경고(`django.request` 의 「Not Found」 등)를 **체인이 끝난 뒤에** 찍기
  때문에 사후 진단에서 제일 먼저 찾는 그 줄이 id 없이 나간다(실제로 테스트가 그렇게 잡았다).

**prod 백엔드의 요청량·지연·상태코드는 `/metrics` 로 나간다**(2026-09-21, `core/metrics.py`).
**대시보드용**이다 — 경보는 걸지 않는다(5xx 는 GlitchTip 이 이미 울린다).

- **내부 이름으로 온 요청에만 답한다** — Host 가 `INTERNAL_SERVICE_HOSTS`(`backend`·`events`)가
  아니면 404(존재를 알려주지 않는다). 공개 프록시는 공개 도메인을 Host 로 넘기고, 세 앱의 BFF
  허용목록에 이 경로가 없고, 백엔드 포트는 호스트 127.0.0.1 에만 열려 있다 — 세 겹 중 이
  파일이 마지막 하나를 지킨다. 감시 스택은 compose 네트워크 안에서 `backend:8000` 으로 긁는다 —
  그래서 oracle 의 prometheus 컨테이너가 **prod 네트워크(`codemit-prod_default`)에도 붙어 있다**.
  그 동안에는 prod 에서 `docker compose down` 을 하면 그 네트워크를 지우지 못한다는 경고가 난다
  (배포는 `up -d` 만 써서 영향이 없다). 배포 직후 요청이 가장 많은 경로는 헤더 알림 벨의
  `api/notifications/unread-count` 폴링이었다(2026-09-21 실측) — 백엔드 부하를 볼 때 첫 자리다.
- **gunicorn 워커 넷을 합산한다** — prod compose 가 backend 에만 `PROMETHEUS_MULTIPROC_DIR`
  를 주고 뜰 때마다 비우며, 죽은 워커 정리는 `config/gunicorn.conf.py` 의 `child_exit` 가
  한다(워커가 각자 카운터를 들면 긁을 때마다 무작위 워커 하나의 값이 와서 튄다). 워커 넷에
  40번 보낸 뒤 긁으면 세 번 모두 같은 합계가 나오는 것을 실측으로 확인했다. staging 은 긁지
  않으므로 그 설정이 없다.
- **라벨은 URL 패턴이다, 실제 경로가 아니다** — `resolver_match.route`(`api/contests/
  <int:contest_id>` 꼴)로 세고 맞지 않은 요청은 `unmatched` 하나로 모은다. 실제 경로를 쓰면
  공모전 수만큼 시계열이 생긴다.

**로그 소음 둘을 걷었다**(2026-09-21, Loki 로 처음 보였다). pgbouncer 가 트랜잭션 모드에서
연결·끊김마다 한 줄씩 **시간당 492줄**(prod 전체의 절반 가까이)을 찍어 `log_connections`·
`log_disconnections` 를 껐다(분당 stats 줄은 남긴다). 그리고 모을 정적 파일이 없어 `STATIC_ROOT`
가 만들어지지 않자 WhiteNoise 가 프로세스마다 `No directory at` 경고를 찍어, settings 가 빈
디렉터리를 만든다.

**오류는 자체 GlitchTip 으로 모인다**(2026-09-16). 예전에는 백엔드 로그가 컨테이너
stdout 에만 남고 세 앱에는 오류를 받을 자리조차 없어(`error.tsx` 도 없었다), 배포된
5xx 가 아무도 모르는 채로 며칠 났다. 지금은 Sentry SDK 로 보내는데 받는 쪽이
sentry.io 가 아니라 **우리가 띄운 GlitchTip**
(`https://glitchtip.honeycombpizza.link`, 저장소 밖에서 사람이 띄웠다)이다 — 수업
제출물·이름·이메일을 다루는 서버라 오류 본문이 바깥 업체로 나가지 않는 편이 낫다.
프로젝트는 **앱마다 하나**(backend·frontend·operator·classroom)고 DSN 도 그만큼 있다.

- **DSN 이 없으면 꺼진 채로 돈다** — dev·CI 는 주지 않는다. 그래서 테스트가 네트워크를
  치지 않고, 잊고 배포해도 부팅은 막히지 않는다(오류 수집이 없어도 서비스는 돌아야
  한다). `SENTRY_DSN_BACKEND`·`SENTRY_DSN_FRONTEND`·`SENTRY_DSN_OPERATOR`·
  `SENTRY_DSN_CLASSROOM` 을 `.env.staging`/`.env.prod` 가 채운다(두 env 예시 파일에
  자리가 있다). 세 앱의 값은 `NEXT_PUBLIC_*` 로 **브라우저 번들에 굳으므로** 바꾸면
  이미지를 다시 굽는다 — `NEXT_PUBLIC_TOSS_CLIENT_KEY` 와 같은 제약이다. **브라우저 쪽
  값은 CI 가 저장소 변수 `STAGING_`/`PROD_SENTRY_DSN_<앱>` 으로 굽고, 서버 쪽 초기화가
  읽을 런타임 ENV 는 `.env` 줄에서 온다** — 둘을 같이 바꾼다(갈리면 브라우저와 서버가
  다른 곳에 보고한다).
- **백엔드 이미지 하나로 도는 다섯 프로세스 전부가 켜진다** — `settings.py` 가 부르는
  `core.observability.configure_sentry()` 한 줄이라 gunicorn·events(ASGI)·celery
  worker·beat·관리 명령이 모두 같은 설정을 받는다.
- **보내지 않는 것**: 세션 리플레이와 성능 추적을 켜지 않았다(GlitchTip 은 리플레이를
  아예 받지 못하고, 리플레이는 화면을 통째로 녹화해 개인정보가 함께 나간다). 사용자
  식별은 **내부 id 하나**뿐이고(`accounts.middleware`·`core.operator_auth` 가 붙인다)
  이메일·IP·요청 본문·쿠키는 보내지 않는다. **세 앱에서는 그 약속을 `sendDefaultPii:
  false` 가 지키지 못했다**(#460, 2026-09-18) — 서버 쪽 `onRequestError` 경로로 올라온
  이벤트에는 요청이 그대로 붙어 `codemit_access`·`codemit_refresh` JWT 가 **평문으로**
  나갔다(refresh 수명 14일이라 그 값 하나로 로그인이 된다). 지금은
  `lib/observability/sentry-options.ts` 의 `beforeSend`(`scrubSensitiveRequestData`)가
  쿠키·요청 본문을 지우고 **헤더는 이름을 아는 것만 남긴다** — 새 헤더의 기본값이
  「보낸다」이면 다음 누출이 조용히 또 생기기 때문이다. 세 앱의 여섯 진입점이 전부
  `buildSentryOptions` 를 지나므로 그 한 자리가 서버·브라우저 양쪽을 덮고, 두 앱의
  `sentry-options.test.ts` 가 그 동작을 고정한다(운영자 앱은 테스트 파일이 없다). **의도한 4xx 도 보내지 않는다** — 422·404·
  403 은 우리가 일부러 내는 응답이라, 그걸 다 보내면 진짜 5xx 가 소음에 묻힌다
  (`core.observability.drop_expected_error`, `backend/tests/test_observability.py` 가
  그 규칙을 고정한다). **남의 코드가 던진 것도 보내지 않는다**(#471, 2026-09-20) —
  브라우저 확장의 콘텐츠 스크립트가 던진 예외를 전역 핸들러가 잡아 강의실 프로젝트로
  보냈고, 하루 만에 prod 미해결 목록이 그 예외 하나로 통째로 찼다(GlitchTip 오류
  62·63, 합쳐 14건). 그 프레임은 `app:///` 로 시작하지만 `/_next/` 아래가 아니다 —
  `app:///` 는 SDK 가 오리진을 떼어낸 흔적이지 우리 번들이라는 뜻이 아니다
  (`chrome-extension://<id>/…` 도 같은 모양이 된다). 지금은 `beforeSend` 가
  **스택이 전부 `/_next/` 밖인 브라우저 이벤트**를 버린다 — 스택이 아예 없거나
  이름 없는 프레임이 섞인 것은 **남긴다**(교차 오리진의 `Script error.` 를 잃지
  않으려고 좁게 막았다). 서버 이벤트는 이 판정을 받지 않는다: 그 프레임은
  `.next/server`·`node_modules` 라 함께 보면 우리 서버 오류가 통째로 버려진다 —
  그래서 여섯 진입점이 `buildSentryOptions` 에 자기가 어느 쪽인지(`"browser"`·
  `"server"`)를 적는다.
- **어느 커밋에서 났는지가 release 태그다** — `deploy.sh` 가 배포하는 커밋 SHA 를
  `SENTRY_RELEASE` 로 내보내 compose 가 백엔드 환경변수로 넘기고, 세 앱은 CI 가 **그 앱
  이미지에 들어가는 코드를 마지막으로 바꾼 커밋**을 빌드 인자로 굽는다(HEAD 로 구우면 커밋마다
  Next 빌드 캐시가 깨졌다 — 이미지 태그는 여전히 HEAD sha 다).
  소스맵은 올리지 않는다(프론트 스택은 압축된 이름으로 보인다).
- **닿는지 확인하는 법**: 설정이 틀려도 조용히 아무 일도 안 일어나는 것이 오류 수집의
  기본 실패 모양이라, 배포 뒤 한 번 쏴 보고 GlitchTip 에서 눈으로 본다.

```bash
ssh sub 'docker exec codemit-staging-backend-1 python manage.py sentry_smoke'
```

**그 오류를 에이전트가 집어 진단한다**(2026-09-18). Orca automation 「GlitchTip prod 오류
진단」이 매분 `scripts/glitchtip_pick.py` 를 precheck 로 돌려 **prod 의 미해결·미클레임
오류 하나**를 고르고, 집힌 것이 있을 때만 이 머신에 세션을 띄운다(워크트리는 실행마다
새로, `origin/main` 기준). 세션이 따르는 절차는 `.claude/skills/glitchtip-triage/` 다 —
재현 루프를 먼저 만들고, **재현되지 않으면 고치지 않고 멈춘다**.

- **고르는 쪽과 판단하는 쪽을 가른다.** 이슈 제목·스택트레이스는 공개 DSN 으로 누구나
  넣을 수 있는 값이다. 무엇을 집을지와 GlitchTip 쓰기는 스크립트가 끝내고, 세션에는
  읽기 전용 토큰(`GLITCHTIP_TOKEN`)만 준다 — 인젝션된 텍스트가 이슈 상태를 바꾸거나
  코멘트를 남길 길이 없다. 쓰기 토큰은 `GLITCHTIP_TOKEN_FOR_AUTOMATION`(스코프
  `event:write` 하나, 루트 `.env`)이고 `project:read` 를 **일부러 안 줬다**.
- **다만 읽기 토큰은 한 자리를 흘린다.** `list_alerts`(REST 로는
  `/projects/{org}/{project}/alerts/`)가 **Discord 웹훅 URL 을 평문으로 돌려준다** —
  읽기 토큰으로는 열리고 쓰기 토큰으로는 403 이다(둘 다 실측, 2026-09-18). 스코프를 더
  가른 토큰을 만들지 않고, 스킬의 「하지 않는 것」이 그 경로를 명시적으로 금지하는 쪽을
  골랐다(세션이 쓰는 경로는 `issues/{id}` 아래 셋뿐이다). 토큰을 더 쪼개려면 `event:read`
  만 가진 세 번째 토큰을 GlitchTip 화면에서 만들어 `GLITCHTIP_TOKEN` 을 그것으로 바꾼다.
- **읽기 토큰은 `~/.claude/settings.json` 의 `env` 에 있다**(저장소 밖, chmod 600) — 그래야
  automation 이 띄우는 세션에도 붙는다. 셸 프로필에 두면 비대화형 셸에서 안 읽힌다.
  `.mcp.json` 은 그 값을 `${GLITCHTIP_TOKEN}` 으로 **참조만** 한다(GlitchTip 6.2.6 의 내장
  MCP, 도구 17개) — 그래서 그 파일은 커밋돼도 비밀이 없다. MCP 가 안 붙어도 세션은 같은
  일을 curl 로 한다.
- **「손 댔다」는 GlitchTip 코멘트다.** 이슈 목록 응답의 `numComments` 가 그 값이라 목록
  API 한 번으로 갈리고, 사람이 같은 사실을 GlitchTip 화면에서 본다. 새 상태 상자를 만들지
  않았다. **판정은 내용이 아니라 개수다** — 쓰기 토큰으로는 코멘트를 달 수만 있고 읽을
  수 없다(`GET issues/{id}/comments/` 가 `Permission denied`, 실측). 그래서 **코멘트가
  하나라도 있으면 집지 않는다**: 사람이 메모를 달아 둔 오류를 자동화가 가져가지 않는 것이
  오히려 맞다. 대가는 무심코 단 코멘트가 그 오류를 영구히 빼는 것이고, 되돌리려면 사람이
  화면에서 지워야 한다(`event:admin` 이 필요하고 이 토큰에는 일부러 없다 — 실제로 한 번
  그렇게 막혔다).
- **예외 하나 — 고친 코드에서 재발한 것은 다시 집는다**(2026-09-22). 위 규칙은 재발을
  생각하지 않고 정했다: 자동 진단이 고치고 CI 가 닫은 오류가 고친 코드에서 또 나면
  GlitchTip 이 스스로 미해결로 되살리는데, 클레임 코멘트가 남아 **자동화가 영영 다시 보지
  않았다**(오류 64). 지금은 main 에 그 오류의 `GlitchTip:` 수정 커밋이 있고 **최신
  이벤트의 release 가 그 최신 수정을 포함하면** 재발로 보고 다시 집는다 — 포함하지 않으면
  수정이 배포되기 전의 옛 코드에서 난 것이라 재발이 아니다(그걸 재발로 보면 배포 대기
  5~10분 사이에 이미 고친 오류를 또 집는다). 수정 커밋이 없으면(사람의 메모·사람에게
  넘긴 것) 원래 규칙대로 건너뛴다. 같은 재발을 매분 또 집지 않도록 「이 발생 시각에서
  이미 다시 집었다」를 `~/.codemit/glitchtip-regressions.json` 에 적는다 — 새 이벤트가
  오면 시각이 바뀌어 또 집힌다. **재발한 그 이벤트가 production 이어야 한다** — 이슈의
  환경 집합은 「prod 에서 난 적이 있는가」라, 처음 판은 staging 배포 창의 이벤트를 prod
  재발로 집었다(오류 74, 2026-09-22). 세션은 클레임 파일의 `regression_of`(지난 수정 커밋)를
  받아 **처음부터가 아니라 그 수정이 무엇을 놓쳤는지부터** 본다.
- **동시 하나는 잠금 파일이 지킨다**(`~/.codemit/glitchtip-lock`). 세션이 끝낼 때 지우고,
  죽었으면 45분에 저절로 풀린다. `orca automations runs` 의 status 값을 보지 않는 이유는
  그 문자열 목록이 어디에도 문서화돼 있지 않아서다 — 추측하면 가드가 **항상 통과하고도
  조용하다**.
- **환경 판정은 집합이다.** 같은 예외가 staging·prod 에서 함께 나면 GlitchTip 이 이슈
  하나로 묶고 태그에 두 값을 다 담는다(실측: issue 1). 「첫 값이 production 인가」로 보면
  순서에 따라 prod 오류가 조용히 빠진다.
- **우리가 일부러 던지는 예외는 집지 않는다.** `SentrySmokeError`(`manage.py
  sentry_smoke`)가 도착한 것은 **오류 수집이 닿는다는 성공 신호**다 — 그걸 집으면 세션
  하나가 「사고가 아니다」라고 스스로 적힌 예외를 재현하려 애쓴다. 판정은
  `metadata.type`(예외 클래스 이름)으로 한다, 제목 문자열이 아니다 — 그 메시지는
  한국어라 바뀌면 조용히 샌다. 목록은 `DELIBERATE_EXCEPTION_TYPES` 한 자리다.
- **해결 표시는 PR 병합이 한다**(2026-10-02). 세션은 커밋 메시지 마지막 줄에
  `GlitchTip: <id>` 를 적고 **분기를 push 해 PR 을 연다**(`main` 에 직접 넣지 않는다). Jenkins
  `codemit-pr` 가 시험을 돌려 초록이면 PR 을 `main` 에 병합하고, **곧바로 그 PR 범위**
  (`merge-base..HEAD`)의 줄을 읽어 이슈를 resolved 로 돌린다(`Jenkinsfile.pr` 의 병합 단계,
  자격증명 `glitchtip-automation-token`) — 「고친 것 같다」와 「고쳤다」를 가르는 자리다.
  범위가 PR 하나로 정확히 닫히므로 옛 방식의 두 문제가 없다: push 와 표시 사이의 5~10분
  공백(그래서 두던 `glitchtip-ack` 예고 코멘트)과, 연달아 push 할 때 취소된 실행이 범위를
  놓치던 것(오류 75 — 그래서 범위를 「직전에 그 잡이 성공한 실행 이후」로 잡았다,
  `glitchtip_resolve.py` 의 `auto` 모드가 그 흔적이다).
- **배경 세션은 「지금」을 말하는 문서를 고칠 수 없다.** 평소 티켓이라면 「티켓을 닫는
  기준」이 `CLAUDE.md`(`docs/ops/`)·`CONTEXT.md`·`docs/features/` 를 같은 커밋에서 고치라고 하는데,
  아무도 보고 있지 않은 세션에는 그 규칙을 적용하지 않는다 — 그 셋(과 `docs/adr/`)이
  틀렸을 때 대신 참을 말해 줄 것이 저장소에 없다. 그런 변경이 필요하면 세션은 **코드만
  분기에 push 하고 `ready-for-human` 티켓**으로 넘긴다(고칠 문장의 초안은 티켓 본문에
  적는다 — 적는 것은 되고 커밋하는 것은 안 된다). 재현하지 못한 오류도 `needs-info`
  티켓을 연다 — 클레임 때문에 다시 집히지 않으므로 티켓이 그 진단이 사람에게 닿는
  유일한 길이다.
- **그 게이트를 `.githooks/pre-commit` 이 기계로도 막는다.** 브랜치가 `auto-` 로
  시작하거나(Orca automation 이 실행마다 만드는 브랜치가 `auto-<이름>-run-<n>-<시각>`
  이다, 실측) `CODEMIT_UNATTENDED=1` 이면 그 네 경로가 staged 된 커밋을 거절한다.
  `--no-verify` 로 넘어가므로 벽이 아니라 감속방턱이다 — 인젝션에 대한 벽은 읽기 전용
  토큰과 경로 울타리이고, 이 검사가 잡는 것은 **정직한 생각없는 수정**이다.
- **precheck 가 청소도 한다 — 그리고 그 청소가 한 번 도는 세션을 죽였다**(#459).
  automation 은 세션이 뜨는 실행마다 워크트리와 브랜치(`auto-<이름>-run-<n>-<시각>`)를
  만들고 끝나도 치우지 않는다 — 안에 `node_modules`·`.venv` 가 각각 들어서므로 몇 건만
  쌓여도 이 머신의 디스크를 먹는다. 매분 도는 것이 precheck 하나뿐이라 그것이
  `origin/main` 에 머지된 `auto-*` 워크트리를 걷는데, **첫 판은 「머지됨」 판정을
  `merge-base --is-ancestor` 하나로 했다** — 막 만들어져 아직 커밋이 없는 분기는 팁이
  곧 `origin/main` 이라 그 판정을 통과했고, 진단 중인 세션이 첫 커밋 전에 다음 분
  precheck 에 워크트리째 사라졌다. 지금은 문이 셋이다:
  **(1)** 잠금이 살아 있으면 청소를 아예 하지 않는다(청소가 잠금 확인 **뒤로** 갔다),
  **(2)** 팁이 `origin/main` 과 같은 분기는 「아무것도 안 했다」로 보고 건드리지 않되
  `--lock-ttl-minutes`(기본 45분)보다 오래 식은 것만 걷는다(재현 실패로 커밋 없이 끝난
  워크트리가 영원히 남지 않게), **(3)** 머지 안 된 것은 그대로 남긴다 — 게이트에 걸려
  사람에게 넘긴 분기가 정확히 그 모양이다.
  사람 워크트리(`chain-*`·`int-*`)는 접두어가 달라 대상이 아니다. `--no-tidy` 로 끈다.
- **GlitchTip 을 눈으로 읽을 때는 `scripts/glitchtip_get.py` 를 쓴다 — `curl` 로 치지
  않는다.** GlitchTip 의 오류 응답은 `{"detail": "Permission denied"}`·`{"detail":
  "Not Found"}` 라서, 그대로 파싱해 필드를 찾으면 **빈 값이 나오고 그것을 「값이 없다」로
  읽게 된다.** 이 저장소에서 실제로 세 번 그렇게 잘못 읽었다(코멘트가 비어 있다 → 실은
  권한 거부, 쿠키가 사라졌다 → 실은 이슈가 삭제됨). 이 도구는 **2xx 가 아니면 필드를
  보여주지 않고 상태와 본문만 적고 죽는다** — 「값이 없다」와 「물어볼 수 없었다」가 같은
  모양으로 나오지 않는다. 자격증명 자리(`cookies`·`data`·`cookie` 헤더)는 값을 찍지
  않고 **있다는 사실만** 알린다. 읽기 전용 토큰만 쓰고 알림 규칙 경로는 지원하지 않는다.

```bash
scripts/glitchtip_get.py issues            # 미해결 목록 (--all 로 해결된 것까지)
scripts/glitchtip_get.py event 60          # 최신 이벤트 요약 (--raw 로 전문)
scripts/glitchtip_get.py tags 60           # 환경·release
```

- **무엇이 집힐지 눈으로 보려면** 필터를 풀어 dry-run 한다(클레임도 잠금도 남기지 않고,
  청소도 하지 않는다):

```bash
scripts/glitchtip_pick.py --dry-run --any-status --any-environment
```
