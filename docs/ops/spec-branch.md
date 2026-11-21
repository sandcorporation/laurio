# 스펙 브랜치 — 티켓 사이에는 PR·CI 없이 `spec/<이름>` 에 올리고, 끝에 PR 하나·검사 한 번·배포 한 번

`CLAUDE.md` 의 부록이다. 대표 결정(2026-11-21, #1210 → #1228). 여러 티켓짜리 스펙에 쓴다 — 독립 고침 한 건짜리는
지금처럼 [티켓을 닫는 기준](ticket-done.md)대로 PR 하나로 main 에 간다. 점수 정정(#1181~#1184)까지는 옛 흐름이다.

> 스펙[이슈 → 다음 이슈 → 다음 이슈 → PR → CI → 실패하면 다시 수정]

- 스펙 하나 = 브랜치 하나(`spec/<이름>`) = PR 하나 = 전체 검사 한 번 = 배포 한 번.
- 작업자는 티켓 하나를 끝내면 커밋하고 `spec.py push` 로 스펙 브랜치에 올린 뒤 바로 다음 티켓으로 간다. 티켓 PR 은 없다.
  티켓은 이슈로 남고, 마지막 PR 의 `Closes` 가 닫는다.
- 의존 사슬 하나는 작업자 하나가 한 세션에서 잇는다. 독립 사슬은 작업자를 나눠 같은 `spec/<이름>` 에 `push` 로 합친다.

명령은 모두 `python3 scripts/spec/spec.py` 하나다. 종료 코드 0 됨 · 1 거절(까닭 한 줄) · 2 사용법·조회 실패.

| 때 | 누가 | 명령 |
| --- | --- | --- |
| 착수 | 조율자 | `spec.py start <이름>` — origin/main 위에 `spec/<이름>` 을 만들어 push(꼬리말 `Spec-Start` 빈 커밋 하나) |
| 티켓 | 작업자 | 워크트리는 `git worktree add -b <로컬 브랜치> <경로> origin/spec/<이름>`. 커밋 제목에 `(#N)`, 꼬리말에 `Spec-Ticket: #N` 과 Co-Authored-By |
| 티켓 끝 | 작업자 | `spec.py push <이름>` — 아래 「push」. 그리고 바로 다음 티켓(같은 워크트리·같은 로컬 브랜치) |
| 따라잡기 | 조율자 | `spec/<이름>` 워크트리에서 `spec.py sync <이름>` — `git merge origin/main` → 보통 push. 충돌이면 파일을 찍고 멈춘다 |
| 마감 | 조율자 | 마지막 티켓이 올라오면 `spec.py finish <이름>` — `spec/<이름>` → main PR 하나(티켓별 커밋·`Closes #…`) |
| 붉음 | 조율자 → 작업자 | `spec.py blame <이름> <실행 번호\|시험 경로>` → 그 티켓의 작업자가 고쳐 커밋(꼬리말 `Spec-Ticket: #그 티켓`) → `spec.py push <이름>` → 같은 PR 이 다시 검사된다 |
| 병합 | 조율자 | 「결과」 초록 → `bash scripts/ci/enqueue.sh <PR> --wait` → 배포 하나 |
| 보기 | 누구나 | `spec.py dev <이름> [--offset N]` — `../codemit-wt/spec-<이름>` 워크트리 + 오프셋 dev 스택 |
| 숫자 | 조율자 | `spec.py report <이름>` · 비교는 `spec.py report --prs 1179,1180,…` |

## push — 작업자 워크트리 → 스펙 브랜치

`git fetch` → `git merge origin/spec/<이름>`(이미 담았으면 건너뜀) → `git push origin HEAD:spec/<이름>`(보통 push).
fetch 와 push 사이에 다른 사슬이 먼저 올려 앞질러졌으면 다시 받아 합친다 — **3번**(`PUSH_TRIES`)까지, 그래도 앞질러지면
거절한다. 사슬이 몇이어도 같은 명령 하나다.

거절하는 것:

- 더러운 작업 트리(추적 파일의 고치지 않은 변경) — 커밋하거나 되돌린 뒤 다시.
- `origin/spec/<이름>..HEAD` 의 merge 아닌 커밋에 `Spec-Ticket: #N` 꼬리말이 없음 — `git commit --amend` 로 더한다.
- `origin/spec/<이름>` 와의 충돌 — 파일을 찍고 merge 상태로 멈춘다. 고친 뒤 `git add` · `git commit --no-edit` · 다시 push.
- 양쪽이 같은 앱에 마이그레이션을 더함 — 아래 「병렬 사슬 충돌」.

## 검사 — 스펙 브랜치 push 로는 돌지 않는다, PR 에서 한 번

`pr-check.yml` 은 `pull_request`·`merge_group` 만 듣는다(`push` 없음, [CI](ci.md)). 그래서 `spec.py push`·`sync` 는 검사를
부르지 않는다. `release.yml` 은 `push: main` 만 들어 스펙 브랜치 push 로 배포되지도 않는다.

- **티켓 사이의 안전망은 로컬의 빠른 것뿐이다**: 고친 곳의 시험, 타입·린트, [커밋 훅](commit-hooks.md).
- **스펙 → main PR**: pull_request 실행이 main 과의 차이 = 스펙 전체로 pytest·e2e 를 고른다. 대기열은 pytest 전부와
  guard 를 돌고 e2e 는 돌지 않는다(#1111) — 스펙이 건드린 앱의 e2e 는 PR 실행이 이미 돌았고, 공통 경로(`packages/`·
  `scripts/`·루트)를 건드렸으면 경로 표가 전부를 고른다. 매시 `e2e.yml` 이 전부를 돈다.
- 붉으면 같은 브랜치에 고친 커밋을 `push` 한다 — 같은 PR 의 새 실행이다. 새 PR 을 열지 않는다. 시험 재실행으로 넘기지 않는다.

## 기록 — 커밋 꼬리말 셋

- `Spec-Start: <이름>` — `start` 의 빈 커밋. `report` 의 착수 시각.
- `Spec-Ticket: #<이슈>` — 티켓 커밋마다(한 커밋에 여러 줄 가능). `push` 가 없으면 거절하고, `finish` 가 티켓별 커밋 목록과
  `Closes` 를, `blame` 이 실패 파일의 티켓을, `report` 가 티켓 수를 여기서 읽는다.
- `Spec-Sync-Conflicts: <수>` — `sync` 의 merge 커밋. 충돌로 멈추면 `MERGE_MSG` 에 충돌 수를 미리 적어 두므로 고친 뒤
  `git add` · `git commit --no-edit` · 다시 `sync` 하면 그대로 남는다(메시지를 고쳐 쓰지 않는다).

`report` 가 내는 것(gh API): 착수 → 배포(`sandcorp/deploy` success) 시각, 티켓 수, 전체 검사 횟수(스펙 → main PR 의
`pr-check.yml` 실행: PR · 대기열), 배포 횟수, 마지막 전체 검사의 실패 잡 수, main 충돌 수(sync 횟수). `--prs` 는 같은 칸을
「티켓마다 main PR」 방식(#1178)으로 낸다(착수 = 가장 이른 커밋, 충돌은 「—」).

## 위험과 대비

**큰 PR 의 실패 가르기.** 티켓이 커밋으로 갈려 있으므로 실패를 티켓으로 되짚는다.
`spec.py blame <이름> <실행 번호>` 는 그 실행의 실패 로그(`gh run view --log-failed`)에서 저장소 파일 경로(pytest `FAILED …`,
playwright `› e2e/…`)를 줍고, 파일마다 `origin/main..origin/spec/<이름>` 에서 그 파일을 마지막으로 바꾼 커밋과 꼬리말의 티켓을
찍는다. 경로를 못 주우면 시험 경로를 직접 준다(`spec.py blame <이름> backend/x/tests/test_y.py`). 스펙이 바꾸지 않은
시험 파일이면 「main 그대로」라고 찍는다 — 그 시험이 부르는 코드를 바꾼 티켓을 본다.

**중간 결과가 운영에 늦게 나간다.** 스펙 크기 상한 기본안은 **티켓 8개 또는 착수 후 2일** 중 먼저 오는 것이다 — 넘을 것
같으면 to-tickets 때 스펙을 둘로 가른다. 급한 고침은 스펙 밖 단독 PR 로 main 에 바로 간다. 스펙이 오래 걸리면 조율자가
`sync` 로 main 을 따라잡는다(작업자는 다음 `push` 때 받는다).

**병렬 사슬 충돌.** to-tickets 때 사슬을 파일(앱)로 가른다 — 두 사슬이 같은 파일을 고치지 않게. 그래도 겹치면 `push` 가
충돌을 거절하고 파일을 찍는다. 마이그레이션은 git 충돌 없이 leaf 가 둘이 될 수 있어서, `push` 는 갈라진 뒤 양쪽이 같은 앱의
`migrations/` 에 파일을 더했으면 합치기 전에 거절한다. 그때는 `git merge origin/spec/<이름>` 뒤 내 마이그레이션을 그 다음
번호로 옮기고 `dependencies` 를 고쳐 커밋하고 다시 `push` 한다(`makemigrations --merge` 는 쓰지 않는다).

## 마이그레이션·되돌리기 — 배포가 한 번이라 생기는 것

- 마이그레이션 호환 검사(`migration_compat.py`)는 스펙 → main PR·대기열에서 main(= 직전 운영 판)과 견준다 — 스펙 전체
  마이그레이션이 직전 운영 판 코드와 호환돼야 통과한다.
- **파괴적 변경의 두 단계([마이그레이션](migrations.md))는 한 스펙 안에서 끝낼 수 없다.** 티켓 둘로 나눠도 스펙 → main
  PR 에서 하나가 되어 거절된다. 첫 단계(코드·상태)는 이 스펙, 정리 단계는 **다음 스펙·다음 배포**다.
- 자동 되돌리기(`rollback`, [배포](deploy.md))는 직전 배포 표식의 이미지로 돌아간다 — 되돌림 범위는 **스펙 전체**다.
  되돌리기 PR 도 스펙 → main 병합 하나를 통째로 되돌린다.

## 안 하는 것

- 티켓 PR — `spec/*` 으로 가는 PR 을 열지 않는다(#1210 의 `merge-ticket` 은 #1228 에서 지웠다). `pr-base.sh` 의
  `spec/*` 기준 갈래는 남아 있지만 쓰이지 않는다.
- force push — `push`·`sync` 는 merge 다. 스펙 브랜치를 rebase 하지 않는다. `spec/*` ruleset(삭제·강제 push 금지)은 그대로다.
- 스펙 브랜치 push 로 배포 — `release.yml` 은 `push: main` 만 듣는다.
- `spec/*` 의 ruleset 은 저장소 관리자 몫이다.
