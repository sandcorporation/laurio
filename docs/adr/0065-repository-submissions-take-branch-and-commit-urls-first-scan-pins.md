# 저장소 제출이 브랜치·커밋 URL 을 받고, 브랜치는 제출 때가 아니라 첫 스캔이 커밋을 고정한다

Status: Accepted (2026-10-21 결정)

## 맥락 (#777)

저장소 제출은 `https://github.com/<owner>/<repo>` 한 모양만 받았고, 채점은 늘 **스캔 시점 기본
브랜치의 최신 커밋**을 봤다(ADR-0027). 참여자가 작업 브랜치나 특정 커밋을 낼 길이 없었다 —
`/tree/<branch>`·`/commit/<sha>` 를 붙여 넣으면 422 였다.

브랜치를 받는 순간 질문이 하나 생긴다: **채점이 보는 커밋은 언제 정해지는가.** 제출 때 GitHub 에
물어 그 순간의 HEAD 를 박는 것이 가장 직관적이지만, 제출 API 는 GitHub 을 부르지 않는다는
결정(ADR-0027 — 마감 직전에 몰리는 제출이 남의 서비스 상태에 인질로 잡히면 안 된다)이 이미 있다.
반대로 끝까지 고정하지 않고 채점 때 HEAD 를 보면 재채점·이의 심판이 「무엇을 채점했는가」를 한
커밋으로 말할 수 없다.

## 결정

- **받는 모양은 셋**이다 — 저장소 · `…/tree/<ref>` · `…/commit/<sha>`(7~40자 16진수). `/tree/`
  뒤는 **나머지 전체**가 브랜치 이름이다(`release/2024` 처럼 슬래시 포함) — 디렉터리 경로와
  구분하지 않고 GitHub 에 묻는다. 그 밖(`/blob/`·`/pull/`·ref 없는 `/tree/`)은 지금처럼 422.
  서버(`submissions.models.parse_github_submission_url`)와 화면(`@codemit/bff-client/repository-url`)이
  같은 규칙이다.
- **저장은 저장소 URL 그대로 + ref·고정 SHA 두 컬럼.** `SubmissionAsset.value` 는 저장소 URL 로
  남는다 — 공개 여부 확인·중복 제약·기존 행이 그 키를 쓴다. `repository_ref`(브랜치 이름)와
  `repository_commit_sha`(고정 커밋)가 나머지를 들고, 낸 URL 은 그 둘로 되살린다(`submitted_url`).
- **브랜치는 처음 성공한 스캔이 고정한다.** 제출 때는 GitHub 을 부르지 않는다(ADR-0027 그대로).
  매시간 도는 공개 여부 확인(`repository-visibility`)이 ref 도 같이 보고, 처음 찾은 순간 그 HEAD 의
  SHA 를 자산에 박는다(`submissions.repository_pins`, 조건부 UPDATE — 스캔과 채점이 겹쳐도 하나만
  남는다). 강의실에는 그 스캔이 없어 **첫 채점**이 같은 길로 박는다. 그 뒤 모든 채점·재채점은
  박힌 SHA 만 본다 — push 해도 바뀌지 않는다. 짧은 커밋 SHA 는 같은 길로 40자로 확정된다.
- **저장소 URL 제출은 고정하지 않는다.** 스캔 시점 기본 브랜치 최신을 보는 지금 규칙 그대로다 —
  기존 공모전 흐름을 바꾸지 않는다. 고정을 원하면 브랜치·커밋으로 내면 된다.
- **ref 를 못 찾으면 비공개와 같은 줄의 새 상태다.** `repository_ref_found=False` — 제출 화면 배지
  「브랜치를 찾을 수 없음 — 채점에 반영되지 않습니다」(커밋이면 「커밋을 찾을 수 없음」). 마감 전에
  고치면 다음 확인이 다시 본다. 마감에도 없으면 비공개 저장소의 0% 판정(ADR-0030)과 같은 줄에
  「낸 브랜치·커밋을 찾을 수 없었다」를 적는다. **기본 브랜치로 대신 채점하지 않는다** — 참가자가
  낸 것이 아닌 코드를 채점하면 그 점수가 누구 것인지 말할 수 없다.

## 왜 제출 때가 아니라 첫 스캔인가

제출을 가볍게 두는 쪽을 택했다. 제출 때 GitHub 을 부르면 오타를 그 자리에서 알려 줄 수 있지만,
그 대가는 ADR-0027 이 이미 거절한 것(제출이 GitHub 가용성에 묶인다)이다. 오타는 배지가 한 시간
안에 말해 주고 마감 전에 고칠 수 있다 — 같은 스캔이 비공개 저장소에 대해 이미 하는 일이다.
「무엇을 채점했는가」는 고정 커밋이 한 값으로 답하므로 이의 심판·재채점이 흔들리지 않는다.

## 결과

- `SubmissionAsset` 에 `repository_ref`·`repository_commit_sha`·`repository_ref_found` 가 생겼다
  (`submissions/migrations/0004`, 셋 다 기본값이 있어 먼저 돌아도 뒤로 호환된다, ADR-0053).
- `GitHubAdapter` 에 `resolve_ref(url, ref)` 가 생기고 `clone` 이 `commit_sha` 를 받는다 —
  `/repos/{o}/{r}/commits/{ref}` 하나가 브랜치·태그·짧은 SHA 를 모두 풀고, 404·422 는
  `GitHubRefNotFoundError` 다(네트워크 순단·5xx 와 구별한다, ADR-0003).
- API 응답의 `value` 는 **낸 URL 그대로**이고 고정 SHA 는 `commit_sha` 로 따로 간다 — 공모전 제출,
  강의실 내 시도·강사 목록, MCP `open_submission_source`(`repository_url`·`commit_sha`) 모두.
- GitLab·Bitbucket(ADR-0027)과 제출 때 GitHub 조회는 여전히 범위 밖이다.
