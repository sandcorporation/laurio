# PR 검사를 GitHub 호스팅 Actions 에서도 돌린다 — 저장소 공개 준비

Status: Accepted (2026-11-09 결정)

## 맥락 (#930)

대표 결정(2026-11-09): 저장소 `sandcorporation/laurio` 를 GitHub public 으로 바꿀 준비를 한다. 공개 저장소의 PR 은
누구나 열 수 있고, 지금 PR 검사는 Jenkins `codemit/ci-pr` 가 우리 노드(macos·home)에서 돈다. 공개 뒤에는 바깥 사람의
코드를 우리 노드에서 돌리지 않는 편이 낫고, 공개 저장소의 GitHub 호스팅 실행기는 분량 제한이 없다.

ADR-0061(2026-10-15)은 Actions 를 떠났다. 그 까닭은 비공개 저장소의 Free 요금제 분량(월 2,000분)이 바닥난 것과
두 체계를 함께 유지하는 비용이었다. 공개 저장소에서는 앞의 까닭이 사라진다.

## 결정

- **PR 검사를 `.github/workflows/pr-check.yml` 에서도 돌린다.** 트리거는 `pull_request` 와 `main` push 다.
- **검사 내용은 Jenkins 와 같은 스크립트를 부른다.** `changed.sh`(문서만이면 ADR 검사만), `sub-checks.sh`,
  `deploy-guard.sh`, `e2e.sh`, `celery-broker.sh` 다. 워크플로에는 검사를 새로 쓰지 않는다 — 두 곳이 다른 검사를 하지
  않게 한다. 잡을 나눠 병렬로 돌리고, 마지막 잡 `결과` 가 하나의 필수 검사 이름이 된다.
- **보안 규칙**: `pull_request_target` 을 쓰지 않는다. GitHub 호스팅 실행기만 쓴다(self-hosted 금지). secrets 를 쓰지
  않는다 — 값은 `scripts/ci/*.env` 의 CI 전용 가짜 값이다. `permissions: contents: read`, 체크아웃은
  `persist-credentials: false`, 액션은 공식 것만 SHA 로 고정한다.
- **배포는 Jenkins 에 둔다.** `main` push → `codemit/deploy` 그대로다(ADR-0068·0071).
- **병합 기준은 Actions 「결과」 잡이다**(2026-11-09 대표 결정 보충). Jenkins `codemit/ci-pr` 는 대장이 끄기 전까지 함께
  돌지만 기다리지 않고 결과도 병합 조건이 아니다.

## Jenkins 와 다른 것

- Actions 는 이미지를 **amd64 로 실행기 안에서** 굽고 레지스트리에 올리지 않는다. 그래서 「시험한 digest = 배포할 digest」
  (Jenkins 의 `images.sh arm64` → e2e, ctx·e2e 태그)는 Actions 에 없다. Jenkins PR 검사를 끄면 배포 잡이 언제나 직접 굽고
  가드하며, prod 의 「e2e 대조」는 「대조 못 함」이 된다(관측만이라 배포를 막지 않는다).
- e2e 는 호스팅 실행기에서 돈다. 시험 하나 3초·재시도 0(playwright.config.ts)은 그대로이고, 코어가 적어 Playwright 일꾼을 하나로 준다(`CODEMIT_E2E_WORKERS=1` — 둘이면 3초를 넘었다).

## 결과

- 비공개인 동안 Actions 실행은 조직의 Free 분량을 쓴다. PR 하나가 잡 여섯(분 단위 올림)이라 분량이 빨리 준다 — 공개
  전환이 늦어지면 ADR-0061 의 바닥이 다시 온다.
- ADR-0061 의 「Actions 를 떠난다」 중 PR 검사 부분을 이 결정이 고친다(Amended).
