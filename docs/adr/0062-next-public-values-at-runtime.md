# Next 앱의 공개 값은 빌드가 아니라 실행 때 넣는다 — 앱 이미지를 환경이 아니라 아키텍처로만 가른다

Status: Accepted (2026-10-15 결정)

세 Next 앱은 브라우저가 알아야 할 값 아홉(frontend: Sentry DSN·환경·release, 토스 클라이언트 키,
포트원 store·channel, 방침의 문의 주소, 공모전·유료 공모전 스위치 / operator·classroom: Sentry 셋)을
`NEXT_PUBLIC_*` 로 받았다. Next 는 그 접두어의 `process.env.X` 를 **빌드 때** 번들에 문자열로 박는다.
그래서:

- 같은 코드를 staging 과 prod 로 두 번 구웠다 — 커밋당 이미지가 열둘(여섯 서비스 × 두 환경)이었고,
  앱 셋은 `<sha>-staging`·`<sha>-prod` 로 backend(`<sha>-amd64`·`-arm64`)와 규칙이 달랐다.
- 열차가 e2e 로 시험하는 이미지(값이 빈 채 구운 것)는 배포되는 이미지와 **다른 산출물**이었다 —
  시험한 것이 배포되는 것이라는 보장이 없었다.
- 값의 원본이 서버 env 가 아니라 Jenkins 자격증명 `codemit-images-env` 였다. 같은 키(DSN 등)를 서버
  `.env` 와 그 자격증명 두 곳에서 따로 관리했고, 값을 바꾸면 이미지를 다시 구워야 했다.
- 빌드 인자가 문맥 해시에 들어가, Sentry release 를 HEAD 로 주면 커밋마다 앱을 다시 구웠다 — #707 은
  release 를 「문맥을 마지막으로 바꾼 커밋」으로 우회했다.

결정(#711): 공개 값을 **실행 때** 넣는다. 이름은 `NEXT_PUBLIC_X` → `CODEMIT_PUBLIC_X` 로 1:1 이다(접두어만
바꿔 Next 가 굽지 않게, `PUBLIC` 을 남겨 비밀이 아님을 이름에 둔다).

- 서버(서버 컴포넌트·라우트·`instrumentation.ts`)는 요청 때 `process.env.CODEMIT_PUBLIC_*` 를 읽는다.
- 브라우저는 루트 레이아웃이 `<head>` 에 직렬화한 `window.__CODEMIT_PUBLIC__` 를 읽는다
  (`<앱>/lib/public-config.ts`). 루트 레이아웃은 이미 `force-dynamic` 이라 요청마다 그린다. **목록에 있는
  이름만** 넘어간다 — 비밀이 실수로 브라우저로 가지 않는다.
- `instrumentation-client.ts` 는 async 스크립트라 그 `<script>` 보다 먼저 돌 수 있다 — 값이 아직 없으면
  `DOMContentLoaded` 까지 Sentry 초기화를 미룬다(그 사이 난 오류는 놓친다).
- compose 가 서버의 `.env.<target>` 에서 넣는다 — 대부분 이미 있던 키(`SENTRY_DSN_<앱>`·
  `TOSS_SANDBOX_CLIENT_KEY`/`TOSS_LIVE_CLIENT_KEY`·`PORT_ONE_V2_STORE_ID`·`KG_INICIS_CHANNEL_KEY`·
  `CODEMIT_*_CONTEST_PRODUCT_ENABLED`)를 보간하고 새 키는 `SUPPORT_EMAIL` 하나다. release 는 `deploy.sh`
  가 export 하는 배포 커밋(`SENTRY_RELEASE`)이다.

결과:

- 앱 이미지도 `<sha>-amd64`(staging)·`<sha>-arm64`(prod) — 커밋당 최대 여섯. 열차가 arm64 를 시험하면
  그 이미지가 그대로 prod 에 갈 수 있다(#712).
- `codemit-images-env` 자격증명과 `images.sh` 의 빌드 인자 처리, `image_context.py release` 가 없어졌다.
  #707 의 release 우회도 거뒀다.
- 값을 바꾸면 `.env.<target>` 을 고치고 배포한다 — `deploy.sh plan` 이 떠 있는 앱의 compose 설정 해시를
  (그 컨테이너의 이미지 태그·release 로 고정해) 지금 설정과 견줘, 어긋난 앱을 다시 띄운다.
- 부팅 가드(`scripts/ci/deploy-guard.sh`)는 값을 `-e` 로 주고 `/privacy` 의 문의 주소와 공개 설정
  스크립트의 토스 키(그리고 시크릿이 없음)를 본다. 서버에 값이 있는지는 compose 의 `${…:?}` 가 배포 때 본다.
- 대가: 브라우저 쪽 공개 값이 요청마다 HTML 에 실린다(수백 바이트). 정적으로 구울 수 있던 화면이
  있었다면 그 이점을 잃지만, 세 앱의 루트 레이아웃은 이미 동적이었다.

거절한 길: 값마다 환경별로 굽던 지금 방식을 유지하고 열차만 두 벌 시험하기 — 이미지 수가 줄지 않고
「시험한 것 = 배포되는 것」이 여전히 성립하지 않는다. 이미지 시작 스크립트로 번들 문자열을 치환하기 —
읽기 전용 파일시스템·digest 동일성과 맞지 않고 무엇을 치환했는지가 보이지 않는다.
