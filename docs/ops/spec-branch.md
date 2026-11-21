# 스펙 브랜치 — 티켓은 `spec/<이름>` 으로 모으고, 스펙 하나 = 전체 검사·배포 한 번

`CLAUDE.md` 의 부록이다. 대표 결정(2026-11-21, #1210). 여러 티켓짜리 스펙에 쓴다 — 티켓 하나짜리 고침은
지금처럼 [티켓을 닫는 기준](ticket-done.md)대로 하나씩 main 으로 간다. 점수 정정(#1181~#1184)까지는 옛 흐름이다.

명령은 모두 `python3 scripts/spec/spec.py` 하나다. 종료 코드 0 됨 · 1 거절(까닭 한 줄) · 2 사용법·조회 실패.

| 때 | 누가 | 명령 |
| --- | --- | --- |
| 착수 | 조율자 | `spec.py start <이름>` — origin/main 위에 `spec/<이름>` 을 만들어 push(꼬리말 `Spec-Start` 빈 커밋 하나) |
| 티켓 | 작업자 | 워크트리는 `origin/spec/<이름>` 에서, PR 의 base 는 `spec/<이름>` |
| 티켓 병합 | 작업자 | PR 「결과」 초록 → `spec.py merge-ticket <PR>` — base 가 `spec/*` 이고 head 의 「결과」가 success 일 때만 squash 병합 |
| 따라잡기 | 조율자 | `spec/<이름>` 워크트리에서 `spec.py sync <이름>` — `git merge origin/main` → 보통 push. 충돌이면 파일을 찍고 멈춘다 |
| 마감 | 조율자 | `spec.py finish <이름>` — `spec/<이름>` → main PR(모인 티켓 PR 목록과 `Closes #…`) → `bash scripts/ci/enqueue.sh <PR> --wait` |
| 보기 | 누구나 | `spec.py dev <이름> [--offset N]` — `../codemit-wt/spec-<이름>` 워크트리 + 오프셋 dev 스택 |
| 숫자 | 조율자 | `spec.py report <이름>` · 비교는 `spec.py report --prs 1179,1180,…` |

## 검사 — 티켓 PR 은 그 PR 의 차이만, 스펙 → main 은 스펙 전체

PR 검사의 기준은 PR 이 가는 브랜치와의 merge-base 다(`scripts/ci/pr-base.sh`, [CI](ci.md)). main 으로 가는 PR 은 예전과
같고, `spec/*` 으로 가는 티켓 PR 은 스펙에 먼저 모인 티켓을 「바뀐 것」으로 세지 않는다.

- **티켓 PR**: 바뀐 앱의 pytest·e2e 만. 「결과」는 같은 이름으로 나오지만 `spec/*` 에는 필수 검사가 없다 — 판정은
  `merge-ticket` 이 한다(필수로 걸면 `sync` 의 merge push 가 막힌다).
- **스펙 → main PR**: pull_request 실행이 main 과의 차이 = 스펙 전체로 pytest·e2e 를 고른다. 대기열은 pytest 전부와
  guard 를 돌고 e2e 는 돌지 않는다(#1111) — 스펙이 건드린 앱의 e2e 는 PR 실행이 이미 돌았고, 공통 경로(`packages/`·
  `scripts/`·루트)를 건드렸으면 경로 표가 전부를 고른다. 매시 `e2e.yml` 이 전부를 돈다. 그래서 대기열에 e2e 를 더하지 않는다.
- 티켓 PR 이 초록이 된 뒤 스펙이 움직였으면 그 조합은 스펙 → main PR 에서 처음 검사된다. 나온 것은 스펙 브랜치에
  티켓 PR 로 고친다.

## 마이그레이션·되돌리기 — 배포가 한 번이라 생기는 것

- 마이그레이션 호환 검사(`migration_compat.py`)의 base 는 PR base 다. 티켓 PR 은 스펙 tip 과, 스펙 → main PR·대기열은
  main(= 직전 운영 판)과 견준다 — 스펙 전체 마이그레이션이 직전 운영 판 코드와 호환돼야 통과한다.
- **파괴적 변경의 두 단계([마이그레이션](migrations.md))는 한 스펙 안에서 끝낼 수 없다.** 티켓 둘로 나눠도 스펙 → main
  에서는 같은 PR 에 둘이 있어 거절된다. 첫 단계(코드·상태)는 이 스펙, 정리 단계는 **다음 스펙·다음 배포**다.
- 자동 되돌리기(`rollback`, [배포](deploy.md))는 직전 배포 표식의 이미지로 돌아간다 — 되돌림 범위는 **스펙 전체**다.
  되돌리기 PR 도 스펙 → main 병합 하나를 통째로 되돌린다.

## 기록 — 커밋 꼬리말 둘

- `Spec-Start: <이름>` — `start` 의 빈 커밋. `report` 의 착수 시각.
- `Spec-Sync-Conflicts: <수>` — `sync` 의 merge 커밋. 충돌로 멈추면 `MERGE_MSG` 에 충돌 수를 미리 적어 두므로 고친 뒤
  `git add` · `git commit --no-edit` · 다시 `sync` 하면 그대로 남는다(메시지를 고쳐 쓰지 않는다).

`report` 가 내는 것(gh API): 착수 → 배포(`sandcorp/deploy` success) 시각, 티켓 PR 수, 전체 검사 횟수(스펙 → main PR 의
`pr-check.yml` 실행: PR · 대기열), 배포 횟수, 마지막 전체 검사의 실패 잡 수, main 충돌 수(sync 횟수). `--prs` 는 같은 숫자를
「티켓마다 main PR」 방식으로 낸다(착수 = 가장 이른 커밋, 충돌은 「—」).

## 안 하는 것

- force push — `sync` 는 merge 다. 스펙 브랜치를 rebase 하지 않는다.
- 스펙 브랜치 push 로 배포 — `release.yml` 은 `push: main` 만 듣는다.
- `spec/*` 의 ruleset 은 저장소 관리자 몫이다.
