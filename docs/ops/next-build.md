# Next 프로덕션 빌드

`CLAUDE.md` 의 부록이다 — 거기서 앵커로 가리키고, 같은 「지금」을 말한다.

**세 앱의 프로덕션 빌드는 Turbopack 이다**(`"build": "next build --turbopack"`, 2026-10-02). webpack
빌드는 호스티드 러너에서 frontend 하나가 2~2.5분이었고(컴파일 37초·추적 수집 52초), 같은 4코어로 잰
로컬 빌드가 54초 → 37.5초가 됐다(컴파일 17.5 → 8.8초). 추적 수집은 Turbopack 에서도 Next 의 nft 가
메인 스레드에서 파일을 하나씩 파싱하는 일이라 약 20초가 남는다 — `outputFileTracingExcludes` 로
빌드 도구를 빼도 7초쯤만 준다. dev(`next dev`)는 그대로 webpack 이다.

**그래서 세 앱이 `require-in-the-middle`·`import-in-the-middle` 을 직접 의존성으로 갖는다** — 코드
어디에서도 import 하지 않지만 **지우면 안 된다.** Sentry 서버 계측(OpenTelemetry)이 쓰는 둘을
Turbopack 은 번들하지 않고 외부 패키지로 남기는데, pnpm 에서는 앱 디렉터리에서 풀리지 않아
「can't be external」 경고와 함께 standalone 에서 빠진다(webpack 은 번들 안에 넣어 문제가
없었다). 앱에 직접 넣어야 standalone 에 실린다. Sentry DSN 을 구워 넣은 Turbopack·webpack 이미지를
가짜 수집기 앞에 띄워 서버 오류가 둘 다 같은 이벤트로 도착하는 것을 확인했다 — CI e2e 는 DSN 이
없어 Sentry 가 꺼진 채로 돌므로 이 실패를 보지 못한다.

**공개 값은 빌드에 굽지 않는다**(#711, ADR-0062). 세 앱에 `NEXT_PUBLIC_*` 가 없다 — Next 가 그
접두어의 `process.env.X` 를 빌드 때 번들에 문자열로 박기 때문이다. 브라우저가 알아야 할 값(Sentry
DSN·환경·release, 토스 클라이언트 키, 포트원 둘, 문의 주소, 공모전 스위치)은 실행 env
`CODEMIT_PUBLIC_*` 로 받고, 루트 레이아웃이 `<head>` 의 `window.__CODEMIT_PUBLIC__` 로 넘긴다
(`<앱>/lib/public-config.ts` — 목록에 있는 이름만 간다). 루트 레이아웃이 `force-dynamic` 이라 요청마다
그리므로 빌드 머신의 빈 값이 HTML 에 박히지 않는다. `instrumentation-client.ts` 는 async 라 그
`<script>` 보다 먼저 돌 수 있어, 값이 아직 없으면 `DOMContentLoaded` 까지 Sentry 초기화를 미룬다.
새 공개 값을 더하면 `NEXT_PUBLIC_` 이 아니라 그 목록과 compose 두 파일의 `environment:` 에 더한다.
둘 다 시험이 지킨다(#727): `process.env.NEXT_PUBLIC_` 이 세 앱·`packages/` 에 다시 들어오거나
`next.config.*` 에 `env:` 키가 생기면(#733)
`backend/tests/test_next_public_env_stays_out.py` 가, 목록 이름이 바뀌면 `<앱>/lib/public-config.test.ts` 가
막는다 — 비밀을 `CODEMIT_PUBLIC_*` 이름으로 넣는 실수는 목록 시험에서만 걸린다.

**빌드는 외부 네트워크를 쓰지 않는다 — 글꼴은 저장소 안이다**(#743). 세 앱의 서체(Pretendard,
IBM Plex Mono latin 400·500·600)는 `<앱>/app/fonts/` 의 woff2 를 `next/font/local` 로 읽는다.
`next/font/google` 은 빌드 때마다 fonts.gstatic.com 을 불러, 그 연결이 한 번 끊기자 이미지 굽기가
죽고 열차가 붉었다(#1945). 다시 들어오면 `backend/tests/test_next_font_stays_local.py` 가 막고, 세
사본이 갈리면 `<앱>/lib/design/tokens.test.ts` 가 막는다. 새 굵기·서체가 필요하면 파일을 받아 세
앱에 같이 넣는다.
