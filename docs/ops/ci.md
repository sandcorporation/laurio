# 검사·이미지는 GitHub Actions, 배포는 Jenkins — PR 검사 하나, 병합 하나 = 승격 하나 = 배포 하나

`CLAUDE.md` 의 부록이다 — 거기서 앵커로 가리키고, 같은 「지금」을 말한다.

**검사와 이미지는 GitHub Actions, 배포는 Jenkins 다**(2026-11-09 #938, ADR-0077 — sandcorp-metrics 와 같은 흐름).

```
PR → pr-check.yml(바뀐 앱만, 「결과」 초록) → 병합 대기열 → pr-check.yml(merge_group, 전부 + guard — 배포 가능 판정 한 번) → squash → main
   → release.yml(push: main): image(image.yml, ubuntu-24.04-arm 일곱) → promote(production fast-forward)
                              ‖ cache·cache-node(PR 검사의 캐시를 main 에 채운다 — 승격은 기다리지 않는다)
   → Jenkins `codemit/deploy`(*/production): 굽지도 검사하지도 않고 ghcr `codemit-<서비스>:<sha>` 를 받아 oracle 에 배포
```

- **PR 검사**는 `.github/workflows/pr-check.yml` 하나다(#930·#932, ADR-0076 — Jenkins PR 검사 `codemit/ci-pr` 는 꺼졌다).
  `pull_request` 마다 호스팅 실행기에서 같은 스크립트를 잡으로 나눠 부른다 — `plan`(`changed.sh`, 문서만이면 ADR 검사만·프런트만·백엔드만이면 해당 잡만, 공개 위생
  `scripts/test_public_repo.py`·승격 배선 `scripts/test_release_flow.py`·`promote_test.sh` 는 늘) → `checks`(`sub-checks.sh`)·`guard`(세 앱을
  amd64 로 굽고 `deploy-guard.sh`, `CODEMIT_GUARD_IMAGE`)·`celery`(`celery-broker.sh`)·`agent-grader`(`agent-grader-check.sh` — `ubuntu-24.04-arm`
  에서 에이전트 채점 실행기 이미지를 굽고 운영과 같은 격리 설정(seccomp 프로필 포함)으로 Codex 샌드박스 한 줄과 가짜 벤더에 두 CLI 를 돌린다. 실행기의 AppArmor 사용자 네임스페이스 제한은 끄고 돈다 — 운영 호스트에는 AppArmor 가 없다, #999) →
  `결과`(모두 초록이면 초록 — 필수 검사로 걸 이름). **병합 기준은 「결과」 잡이다** — `gh pr checks <PR>`·`gh run watch` 로 본다.
  **PR 에서는 `guard` 를 건너뛴다**(#1015, 줄 서기 단축). **`e2e` 는 PR 에서만 바뀐 앱의 시험을 조각 나란히로 돌고 「결과」에 필수다. 병합 대기열(`merge_group`)은 e2e 를 돌지 않고, 전부는 매시 main 의 `e2e.yml` 이 돈다**(#1089·#1111).
  `guard` 는 `plan` 잡 출력 `guard`(PR 이벤트면 빔)를 `if` 가 본다. 잡 이름·`결과` 는 그대로다.
  - **`결과` 는 skipped 를 통과로 세지 않는다**: plan 이 시험 없음(문서만)이면 나머지가 skipped, 아니면 checks·celery 는 success, guard 는 PR 이 아닐 때 success(PR 에서만 skipped)여야 통과다. 조건을 잘못 걸어 필수 잡이 통째로 건너뛰어도 초록이던 구멍을 막는다.
  - **PR 검사 잡**: plan · checks(static·pytest 조각·web) · celery · agent-grader · 결과(guard 는 skipped). 어느 잡이 도는지는 `changed.sh` 가 바뀐 경로로 고른다(#1082):

    | 바뀐 경로 | 도는 잡 | 건너뛰는 잡 |
    | --- | --- | --- |
    | 문서만(`*.md`·`docs/`) | plan 의 검사만 | checks·celery·agent-grader |
    | 프런트만(`frontend/`·`operator/`·`classroom/`·`packages/`) | checks static·web | pytest·celery·agent-grader |
    | 백엔드만(`backend/`·`docker/`) | checks static·pytest(바뀐 앱만, 아래)·celery·agent-grader | web (`schema.gen.ts` 최신성은 static 에 남는다) |
    | 둘 다, 또는 그 밖(`.github/`·`scripts/`·루트 설정·`pnpm-lock.yaml`) | 전부 | — |

    `결과` 는 위 표대로 돌아야 할 잡이 success, 건너뛰어야 할 잡이 skipped 일 때만 초록이다.
    경로 표는 `scripts/ci/paths.py` 하나다 — `changed.sh`·`e2e_plan.py`·`pytest_plan.py` 가 모두 이것을 읽는다. `scripts/test_changed_paths.py` 가 고정한다.
  - **병합 대기열 잡**(`merge_group`): 경로와 상관없이 전부(pytest 6조각 — e2e 는 빼고, #1111) 돌고 위에 **guard(frontend·operator·classroom)** 가 더해진다 — 배포 가능 판정은 여기 한 번이다(#1090).
  - **e2e 는 PR 검사의 `e2e` 잡(바뀐 앱, 필수)과 매시 main 의 `e2e.yml`(전부)이다**(#1089·#1111). 시험은 `frontend/e2e/<앱>/`(공개)·`frontend/e2e/operator/<앱>/`·`frontend/e2e/classroom/` 에 두고 **폴더 이름이 앱 표시다** — `backend/app_deps.toml` 의 앱 이름이거나 `frontend`(백엔드 앱이 없는 화면·BFF 시험). `plan` 잡이 `scripts/ci/e2e_plan.py` 로 조각을 낸다: PR 은 바뀐 백엔드 앱(`app_deps.py affected`)의 폴더, 앞단이 바뀌면 그 앱 시험 전부, 시험 폴더만 바뀌면 그 폴더만, 공유 도우미·설정·워크플로·그 밖은 전부. 매시 `e2e.yml` 은 늘 전부(`--all`). 시험 파일을 **기록된 시험 시간**으로 조각에 나눠 담고(#1112 — 조각 수는 시간 합 ÷ 25초, 프로젝트 수~5(#1116 — 층 캐시가 찬 뒤 조각 준비가 ~150초라 8조각은 끝 시각을 거의 줄이지 못하고 실행기 시간만 먹었다), 프로젝트마다 한 조각에서 시작해 조각당 시간이 가장 긴 프로젝트에 하나씩 더 준다) 조각마다 실행기 하나가 스택을 따로 굽는다(`CODEMIT_E2E_PATHS`, `e2e.sh`).
    **e2e 시간 기록(#1112)**: `e2e.sh` 가 패스마다 Playwright JSON 리포트를 `test-results/timings/` 에 남기고, 매시 `e2e.yml` 의 `durations` 잡이 조각들의 것을 직전 기록에 합쳐(`scripts/ci/e2e_durations.py update` — 통과한 파일만 직전 값과 평균, 실패·못 잰 파일은 그대로, 지운 파일은 뺀다) Actions 캐시 `e2e-durations-<실행>` 으로 저장한다. PR 검사·`e2e.yml` 의 계획 잡은 가장 새 것을 복원해 `--durations` 로 넘긴다. **커밋하지 않는다** — 대기열·PR 에 쓰기 권한을 더하지 않고 매시 저절로 새로워진다. 캐시가 없으면(첫 실행, 7일 안 쓴 캐시가 지워졌을 때) 저장소의 씨앗 기록 `scripts/ci/e2e-durations.json` 을 쓴다 — 씨앗은 가끔 `durations` 잡의 산출물 `e2e-durations`(30일)를 받아 그대로 커밋해 새로 한다. 기록에 없는 새 시험은 기록 평균으로 센다. 규칙은 `scripts/test_e2e_plan.py` 가 고정한다. 조각 시간의 대부분은 시험 밖 준비다 — 층 캐시가 찬 뒤(#1116) 체크아웃·캐시 복원·굽기(23~43초)·띄우기·정리를 합쳐 121~187초, 시험은 조각당 12~25초. 포크에 캐시가 없던 동안은 굽기만 120~200초였다. 병합 기준 `결과` 가 `e2e` 를 본다(조각이 있으면 success). 이미지 층 캐시는 release 의 `cache` 잡이 저장하고 PR 검사의 잡은 모두 복원만 한다(#1090). 매시 `e2e.yml` 이 저장하는 캐시는 e2e 시간 기록 하나다.
  - **대기열에서 e2e 를 뺀 까닭(#1111, 대표 결정 2026-11-20)**: 대기열 시간의 대부분이 e2e 조각(4:20~9:29)이었는데, CI 의 e2e 가 11일 동안
    막은 실제 버그는 0, 헛실패는 5였다. 대가: 각자 초록인 두 PR 이 함께 깨뜨린 화면은 대기열이 못 잡고 최대 한 시간 뒤 매시 e2e 가 잡는다.
  - **매시 `e2e.yml`**: 본 저장소의 것(#1015·#1020)을 되살린 꼴 — `gate` 가 직전 schedule 실행이 같은 sha 를 초록으로 돌았으면 건너뛰고,
    조각은 `e2e_plan.py --all`, Playwright 는 공식 이미지(#1109). main 에서 붉으면 고정 제목 이슈 「e2e 실패 — main 의 화면이 깨졌을 수 있다」
    (라벨 `ci-red`, `scripts/ci/ci-issue.sh`)를 열거나 댓글을 달고, 초록이면 「복구됨」 댓글을 달고 닫는다. **제목을 바꾸지 않는다** — 조율자
    점검(`stall-check.sh`)이 이 제목으로 찾는다. 실제 실패 이슈는 본 저장소에서만 만든다(notify 잡의 `github.repository` 조건, 포크는 알림 시험만).
    알림 시험: `gh workflow run e2e.yml --ref main -f simulate=fail`(새 이슈, 한 번 더면 댓글)·`-f simulate=ok`(복구·닫기) — 제목에 「(알림 시험)」.
  - **필수 검사 이름은 그대로 「결과」 하나다** — e2e 는 「결과」가 PR 에서 집계하고, 대기열에서는 plan 이 조각을 내지 않아 `skipped` 를 기대한다.
  - **pytest 는 PR 에서는 바뀐 앱과 그 앱에 기대는 앱의 시험만, 병합 대기열에서는 전부를 조각 나란히로 돈다**(#1088). `plan` 잡이 `scripts/ci/pytest_plan.py` 로 고른다:
    `backend/<앱>/…` → `app_deps.py affected` 가 고른 앱(바뀐 앱·그 앱을 쓰는·읽는 앱·그 앱들이 꽂힌 앱)의 `<앱>/tests/`, `backend/tests/**/test_*.py` 만 바뀌면 그 파일만,
    그 밖의 backend(`config/`·`conftest.py`·시험 도우미·`pyproject.toml`·`uv.lock`)·`docker/`·`scripts/`·`.github/`·루트는 전부. 앱 사이 시험(`tests/integration/`)은
    **닿는 앱**(import·주소 — `tests_layout.py` 가 그 파일의 자리를 정한 규칙, `touched()`)이 고른 앱과 겹칠 때만 돌고, 다 안 보이는 파일(전체 주소·`OVERRIDES`)은 늘 돈다.
    구조·전체 주소 시험(`tests/` 바로 아래, 경계 시험 포함)은 pytest 가 돌면 늘 돈다. 조각 수는 고른 파일의 기록 시간 합 ÷ 120초(1~6) — 전부면 6조각이다.
    고른 파일은 `CODEMIT_PYTEST_FILES` 로 조각 잡에 가고 `pytest_shards.py pick` 이 그 안에서 나눈다(없으면 전부). 규칙은 `scripts/test_pytest_plan.py` 가 고정한다.
    시간 기록 산출물 `pytest-junit-<조각>` 은 **전부를 돈 실행만** 올린다 — 일부의 junit 으로 기록을 쓰면 안 돈 파일이 0초가 된다.
    전부는 병합 대기열이 돈다 — 배포 판정은 그 한 번이다(#1090). 기록 갱신(`pytest-durations-update.sh`)도 최근 초록 대기열 실행에서 받는다.
  - **release 를 끈 뒤 켜면**(그동안 병합된 main 머리는 다음 push 까지 안 나간다) `gh workflow run release.yml --ref main` 으로 한 번 돌린다(`workflow_dispatch`, #1018). main 이 아닌 ref 는 `main_only` 잡이 실패시켜 뒤 잡(승격 포함)이 모두 멈춘다.
  - **celery 잡**(#1020)은 `celery-worker` 와 그 의존(db·redis·minio·backend)만 띄운다 — Next 앱 셋·events·grader 는 굽지 않는다. beat 간격은 `compose.ci.yaml` 의 `CODEMIT_CI_BEAT_INTERVAL_SECONDS=10`(`config/celery.py` 가 주기 스캔에만 적용, 운영·dev 는 그대로 60초).
  - **빨강 알림 = 라벨 `ci-red` 이슈**(`scripts/ci/ci-issue.sh`, release `notify`·e2e `notify` 잡, `issues: write` 하나): 종류(「release 이미지 실패」·「e2e 실패」)마다 열린 이슈는 하나, 이미 있으면 댓글. 본문에 실패 sha·run 링크·실패한 잡·직전 초록…이번 sha compare 링크. 다시 초록이면 「복구됨 <sha>」 댓글 후 닫는다 — **열린 `ci-red` 이슈 = 지금 빨강**이다. 라벨이 없으면 workflow 가 만든다. **담당**: 저장소 변수 `CI_RED_ASSIGNEE`(GitHub 계정, 설정은 대장 몫)가 있으면 이슈를 연 뒤 따로 담당으로 지정하고(실패는 경고, 이슈는 열린다), 담당 없는 열린 이슈에 댓글을 달 때도 지정한다 — GitHub 가 담당자에게 알린다. 비어 있으면 잡 요약에 경고만 남는다.
  - **release 에서 image 가 실패하면**(arm64 굽기·arm64 부팅 가드): `promote` 가 돌지 않는다 → production 이 승격되지 않는다 → **배포가 없다**.
    PR 은 이미 병합됐으니 main 만 앞서 있다. 아는 쪽은 `ci-red` 이슈(제목 「release 이미지 실패 — production 승격·배포 멈춤」)를 보는 조율자·대표다. 고쳐서 main 에 새 커밋(또는 revert PR)이 병합되면 다음 승격이 이어 간다.
- **release 는 검사하지 않는다 — 이미지와 승격만**(#1090). `pr-check.yml` 은 `pull_request`·`merge_group` 으로만 돌고 `push: main`·`workflow_call`
  트리거가 없다(같은 커밋을 PR·release 에서 두 번 검사하던 것을 걷었다). release 는 image(`image.yml`)가 일곱 arm64 이미지를 굽고(문맥 해시 건너뛰기·부팅 가드·ctx 태그 — 「배포」 문서)
  초록이면 promote 가 `production` 을 그 sha 로 앞당긴다(`scripts/ci/promote.sh ff`). 실행은 `gh run list --workflow release.yml`.
- 보안(공개 저장소, `scripts/test_public_repo.py`): `pull_request_target`·self-hosted 없음, secrets 없음(`github.token` 하나), 워크플로
  기본 권한 `contents: read`, **쓰기는 정해진 자리에만** — `packages: write` 는 image(image.yml·release.yml 의 image 잡), `contents: write`
  는 release.yml 의 promote 잡. 액션은 SHA 로 고정한다. PR 검사가 굽는 amd64 이미지는 올리지 않는다.
- **e2e 대조·e2e 태그는 없다**(#938에서 걷었다) — Actions PR 검사가 이미지를 올리지 않아 태그를 붙일 쪽이 없다.
- **production 승격 전에 그 커밋을 보증하는 것: main 은 병합 대기열로만 움직인다**(#1090 — #959 의 트리 비교 `verified_tree.py` 를 대신한다).
  - ruleset `main-merge-queue`(기본 브랜치, `enforcement: active`, **bypass_actors 없음** — 관리자도 넘지 못한다): `merge_queue`(squash, `ALLGREEN`)와
    필수 검사 「결과」. 대기열을 거치지 않은 push 는 거절되고, 대기열은 main 머리 위에 PR 을 얹은 머지 커밋으로 `pr-check.yml` 을 전부 돌려
    「결과」가 초록일 때 그 커밋을 그대로 main 에 올린다. 그래서 **main 의 모든 커밋 = 대기열이 초록으로 돈 트리**이고, release 가 그것을
    다시 증명(옛 verify)하거나 다시 돌(옛 check) 까닭이 없다. 두 PR 의 조합도 대기열이 main 머리 위에서 돈다(옛 「ruleset strict 꺼짐」 구멍이 없다).
  - amd64 부팅 가드(guard)는 대기열에서, arm64 부팅 가드는 release 의 `image.yml` 에서 그대로 돈다.
  - **이 보증은 대기열에 기댄다** — 대기열이 없는 저장소(본 저장소, 2026-11-20 지금)로 이 꼴을 옮기면 main 의 커밋이 아무 검사 없이 승격된다.
    대기열을 먼저 걸거나 release 에 check 를 되살린다(되돌리기: `release.yml` 에 `check: uses: ./.github/workflows/pr-check.yml` 과
    `pr-check.yml` 의 `workflow_call` 트리거를 되살리고 promote 를 `needs: [main_only, check, image]` 로).
  - 배선은 `scripts/test_release_flow.py` 가 고정한다 — release 가 `pr-check.yml` 을 부르지 않는다, 잡 집합, promote 가 image 만 기다린다,
    cache 잡 키 = pr-check.yml 의 복원 키.
- **워크플로 문법 검사(#1105)**: `workflow-lint.yml`(별도 파일 — pr-check.yml 자체가 파싱 안 되면 그 안의 어떤 잡도 안 뜨기 때문)이 `.github/workflows/**` 가 바뀐 PR 에서만 `scripts/ci/actionlint.sh --all` 로 actionlint(1.7.12, linux amd64 tarball 을 sha256 고정으로 내려받음)를 돌린다. 필수 검사(「결과」·ruleset)에는 넣지 않는다 — PR 에 빨강으로 보이는 것이 목적이다. `.githooks/pre-commit` 도 워크플로가 staged 일 때 같은 스크립트를 건다(로컬에 actionlint 가 있을 때). 로컬: `scripts/ci/actionlint.sh --all`.
- **아래에서 「PR 검사(Jenkins)」·macos·e2e 태그를 말하는 표와 글은 꺼진 검사의 기록이다.** Jenkins 이미지 빌드 비상 길도 제거했다. 검사와 이미지 빌드는 GitHub Actions만 수행한다.

### Actions 의 캐시 — main(release 의 cache 잡)이 저장하고 PR·대기열은 복원만 한다(#932·#1090)

처음에는 캐시가 없어 PR 하나가 11분(646~665초)쯤 걸렸다. 잡 안쪽을 재 보니 시간은 **이미지 굽기**(`checks` 의 CI 이미지 약 107초,
`guard` 92~112초, `e2e`·`celery` 의 스택 굽기 e2e 약 6분·celery 약 6분)와 **backend pytest 435초**에 몰려 있다. 앞의 것만 캐시로 줄인다 —
시험 시간은 그대로다.

- **이미지 층**: buildx `type=local` 캐시를 `actions/cache` 에 얹는다(`docker/setup-buildx-action` 의 컨테이너 빌더, 그래서 `--load`).
  폴더는 이미지별 — `ci`(`checks`)·`backend`(`e2e`)·`frontend`·`operator`·`classroom`(`guard`) — 이고, 키는
  `bk-<이름>-<Dockerfile·lockfile 해시>` 다. 복원은 `actions/cache/restore` 가 정확한 키 다음 `bk-<이름>-` 접두사로 가장 새 main 캐시를 받는다.
  `e2e`·`celery` 는 backend·세 앱 폴더를 모두 복원한다(compose 쪽 연결은 `docker/compose.ci-cache.yaml`).
- **CI 이미지의 node_modules 층도 캐시에서 온다(#1081)**: `ci.Dockerfile` 은 워크스페이스 매니페스트만 먼저 넣고 `pnpm install` 한 뒤
  소스를 넣는다 — 의존이 같으면 설치 층이 캐시 적중이다. 워크스페이스 패키지를 더하면 그 `package.json` COPY 도 더한다
  (`scripts/test_ci_images.py` 가 어긋나면 막는다). 이미지를 한 번 굽어 잡들이 나눠 받는 길은 재 보니 걸림 경로가 늘어 접었다(#1081 댓글).
- **저장은 main 에서만, release.yml 의 `cache`·`cache-node` 잡이 한다**(#1090) — PR·대기열(`gh-readonly-queue/…` ref)에서 만든 캐시는 그 ref
  안에서만 쓰여 다른 PR 에 소용이 없고 10GB 만 먹는다. 잡은 이름마다(ci·backend·frontend·operator·classroom) 정확한 키를 `lookup-only` 로 보고
  **이미 있으면 받지도 굽지도 않는다** — 키 파일(`docker/*.Dockerfile`·`backend/uv.lock`·`pnpm-lock.yaml`)이 바뀐 병합에서만 굽는다.
  없으면 앞 세대(`bk-<이름>-` 접두사)를 복원해 `--output type=cacheonly` 로 층만 굽고 `/tmp/bk-new` 에 내보낸 뒤 복원 폴더 자리에 바꿔 끼워
  저장한다(actions/cache 의 버전은 경로로 갈려 같은 경로여야 PR 이 받는다, 한 세대만 남는다). 저장소 쓰기 권한이 필요 없다 — GHA 캐시 백엔드
  `type=gha` 는 쓰지 않는 까닭. 승격은 이 잡을 기다리지 않는다. **포크(#1116)에서도 main push 면 이 두 잡만 돈다**(`main_only` 가 건너뛰어진
  자리를 `github.repository`·`github.ref` 로 대신 본다) — 전에는 포크 release 가 통째로 건너뛰어 캐시가 한 번도 저장되지 않았고, 포크 PR 의 e2e 조각은 층 없이 ~200초씩 구웠다. 키는 `pr-check.yml` 의 복원 키와 같아야 한다(`test_release_flow.py`).
- **병렬화(#932)**: `checks` 는 `sub-checks.sh <묶음>` 으로 여섯 실행기 — `static`(Django·마이그레이션 호환·생성물·문서·언어 검사)·`pytest I/N`(전부면 6조각, PR 은 고른 시험의 시간만큼,
  파일별 시간 기록으로 고르게 — `pytest_shards.py`, 기록 갱신은 `pytest-durations-update.sh`, #1083)·`web`(단위 시험·typecheck). 인자 없이는 전부 돈다(로컬 길). `e2e` 는 `CODEMIT_E2E_TARGETS` 로
  `public operator`·`classroom` 두 실행기(일꾼 1개 그대로). Playwright `--shard` 대신 프로젝트 단위로 나눈 까닭은 `e2e-two-pass.sh` 의
  `@exclusive` 패스가 시험 순번 shard 와 섞이면 일꾼 하나 보장이 깨지기 때문이다. 실패 결과물은 `checks-test-results-<묶음>`·`e2e-test-results-<이름>`, pytest 조각의 junit 은 전부를 돈 실행이면 초록이어도 `pytest-junit-<조각>`(14일).
  동시 잡은 plan 1 + checks 최대 8(static·pytest 6·web) + guard 3 + e2e 조각 + celery 1 + agent-grader 1 + 결과 1 — 공개 저장소 한도 20 을 넘는 만큼은 줄을 선다. 잡 분 합계는 늘 수 있다 — 실행기마다 이미지를 따로 굽기 때문이다.
- **pnpm 저장소**(`e2e` 잡 호스트 설치, 키는 lockfile 해시)도 같은 규칙이다.
- **e2e 의 Playwright 는 공식 이미지에서 돈다 — 잡이 apt 도 브라우저 CDN 도 부르지 않는다(#1109).** 예전에는 조각마다
  `playwright install --with-deps chromium` 이 실행기 미러에서 글꼴·라이브러리를 apt 로 받았고(브라우저 캐시는 포크에서 한 번도 저장되지
  않아 브라우저도 매번 받았다), 미러가 느린 날 그 조각 하나가 5분을 넘겨 대기열 전체를 붙잡았다. 지금은 `e2e.sh` 가
  `CODEMIT_E2E_PLAYWRIGHT_IMAGE=1` 일 때 `scripts/ci/playwright-image`(MCR `playwright:v<판>-noble`, 다이제스트 고정)를 스택 굽기와 겹쳐
  받고, Playwright 만 그 안에서 `--network host`·호스트 사용자로 돌린다 — 스택은 호스트 compose 그대로, node_modules 는 호스트에서 깔아
  같은 경로로 마운트한다. **이미지 판 ≠ lockfile 의 `@playwright/test` 면 시험 전에 실패한다**(`scripts/ci/playwright_image.py`, 시험
  `scripts/test_playwright_image.py` 가 plan 잡에서 돈다). `@playwright/test` 를 올리는 PR 은 이 파일의 태그·다이제스트도 같이 고친다
  (다이제스트 얻는 법은 스크립트 머리말). 로컬 `scripts/test.sh e2e` 는 그대로 호스트 Playwright 다.
- **10GB**: 키가 lockfile·Dockerfile 해시라 바뀔 때만 새 항목이 생기고, 안 쓰인 것은 GitHub 가 7일 뒤·한도 초과 때 오래된 것부터 지운다.
  `gh cache list` 합계를 가끔 본다.
- 보안 규칙(`scripts/test_public_repo.py`)은 그대로다 — 액션 SHA 고정, `permissions: contents: read`, secrets 없음.

(아래 표·글은 꺼진 Jenkins PR 검사의 기록이다.)

| 단계 | 노드 | 하는 일 |
| --- | --- | --- |
| 노드 고르기 | — | **macos 먼저**(`prefer: 'macos'`), 25분 안에 못 잡으면 home — e2e 가 macos 에서만 돌아 home 으로 넘어간 빌드는 ① 만 돌고 붉다 |
| 검사 | macos | `scripts/ci/pr-check.sh`. 문서(`.md`·`docs/`)만 바뀌었으면(`changed.sh`, merge-base 와 견준다) ADR 검사만. 아니면 ① `sub-checks.sh`(파일 이름의 sub 는 옛 호스트 이름) — Django `check`·`check --deploy`, pytest 전체, 생성물 최신성 둘, ADR·화면 언어·고정 대기 검사, 단위 시험, 세 앱 typecheck ② `macos-sweep.sh` → `images.sh arm64`(prod 여섯을 이 커밋으로, 바뀌지 않은 문맥은 ctx 로 건너뜀, `ghcr-push-token`) ③ 이번에 구운 앱의 부팅 가드(`deploy-guard.sh`, #838) ④ **그 이미지를 받아** `e2e.sh`(세 프로젝트)·`celery-broker.sh` ⑤ 초록이면 ctx 태그(`images-ctx.sh`)와 e2e 태그(`images-e2e.sh`) |

파괴적 migrate 검사(라이브러리)는 끈다(`migrationGuard: false`) — codemit 은 마이그레이션 호환을 PR 검사 static 묶음의
`scripts/ci/migration_compat.py` 로 지킨다([마이그레이션](migrations.md), #1091).

**배포 이미지는 PR 검사가 굽고, 배포 잡은 대개 커밋 태그만 더한다.** PR 검사는 이 브랜치 머리로 여섯을 굽고
커밋 태그 `<sha>-arm64` 로 올린다. e2e·celery 는 스택이 따로 굽지 않고 그 이미지를 받아 돈다
(`docker/compose.ci-images.yaml`, `CODEMIT_IMAGE_TAG`) — 그래서 **e2e 가 본 digest 가 prod 에 가는 digest 다**
(`test-results/images.txt`). 초록이면 그 digest 마다 `e2e-<트리>-arm64` 태그를 붙이고(`images-e2e.sh`, #729), prod 배포의
「e2e 대조」(`deploy.sh prod e2e-digest`)가 그 커밋의 트리로 태그를 받아 떠 있는 backend·세 앱의 이미지 ID 와 견줘 콘솔에
적는다(관측만 — 붉히지 않는다). 서비스마다 한 줄 — `e2e 대조: <서비스> — 같다 (<ID>)`, 다르면 `… — <판정> 떠 있는 것 <ID>
(<떠 있는 커밋 12자>), e2e 가 본 것 <ID>`, 태그나 컨테이너가 없으면 대조 못 함 — 이고 끝 줄이
`e2e 대조: 같다 N · 다시 구움 N · 다르다 N · 대조 못 함 N (트리 <12자>)` 다. 다르면 떠 있는 컨테이너를 만든 커밋과 이 커밋의
문맥을 `image_context.py changed` 로 견줘 「다르다(문맥 같음 — 다시 구운 것)」·「다르다!(문맥 다름)」·「다르다!(문맥 모름)」
으로 가른다(#738, #741).

- **왜 배포 잡이 건너뛰나 — sha 가 아니라 트리다.** squash 병합 커밋은 PR 머리와 sha 가 다르지만, PR 이 main 위에
  있었으면(뒤처지지 않았으면) 트리가 같고 서비스마다 문맥 해시도 같다 — 배포 잡의 `images.sh` 는 ctx 를 보고 굽지 않는다.
  PR 이 뒤처진 채 병합됐으면 다른 문맥만 배포 잡이 굽고 가드한다 — 해시가 판단하므로 틀린 이미지가 건너뛰어지지 않는다.
- **ctx 는 「그 문맥을 어느 빌드가 끝까지 초록으로 봤다」이다**(#709). PR 검사는 e2e·celery 까지 초록일 때, 배포 잡은
  굽기·가드가 초록일 때만 붙인다. 붉은 빌드의 이미지는 커밋 태그만 남아 다음 빌드가 다시 굽는다. 병합되지 않은 PR 의
  커밋 태그 이미지는 `codemit/ghcr-prune` 이 먼저 지운다(main 에 없는 커밋).
- **PR 검사는 자동 재시도하지 않는다.** 열차의 「인프라 고장이면 같은 묶음을 한 번 더」(#716·#729, `e2e_stall.py`)는 열차와 함께
  걷었다. 붉으면 작업자가 Actions 로그를 보고 고치거나(코드 탓), GitHub Actions 에서 같은 커밋을 다시 실행한다(인프라 탓).
- **「시험 하나 3초·재시도 없음」은 그대로다**(playwright.config.ts).

- **macos 의 Docker VM 디스크는 96GiB 이고, 묶음마다 무엇이 남는지 정해 두어야 찬다.** 맥 호스트
  디스크가 남아도 Docker Desktop 의 `Docker.raw` 가 차면 MinIO 가 `XMinioStorageFull` 로 업로드를
  거절하고 db 컨테이너가 죽는다 — 코드와 무관하게 묶음이 붉다. 실행마다 compose 프로젝트 이름이
  달라(`CODEMIT_CI_RUN_ID`) 쌓이는 것은 그 실행의 볼륨과 이미지다. 지금(#712, #873) PR 검사의 스택은 굽지 않고
  `images.sh` 가 올린 `ghcr.io/sandcorporation/codemit-<서비스>:<sha>-arm64` 를 받는다 — 커밋마다 새 태그라
  `macos-sweep.sh` 가 저장소마다 **가장 새것 하나**만 남긴다(다음 실행이 바뀌지 않은 층을 다시 받지 않는 층
  캐시). 굽는 쪽 캐시는 빌더 `codemit-images` 의 것이고 `images.sh` 가 20GB 로 자른다. `e2e.sh`·
  `celery-broker.sh` 는 내릴 때 `down -v --rmi local` 로 볼륨과 (굽는 길이면) 자기가 구운 이미지를 지운다.
  trap 이 못 돈 중단 빌드의 찌꺼기는 다음 빌드 첫머리의 `macos-sweep.sh` 가 걷고, 기본 빌더 캐시(이제
  로컬 굽기 길만 쓴다)는 나이가 아니라 크기(10GB, 오래 안 쓴 것부터)로 자른다. 사고 둘: 2026-10-03 중단된
  스택의 볼륨 400여 개(30GB), 2026-10-14 지워지지 않은 이미지 1,283개(51GB)와 캐시 48GB.
- **노드는 실행기가 하나라 통째로 쓴다.** 예전에는 GitHub Actions 의 셀프호스티드 러너
  셋(home)이 home 의 코어를 제한 없이 나눠 써, 이미지 빌드와 겹친 시험이 경합만으로 한도를
  넘었다(#499 의 첫 CI — 공개 e2e 10건·단위 2건 타임아웃). 오래 걸리는 e2e 를 성능이 좋은
  macos 에, 짧은 것을 배포 잡의 built-in 단계와 실행기를 나눠 쓰는 home 에 둔다(#840 전에는 staging 배포 전체와 나눠 썼다).
- **e2e 가 흔들리면 무엇을 보나**(#699). PR 검사 빌드의 작업 공간(`test-results/**`, macos)에
  셋이 있다. ① `test-results/playwright/<프로젝트>[-exclusive]/<시험>/` — 실패한 시험의 `trace.zip`
  (`pnpm --dir frontend exec playwright show-trace <파일>` 로 연다)과 `error-context.md`. 성공한 시험의
  것은 남지 않는다(`retain-on-failure`). 패스마다 폴더가 다른 것은 Playwright 가 실행마다 출력 폴더를
  비우기 때문이다 — 한 폴더면 뒤의 `@exclusive` 패스(시험 0개여도)가 앞 패스의 trace 를 지운다. 두 패스의 정의는
  `frontend/scripts/e2e-two-pass.sh` 하나다(#702 — `package.json`·`scripts/test.sh` 도 그것을 부른다).
  ② `test-results/stack/<서비스>.log` — 스택의 서비스마다 로그 전체, 줄마다 Docker 타임스탬프(나노초).
  `backend.log` 에는 gunicorn 접근 로그가 요청마다 한 줄 있다(`POST /api/… HTTP/1.1 201 128 24ms pid=<13>`
  — 상태·응답 바이트·걸린 ms·워커). `db.log` 에는 300ms 넘은 문장(`LOG:  duration: 400.691 ms  statement: …`)과
  300ms 넘게 잠금을 기다린 세션(`still waiting for AccessShareLock … after 300.082 ms` · 쥔 프로세스 ·
  `acquired … after`)이 찍힌다 — `compose.ci.yaml` 의 db·backend 오버라이드가 켠다(dev·배포는 그대로).
  ③ `test-results/summary.txt` — 프로젝트별 통과·실패와 걸린 초. 여러 시험이 한꺼번에 3초를 넘었으면
  trace 의 정지 시각을 `backend.log`·`db.log` 의 같은 시각과 맞춰 본다(열차 #1840 은 이것이 없어 원인을
  못 남겼다). ④ `test-results/host/*.log` — macos 호스트의 1초 샘플(#716, `scripts/ci/host-sample.sh` — vm-top 만 1.5~2초):
  `memory.log`(memory_pressure 의 남은 %·vm_stat 의 free/compressed/swapins/swapouts·스왑·load),
  `vm-top.log`(Docker VM 프로세스의 CPU·메모리 — 첫 줄은 이름이 맞는 후보 전부의 pid·RSS·실행 파일이고, 그중
  RSS 가 가장 큰 것을 VM 본체로 본다. CPU 는 `top -l 2 -s 1` 의 둘째 샘플이라 줄이 1.5초쯤마다 찍힌다 — 열차
  #1899 는 `pgrep | head -1` 이 RSS 39M 짜리 보조 프로세스를 집었고 `top -l 1` 의 첫 샘플이라 내내 0.0 이었다,
  #719), `docker-stats.log`(컨테이너마다, 따로 돌아 VM 이 멈추면
  줄 사이가 빈다). 줄마다 UTC 초 시각이라 스택 로그·trace 와 맞춰 본다. 명령이 없거나 권한이 없으면 그 칸이
  빌 뿐 e2e 를 붉게 만들지 않는다. 로컬 `scripts/test.sh e2e` 는 같은 trace 를 `frontend/test-results/`(뒤 패스는
  `frontend/test-results/exclusive/`)에 두고, 스택 로그는 `CODEMIT_E2E_KEEP=1` 로 남긴 스택에서
  `docker compose -p <워크트리>-e2e … logs --timestamps <서비스>` 로 본다.
- **backend 요청 0건 틈**(#716·#723). 열차 시절 e2e 넷이 한꺼번에 3초를 넘던 모양(backend 접근 로그에 4초 동안 요청 0건)은
  VM 정지가 아니라 강의실 BFF 가 끊긴 연결을 backend 에 넘겨 gunicorn 워커가 모두 붙잡힌 코드 탓이었다(#723 이 고쳤다).
  그 모양을 인프라로 가르던 판정(`e2e_stall.py`)과 재실행은 열차와 함께 걷었다(#873) — 다시 보이면 trace 의 정지 시각을
  `test-results/stack/backend.log`·`db.log` 와 맞춰 코드부터 본다.
- **macos 의 Docker Desktop 설정**(#716 — 사람이 mac 에서 한 번 읽어 적는다). 지금까지 trace 로 본 틈은
  VM 정지가 아니라 코드 탓(#723)이었다. 표는 다음에 판정이 발동하면 VM·호스트 쪽을 배제하거나 짚는 데
  쓰려고 남긴다 — 그 전에는 채울 급한 이유가 없다:

  | 항목 | 값 | 읽은 날 |
  | --- | --- | --- |
  | VM 메모리 | 11.67GiB — `test-results/host/docker-stats.log` 의 분모(`/ 11.67GiB`)로 읽을 수 있다(`playwright.config.ts` 주석은 24GB) | 2026-10-15(열차 #1899) |
  | VM CPU 수 | (적을 자리) | |
  | 스왑 | (적을 자리) | |
  | 가상화 프레임워크(Apple Virtualization·Docker VMM·QEMU) | (적을 자리) | |
  | 파일 공유(VirtioFS·gRPC FUSE·osxfs) | (적을 자리) | |
  | 네트워크 모드·포트 전달 | (적을 자리) | |
  | Resource Saver | (적을 자리) | |
  | Docker Desktop 버전 · macOS 버전 · 호스트 RAM | (적을 자리) | |

- **home 의 Jenkins 는 컨테이너라 node·pnpm·uv 가 없다** — 그래서 home 쪽은 저장소를 담은
  시험 이미지(`docker/ci.Dockerfile`)를 굽고 사이드카 postgres(tmpfs·fsync 끔)와 같은 망에서
  `scripts/ci/sub-checks-inside.sh` 를 돈다. 바인드 마운트는 쓰지 않는다(컨테이너와 호스트의
  경로가 다르다, 아래 「Jenkins 는 home 호스트에 있다」). 그 이미지는 루트
  `.dockerignore` 대신 `docker/ci.Dockerfile.dockerignore` 를 읽어 **문서를 들인다** — 문서 검사와
  다이어그램 최신성 시험이 그것을 읽는다(빼먹었을 때 넷이 「파일이 없다」로 빨갰다).
- **실측**(2026-10-02, 첫 초록): home 쪽 전체 약 3분(pytest 2489건 47초), macos e2e 공개 14초 ·
  운영자 4초 · 강의실 4초(이미지 굽기 제외).
- **잡 설정은 저장소 밖이다** — Multibranch 잡·배포 잡·자격증명(`github-sandcorporation-token` 은
  fine-grained PAT: 저장소 읽기·PR·커밋 상태·Contents 쓰기, `glitchtip-automation-token`, 이미지 쓰기 토큰은 GitHub Actions `GITHUB_TOKEN` 을 쓴다. (이 표는 당시 Jenkins 설정 기록이다.) Jenkins 설정을 API 로 고칠 때는 `Content-Type: application/xml;
  charset=utf-8` 을 붙인다 — 없으면 한글이 Latin-1 로 읽혀 500 이 난다.
- **잡은 폴더 `codemit/` 안에 넷이다**(2026-10-23, #780) — Jenkins 첫 화면에는 폴더 하나만 보인다. 2026-10-15(#708)
  부터는 `codemit-<역할>-<대상>` 으로 나란히 섰고, #779 가 `codemit-deploy-prod` 를 `codemit-deploy-staging` 의 「prod 배포」
  단계로 합쳐 넷이 남자 폴더로 묶으며 접두 `codemit-` 을 뗐다. 접두를 뗀 이유는 `BUILD_TAG`(`jenkins-<전체 이름의 / 를 - 로>-<번호>`)
  가 **그대로**이기 때문이다 — `codemit/ci-train` → `jenkins-codemit-ci-train-N`. 그래서 `macos-sweep.sh` 의 compose
  프로젝트 패턴과 #735 는 건드리지 않았다. API 경로는 `/job/codemit/job/<이름>/…`, 잡 디렉터리는
  `/var/jenkins_home/jobs/codemit/jobs/<이름>/` 이다.

  | 잡 | 옛 이름 | 파일 | 워크스페이스·이름에 묶인 것 |
  | --- | --- | --- | --- |
  | `codemit/ci-pr`(Multibranch) | `codemit-ci-pr` | `Jenkinsfile.pr` | 검사의 컨테이너·네트워크·이미지(`codemit-ci:<run_id>`)와 e2e·celery 스택 `jenkins-codemit-ci-pr-*`(`BUILD_TAG` 에서) |
  | `codemit/deploy` | `codemit-deploy-staging` | `Jenkinsfile` | jenkins-shared `sandcorpDeploy` — 확인·알림은 built-in 의 잡 워크스페이스, 배포는 에이전트 `oracle` 의 `ws('/home/jenkins/agent/workspace/codemit-deploy-prod')` = oracle 호스트 `/var/jenkins_home/workspace/codemit-deploy-prod/`(사람이 둔 `docker/.env.prod`·배포 표식) |
  | `codemit/ghcr-prune` | `codemit-ghcr-prune` | 저장소 밖 | |

  더 전의 이름은 `codemit-pr`·`codemit-train`·`laurio`·`codemit` 이다. 열차 잡 `codemit/ci-train`(2026-10-03~11-05)은
  #873 이 `Jenkinsfile.train` 을 지워 할 일이 없다 — 잡·자격증명 `codemit-train-webhook-token`·열차용 GitHub 웹훅을 지우는 것은
  대장 몫이다(그때까지 30분 cron 이 지워진 파일을 찾다 붉게 끝난다). 잡을 이름으로 부르는 자리는 이제 없다.
  GitHubPushTrigger(저장소 URL)·전역 자격증명·GitHub 커밋 상태 문맥(`continuous-integration/jenkins/branch`,
  `sandcorp/deploy`)은 잡 이름과 무관하다. PR CI·prune 의 워크스페이스는 새로 받아도 되는
  체크아웃이라 붙잡지 않았다(옮긴 뒤 첫 빌드가 통째로 clone 해 한 번 느리다). `macos-sweep.sh` 는
  rename 직전에 남은 `jenkins-codemit-(pr|train)-*` 도 한동안 같이 걷는다 — 2026-11-15 이후 #735 로 지운다(지울 조건은 그 파일 머리말).
  #708 끝 조건의 「새 이름으로 한 번씩 초록」은 prod 를 뺀 셋이었다 — 옛 `codemit-deploy-prod` 는 10-21 prod #177
  이 마지막 빌드였고 #779 로 사라졌다.
- **문서(`*.md`·`docs/`)만 바뀐 커밋은 시험도 교체도 건너뛴다.** PR 검사는 `scripts/ci/changed.sh`(merge-base 와 견준다)로
  ADR 검사만 한다. release 의 image 잡은 문맥 해시로 전부 「건너뛴다」(커밋 태그만)가 되고 production 이 앞당겨지면, oracle 의 `deploy.sh plan` 이 **배포 표식**(`.jenkins-prod-deployed`, 마지막으로
  성공한 prod 배포) 기준으로 바뀐 서비스가 없다고 내 교체 없이 표식만 옮긴다(#873 — 그 전에는 GitHub 의 `production` 브랜치와
  `changed.sh` 로 견줘 노드도 잡지 않았다, #840). 배포 표식은 성공한 배포의 마지막에만 옮기므로 배포가 실패한 커밋 뒤의 문서
  커밋도 그 배포를 다시 시도한다(#709 의 교훈).
- **배포 이미지는 다시 GitHub Actions 가 굽는다**(2026-11-09 #938, ADR-0077 — 공개 저장소라 분량 제한이 없다). 2026-10-15(#705,
  ADR-0061)에는 조직이 Free 요금제라 호스티드 분량(월 2,000분)이 바닥나자 `staging` 이 멈췄고, 결제하지 않고 떠났다. 아래는 그 뒤
  ~ 11-09 의 Jenkins 굽기이고, 지금은 image.yml 이 arm64 실행기에서 부른다. Jenkins 빌드 비상 길은 제거했다. Actions 가 하던 셋 — 배포 이미지, 부팅
  가드, `staging` 앞당기기 — 은 `main` push 에서 도는 Jenkins `codemit/deploy` 잡(`Jenkinsfile`)의 앞 단계가 됐다
  (「배포」 절, `staging` 앞당기기는 #840 에서 걷었다). 이미지는 macos 가 arm64 여섯을 굽고(`scripts/ci/images.sh`; #840 전에는 home 가 amd64 여섯도 구웠고 #841 에서 걷었다),
  **바뀌지 않은 서비스는 빌드 문맥 해시로 건너뛴다**. 구운 이미지는 커밋 태그로만 올리고, 문맥 태그
  (`ctx-<해시>`)는 굽기와 부팅 가드가 **모두 초록인 뒤에** 「문맥 태그」 단계(`scripts/ci/images-ctx.sh`,
  macos)가 붙인다(#709) — 그래서 「건너뛴다」는 언제나 앞 빌드가 끝까지 초록으로 본 이미지이고, 가드가 빨갛거나
  굽기가 실패한 빌드의 이미지는 다음 빌드가 다시 굽고 가드도 다시 돈다. 부팅 가드 셋(`scripts/ci/deploy-guard.sh`, prod 의 arm64 를 PR 검사(macos, #838)와 배포 잡의 「이미지 굽기」(#840, #873)가 본다)은
  **방금 올린 그 이미지를 ghcr 에서 받아** 배포 설정 없이는 죽고 완전한 설정으로는 뜨는지 본다 — 이번에
  구운 앱만(건너뛴 앱의 이미지는 이미 한 번 지났다). 앱 이미지는 환경을 모르므로(#711) 가드가 공개 값을
  `-e CODEMIT_PUBLIC_*` 로 주고, 방침의 문의 주소가 `/privacy` 에, 토스 클라이언트 키가 첫 화면의
  `window.__CODEMIT_PUBLIC__` 에 실리는지(시크릿은 실리지 않는지)로, `.dockerignore` 는 가짜 시크릿을 심은 **빌드 컨텍스트**(`COPY . /ctx`
  만 하는 이미지)로 본다 — 표식에 빌드마다 다른 값을 섞는다(스크립트 자신이 문맥에 들어 고정 문자열이면
  늘 걸린다). 컨테이너 포트를 노드에 열지 않고 띄운 컨테이너의 네트워크에 curl 컨테이너를
  붙여(`--network container:<이름>`) 친다(home 의 Jenkins 가 컨테이너라 바인드 마운트도 쓰지 않는다).
- **`Jenkinsfile`(배포)·`deploy-prod.sh` 와 `image.yml`·`release.yml` 은 PR 검사가 돌려 보지 못한다** — 바꾼 PR 의 병합 뒤 첫 release
  실행·첫 배포가 곧 그 시험이다(`scripts/test_release_flow.py` 는 배선만 본다). 라이브러리 쪽은 `@Library('sandcorp@<브랜치>')` 로 시험할 수
  있다(라이브러리 README). 스크립트 쪽은 로컬에서 돈다: `CODEMIT_IMAGES_MODE=plan`(해시와 판단만),
  `CODEMIT_IMAGE_REGISTRY=localhost:<포트>`(로컬 `registry:2` 에 실제로 굽고 건너뛰기), `CODEMIT_GUARD_IMAGE=<이미지>`(가드가
  받을 이미지), `CODEMIT_IMAGE_TAG=<sha>-<arch> scripts/test.sh e2e`(올린 이미지로 e2e — PR 검사의 길). 두 스크립트는 macos 의
  bash 3.2 에서도 돈다.

**CI 는 `docker/compose.ci.yaml` 을 dev compose 위에 겹쳐 쓴다 — 지우면 CI 가 깨진다.**
`compose.dev.yaml` 의 `..:/app` 은 **개발용 핫리로드 장치**다. 러너 안에서 그 상대 경로는
호스트 데몬 기준으로 풀려 `/app` 이 통째로 비고, backend 는 `can't open file '/app/manage.py'`
로, 두 앱은 `Scope: all 0 workspace projects` 로 죽는다. 오버라이드가 하는 일은 셋뿐이다:

- 다섯 서비스(backend·events·frontend·operator·classroom, #379)의 `volumes` 를 `!reset []` —
  마운트 없이 **이미지 안의 코드**로 돈다.
- 세 앱(frontend·operator·classroom, #277)의 빌드 `target` 을 `runner` 로 — dev 서버가
  아니라 **배포되는 그 이미지**를 친다.
- 세 앱의 `command` 를 `!reset null` — 이미지의 `node server.js` 가 산다.

PR 검사는 셋째 장 `docker/compose.ci-images.yaml` 을 더 얹는다(#712) — 위 셋은 그대로 받고 `build` 를 걷어
`images.sh` 가 올린 `codemit-<서비스>:${CODEMIT_IMAGE_TAG}` 를 받는다(backend 계열 다섯은 `codemit-backend`
하나). `CODEMIT_IMAGE_TAG` 가 없으면 `e2e.sh`·`celery-broker.sh`·`scripts/test.sh e2e` 는 예전처럼 스택이 굽는다.

**그래서 e2e 가 검증하는 대상이 바뀌었다.** 예전엔 `next dev` 를, 지금은 프로덕션 빌드를
친다 — 배포되는 것과 테스트되는 것이 같아졌다. 위 `next dev` 메모리 주의는 이제
**로컬에서 스위트를 돌릴 때만** 해당한다.

**스택마다 이름을 갈라 준다.** e2e 와 celery-broker 의 compose 프로젝트 이름은 빌드
식별자(`CODEMIT_CI_RUN_ID` — 빌드 태그 + 시작 시각)에서 나오고, 포트는 compose 가 비어 있는 것을
고른다. 끝나면(성공·실패·중단 모두) `down -v` 로 지운다.

**화면 언어 검사**(#267, #268 — PR CI 의 home 단계)는 스텝 둘로 두 표면을 막는다. 첫 스텝
(`scripts/check_screen_language.py`)은 공개 앱(`frontend/`)의 화면 문자열에
`CONTEXT.md` 가 정한 영어 도메인 용어(`Sponsor`·`Contest`·`Escrow` 등)나
`ADR-숫자`·`#숫자` 참조가 있으면 막는다. 둘째 스텝(`scripts/
check_backend_error_language.py`, #268)은 백엔드가 공개 앱으로 던지는
`HttpError(...)` 의 message 인자에 같은 것을 막는다 — 화면 문자열 자체가
아니라 백엔드 오류를 그대로 렌더하는 자리(`packages/bff-client/src/
result.ts` 의 `normalizeDetail`)라 첫 스텝이 볼 수 없던 표면이다. 운영자 API
(`/api/operator/*`)는 두 스텝 다 대상이 아니다 — 뒤쪽은 파일이 아니라 함수
단위로(데코레이터가 `router`인지 `operator_router`인지, 도우미는 호출
그래프로) 가른다. 정말 필요한 예외는 둘 다 같은 `SCREEN-LANGUAGE-EXCEPTION:
<이유>` 주석으로 표시한다.

**첫 스텝이 셋째 것도 막는다 — 화면이 자기 구현을 설명하는 문장이다**(2026-09-21).
이 저장소는 주석과 `docs/` 를 두껍게 쓰는데, 그 말투가 **사용자가 읽는 화면으로
새어 나간 적이 있다**: 이용약관에 「유료 공모전을 여는 시점에 채우는 조항」이라는
절이 있었고 방침 서두가 「그 조항은 8절에 자리만 남겨 두었고, 기능을 열 때
채웁니다」라고 말했다 — 없는 조항을 목차로 예고하는 약관은 없다. 공모전 상세의
무료 안내도 같은 종류로 한 번 지적받았다(2026-09-20, 화면 맨 위 상자 → 맨 아래
작은 글씨).

**규칙은 하나다: 화면은 지금 참인 사실만 말하고, 아직 없는 것은 적지 않는다.**
기능을 열 때 그 문서를 고쳐 알린다(약관·방침은 스스로 개정 조항을 갖고 있다).
`check_screen_language.py` 의 `META_PHRASES`(`자리만 남`·`채울 자리`·`나중에
채우`·`아직 구현`·`TODO` 등)가 그 말투를 기계로 막고, 같은
`SCREEN-LANGUAGE-EXCEPTION: <이유>` 로 연다. 목록은 오탐을 만들지 않도록 「이
자리는 나중에 채운다」는 뜻으로만 쓰이는 토막만 담는다 —
`scripts/test_check_screen_language.py` 가 「남은 자리가 없습니다」 같은 정상
문구가 통과하는 것까지 고정한다.

### 포크 `laurio-restructure` — 이미지·승격·스케줄·이슈는 돌지 않는다, 병합은 대기열로(#1084)

구조 재편(#1079)은 포크에서 한다. 포크에는 비밀값·변수·환경이 없고, 같은 워크플로가 돌되 운영에 닿는 잡은
`github.repository == 'sandcorporation/laurio'` 조건으로 멈춘다(본 저장소에서는 늘 참이라 무해하다).

| 워크플로 | 포크에서 |
| --- | --- |
| `release.yml` | `main_only` 가 건너뛰어 image·cache·cache-node·promote·notify 가 모두 멈춘다 |
| `image.yml` | `build` 가 건너뛴다(수동 실행도) — 운영 이미지 저장소에 올리지 않는다 |
| `pr-check.yml` | PR 과 병합 대기열(`merge_group`) 양쪽에서 돈다 |

포크 main 은 ruleset `main-merge-queue` 의 병합 대기열(squash)과 필수 검사 「결과」로만 들어간다.
PR 이 초록이면 `bash scripts/fork/enqueue.sh <번호>` 로 대기열에 넣는다(포크는 자동 병합이 꺼져 있어 `gh pr merge` 가 거절한다) —
대기열이 머지 커밋으로 `pr-check.yml` 을 다시 돌려 「결과」가 초록이면 squash 병합한다.
`scripts/test_release_flow.py` 가 위 조건과 `merge_group` 트리거를 고정한다.

본 저장소 main 은 매일(그리고 포크 티켓을 시작하기 전에) `bash scripts/fork/sync-upstream.sh` 로 당겨 맞춘다 —
마지막으로 당긴 sha(`scripts/fork/upstream-sha`)부터의 차이를 얹어 PR 을 열고 대기열에 넣는다. 충돌이면 멈춘다.
`scripts/fork/` 는 본 저장소로 되돌리는 PR 에 싣지 않는다.
