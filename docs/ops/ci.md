# CI 는 Jenkins 에서 돈다 — 브랜치마다, 노드를 통째로

`CLAUDE.md` 의 부록이다 — 거기서 앵커로 가리키고, 같은 「지금」을 말한다.

**시험은 Jenkins `codemit-ci-pr`(Multibranch, `Jenkinsfile.pr`)가 돌린다**(2026-10-02). GitHub
소스 `sandcorporation/laurio` 의 브랜치(`main`·`staging`·`production` 은 뺀다)마다 하위 잡이
생기고, 5분마다 훑어 새 push 를 찾는다. 결과는 GitHub 커밋 상태로 남는다. 같은 브랜치에 새로
push 하면 옛 빌드를 끊는다.

**PR 마다** — sub 검사만 돌고, 초록이면 그 커밋을 줄 세운다:

| 단계 | 노드 | 하는 일 |
| --- | --- | --- |
| 변경 | sub(`laurio-staging`) | `scripts/ci/changed.sh` — 문서(`.md`·`docs/`)만 바뀌었으면 시험을 건너뛰고 문서 검사만 |
| 시험(병렬) | sub | `scripts/ci/sub-checks.sh` — Django `check`·`check --deploy`, pytest 전체(junit), 생성물 최신성 둘, ADR·화면 언어 검사, 단위 시험 여섯, 세 앱 typecheck |
| 줄 서기 | sub | 초록이면 머리 커밋의 상태 `codemit/automerge` 를 `pending`(「다음 묶음을 기다린다」)으로 두고 `codemit-ci-train` 을 부른다 |

**묶음마다** — Jenkins `codemit-ci-train`(Pipeline, `Jenkinsfile.train`, 2026-10-03)이 줄 선 PR 을
최신 `main` 위에 차례로 쌓아 **한 번** 시험하고 초록이면 차례로 합친다. PR CI 가 부르고, GitHub 의
`pull_request` 웹훅이 hold 를 떼거나·초안을 풀거나·다시 연 PR 에서 부르며(아래 「줄에서 빠지는 법·돌아오는
법」), 30분마다 스스로도 돈다(뒷받침). 규칙은 `scripts/ci/train.py` 머리말에 있다.

**배포 이미지는 열차가 굽는다**(#712). 시험 두 가지가 묶음의 트리로 여섯 서비스를 아키텍처마다
`images.sh` 로 굽고(바뀌지 않은 문맥은 ctx 로 건너뛴다) 커밋 태그 `<묶음 머리 sha>-<arch>` 로 올린다. macos 의
e2e·celery 는 스택이 따로 굽지 않고 그 arm64 이미지를 받아 돈다(`docker/compose.ci-images.yaml`,
`CODEMIT_IMAGE_TAG`) — 그래서 **e2e 가 본 digest 가 prod 에 가는 digest 다**(`test-results/images.txt` 에
남는다). 「병합」은 병합 전에 그 digest 마다 `e2e-<묶음 트리>-arm64` 태그를 붙이고(`scripts/ci/images-e2e.sh`,
#729), prod 배포의 「e2e 대조」 단계(`deploy.sh prod e2e-digest`)가 그 커밋의 트리로 태그를 받아 떠 있는
backend·세 앱의 이미지 ID 와 견줘 콘솔에 `e2e 대조: <서비스> — 같다|다르다!|…` 를 적는다(관측만 — 붉히지 않는다).
열차 산출물을 Jenkins API 로 읽지 않고 레지스트리를 쓰는 이유: oracle 에이전트에는 Jenkins 자격증명이 없고
(copyartifact 플러그인도 없다) ghcr 로그인은 이미 있으며, 쌓은 sha·main sha 는 달라도 **트리**는 같다. ctx 태그는 시험 두 가지가 초록인 묶음에만, 「병합」 단계가 **병합 전에** 붙인다(#709 의 「초록 뒤에만」,
#729) — 붉은 묶음의 이미지는 커밋 태그만 남고 ctx 가 없어, 반으로 갈라 다시 도는 묶음이나 다음 빌드가 다시
굽는다. 병합 뒤에 붙이던 때(#712)는 병합 push 가 깨운 `codemit-deploy-staging` 이 ctx 보다 먼저 떠 같은 트리를
다시 굽기도 했다. ctx 는 내용 기준의 사실이라 병합이 거절돼도 무해하다(main 의 트리가 다르면 해시가 다르다).
병합 뒤 `codemit-deploy-staging` 은 「대상 확인」(built-in)에서 `images.sh` 의 **retag**(굽지 않고 커밋 태그만 더한다,
빌더도 띄우지 않는다)를 먼저 해 보고, 한 아키텍처가 전부 「건너뛴다」면 그 이미지 가지를 돌지 않는다 —
macos·sub 실행기를 다음 열차와 다투지 않는다(#729). 가드·문맥 태그 단계도 할 일이 없어 건너뛴다.

- **왜 배포 잡이 건너뛰나 — sha 가 아니라 트리다.** 쌓기는 cherry-pick 이라 노드마다 머리 커밋 sha 가 다르고
  GitHub 의 rebase 병합도 새 커밋을 만든다. 같은 것은 트리다: `train.py merge` 는 마지막 PR 까지 합친 뒤 main 의
  트리가 계획의 트리(`train.plan` 의 `tree`, 시험 두 가지가 `assemble` 에서 같은지 확인한다)와 같은지 콘솔에
  적는다. 같으면 서비스마다 문맥 해시도 같다. 다르면(그 사이 main 에 다른 커밋이 들어왔다·중간에 멈췄다)
  다른 문맥만 배포 잡이 굽고 가드한다 — 해시가 판단하므로 틀린 이미지가 건너뛰어지지는 않는다.
- **이미지가 붉은 것도 묶음이 붉은 것이다** — 다만 레지스트리·buildx 탓으로 붉었으면 e2e 정지와 같은 인프라
  재실행을 받는다(#729). `images.sh` 가 실패한 서비스의 로그를 `test-results/images-<arch>/` 에 남기고,
  `scripts/ci/e2e_stall.py images <arch>` 가 가른다: 실패한 서비스마다 로그에 **코드 탓 문구**(RUN 단계가 0 아닌
  코드로 끝났다 `did not complete successfully: exit code`, COPY 할 경로가 없다 `failed to compute cache key`,
  Dockerfile 을 못 읽었다)가 없고 **인프라 문구**(레지스트리 5xx·429, 연결 끊김·시간 초과·이름 풀이, BuildKit
  `rpc error: code = Unavailable`, 디스크가 찼다)가 있어야 인프라다. 결과 파일이 없으면(preflight — buildx 가 없다)
  판정하지 않는다. 종료코드로는 가르지 못한다 — buildx 는 어느 실패든 1 이다. RUN 안의 `pnpm install` 이 네트워크로
  죽어도 코드 탓으로 센다(좁게). 판정은 `post failure` 가 **붉은 쪽(sub·macos)마다** 모은다 — 붉은 쪽 하나라도
  판정이 없으면(검사·가드·celery 가 붉다) 넘기지 않고, `train.py fail` 은 넘어온 판정이 **전부** 인프라일 때만
  같은 묶음을 다시 돈다.
| 단계 | 노드 | 하는 일 |
| --- | --- | --- |
| 묶기 | sub | 열린 main PR 중 머리 커밋이 줄에 선 것(초안·`hold` 는 빼고, 8개까지)을 번호 순으로 cherry-pick 해 쌓는다. 얹히지 않는 PR 은 `failure` 로 돌려보낸다 |
| 시험(병렬) | sub | 같은 계획으로 다시 쌓고(트리 해시 확인) `scripts/ci/sub-checks.sh` → 초록이면 `scripts/ci/images.sh amd64`(staging 여섯, #712) → 이번에 구운 앱만 부팅 가드(`scripts/ci/deploy-guard.sh`) |
| | macos | 같은 계획으로 다시 쌓고 `scripts/ci/macos-sweep.sh`(중단된 앞 빌드가 남긴 `jenkins-codemit-ci-pr-*`·`jenkins-codemit-ci-train-*` 스택(#708 전 이름 `jenkins-codemit-pr-*`·`jenkins-codemit-train-*` 도 한동안 — 「잡 이름」)·볼륨·이미지와, 받아 둔 배포 이미지 중 저장소마다 가장 새것 하나만 남기고 걷는다. 기본 빌더 캐시는 10GB 로 자른다 — 중단은 trap 을 건너뛰어, 남은 볼륨이 Docker VM 을 채우자 MinIO 가 `XMinioStorageFull` 로 업로드를 거절했다, 2026-10-03) → `scripts/ci/images.sh arm64`(prod 여섯, #712) → **그 이미지를 받아** `scripts/ci/e2e.sh`(세 프로젝트) → `scripts/ci/celery-broker.sh` |
| 병합 | sub | 초록이면 차례로 rebase 병합(`sha` 로 머리를 고정 — 그 사이 push 된 PR 에서 멈춘다) — 그 **앞에** 이 묶음이 구운 이미지에 ctx 태그(`scripts/ci/images-ctx.sh`, #712·#729) → 합친 범위의 `GlitchTip:` 줄 해결 표시 → 남은 줄이 있으면 다음 묶음 |
| 붉으면 | sub | 붉은 쪽마다 「인프라 고장」 판정이 있으면(macos 의 e2e 정지·이미지 굽기, sub 의 이미지 굽기 — sub 는 검사가 초록일 때만) **같은 묶음을 한 번 더**(아래 「backend 요청 0건 틈은 묶음을 한 번 더 돈다」). 아니면 둘 이상일 때 앞의 절반으로 다시 돈다. 하나만 묶은 시험이 붉으면 그 PR 에 `failure` |

- **왜 묶나**(2026-10-03). PR 마다 macos e2e 를 따로 돌리면 이미지 셋 굽기 포함 약 8분이 노드
  실행기 하나에 줄을 서(PR 넷이면 32분), 각 PR 은 자기가 갈라진 **옛 main** 위에서만 시험됐다 —
  먼저 합쳐진 PR 과 충돌하는 PR 이 초록인 채 남았다(#530 이 #531·#532 와 그렇게 충돌했다).
- **줄에서 빠지는 법·돌아오는 법.** 새로 push 하면 새 커밋에는 상태가 없어 저절로 빠지고, PR CI
  가 다시 세운다. `failure` 를 받은 커밋은 PR CI 를 다시 돌리면(`POST /job/codemit-ci-pr/job/<브랜치>/build`)
  줄로 돌아온다 — 위 판정에 들지 않는 인프라 고장으로 붉은 묶음이 가르기 끝에 PR 하나를 억울하게 잡았을 때의 길이다.
  초안을 풀거나 `hold` 를 떼거나 PR 을 다시 열면 다시 빌드하지 않아도 열차가 곧 데려간다(#709) — 셋은
  push 가 아니라 PR CI 가 부르지 않으므로, `Jenkinsfile.train` 의 `GenericTrigger`(플러그인
  generic-webhook-trigger)가 GitHub 웹훅(`pull_request` 이벤트만, `/generic-webhook-trigger/invoke?token=…`,
  토큰은 자격증명 `codemit-train-webhook-token`)을 받아 `unlabeled`(라벨 `hold`)·`ready_for_review`·`reopened`
  이고 초안이 아니며 base 가 `main` 인 것에서만 열차를 깨운다. 그 밖의 이벤트(opened·synchronize·labeled·
  closed)는 PR CI 가 push 로 다룬다. 웹훅이 빠지면 30분 cron 이 데려간다. Jenkins 는 `triggers` 를 **잡이 한
  번 돈 뒤에** 반영하므로, 이 블록을 바꾸면 그 뒤 첫 빌드부터 듣는다. 기다리기 싫으면 손으로 깨운다:
  `POST /job/codemit-ci-train/buildWithParameters`.

- **macos 의 Docker VM 디스크는 96GiB 이고, 묶음마다 무엇이 남는지 정해 두어야 찬다.** 맥 호스트
  디스크가 남아도 Docker Desktop 의 `Docker.raw` 가 차면 MinIO 가 `XMinioStorageFull` 로 업로드를
  거절하고 db 컨테이너가 죽는다 — 코드와 무관하게 묶음이 붉다. 실행마다 compose 프로젝트 이름이
  달라(`CODEMIT_CI_RUN_ID`) 쌓이는 것은 그 실행의 볼륨과 이미지다. 지금(#712) 열차의 스택은 굽지 않고
  `images.sh` 가 올린 `ghcr.io/sandcorporation/codemit-<서비스>:<sha>-arm64` 를 받는다 — 커밋마다 새 태그라
  `macos-sweep.sh` 가 저장소마다 **가장 새것 하나**만 남긴다(다음 실행이 바뀌지 않은 층을 다시 받지 않는 층
  캐시). 굽는 쪽 캐시는 빌더 `codemit-images` 의 것이고 `images.sh` 가 20GB 로 자른다. `e2e.sh`·
  `celery-broker.sh` 는 내릴 때 `down -v --rmi local` 로 볼륨과 (굽는 길이면) 자기가 구운 이미지를 지운다.
  trap 이 못 돈 중단 빌드의 찌꺼기는 다음 빌드 첫머리의 `macos-sweep.sh` 가 걷고, 기본 빌더 캐시(이제
  로컬 굽기 길만 쓴다)는 나이가 아니라 크기(10GB, 오래 안 쓴 것부터)로 자른다. 사고 둘: 2026-10-03 중단된
  스택의 볼륨 400여 개(30GB), 2026-10-14 지워지지 않은 이미지 1,283개(51GB)와 캐시 48GB.
- **노드는 실행기가 하나라 통째로 쓴다.** 예전에는 GitHub Actions 의 셀프호스티드 러너
  셋(sub)이 sub 의 코어를 제한 없이 나눠 써, 이미지 빌드와 겹친 시험이 경합만으로 한도를
  넘었다(#499 의 첫 CI — 공개 e2e 10건·단위 2건 타임아웃). 오래 걸리는 e2e 를 성능이 좋은
  macos 에, 짧은 것을 staging 배포와 실행기를 나눠 쓰는 sub 에 둔다.
- **e2e 가 흔들리면 무엇을 보나**(#699). 열차 빌드의 산출물(`test-results/**`, macos 단계가 거둔다)에
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
  빌 뿐 e2e 를 붉게 만들지 않는다. ⑤ `test-results/e2e-verdict.json` — 아래 인프라 판정. 로컬 `scripts/test.sh e2e` 는 같은 trace 를 `frontend/test-results/`(뒤 패스는
  `frontend/test-results/exclusive/`)에 두고, 스택 로그는 `CODEMIT_E2E_KEEP=1` 로 남긴 스택에서
  `docker compose -p <워크트리>-e2e … logs --timestamps <서비스>` 로 본다.
- **backend 요청 0건 틈은 묶음을 한 번 더 돈다**(#716). 열차 #1840·#1890 에서 강의실 e2e
  넷이 한꺼번에 3초를 넘었다. #1890 의 산출물로 가린 모양은 **backend 접근 로그에 3.9초 동안 요청 0건**
  (앞뒤는 초당 50~146건, 틈 앞뒤 요청은 8~25ms)이고, 시험 넷의 마지막 요청이 서로 다른 두 Next 컨테이너에서
  같은 시각에 미완료였다 — 그때는 코드가 아니라 Docker VM(또는 포트 전달) 전체가 멈췄다고 읽었다.
  **#1906 에서는 그 읽기가 틀렸다(#723).** #1902·#1906·#1907 의 같은 모양(틈 3.98~4.01초)을 로컬에서 재현해 backend
  망에서 패킷을 잡으니, 강의실 컨테이너가 맺은 연결 다섯이 **요청을 한 줄도 보내지 않고 정확히 4.00초
  뒤 FIN** 했고, 그동안 gunicorn sync 워커 넷이 전부 그 연결에서 요청 머리를 기다리며 멈춰 있었다.
  강의실 BFF 가 브라우저의 끊김을 backend fetch 에 바로 넘겨, Node fetch(undici)가 끊긴 요청 자리에
  맺어 둔 빈 연결을 keep-alive 기본값 4초 동안 쥔 것이다(`packages/bff-shared/src/forward.ts`, 시험이
  끝나 브라우저 맥락이 닫힐 때마다 생긴다). 그러니 #1906 을 인프라로 분류한 것은 **틀린 판정**이었고,
  「backend 요청 0건」은 코드 밖의 증거가 아니다 — 워커가 모두 붙잡혀도 같은 모양이다. trace 로 본 것은
  #1902·#1906·#1907 셋뿐이고, #1840·#1890 은 같은 모양이므로 같은 원인으로 본다. **판정은 남기고 발동
  횟수를 센다**(2026-10-15 사용자 결정, #721 — 0 이 이어지면 걷는다). 이 판정은 VM 정지와 backend 워커가
  모두 붙잡히는 코드 탓 멈춤(#723)을 가르지 못한다 — 그런 멈춤이 다시 생기면 재실행 한 번을 공짜로
  얻는다. 발동은 열차 콘솔의 `인프라 고장으로 분류:` 줄이고(커밋 제목에도 같은 말이 있어 앞의 `Z] ` 까지
  잡는다), Jenkins 가 남긴 빌드(최근 50개)를 이렇게 센다 — `JENKINS_*` 는 `~/.config/codemit-ghcr-wizard.env`:

  ```bash
  for n in $(curl -s -u "$JENKINS_USER:$JENKINS_API_TOKEN" "$JENKINS_UI_URL/job/codemit-ci-train/api/json?tree=builds%5Bnumber%5D" | python3 -c 'import json,sys;print(*[b["number"] for b in json.load(sys.stdin)["builds"]])'); do curl -s -u "$JENKINS_USER:$JENKINS_API_TOKEN" "$JENKINS_UI_URL/job/codemit-ci-train/$n/consoleText" | grep -q 'Z\] 인프라 고장으로 분류: ' && echo "$n"; done
  ```

  2026-10-15 에 센 값은 #1890~#1939 에서 둘(#1902·#1906, 둘 다 #723 이 고친 코드 탓)이고 #723 병합(#1911)
  뒤(#1911~)로는 0 이다. macos 단계가 e2e 뒤에
  `scripts/ci/e2e_stall.py` 로 판정한다: 실패가 하나 이상이고 전부 「Test timeout」이며, 시험마다 그 마감
  (trace 의 시작 + 한도)이 backend 접근 로그의 **3초 이상 요청 0건 틈** 안에 있다. `.last-run.json` 이
  `status: failed` 인데 `failedTests` 가 빈 프로젝트(「No tests found」·globalSetup 오류)가 있으면 판정하지
  않는다(#719). 한도는 trace 첫 줄의 `testTimeout`(설정의 한도)이라 **스펙에서 `test.setTimeout`·`test.slow`·
  `test.describe.configure({ timeout })` 로 시험 한도를 바꾸면 마감이 어긋난다** — 지금 스펙은 아무도 쓰지
  않는다(2026-10-15 `git grep`). celery-broker 가 초록이고, sub 단계가 초록이거나 sub 의 이미지 굽기도
  인프라 판정이면(위 「이미지가 붉은 것도 묶음이 붉은 것이다」, #729) `train.py fail --verdict` 가 PR 에
  `failure` 를 주지 않고 같은 묶음을 다시 부르며
  콘솔에 `인프라 고장으로 분류: backend 요청 0건 3.9초 틈 @…` 한 줄을 남긴다. **재실행은 가르기 사슬
  전체에 한 번이다**(#718) — 다시 붉으면(`INFRA_RETRY=1` 빌드) 지금 규칙대로 가르거나 `failure` 이고,
  가른 묶음도 `INFRA_RETRY=1` 을 물려받아 판정을 다시 읽지 않는다. 몫은 초록 뒤(다음 묶음이
  `INFRA_RETRY` 없이 뜬다)나 PR 하나가 붉어 사슬이 끝난 뒤에야 돌아온다. 그래서 재실행은 **사슬마다
  한 번이고, 초록 절반이 새 사슬을 연다**(#721): 앞 절반이 초록이면 합쳐지고, 남은 뒤 절반은 기본값
  빌드(`MAX_PRS=0`)로 다시 묶여 몫을 새로 받는다. 코드 탓 실패가 매번 인프라로 잘못 분류될 때 범인이
  앞 절반에 있으면 8 → 재8 → 4 → 2 → 1(빌드 한 번 더)이지만, 범인 하나의 최악(맨 뒤)은 8 → 재8 → 4 →
  4 → 재4 → 2 → 2 → 재2 → 1 → 1 → 재1, 재실행 **log2(n)+1 회**(8개면 넷, 빌드 11번)다. 사슬 상태는
  매개변수로만 넘어가므로, 붉은 빌드가 도는 동안 cron·웹훅·PR CI 가 먼저 줄 세운 기본값 빌드가 있으면
  그것이 먼저 떠 남은 PR 을 몫과 함께 새로 묶을 수 있다(코드 읽기 — #1890~#1939 의 사슬 둘, #1902 →
  #1903 과 #1906 → #1907 → #1908 에서는 끼어든 빌드가 없었다).
  「시험 하나 3초·재시도 없음」은 **시험 단위의 규칙이라 그대로다**: 시험을 다시 돌려 초록을 사는 것이
  아니라 묶음 전체를 처음부터 다시 돈다. 다만 다시 도는 조건 「그 순간 서버가 요청을 하나도 받지
  않았다」는 위대로 코드 밖의 증거가 아니다. **판정은 사실상 그 셋째 조건 하나에 기댄다** — 시험 한도(3초)가 `expect` 의 기본
  기다림(5초)보다 짧아, 요소가 없거나 문구가 바뀐 흔한 화면 회귀도 거의 다 「Test timeout」으로 끝나므로
  「전부 timeout」은 거르는 힘이 거의 없다. 그리고 코드 탓의 멈춤이 늘 backend 가 요청을 받는 동안
  생기는 것도 아니다: 브라우저가 없는 요소를 기다리는 동안에는 backend 를 부르지 않을 수 있어, 일꾼
  하나인 `@exclusive` 패스나 프로젝트 끝에 시험 하나만 남았을 때 SSR 뒤 backend 를 더 부르지 않는
  화면이면 3초 틈이 생길 수 있다(얼마나 자주인지는 확인하지 않았다). 그렇게 잘못 분류된 대가는 위의
  사슬마다 한 번이다. 「실패 시험의 시작도 틈 안」 조건은 넣지 않는다 — #1890 의 실패 넷 중 셋이 틈
  (19:48:42.667Z)보다 0.07~0.36초 먼저 시작했으므로, 넣으면 그 모양 자체를 거른다(#721).
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

- **sub 의 Jenkins 는 컨테이너라 node·pnpm·uv 가 없다** — 그래서 sub 쪽은 저장소를 담은
  시험 이미지(`docker/ci.Dockerfile`)를 굽고 사이드카 postgres(tmpfs·fsync 끔)와 같은 망에서
  `scripts/ci/sub-checks-inside.sh` 를 돈다. 바인드 마운트는 쓰지 않는다(컨테이너와 호스트의
  경로가 다르다, 아래 「Jenkins 는 staging 배포 호스트에 있다」). 그 이미지는 루트
  `.dockerignore` 대신 `docker/ci.Dockerfile.dockerignore` 를 읽어 **문서를 들인다** — 문서 검사와
  다이어그램 최신성 시험이 그것을 읽는다(빼먹었을 때 넷이 「파일이 없다」로 빨갰다).
- **실측**(2026-10-02, 첫 초록): sub 쪽 전체 약 3분(pytest 2489건 47초), macos e2e 공개 14초 ·
  운영자 4초 · 강의실 4초(이미지 굽기 제외).
- **잡 설정은 저장소 밖이다** — Multibranch 잡·묶음 잡 `codemit-ci-train`(Pipeline, `*/main` 의 `Jenkinsfile.train`)·자격증명(`github-sandcorporation-token` 은
  fine-grained PAT: 저장소 읽기·PR·커밋 상태·Contents 쓰기, `glitchtip-automation-token`, 이미지 잡의 `ghcr-push-token`)은 사람이
  Jenkins 에 만든다. Jenkins 설정을 API 로 고칠 때는 `Content-Type: application/xml;
  charset=utf-8` 을 붙인다 — 없으면 한글이 Latin-1 로 읽혀 500 이 난다.
- **잡 이름은 `codemit-<역할>-<대상>` 이다**(2026-10-15, #708). 잡이 다섯이다.

  | 잡 | 파일 | 워크스페이스·이름에 묶인 것 |
  | --- | --- | --- |
  | `codemit-ci-pr`(Multibranch) | `Jenkinsfile.pr` | sub 검사의 컨테이너·네트워크·이미지(`codemit-ci:<run_id>`) `jenkins-codemit-ci-pr-*`(`BUILD_TAG` 에서) — e2e·celery 는 열차만 돈다 |
  | `codemit-ci-train` | `Jenkinsfile.train` | 스택 `jenkins-codemit-ci-train-*`, 다음 묶음은 `env.JOB_NAME` 으로 부른다 |
  | `codemit-deploy-staging` | `Jenkinsfile` | sub `workspace/codemit-deploy-staging/`의 `docker/.env.staging`·`.jenkins-staging-deployed`, 이미지 단계 `customWorkspace 'codemit-deploy-staging-images'` |
  | `codemit-deploy-prod` | `Jenkinsfile.production` | oracle 호스트 `/var/jenkins_home/workspace/codemit-deploy-prod/`의 `docker/.env.prod`·배포 표식 |
  | `codemit-ghcr-prune` | 저장소 밖 | |

  이전 이름은 `codemit-pr`·`codemit-train`·`laurio`·`codemit` 이다. 잡을 이름으로 부르는 자리는
  `Jenkinsfile.pr` 의 `build job: '/codemit-ci-train'` 하나다(실패해도 열차는 30분 cron 으로 돈다).
  자격증명 `codemit-train-webhook-token` 은 잡 이름이 아니라 ID 라 그대로 뒀다. `macos-sweep.sh` 는
  rename 직전에 남은 `jenkins-codemit-(pr|train)-*` 도 한동안 같이 걷는다 — 2026-11-15 이후 #735 로 지운다(지울 조건은 그 파일 머리말).
  끝 조건의 「새 이름으로 한 번씩 초록」은 prod 를 뺀 셋이다 — `codemit-deploy-prod` 는 사용자가 prod
  승격을 말할 때 처음 돈다.
- **문서(`*.md`·`docs/`)만 바뀐 커밋은 시험도 이미지도 건너뛴다** — PR CI 와 `codemit-deploy-staging` 잡 모두 `scripts/ci/changed.sh`(`codemit-deploy-staging` 은 **마지막으로 staging 배포를 끝낸 커밋** — 배포 표식 `.jenkins-staging-deployed` — 과 견준다. `staging` 브랜치는 배포보다 먼저 앞당겨지므로, 그것과 견주면 배포가 실패한 커밋 뒤의 문서 커밋이 그 배포를 다시 시도하지 않고 초록이 됐다, #709). 그런 커밋은 staging·production 을 앞당기지 않고 다음 코드 커밋과 함께 간다.
- **GitHub Actions 는 쓰지 않는다**(2026-10-15, #705, ADR-0061). 조직이 Free 요금제라 호스티드 분량(월
  2,000분)이 바닥나자 `staging` 이 멈췄고, 결제하지 않고 떠났다. Actions 가 하던 셋 — 배포 이미지, 부팅
  가드, `staging` 앞당기기 — 은 `main` push 에서 도는 Jenkins `codemit-deploy-staging` 잡(`Jenkinsfile`)의 앞 단계가 됐다
  (「배포」 절). 이미지는 macos 가 arm64 여섯, sub 가 amd64 여섯을 함께 굽고(`scripts/ci/images.sh`),
  **바뀌지 않은 서비스는 빌드 문맥 해시로 건너뛴다**. 구운 이미지는 커밋 태그로만 올리고, 문맥 태그
  (`ctx-<해시>`)는 이미지 두 가지와 부팅 가드가 **모두 초록인 뒤에** 「문맥 태그」 단계(`scripts/ci/images-ctx.sh`,
  sub)가 붙인다(#709) — 그래서 「건너뛴다」는 언제나 앞 빌드가 끝까지 초록으로 본 이미지이고, 가드가 빨갛거나
  한 가지가 실패한 빌드의 이미지는 다음 빌드가 다시 굽고 가드도 다시 돈다. 부팅 가드 셋(`scripts/ci/deploy-guard.sh`, sub)은
  **방금 올린 그 이미지를 ghcr 에서 받아** 배포 설정 없이는 죽고 완전한 설정으로는 뜨는지 본다 — 이번에
  구운 앱만(건너뛴 앱의 이미지는 이미 한 번 지났다). 앱 이미지는 환경을 모르므로(#711) 가드가 공개 값을
  `-e CODEMIT_PUBLIC_*` 로 주고, 방침의 문의 주소가 `/privacy` 에, 토스 클라이언트 키가 첫 화면의
  `window.__CODEMIT_PUBLIC__` 에 실리는지(시크릿은 실리지 않는지)로, `.dockerignore` 는 가짜 시크릿을 심은 **빌드 컨텍스트**(`COPY . /ctx`
  만 하는 이미지)로 본다 — 표식에 빌드마다 다른 값을 섞는다(스크립트 자신이 문맥에 들어 고정 문자열이면
  늘 걸린다). 컨테이너 포트를 노드에 열지 않고 띄운 컨테이너의 네트워크에 curl 컨테이너를
  붙여(`--network container:<이름>`) 친다(sub 의 Jenkins 가 컨테이너라 바인드 마운트도 쓰지 않는다).
- **`Jenkinsfile` 은 PR CI 가 보지 못한다**(`Jenkinsfile.train` 도 — 그 PR 을 실은 열차는 아직 main 의 것으로 돈다) — 그 파일을 바꾼 PR 은 병합 전에 그 브랜치를 가리키는 임시
  잡으로 `IMAGES_ONLY=true` 를 돌려 본다(이미지·가드까지만). 스크립트 쪽은 로컬에서 돈다: `CODEMIT_IMAGES_MODE=plan`
  (해시와 판단만), `CODEMIT_IMAGE_REGISTRY=localhost:<포트>`(로컬 `registry:2` 에 실제로 굽고 건너뛰기),
  `CODEMIT_GUARD_IMAGE=<이미지>`(가드가 받을 이미지), `CODEMIT_IMAGE_TAG=<sha>-<arch> scripts/test.sh e2e`(올린
이미지로 e2e — 열차의 길). 두 스크립트는 macos 의 bash 3.2 에서도 돈다.

**CI 는 `docker/compose.ci.yaml` 을 dev compose 위에 겹쳐 쓴다 — 지우면 CI 가 깨진다.**
`compose.dev.yaml` 의 `..:/app` 은 **개발용 핫리로드 장치**다. 러너 안에서 그 상대 경로는
호스트 데몬 기준으로 풀려 `/app` 이 통째로 비고, backend 는 `can't open file '/app/manage.py'`
로, 두 앱은 `Scope: all 0 workspace projects` 로 죽는다. 오버라이드가 하는 일은 셋뿐이다:

- 다섯 서비스(backend·events·frontend·operator·classroom, #379)의 `volumes` 를 `!reset []` —
  마운트 없이 **이미지 안의 코드**로 돈다.
- 세 앱(frontend·operator·classroom, #277)의 빌드 `target` 을 `runner` 로 — dev 서버가
  아니라 **배포되는 그 이미지**를 친다.
- 세 앱의 `command` 를 `!reset null` — 이미지의 `node server.js` 가 산다.

열차는 셋째 장 `docker/compose.ci-images.yaml` 을 더 얹는다(#712) — 위 셋은 그대로 받고 `build` 를 걷어
`images.sh` 가 올린 `codemit-<서비스>:${CODEMIT_IMAGE_TAG}` 를 받는다(backend 계열 다섯은 `codemit-backend`
하나). `CODEMIT_IMAGE_TAG` 가 없으면 `e2e.sh`·`celery-broker.sh`·`scripts/test.sh e2e` 는 예전처럼 스택이 굽는다.

**그래서 e2e 가 검증하는 대상이 바뀌었다.** 예전엔 `next dev` 를, 지금은 프로덕션 빌드를
친다 — 배포되는 것과 테스트되는 것이 같아졌다. 위 `next dev` 메모리 주의는 이제
**로컬에서 스위트를 돌릴 때만** 해당한다.

**스택마다 이름을 갈라 준다.** e2e 와 celery-broker 의 compose 프로젝트 이름은 빌드
식별자(`CODEMIT_CI_RUN_ID` — 빌드 태그 + 시작 시각)에서 나오고, 포트는 compose 가 비어 있는 것을
고른다. 끝나면(성공·실패·중단 모두) `down -v` 로 지운다.

**화면 언어 검사**(#267, #268 — PR CI 의 sub 단계)는 스텝 둘로 두 표면을 막는다. 첫 스텝
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
