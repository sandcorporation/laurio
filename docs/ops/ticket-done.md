# 티켓을 닫는 기준

`CLAUDE.md` 의 부록이다 — 거기서 앵커로 가리키고, 같은 「지금」을 말한다.

로컬 게이트는 셋이다 — **바꾼 자리의 백엔드 시험**(`scripts/test.sh backend <파일…>`,
400개까지), **세 앱 `typecheck`**, **에이전트가 브라우저로 걸어본 결과**. **전체 시험은
브랜치 PR 의 CI 로 본다**(2026-10-02) — 브랜치를 push 하고 `main` 으로 PR 을 연다. GitHub
Actions `PR 검사`(`pr-check.yml`)가 검사 묶음과 amd64 이미지 부팅 가드·e2e·celery 를 돈다(Jenkins PR 검사는 2026-11-09 에 꺼졌다, #932 — 「CI」 문서).
**GitHub Actions `PR 검사` 의 「결과」 잡(`gh pr checks <PR>`·`gh run watch`)이 초록이면(2026-11-09 #930 — Jenkins PR 검사는 기다리지 않는다) 작업자가 `gh pr merge <PR> --squash` 로
병합한다**(2026-11-05 #873 — 그 전에는 열차 `codemit/ci-train` 이 rebase 병합했다). **병합 하나가 곧 승격 하나·prod 배포
하나다**(2026-11-09 #938, ADR-0077): 병합하면 Actions `release.yml` 이 검사·이미지(병렬) → `production` 승격을 돌고(`gh run list
--workflow release.yml`), `production` push 가 Jenkins 배포 잡(`codemit/deploy`)을 깨운다. 그다음
`python3 ~/.claude/skills/issue-track/scripts/wait-deploy.py --job codemit/deploy --pr <PR>` 로 배포 잡의 GitHub 상태
`sandcorp/deploy` 를 끝까지 기다려 결과를 보고한다(문서만이면 교체 없이 초록 — release 가 몇 분 걸리니 그만큼 늦게 시작한다).
`main` 에 직접 push 하지 않는다(PR 검사 없이 release 가 돈다). PR 검사의 실패 줄은 Actions 실행 로그
(`gh run view <id> --log-failed`)에서 본다.

**push 를 빠뜨리면 CI 는 아무것도 보지 않는다.** 실제로 그런 적이 있다 — 하루 작업 20커밋이
푸시되지 않은 채 쌓였고, 그 사이 CI 잡 하나가 21시간 빨간 것도 아무도 몰랐다. e2e 를 CI 에
맡기는 이상 push 와 결과 확인이 그 규율의 절반이다.

**그리고 이 티켓이 `CLAUDE.md`(`docs/ops/` 포함)·`CONTEXT.md`·`docs/features/` 의 어떤 문장을 거짓으로
만들었는지 확인하고, 만들었으면 같은 커밋에서 고친다.** 그 셋만 「지금」을 말하기로
했으므로(아래 「어느 문서가 「지금」을 말하는가」) 그것이 낡으면 대신 참을 말해 줄 문서가
없다. 이 파일은 이미 한 번 거짓말한 적이 있다 — 「tick 을 쏘면 21일 시나리오를 몇 초에
재현할 수 있다」가 그랬고, 한참 뒤에야 커밋 하나로 고쳐졌다.

**셋의 분업이 있다.** `CLAUDE.md` 는 저장소를 어떻게 굴리는가, `CONTEXT.md` 는 낱말이 무슨
뜻인가, `docs/features/` 는 **서비스가 무엇을 하는가**다. 같은 사실을 두 곳에 적지 않는다 —
적으면 갈라지고, 갈라진 쪽을 읽은 사람이 틀린다. 무엇이 바뀌면 `docs/features/` 의 어디를
고쳐야 하는지는 그 디렉터리의 `README.md` 가 표로 들고 있고, 세는 일을 손으로 하지 않도록
명령도 함께 적혀 있다.

가장 잘 썩는 것은 **수치와 목록**이다 — 포트 표, 어댑터 목록, 채점 예산, 실측 시간, 테스트
건수, 그리고 `docs/features/` 의 엔드포인트·스캔·화면 목록. 그것을 바꾸는 티켓이면 그 표를
같이 고친다.

## 워크트리에서 티켓을 처리하는 작업자가 지킬 것

작업자는 전역 에이전트 `issue-worker` 다.
일반 절차는 그쪽이 들고 있고, 이 저장소에만 해당하는 것은 여기 있다.

- **워크트리와 포트.** `git worktree add ../codemit-<이름> -b <브랜치> origin/main` 으로 만들고,
  `sh docker/dev-env.sh | head -1` 이 지시서가 준 오프셋과 같은지 본다. 새 오프셋의 DB 는 `migrate` 부터.
- **compose 는 언제나 `-p codemit-dev-<오프셋>`, 필요한 컨테이너만.** 공유 스택 `codemit-dev`(오프셋 0)와 남의
  오프셋은 내리지 않는다. 사용자 슬라이스 메모리 한도가 빠듯하니 호스트 `next dev` 는 `scripts/dev-server.sh` 로만
  띄우고(출력은 파일로, `| tail` 하면 안 돌아온다) 끝나면 `stop-all` 한다.
- **`.env` 의 OpenAI 키는 잔고가 0원이다.** `live_vendor` 시험과 실제 OpenAI 를 부르는 확인은 하지 않는다 — 흉내
  어댑터나 로컬 흉내 서버로 한다. 풀러·Redis·OpenSearch 실물 시험(`live_infra`)은 dev 프로필을 띄워 돌려도 된다.
- **시임은 마운트된 HTTP API** (`backend/tests/classroom_scenarios.py` 빌더 — ORM 으로 상태를 만들지 않는다)와 앱별
  e2e 다. 시험 한도는 `testing.md`(CPU 1초)·`frontend.md`(e2e 3초) — 넘으면 한도를 늘리지 말고 원인을 줄인다.
- **화면을 바꾸면** 1440px·390px 스크린샷을 검토 Artifact 「Codemit 화면 검토」
  (https://claude.ai/artifact/8Xc8xeV9duZJdZhzpxFEcH) 맨 위에 그 PR 절로 더한다(read 후 publish, 새 아티팩트를
  만들지 않는다).
- **병합 = 승격 = prod 배포다**(ADR-0068·ADR-0077). release 가 빨가면 production 이 움직이지 않는다 — 그 실행의 실패 줄을 보고 고친다. 문서만 바뀐 병합은 `codemit/deploy` 가 교체 없이 표식만 옮긴다. 배포가 돌았다면 prod
  `/api/health` 200 과 콘솔의 「디스코드 알림 실패」 0건을 확인한다(읽기만 — Jenkins 자격증명은 셸 env 의
  `JENKINS_URL`·`JENKINS_USER`·`JENKINS_API_TOKEN`, 값은 출력하지 않는다).
- **끝나면** 이슈가 닫혔는지 보고, 띄운 `-p codemit-dev-<오프셋>` 스택을 내리고 dev 서버를 멈춘 뒤 워크트리·로컬
  브랜치·원격 브랜치를 지운다.

| 언제 | 무엇 | 실측 (이 머신, 2026-09-04) |
| --- | --- | --- |
| red→green 반복 | 백엔드 테스트 파일 하나 | **12초** |
| red→green 반복 | 브라우저로 화면 하나 걸어보기 | **수 초** |
| 티켓 커밋 직전 | 바꾼 자리의 `pytest` | 수 초 ~ 수십 초 |
| 티켓 커밋 직전 | 세 앱 `typecheck` | 각 10~20초 |
| 브랜치 PR 의 CI | 전체 | 백엔드 + e2e |

로컬에서 `pnpm --dir frontend test`(전체)를 돌리지 않는다 — 로컬 e2e 는 `scripts/test.sh
e2e` 로 파일·프로젝트를 좁혀 돌린다. 그 스크립트들은 CI 가 쓴다.

**이번엔 전부 이 머신에서 다시 쟀다** — 옛 표의 e2e 수치는 이전 머신(WSL) 것이었다.

```bash
scripts/test.sh backend tests/test_payouts.py -q
scripts/test.sh e2e --project=public e2e/payout.spec.ts -g "상금 그대로가"
```

안쪽 고리에서 전체를 돌리면 **한 번의 red→green 이 4초가 아니라 7분**이 된다. 슬라이스
하나에 그 왕복이 여러 번 있으니 티켓 하나가 통째로 테스트 대기에 잠긴다.

**CI 가 돌리는 것.** PR 검사(`codemit/ci-pr`, macos)가 `scripts/ci/e2e.sh` 로 세 프로젝트를
`frontend/scripts/e2e-two-pass.sh` 의 두 패스씩 돈다(#702). 로컬에서 같은 것을 한 프로젝트만 돌리면
`scripts/test.sh e2e --project=<public|operator|classroom>` 이고, 한 번에 400개까지다.
