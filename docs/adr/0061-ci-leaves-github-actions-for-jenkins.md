# CI 는 GitHub Actions 를 떠나 전부 Jenkins 에서 돈다 — 바뀌지 않은 서비스의 이미지는 굽지 않는다

Status: Accepted (2026-10-15 결정)

2026-10-02 부터 시험은 Jenkins(`codemit-pr`·`codemit-train`)가 돌렸고, GitHub Actions 에는 셋만
남았다 — 배포 이미지 열둘(staging amd64 여섯·prod arm64 여섯), 그 staging 이미지를 받아 보는 부팅
가드 셋, 다 초록이면 `staging` 브랜치를 앞당기는 잡 하나(`.github/workflows/images.yaml`, 호스티드
러너). 10-14 22:46(e95f314) 뒤로 그 잡들이 시작하지 못했다. 조직이 Free 요금제라 포함 분량
2,000분($12)을 다 썼고(9월도 정확히 $12.00 에서 멈췄다) 지출 한도가 $0 이다. 커밋마다 호스티드 잡
16개가 각각 1분 단위로 올림돼 커밋당 약 20분이었고, 10-14 하루에 50개 넘게 병합돼 바닥났다.
`staging` 이 e95f314 에 멈췄다.

결정: 결제하지 않고 Actions 를 떠난다. 셀프호스티드 러너도 쓰지 않는다. 그 셋은 `main` push 에서
도는 Jenkins `laurio` 잡(`Jenkinsfile`)의 앞 단계가 된다 — 대상 확인(문서만이면 끝) → 이미지(macos 가
arm64, sub 가 amd64, `scripts/ci/images.sh`) → 부팅 가드(sub, `scripts/ci/deploy-guard.sh`) → `staging`
앞당기기(`scripts/ci/fast_forward.py`) → 지금까지의 staging 배포 → (켜져 있으면) `production` 앞당기기.
`staging`·`production` 브랜치는 그대로 둔다 — 배포 기록이고 `production` 은 prod 잡의 트리거다.

그리고 **바뀌지 않은 서비스의 이미지는 굽지 않는다.** 서비스마다 빌드 문맥 해시(Dockerfile 이 읽는
경로의 git 해시 + Dockerfile + `.dockerignore` + 대상·플랫폼 + 빌드 인자 값)를 내고, `ctx-<해시>-<태그>`
가 ghcr 에 있으면 커밋 태그만 그 매니페스트에 더한다.

## 왜

- **Jenkins 노드는 이미 있다.** sub·macos 는 시험에 쓰이고 있고, macos 에는 열차가 e2e 이미지를 굽는
  buildx 가 있다. 분량 제한도 분 단위 올림도 없다. 커밋 하나의 여정(이미지 → 가드 → 배포 → 승격)이
  빌드 하나에 다 보이는 것도 얻는다 — 예전에는 Actions 실행과 Jenkins 빌드 둘을 맞춰 봐야 했다.
- **결제하면 문제가 다시 온다.** 지출 한도를 올려도 병합이 많은 날마다 같은 바닥에 닿고, 그때마다
  배포가 조용히 멈춘다(이번에도 그렇게 하루를 몰랐다).
- **열둘 중 대부분은 굽자마자 버려졌다.** `deploy.sh plan` 이 `git diff` 로 바뀐 서비스만 바꿔
  끼우므로, 강의실만 고친 커밋에서도 열둘을 다 구운 것은 시간과(Actions 시절엔) 돈만 썼다. 해시로
  건너뛰면 그 커밋은 둘(강의실 staging·prod)만 굽는다. 같은 노드에서 시험과 겹치는 부담도 그만큼 준다
  — 09-17 에 sub 에서 이미지를 뺀 이유가 디스크 대기 14~84% 였다.

## 결과

- **가장 위험한 자리는 문맥 표가 Dockerfile 보다 좁은 것이다** — 빠진 경로를 고친 커밋은 옛 이미지로
  배포된다. 표는 `scripts/ci/image_context.py` 에 있고, `scripts/test_image_context.py`(PR CI)가
  Dockerfile 의 `COPY`/`ADD`/`RUN --mount=type=bind` 원본이 전부 표 안에 있는지 본다.
- 세 앱의 `NEXT_PUBLIC_SENTRY_RELEASE` 는 HEAD 가 아니라 **그 문맥을 마지막으로 바꾼 커밋**이다(그
  전부터 Next 캐시 때문에 그랬다). HEAD 면 문맥 해시가 커밋마다 달라져 건너뛰기가 무의미하다. 문맥
  해시 자체를 release 로 쓰는 길도 있었지만, GlitchTip 자동 진단의 「release 가 수정 커밋을 품는가」
  판정이 커밋을 요구해 고르지 않았다(`docs/ops/operations.md` GlitchTip 절).
- 커밋 태그를 더할 때 매니페스트를 그대로 베낀다(`imagetools create --prefer-index=false`). buildx
  기본값은 매니페스트 하나짜리 index 를 새로 만드는데, 그러면 ghcr 에 원본과 index 가 따로 버전으로
  남아 정리 잡이 원본만 지우면 커밋 태그가 깨진다. 베끼면 같은 버전에 태그만 붙는다.
- 배포 중인 커밋의 이미지가 오래전에 만든 버전일 수 있다(강의실만 고친 지 한참 뒤의 backend 등).
  `codemit-ghcr-prune` 은 `main`·`staging`·`production` 끝 커밋의 태그를 가진 버전을 순서와 무관하게
  남기고, 순서는 태그가 붙은 때로 센다.
- NEXT_PUBLIC 값의 원본은 저장소 변수가 아니라 Jenkins 자격증명 `codemit-images-env`(Secret file)다. 값이
  해시에 들어가 바꾸면 다음 빌드가 그 앱을 저절로 다시 굽는다 — 「값을 바꾸면 CI 를 다시 돌려야」
  규칙이 저절로 된다. ghcr 쓰기 토큰은 `ghcr-push-token`.
- `Jenkinsfile` 은 PR CI 가 보지 못한다. 그 파일을 바꾸는 PR 은 병합 전에 그 브랜치를 가리키는 임시
  잡으로 `IMAGES_ONLY=true` 를 돌려 본다.
- 이미지 굽기가 다시 sub 에 얹힌다. 디스크 대기가 다시 오르면 amd64 를 Jenkins 노드 `desktop`(Linux
  amd64)으로 옮긴다 — 그때는 거기 buildx 가 필요하다.
- 둘째 단계(Next 세 앱을 한 이미지로, #706)는 따로 간다.
