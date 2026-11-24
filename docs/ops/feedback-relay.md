# 제보 전달 — 앱 전송 길과 손보기

운영에 들어온 건의·버그 제보(`feedback` 앱, #1238·#1239)는 접수되면 앱이 알림 목적지로 번호·종류·앱만 보낸다(아래 「앱 전송 길」, #1366).
매분 work 의 Orca 자동화가 대장 메일함(switchboard `sandcorp/boss`)으로 넘기던 길(#1240)은 꺼졌고, 아래 「구성」·「흐름」·「실패는 드러난다」는
예전 길이자 손으로 쓸 때의 설명이다. 내용·스크린샷은 알림에 싣지 않고, 읽을 사람이 `scripts/feedback.sh show <번호>` 로 운영에서 직접 읽는다.
스크린샷은 `scripts/feedback.sh screenshot <번호>` 로 work 의 임시 파일에 받아 연다(아래 「스크린샷」). daypage 건의함
(`~/workspace/daypage/scripts/suggestions.sh`)과 같은 꼴이다.

## 상태는 처리에 맞춰 바로 바꾼다

처리하는 쪽이 제보를 만지는 순간 `scripts/feedback.sh status <번호> <상태> "처리 글"` 로 상태를 바꾼다. 나중에 몰아서 바꾸지 않는다.

- 집어서 처리를 시작하면 `in_progress`.
- 고쳐서 배포까지 끝나면 `deployed`.
- 하지 않기로 하면 `declined`.
- 시험 제보는 수신을 확인하면 바로 `declined` 로 닫는다 — 접수·작업 중으로 남기지 않는다.

`status` 는 운영자 화면과 같은 서비스 함수라 이력에 「대장(명령)」으로 남고, **제보자에게 앱 안 알림이 간다**.

## 구성

| 것 | 어디 |
| --- | --- |
| 스크립트 | `scripts/feedback.sh` — 운영 접근은 `ssh oracle` → compose 표지(`codemit-prod`·`backend`)로 찾은 backend 컨테이너의 `manage.py feedback_report` 하나 |
| 집음·전달 기록 | 운영 DB `FeedbackReport.taken_at`·`forwarded_at`(이 컴퓨터에 파일을 두지 않는다). 집고 15분 안에 전달 표시가 없으면 다시 나온다 |
| 받는 곳 | `CODEMIT_FEEDBACK_RELAY_TO`(기본 `sandcorp/boss`), 프로필 `CODEMIT_FEEDBACK_RELAY_PROFILE`(기본 `codemit-coordinator`), task `CODEMIT_FEEDBACK_RELAY_TASK`(기본 `codemit-feedback`) |
| 바꿔 끼우기 | `CODEMIT_FEEDBACK_SSH`·`CODEMIT_FEEDBACK_SSH_HOST`·`CODEMIT_FEEDBACK_COMPOSE_PROJECT`·`CODEMIT_SWITCHBOARD` — 시험(`scripts/test_feedback_relay.py`)이 가짜를 꽂는다 |
| 진입 | `scripts/automation-run.sh` — 체크아웃을 `origin/main` 으로 따라잡고 본 명령을 부르며, 정상 코드가 아닌 실패를 대장 메일함에 드러낸다(아래 「실패는 드러난다」). 상태는 `~/.cache/codemit-automation/<이름>.state` |
| Orca 자동화 | work, 이름 「제보 전달」, 매분, precheck = `scripts/automation-run.sh feedback-relay -- scripts/feedback.sh check`, workspace = `~/workspace/codemit` main 체크아웃 |

## 흐름

1. precheck `automation-run.sh` 가 먼저 체크아웃을 따라잡고(아래) `check` 를 부른다 — 넘길 제보가 없으면 1, 있으면 0 이다.
   운영에 못 닿으면 2, backend 를 못 찾으면 3 으로 끝나 에이전트가 뜨지 않지만 **대장에게 메일이 간다**.
2. 있으면 워커가 `take` 로 집고(JSON 한 줄씩), 제보마다 `forward <번호>`.
3. `forward` 는 switchboard 가 0 으로 끝나고 `#번호` 줄을 찍어야 보낸 것으로 보고 `mark-forwarded` 한다.
   아니면 `untake` 로 되돌리고 0 이 아닌 코드로 끝난다 — 다음 check 에서 다시 잡힌다.
4. 워커가 집고 나서 죽으면 15분 뒤 서버가 다시 내놓는다. 전달 표시가 된 제보는 다시 나오지 않는다.

## 앱 전송 길 (#1366)

`FEEDBACK_NOTICE_WEBHOOK_URL` 이 있으면 앱이 접수가 커밋된 뒤(`transaction.on_commit`) 알림 목적지로 한 건 보낸다.
비어 있으면 아무것도 하지 않는다 — 전달 표시도 찍지 않는다. 자동화는 꺼졌으니 못 넘긴 제보는 `check`·`list` 에 남고, 보면 운영 쪽에 알린다.

- 본문은 `{"content": "📮 [Codemit] 새 제보 #123 · 버그 · classroom"}` 한 줄이다. 번호·종류·앱 갈래만 들어가고
  제보 본문·스크린샷·제보자·페이지 주소는 넣지 않는다.
- 접수 커밋 뒤 celery 작업(`feedback.send_feedback_notice`)을 큐에 넣고 worker 가 운영 경보와 같은 소켓 한도(5초)로
  보낸다 — 받는 곳이 느려도 접수 응답은 늦지 않는다. 재시도는 없고, 실패(큐에 못 넣음 포함)는 삼키며 로그에는 예외 종류만 남긴다.
- 보내기에 성공하면 그 제보에 전달 표시(`forwarded_at`)를 찍는다 — 자동화가 켜져 있어도 같은 제보가 두 번 넘어가지 않는다.
  실패한 제보는 `check`·`list` 에 남아 손으로 넘길 수 있다.
- 설정을 읽는 프로세스는 celery worker 다(dev 는 작업이 eager 라 `backend` 도 읽는다). 값을 넣은 뒤 `celery-worker` 컨테이너를 다시 띄운다.

## 실패는 드러난다 (#1252)

Orca 는 precheck 가 0 이 아니면 무엇이든 `skipped_precheck` 로 넘기므로 「제보 없음(1)」과 고장이 같게 보인다.
그래서 precheck 를 `scripts/automation-run.sh <이름> [--ok 0,1] -- <명령>` 으로 감싼다.

- **따라잡기**: `git fetch` 뒤 체크아웃이 `main` 에 있고, 추적 파일이 깨끗하고, `origin/main` 보다 앞서 있지 않을 때만
  `merge --ff-only`. 아니면(더럽다·앞서 있다·갈라졌다·다른 브랜치·fetch 실패) **건드리지 않고** 알린다 — 이
  체크아웃에서 다른 세션이 main 에 커밋하기도 해서 그 커밋을 버리면 안 된다. 따라잡기에 실패하면 본 명령을 돌리지
  않고 70 으로 끝난다(묵은 코드로 도는 것이 조용한 고장이다). 에이전트(`take`·`forward`)는 같은 체크아웃에서 precheck 직후
  돌므로 같은 최신 코드를 본다.
- **잠금(#1280)**: 같은 저장소를 자동화 여럿이 매분 같은 순간에 따라잡고 조율자·작업자도 fetch 해서, origin/main 이 움직인
  첫 분에 `incorrect old value provided` 로 지는 쪽이 났다. 따라잡기 전체(fetch + ff-only)가 `<git-common-dir>/codemit-fetch.lock`
  (`flock`) 안에서 돈다. `CODEMIT_AUTOMATION_LOCK_WAIT`(기본 60초) 안에 못 잡으면 재시도 없이 「잠금 대기 초과」로 실패한다.
  조율자·작업자의 사실 확인 fetch 는 `scripts/git-fetch-locked.sh -q origin main` 으로 같은 잠금을 쓴다.
- **원격 실패 까닭(#1280)**: `feedback.sh` 가 운영 호출에 실패하면 진짜 종료 코드와 까닭(`원격 실패 rc=143: 시그널(15)로 종료됐다(배포 중 컨테이너
  교체로 보인다)`)을 표준오류에 남긴다. `check` 의 종료 코드는 그대로 2 이고, 다시 시도하지 않는다. 알림의 표준오류 끝에 이 줄이 실린다.
- **알림**: `--ok` 밖의 종료 코드(기본 0·1 밖: 127·2·3…)와 따라잡기 실패는 `sandcorp/boss` 로 한 통. 같은 원인은
  처음 한 번, 이어지면 1시간마다 한 번(`CODEMIT_AUTOMATION_REPEAT_SECS`), 정상으로 돌아오면 「회복」 한 통. 메일은
  `feedback.sh forward` 와 같은 프로필·task 환경변수를 쓴다. 메일을 못 보냈으면 상태를 남기지 않아 다음 분에 다시 시도한다.
- 이 스크립트가 아직 없는 묵은 체크아웃(127)은 **한 번 손으로** `git pull --ff-only` 해야 시작된다. 그 뒤로는 스스로 따라간다.
- 시험: `python3 scripts/test_automation_run.py`(진짜 git·가짜 switchboard, PR 검사가 돈다).

같은 꼴로 「CI 빨강 전달」 자동화가 핫픽스 길의 ci-red 이슈를 넘긴다 — [배포 길 셋](deploy-paths.md).

제목은 `[제보] codemit #<번호> <건의|버그> · <공모전|강의실>`, 본문 둘째 줄은 `scripts/feedback.sh show <번호>`.

## 스크린샷 (#1347)

`scripts/feedback.sh screenshot <번호>` 가 운영 backend 의 `manage.py feedback_report screenshot <번호>` 를 ssh 로 불러
그림 바이트를 표준출력으로 받고, 이 컴퓨터의 임시 폴더에 파일로 쓴 뒤 **경로 한 줄만** 찍는다.

- **받는 길**: 바이트를 ssh 로 받는다. 서명 주소(`request_download_url`)를 만들지 않는다 — 주소가 출력·로그에 남을 일이
  없고, work 가 저장소 끝점에 닿을 필요도 없이 이미 쓰는 ssh 한 길로 끝난다. 운영에서는 읽기만 한다.
- **어디**: `${TMPDIR:-/tmp}/codemit-feedback-shots-<uid>/report-<번호>.<png|jpg|webp>` — 저장소 밖, 폴더 700·파일 600.
  폴더가 링크이거나 남의 것이면 쓰지 않는다. 바꿔 끼우기는 `CODEMIT_FEEDBACK_SHOT_DIR`.
- **지우기**: 일이 끝나면 `scripts/feedback.sh screenshot-rm <번호>`(번호 없이 부르면 전부). 잊어도 받은 지 24시간
  (`CODEMIT_FEEDBACK_SHOT_TTL_MIN`, 분)이 지난 파일은 다음 `screenshot` 이 지운다.
- **실패**: 제보 없음 4 · 스크린샷 없음 5 · 저장소에 그림 없음(보존 기간이 지나 지워짐 등) 6 · 운영에 못 닿음 2. 표준오류에
  `원격 실패 rc=…: <까닭>` 한 줄이 남고 파일은 남지 않는다.

**다루는 법**

- 그림은 저장소·이슈·PR·메일·보고에 올리지 않는다. 일이 끝나면 지운다.
- 스크린샷에는 학생 이름·제출 화면이 찍힐 수 있다. 본 것을 글로 옮길 때도 학생·강사·클래스 이름은 적지 않는다.
- 시험에는 진짜 운영 그림을 쓰지 않는다. 만든 가짜 바이트를 쓴다(`scripts/test_feedback_relay.py`·
  `backend/feedback/tests/test_operator_reports.py`).

## 손보기

```
scripts/feedback.sh list                         # 넘길 제보 보기(기록 안 바꿈)
scripts/feedback.sh show 12                      # 내용·상태·이력(스크린샷은 있는지만)
scripts/feedback.sh screenshot 12                # 그림을 임시 파일로 받고 경로를 찍는다
scripts/feedback.sh screenshot-rm 12             # 받은 그림 지우기(번호 없으면 전부)
scripts/feedback.sh mark 3 4                     # 보내지 않고 전달 표시(처음 켤 때 지난 제보 거르기)
scripts/feedback.sh untake 12                    # 집음을 지워 다음 실행에서 다시 보내기
scripts/feedback.sh status 12 deployed "PR #1300 으로 고쳤습니다"   # 제보자에게 앱 안 알림이 간다

orca-ide automations create --name "제보 전달" --trigger "* * * * *" \
  --precheck "scripts/automation-run.sh feedback-relay -- scripts/feedback.sh check" \
  --workspace path:$HOME/workspace/codemit --workspace-mode existing \
  --provider claude --prompt "scripts/feedback.sh take 로 제보를 집고, 줄마다 scripts/feedback.sh forward <id> 를 실행한다. 코드를 고치지 않는다." --json
# `--repo path:…` 는 orca 가 「Selected workspace belongs to a different repo」 로 거절한다 — `--workspace` 를 쓴다.
orca-ide automations list --json                 # id 찾기
orca-ide automations edit <id> --disabled --json # 잠시 끄기
```

운영 DB 에 쓰는 것은 집음·전달 표시와 `status` 뿐이다. `status` 는 운영자 화면과 같은 서비스 함수라 이력에
「대장(명령)」으로 남는다.
