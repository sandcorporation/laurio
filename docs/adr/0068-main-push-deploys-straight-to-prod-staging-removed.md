# main push 가 곧 prod 배포다 — staging 배포·amd64 이미지·PROMOTE_PRODUCTION 을 걷는다

Status: Amended by ADR-0071 (2026-10-30 결정)

## 맥락 (#836, #840)

2026-10-15(ADR-0061) 뒤의 배포 잡 `codemit/deploy`(`Jenkinsfile`)는 한 빌드에서 이렇게 돌았다:
arm64(macos)·amd64(sub) 이미지 → amd64 부팅 가드(sub) → 문맥 태그 → `staging` 앞당기기 → staging 배포
(built-in) → `PROMOTE_PRODUCTION` 을 켰을 때만 prod 배포(oracle) → `production` 앞당기기.
`PROMOTE_PRODUCTION` 은 2026-10-14 부터 기본 꺼짐이라(강의실 v2 동안 prod 를 붙잡으려고) 웹훅 빌드는
staging 까지만 가고 prod 는 사람이 손으로 승격했다.

2026-10-30 대표가 staging 을 전부 없애기로 했다. 조사(#836 §0)에서 나온 사실:

- amd64 이미지를 쓰는 곳은 staging 배포와 부팅 가드뿐이다. CI 시험(sub 검사)은 그 자리에서 `ci.Dockerfile`
  로 굽고, 열차의 e2e·celery 는 arm64 이미지를 쓴다.
- 배포 잡의 부팅 가드는 staging 의 amd64 만 봤다 — prod 로 가는 arm64 이미지는 배포 잡에서 가드를 지나지
  않았다(열차를 거친 커밋만 열차의 macos 가드를 지났다, #838).
- 「문서만 바뀐 빌드」를 가리는 기준이 staging 배포 표식 `.jenkins-staging-deployed` 였다 — staging 과 함께
  사라진다.

## 결정

- **main push 가 곧 prod 배포다.** `PROMOTE_PRODUCTION` 을 지운다. 흐름은
  대상 확인(built-in) → 이미지(macos: arm64 굽기 → 부팅 가드 → 문맥 태그) → prod 배포(oracle) →
  `production` 앞당기기(built-in) → 디스코드 알림(built-in).
- **비상 브레이크는 잡 「Disable」이다.** 파라미터로 prod 를 막는 길을 남기지 않는다 — 남기면 「main 은
  초록인데 prod 는 아무 데도 가지 않는」 길이 다시 생긴다. prod 만 다시 돌리려면 「Build Now」(`deploy.sh plan`
  이 이미 배포된 커밋을 비운다).
- **`IMAGES_ONLY` 는 남긴다** — `Jenkinsfile` 을 바꾼 PR 을 병합 전에 돌려 보는 유일한 길이다. prod·`production` 은
  건드리지 않는다.
- **문서만 판단의 기준은 GitHub 의 `production`** 이다(`ls-remote`, `Jenkinsfile.ghcr-prune` 과 같은 방식).
  `production` 은 prod 배포가 초록인 뒤에만 앞당기므로 「마지막으로 성공한 prod 배포」와 같다 — #709 의 함정
  (배포 전에 앞당긴 브랜치를 기준으로 삼아 실패한 배포를 다시 시도하지 않은 것)이 생기지 않는다. 앞당기기만
  실패하면 기준이 옛 커밋이 되어 범위가 넓어질 뿐이다. 못 읽으면 전부 돈다. oracle 의 `.jenkins-prod-deployed`
  를 읽는 길은 첫 단계부터 oracle 노드를 잡아야 해서 버렸다.
- **부팅 가드는 macos 에서 arm64 로**(`CODEMIT_GUARD_ARCH=arm64`, #838) 「이미지」 단계 안의 하위 단계로 돈다 —
  macos 실행기 하나를 그대로 쓰고, 방금 구운 자리라 pull 이 작다. oracle 에서 돌리지 않는다(probe 이미지를
  굽고 Next 컨테이너를 띄웠다 내려 prod 호스트를 흔든다).
- **built-in 단계는 잡의 기본 워크스페이스**(`workspace/codemit/deploy`)를 쓴다 — 셋 다 `.env` 가 필요 없다.
- prod 배포 단계의 안전장치(Preflight·변경 계획·이미지 받기·교체·확인·e2e 대조·배포 표식·정리)는 그대로다.
  마이그레이션이 있는 배포는 `up` 이 migrate 전에 DB 를 덤프한다(#839).

### 옮긴 것 / 버린 것

| 지금까지 | 결정 | 새 자리 / 이유 |
| --- | --- | --- |
| 대상 확인 — main 인지 | 남김 | 문구만 「main 만 prod 로 배포한다」 |
| 대상 확인 — 문서만인지(`.jenkins-staging-deployed`) | 옮김 | 기준 = GitHub `production`(ls-remote) |
| 대상 확인 — retag(arm64·amd64) | arm64 만 | amd64 를 굽지 않는다 |
| 이미지 arm64(macos) | 남김 | prod 이미지 |
| 이미지 amd64(sub) | 버림 | staging 배포와 가드에만 쓰였다 |
| 부팅 가드(sub, amd64) | 옮김 | macos 「이미지」 단계 안, arm64 |
| 문맥 태그(sub, amd64+arm64) | 옮김 | macos 「이미지」 단계 끝, arm64 만 |
| `staging` 앞당기기 | 버림 | 배포 기록은 `production` 하나 |
| staging 배포(Preflight~정리, 재색인 포함) | 버림 | 같은 단계가 prod 에 있다. `deploy.sh` 의 staging 대상은 #836 T4 가 걷는다 |
| `PROMOTE_PRODUCTION` | 버림 | main push 가 prod 배포. 브레이크는 잡 Disable |
| `IMAGES_ONLY` | 남김 | 설명만 「prod·production 은 건드리지 않는다」 |
| prod 배포 단계 | 남김 | when 에서 PROMOTE 만 뺐다 |
| `production` 앞당기기 | 남김 | when 에서 PROMOTE 를 빼고 기본 워크스페이스 |
| 디스코드 알림 | 남김, 문구만 | `[Codemit] prod 배포 <결과>` — staging 부분을 걷었다 |

## 결과

- **잃는 것은 staging 의 실물 리허설이다** — 마이그레이션이 데이터가 든 DB 위에서, compose·`deploy.sh`
  변경이 실물 호스트에서 처음 도는 자리. 이제 prod 에서 처음 돈다. 완화: 마이그레이션 전 덤프(#839),
  `deploy.sh` 의 가짜 docker 시험과 `ROLLING-DEPLOY-UNSAFE` 규칙, compose·`deploy.sh`·마이그레이션을 바꾸는
  PR 은 사람이 보는 시간에 병합한다.
- 되돌리기는 옛 커밋으로 `deploy.sh prod all`(ghcr 에 `-arm64` 가 KEEP_IMAGES 만큼 남는다) 또는 revert 커밋.
- 열차는 아직 amd64 를 굽고(#836 T3), compose·env 예시·`deploy.sh` 의 staging 대상·ghcr-prune 의 `staging`
  보호는 T4 가 걷는다. 서버의 staging 스택·워크스페이스·Jenkins 설정은 사람이 지운다(#836 §6).
