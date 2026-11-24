# 배포 길 셋 — 핫픽스 · 스펙 · 낱개 이슈

`CLAUDE.md` 의 부록이다. 대표 결정(2026-11-22, #1325). main 에 오르는 길은 셋이고, 셋 모두 main push → `release.yml`
(이미지 → `production` 승격) → Jenkins 배포로 끝난다. 갈리는 것은 **검사가 언제 도는가**다.

| | 핫픽스 | 스펙 | 낱개 이슈 |
| --- | --- | --- | --- |
| 대상 | 운영에서 사용자가 지금 피해를 보는 장애 | 한 목표에 티켓이 둘 이상인 일 | 그 밖(독립 고침 한 건) |
| 정하는 사람 | 대장 — 지시서에 「핫픽스 길」이라 적는다. 조율자가 스스로 고르지 않는다 | 조율자 | 기본 |
| 명령 | `python3 scripts/hotfix.py push --issue <N>` | `scripts/spec/spec.py` — [스펙 브랜치](spec-branch.md) | PR → `bash scripts/ci/enqueue.sh <N>` — [티켓을 닫는 기준](ticket-done.md) |
| 검사 | **배포와 나란히 뒤따라** — `after-push.yml` 이 PR 검사(`pr-check.yml`)를 부른다 | 스펙 PR 하나에서 한 번, 병합 대기열에서 한 번 | PR 에서, 병합 대기열에서 한 번 |
| 검사가 실패하면 | 운영은 그대로. ci-red 이슈 → 대장 메일함. 고치는 커밋을 같은 길로 다시 | 병합되지 않는다 | 병합되지 않는다 |

## 핫픽스 길

```
python3 scripts/hotfix.py push --issue 1316 --dry-run   # 표식·따라잡기까지, push 는 dry-run
python3 scripts/hotfix.py push --issue 1316             # main 에 올리고 release·뒤따른 검사 run·배포 상태를 보인다
python3 scripts/hotfix.py runs <sha>                    # 나중에 다시 보기
```

- 워크트리는 `origin/main` 에서 따고 고침을 **커밋 하나**로 만든다. 고친 곳의 시험·타입·린트는 로컬에서 돌린다(검사를 뒤로 미룰 뿐 건너뛰지 않는다).
- `push` 는 깨끗한지·커밋 하나인지 보고, `Hotfix: #<N>` 꼬리말을 달고(amend), main 이 앞서 있으면 그 위로 rebase 해
  `git push origin HEAD:main` 한다. 충돌이면 되돌리고 거절한다. force push 는 없다.
- 배포는 낱개 이슈 길과 같다 — `release.yml` 은 main push 만 듣고(`main_only` 는 ref 만 본다) 대기열을 따지지 않으며, `promote.sh ff` 의
  전제는 「`production` 이 이 sha 의 조상」뿐이다. 핫픽스 커밋은 main 머리 위 보통 커밋이라 그대로 승격된다.
- 되돌림은 대장이 정한다. 자동 되돌림은 없다 — [배포](deploy.md) 「되돌리기」.

## 뒤따르는 검사 — `.github/workflows/after-push.yml`

main push 마다 `kind` 잡이 push 를 가른다(`scripts/ci/push_kind.py`).

- **대기열 커밋** — 그 sha 로 `merge_group` 실행이 있었다(대기열은 검사한 머지 커밋으로 main 을 옮기므로 push 머리 = 검사한 sha).
  PR 검사를 다시 돌리지 않는다(#1090). 열린 「핫픽스 뒤 검사 실패」 이슈가 있으면 닫는다 — main 이 다시 초록으로 검사됐다.
- **핫픽스** — 올라온 커밋이 모두 `Hotfix:` 꼬리말을 달았다. `pr-check.yml` 을 workflow_call 로 부른다 — 대기열과 같은 묶음(pytest 전부·
  amd64 부팅 가드, e2e 는 매시 `e2e.yml`).
- **표식 없는 직접 push** — 그 밖. 검사는 핫픽스와 똑같이 돌고, 곧바로 「표식 없는 main 직접 push — <sha>」 ci-red 이슈를 연다(커밋마다 하나).
  우회 권한은 그 계정을 쓰는 모든 세션에 열리므로 핫픽스 길이 아닌 push 가 조용히 지나가지 않게 한다. 읽은 대장이 닫는다.
  대기열 실행 조회가 실패해도 이쪽으로 본다.

검사 결과는 `notify` 잡이 「핫픽스 뒤 검사 실패 — main 붉음」 ci-red 이슈 하나로 낸다(`scripts/ci/after-push-notify.sh`) —
실패면 열고, 이어지는 실패는 댓글, 초록이면 「복구됨」 댓글로 닫는다. 실패한 잡·sha·run 링크가 본문에 있다.

## 운영 담당 Orca 메일로 — work Orca 자동화 「CI 빨강 전달」

GitHub 에서 Orca 메일로 바로 쏘는 길은 없어, work 의 Orca 자동화가 위 두 종류의 ci-red 이슈를 운영 담당 Orca 메일로
넘긴다(`scripts/ci/ci_red_relay.py` → `scripts/notify-ops.sh`, 제목 `[codemit] ci-red …`). [제보 전달](feedback-relay.md)과 같은 꼴이고 같은 `automation-run.sh` 로 감싼다.

- 열린 이슈를 처음 보면 한 통 — 번호·종류·sha·run 링크만. 이어지는 실패(댓글)는 다시 보내지 않는다. 보낸 이슈가 닫히면 「복구·닫힘」 한 통.
- 기록은 `~/.cache/codemit-automation/ci-red-relay.json`(처음 켤 때 `mark` 가 만든다). 처음 보는 닫힌 이슈는 보내지 않는다.
  기록이 없거나 깨졌으면 아무것도 보내지 않고 기록만 다시 만든 뒤 3 으로 끝난다 — 열린 이슈를 한꺼번에 다시 보내지 않고, 건너뛴 번호는 한 통으로 드러난다.
- 보낼 것을 precheck 가 직접 보내고 늘 1 로 끝난다 — 에이전트를 띄우지 않는다. gh 조회 실패(2)·메일 실패(3)는 `automation-run.sh` 가
  운영 담당 메일로 드러내고, 못 보낸 이슈는 다음 분에 다시 보낸다.
- 받는 곳은 [제보 전달](feedback-relay.md)의 「받는 곳」과 같다(저장소에 적지 않는다). 상태 파일 `CODEMIT_CI_RED_RELAY_STATE`, `orca` 경로 `CODEMIT_ORCA`.

```
orca-ide automations create --name "CI 빨강 전달" --trigger "* * * * *" \
  --precheck "scripts/automation-run.sh ci-red-relay -- python3 scripts/ci/ci_red_relay.py relay" \
  --workspace path:$HOME/workspace/codemit --workspace-mode existing \
  --provider claude --prompt "할 일 없음. 코드를 고치지 않는다." --json
python3 scripts/ci/ci_red_relay.py mark     # 처음 켤 때 — 지금 열린 이슈를 보내지 않고 기록만
```

## 대표 몫 — 열림(2026-11-23, 대표·대장) — 지금 규칙 두 묶음

main 보호 규칙을 둘로 나눠 핫픽스 길을 열었다(대장 #5811). 우회가 ruleset 하나에 통째로 걸려(강제 push 금지도 같이 풀린다)
나눴다(#1325 PR 본문 「대표 몫」).

1. ruleset 27845997 「main: 강제 push·삭제 금지」 — 대상 기본 브랜치, 규칙 `deletion`·`non_fast_forward`, **우회 없음**.
2. ruleset 26845555 「main: PR 검사 통과 필수」 — `required_status_checks`(「결과」)·`merge_queue`, 우회 Repository role
   **Admin** 방식 **always** — 세션들이 쓰는 계정이 저장소 admin 이라 main 직접 push 가 막히지 않는다. `spec branches`
   ruleset(27792646)의 우회와 같은 꼴.

막히지 않는다고 길이 열린 것은 아니다 — 핫픽스 길은 대장 지시서로만 쓴다. 그 밖의 main 직접 push 는 [티켓을 닫는 기준](ticket-done.md)대로
하지 않는다. 직접 push 도 pre-push 훅(「로컬 고르기 기록」, [커밋 훅](commit-hooks.md))을 지난다. `hotfix.py` 가 ruleset 거절을 「대표 몫」으로
알리는 길은 규칙이 다시 막혔을 때를 위해 남아 있다.

## 시험

`python3 scripts/test_hotfix_flow.py` — 분류(실제 git), 알림 → ci-red → 전달(가짜 gh·orca), `hotfix.py`(맨 원격 + 클론, ruleset
거절은 pre-receive 훅으로 흉내). 워크플로 배선은 `scripts/test_release_flow.py`, 권한은 `scripts/test_public_repo.py`. PR 검사의 plan 잡이 셋을 돈다.
