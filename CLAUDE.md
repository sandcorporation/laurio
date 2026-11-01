# Codemit

## 개발 환경

Python + uv, Django + django-ninja, PostgreSQL. 백엔드는 `backend/`, 컨테이너 구성은 `docker/`.

```bash
docker compose -f docker/compose.dev.yaml up          # 전체 스택
docker compose -f docker/compose.dev.yaml up -d db redis   # 테스트용 인프라
scripts/test.sh backend tests/test_x.py              # 테스트(로컬은 400개까지, 전체는 PR CI)
```

**공개 포트가 표준이 아니다.** compose 기본값이 5432·8000·6379·3000을 통째로 비켜 잡아
뒀다 — 표준 포트를 쓰는 다른 프로젝트와 한 머신에 얹기 위해서다. 지금 개발 머신에는
그런 프로젝트가 없지만 기본값은 그대로 둔다(옮기면 아래 표의 환경변수와 문서·스크립트가
같이 흔들린다).

| | 호스트 | 컨테이너 | 환경변수 |
| --- | --- | --- | --- |
| PostgreSQL | `55432` | 5432 | `CODEMIT_DB_PORT` |
| backend | `58000` | 8000 | `CODEMIT_API_PORT` |
| Redis | `16379` | 6379 | `CODEMIT_REDIS_PORT` |
| 공개 앱(`frontend/`) | `53000` | 3000 | `CODEMIT_WEB_PORT` |
| 운영자 앱(`operator/`, #63) | `53001` | 3000 | `CODEMIT_OPERATOR_WEB_PORT` |
| 강의실 앱(`classroom/`, #276) | `53002` | 3000 | `CODEMIT_CLASSROOM_WEB_PORT` |
| 이벤트 서비스(`events`, #379, ADR-0046) | `58001` | 8001 | `CODEMIT_EVENTS_PORT` |
| 검색 엔진(`search`, dev `search` 프로필, #450) | `19200` | 9200 | `CODEMIT_SEARCH_PORT` |
| 연결 풀러(`pgbouncer`, dev `pgbouncer` 프로필, #453/#457) | `16432` | 6432 | `CODEMIT_PGBOUNCER_PORT` |

## 더 읽을 곳 — `docs/ops/`

이 파일은 첫머리만 둔다. 나머지는 아래 파일이고, **같은 「지금」을 말한다**(이 파일의 부록이다).
작업이 닿는 곳의 파일을 먼저 읽는다.

- [티켓을 닫는 기준](docs/ops/ticket-done.md) — 로컬 게이트 셋, 브랜치 → PR → Jenkins 자동 병합, 「지금」 문서를 같은 커밋에서 고친다. **모든 작업 전에.**
- [물어볼 때는 AskUserQuestion 으로](docs/ops/asking-questions.md) — 권장안을 첫째에, 선택지마다 대가를.
- [어느 문서가 「지금」을 말하는가](docs/ops/which-docs-are-current.md) — ADR·이슈·스펙은 그 시점의 판단이다.
- [개발 환경](docs/ops/dev-environment.md) — 이벤트 서비스·워크트리별 스택·dev 프로필(celery·search·pgbouncer)·마이그레이션.
- [테스트](docs/ops/testing.md) — 호스트에서 돈다, `scripts/test.sh`, 앱 경계·금칙어 구조 테스트, 시드.
- [프론트엔드](docs/ops/frontend.md) — 워크스페이스·e2e 시임·워크트리 dev 서버·남길 e2e·토큰·Docker 함정.
- [Next 프로덕션 빌드](docs/ops/next-build.md) — Turbopack, 지우면 안 되는 의존성 둘.
- [CI](docs/ops/ci.md) — 전부 Jenkins(PR·열차·`main` push 의 이미지→가드→배포), GitHub Actions 는 쓰지 않는다.
- [배포](docs/ops/deploy.md) — PR → main(= prod 배포) 체인, deploy.sh, 겹쳐 바꾸기, 풀러, 제품 스위치.
- [운영](docs/ops/operations.md) — admin 없음, 백업, Prometheus·Loki·GlitchTip, GlitchTip 자동 진단.
- [커밋 훅](docs/ops/commit-hooks.md) — `.githooks/pre-commit` 이 하는 셋.

## Agent skills

### Issue tracker

GitHub Issues on `sandcorporation/laurio`, via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical roles, unchanged: `needs-triage`, `needs-info`,
`ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context — `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

**ADR 은 역사다** — 위 「어느 문서가 「지금」을 말하는가」를 먼저 읽는다. ADR 과 나란히
현재를 말하는 것은 `CONTEXT.md` 와 `docs/features/` 다.

### Feature docs

`docs/features/` 가 **지금 이 서비스가 무엇을 하는가**를 말한다 — 백엔드·공개 앱·운영자 앱
하나씩. 기능을 더하거나 지우는 티켓이면 여기도 같은 커밋에서 고친다(위 「티켓을 닫는
기준」). 무엇이 바뀌면 어디를 고치는지는 `docs/features/README.md` 의 표가 들고 있다.

### Legal docs

`docs/legal/` 은 지도다 — 어느 법이 어디에 닿고, 코드가 어디서 지키며, 무엇이 아직
확인되지 않았는지. `README.md` 가 색인이고 열린 항목을 한 표로 모은다. 결정의 원문은
ADR, 값은 코드에 있다 — 세무·개인정보·약관·IP·결제 구조를 건드리면 먼저 읽고, 새
결정이 「약관 항목」을 만들면 `contracts-and-ip.md` 의 목록에 더한다.

### 이 저장소에만 있는 스킬

`.claude/skills/` 에 둔다 — 이 저장소를 열 때만 뜨고, 저장소와 함께 버전이 남는다
(`.gitignore` 가 `.claude/worktrees/` 만 무시하고 나머지는 커밋하도록 열어 둔 이유가
이것이다).

- **`contest-copy`** — 공모전 설명 문구를 쓰거나 고친다(2026-09-17). 실제 공모전 공고의
  항목 구성·어투, 이 서비스의 렌더러가 실제로 그리는 것(ADR-0047), 그리고 **공개한 뒤에는
  설명을 고치는 API 가 없다**는 사실이 그 안에 있다. 첫 무료 공모전의 설명이 「AI 가 쓴
  어투」라는 지적을 받아 고치면서, 무엇이 갈리는지를 세어 본 결과를 남겼다.

### 작업자

티켓은 전역 에이전트 `issue-worker` 가 처리한다. 이 저장소만의 절차는 `docs/ops/ticket-done.md` 에 있다.
