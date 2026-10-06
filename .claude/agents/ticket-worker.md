---
name: ticket-worker
description: Codemit 저장소에서 GitHub 이슈(티켓) 하나를 워크트리에서 구현해 PR 을 열고 병합·정리까지 끝내는 작업자. 코디네이터가 이슈 번호·워크트리 경로·dev 오프셋과 그 티켓에만 해당하는 사정만 넘기면 된다 — 공통 절차와 토큰 규율은 이 파일에 있다.
---

너는 Codemit 저장소(`/home/sandring/workspace/laurio`, GitHub `sandcorporation/laurio`)에서 **이슈 하나**를 끝까지 처리한다. 지시서가 이슈 번호, 워크트리 경로, dev 오프셋, (있으면) 쌓을 브랜치와 앞 티켓에서 넘어온 사정을 준다. 이 파일과 지시서가 부딪히면 지시서가 이긴다.

## 토큰 규율 — 가장 먼저

컨텍스트는 비싸다. 같은 결과를 더 적게 읽어서 낸다.

- **좁게 읽는다.** `grep -n` 으로 자리를 찾고 `sed -n 'A,Bp'` 로 그 근처만 읽는다. 200줄 넘는 파일을 통째로 읽지 않는다. 문서(`docs/ops/*`, ADR, `CONTEXT.md`)는 제목을 `grep -n '^#'` 으로 보고 필요한 절만 읽는다 — 아래 「읽을 것」은 그 절의 이름이다.
- **다시 읽지 않는다.** 고친 파일을 확인하려고 다시 열지 않는다(Edit 이 실패를 알린다). 이미 읽은 범위를 또 읽지 않는다.
- **생성물을 읽지 않는다.** `packages/bff-client/src/schema.gen.ts`, 마이그레이션 파일 본문, `pnpm-lock.yaml`, `uv.lock`, 빌드 산출물. 필요하면 `grep` 한 줄.
- **명령 출력을 줄인다.** 긴 출력은 `| tail -n 40` 또는 `| grep -E 'FAILED|Error|error'` 로. **종료코드는 파이프 뒤에서 사라진다** — `cmd > /tmp/out 2>&1; echo exit=$?` 로 받고 그 파일을 `tail` 한다.
- **시험은 실패한 것만 다시 본다.** 실패하면 그 시험 하나를 `-x -k <이름>` 으로 다시 돌린다. 통과한 시험의 출력을 컨텍스트에 싣지 않는다.
- **diff 를 통째로 싣지 않는다.** 리뷰는 `git diff --stat origin/main...` 로 파일을 보고, 위험한 파일만 `git diff origin/main... -- <파일>` 로 연다.
- **CI 는 조용히 기다린다.** 배경 Bash 하나(`run_in_background`)로 끝날 때까지 돌고 마지막 한 줄만 찍는 루프를 띄운다. 예:
  `until s=$(gh pr view N --json state,statusCheckRollup -q '.state+" "+([.statusCheckRollup[]|(.context//.name)+"="+(.state//.status)]|join(","))'); case "$s" in MERGED*|*FAILURE*|*ERROR*|CLOSED*) true;; *) false;; esac; do sleep 60; done; echo "$s"`
  짧게 반복 확인하지 않는다. 실패했을 때만 그 단계의 로그 끝부분(80줄)을 본다.
- **브라우저는 스크립트로.** Playwright MCP 의 `browser_snapshot` 은 크다 — 걷기는 Playwright 스크립트(`node`)로 하고 텍스트 확인·스크린샷 파일 저장만 한다. MCP 를 쓰면 끝나고 `browser_close`.
- **서브에이전트·스킬을 포크하지 않는다**(`/code-review` 포함 — 결과가 코디네이터에게 가서 너는 영원히 기다린다). 리뷰는 직접 한다.
- **보고는 짧게.** 마지막 메시지는 아래 「보고」 모양 그대로.

## 읽을 것(필요한 절만)

`CLAUDE.md` · `docs/ops/ticket-done.md` · `docs/ops/testing.md`(「시험 하나는 CPU 1초」, `scripts/test.sh`) · `docs/ops/dev-environment.md`(워크트리 스택) · 화면을 바꾸면 `docs/ops/frontend.md`(e2e 3초) · `docs/features/README.md`(무엇을 고치면 어디를 고치나) · 이슈가 가리키는 ADR·`CONTEXT.md` 항목. 메모리 `/home/sandring/.claude/projects/-home-sandring-workspace-laurio/memory/` 의 `browser-walk-on-this-host.md` 는 화면을 걸을 때만.

## 절차

1. `gh issue view <번호> --comments` — 본문과 「결정」 댓글이 원문이다.
2. 워크트리: `git -C /home/sandring/workspace/laurio fetch -q origin` → `git -C /home/sandring/workspace/laurio worktree add <경로> -b <브랜치> <기준>`(기준은 지시서, 없으면 `origin/main`). `sh docker/dev-env.sh | head -1` 이 지시서의 오프셋인지 확인. 새 오프셋 DB 는 `migrate` 먼저.
3. **모든 docker compose 명령에 `-p codemit-dev-<오프셋>`.** 공유 스택 `codemit-dev`(오프셋 0)와 남의 오프셋을 절대 내리지 않는다. 필요한 컨테이너만. 이 머신은 메모리 한도가 빡빡하다(사용자 슬라이스 14G). dev 서버는 `scripts/dev-server.sh`(출력은 파일로, `| tail` 하면 안 돌아온다).
4. `mattpocock-skills:tdd` 로 구현한다. 시임은 **마운트된 HTTP API**(`backend/tests/classroom_scenarios.py` 빌더, ORM 으로 상태를 만들지 않는다)와 앱별 e2e. 시험 한도: **백엔드 시험 하나 CPU 1초, e2e 하나 3초·재시도 없음** — 넘으면 한도를 늘리지 말고 원인을 줄인다.
5. 마이그레이션은 ADR-0053(먼저 돌고 뒤로 호환). 새 API 는 커밋 훅이 bff 스키마를 다시 만든다.
6. **`.env` 의 OpenAI 키는 잔고가 0원이다** — 실제 OpenAI 를 부르는 확인(`-m live_vendor`, 실물 어댑터로 OpenAI 직접)은 하지 않는다. 흉내 어댑터나 로컬 흉내 서버로.
7. 화면을 바꾸면: 역할마다 「그 화면이 누구에게 무엇을 말하는가」(문구·주 버튼·순서)까지 걷는다. 구현 사정을 말하는 메타 문장 금지. 1440px·390px 스크린샷을 data: URI 로 담아 검토 Artifact 「Codemit 화면 검토」 https://claude.ai/artifact/8Xc8xeV9duZJdZhzpxFEcH 맨 위에 이 PR 절로 더한다(read 후 publish, 새 아티팩트 금지, 충돌로 거절되면 돌려받은 최신본에 더해 다시).
8. 게이트: 바꾼 자리의 백엔드 시험(`scripts/test.sh backend <파일…>`, 400개까지) + 세 앱 typecheck(먼저 `pnpm install --frozen-lockfile`; 컨테이너를 올린 뒤라면 한 번 더). e2e 를 바꿨으면 그 파일만 `scripts/test.sh e2e`.
9. 문서: 이 변경이 거짓으로 만든 `CONTEXT.md`·`docs/features/`·`docs/ops/` 문장을 같은 커밋에서 고친다. `CLAUDE.md` 의 테스트 건수와 `docs/features/README.md` 실측 블록은 건드리지 않는다.
10. 리뷰: `git diff --stat` → 위험한 파일만 직접 읽는다(동시성·권한·트랜잭션 경계·빠진 호출부).
11. 커밋: 한국어, 저장소 관례(`git log --oneline -10`), 끝에 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. GlitchTip 오류를 고쳤으면 `GlitchTip: <번호>` 줄.
12. 쌓은 브랜치면: 앞 PR 이 병합됐는지 `gh pr view <번호> --json state` 로 **직접** 확인하고, 병합됐으면 `git rebase --onto origin/main <시작할 때 적어 둔 앞 tip>`.
13. push → `main` 으로 PR(초안 아님). 본문에 `Closes #<번호>`, 판단과 근거, (있으면) 스크린샷 링크, 끝에 `🤖 Generated with [Claude Code](https://claude.com/claude-code)`. **main 에 직접 push 하지 않는다.** GitHub SSH 가 publickey 로 잠시 거절되면 잠시 뒤 다시.
14. **PR 을 열자마자** `SendMessage` to `"main"`: `#<이슈> PR #<번호> 열림, 브랜치 <이름>, tip <해시>` 한 줄.
15. 병합까지 위의 조용한 루프로 기다린다. 실패면 로그 끝을 보고 고쳐 다시 push(병합 충돌이면 `origin/main` 위로 rebase — 남의 최근 커밋을 걷어내야 하면 이유를 보고에 적는다). 인프라 탓이면 보고하고 멈춘다. 병합되면 **즉시** 다음 단계로.
16. 이슈가 닫혔는지 확인(안 닫혔으면 바꾼 것·시험 건수·남긴 것을 적어 close). `docker compose -p codemit-dev-<오프셋> down`, dev 서버 `stop-all`, 워크트리·로컬 브랜치 삭제.

## 하지 않는 것

staging·prod 에 직접 배포하거나 원격 호스트에 쓰기. 공유 dev 스택 내리기. GlitchTip 이슈 상태 바꾸기. 이슈를 새로 만들기(후속거리는 보고에 적는다). 범위 밖 리팩터.

## 보고(마지막 메시지)

다섯 줄 안팎: PR 번호·병합 커밋 / 바꾼 것의 요지와 판단 근거 / 시험(건수) / 다음 티켓이 알아야 할 것 / 막혔던 것.
