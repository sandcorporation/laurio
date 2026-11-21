# 제보 → 대장 메일함 (work 의 Orca 자동화)

운영에 들어온 건의·버그 제보(`feedback` 앱, #1238·#1239)를 work 의 Orca 자동화가 대장 메일함(switchboard
`sandcorp/boss`)으로 넘긴다(#1240). 메일에는 **번호·갈래·앱·받은 시각만** 싣는다 — 내용·스크린샷은 싣지 않고,
읽을 사람이 `scripts/feedback.sh show <번호>` 로 운영에서 직접 읽는다. 처리(이슈·작업자·상태 바꾸기)는 대장이
codemit 조율자에게 지시한다. daypage 건의함(`~/workspace/daypage/scripts/suggestions.sh`)과 같은 꼴이다.

## 구성

| 것 | 어디 |
| --- | --- |
| 스크립트 | `scripts/feedback.sh` — 운영 접근은 `ssh oracle` → compose 표지(`codemit-prod`·`backend`)로 찾은 backend 컨테이너의 `manage.py feedback_report` 하나 |
| 집음·전달 기록 | 운영 DB `FeedbackReport.taken_at`·`forwarded_at`(이 컴퓨터에 파일을 두지 않는다). 집고 15분 안에 전달 표시가 없으면 다시 나온다 |
| 받는 곳 | `CODEMIT_FEEDBACK_RELAY_TO`(기본 `sandcorp/boss`), 프로필 `CODEMIT_FEEDBACK_RELAY_PROFILE`(기본 `codemit-coordinator`), task `CODEMIT_FEEDBACK_RELAY_TASK`(기본 `codemit-feedback`) |
| 바꿔 끼우기 | `CODEMIT_FEEDBACK_SSH`·`CODEMIT_FEEDBACK_SSH_HOST`·`CODEMIT_FEEDBACK_COMPOSE_PROJECT`·`CODEMIT_SWITCHBOARD` — 시험(`scripts/test_feedback_relay.py`)이 가짜를 꽂는다 |
| Orca 자동화 | work, 이름 「제보 전달」, 매분, precheck = `scripts/feedback.sh check`, workspace = `~/workspace/codemit` main 체크아웃 |

## 흐름

1. precheck `check` — 넘길 제보가 없으면 1, 운영에 못 닿으면 2 로 끝나 에이전트가 뜨지 않는다.
2. 있으면 워커가 `take` 로 집고(JSON 한 줄씩), 제보마다 `forward <번호>`.
3. `forward` 는 switchboard 가 0 으로 끝나고 `#번호` 줄을 찍어야 보낸 것으로 보고 `mark-forwarded` 한다.
   아니면 `untake` 로 되돌리고 0 이 아닌 코드로 끝난다 — 다음 check 에서 다시 잡힌다.
4. 워커가 집고 나서 죽으면 15분 뒤 서버가 다시 내놓는다. 전달 표시가 된 제보는 다시 나오지 않는다.

제목은 `[제보] codemit #<번호> <건의|버그> · <공모전|강의실>`, 본문 둘째 줄은 `scripts/feedback.sh show <번호>`.

## 손보기

```
scripts/feedback.sh list                         # 넘길 제보 보기(기록 안 바꿈)
scripts/feedback.sh show 12                      # 내용·상태·이력(스크린샷은 있는지만)
scripts/feedback.sh mark 3 4                     # 보내지 않고 전달 표시(처음 켤 때 지난 제보 거르기)
scripts/feedback.sh untake 12                    # 집음을 지워 다음 실행에서 다시 보내기
scripts/feedback.sh status 12 deployed "PR #1300 으로 고쳤습니다"   # 제보자에게 앱 안 알림이 간다

orca-ide automations create --name "제보 전달" --trigger "* * * * *" \
  --precheck "scripts/feedback.sh check" --workspace path:$HOME/workspace/codemit --workspace-mode existing \
  --provider claude --prompt "scripts/feedback.sh take 로 제보를 집고, 줄마다 scripts/feedback.sh forward <id> 를 실행한다. 코드를 고치지 않는다." --json
orca-ide automations list --json                 # id 찾기
orca-ide automations edit <id> --disabled --json # 잠시 끄기
```

운영 DB 에 쓰는 것은 집음·전달 표시와 `status` 뿐이다. `status` 는 운영자 화면과 같은 서비스 함수라 이력에
「대장(명령)」으로 남는다.
