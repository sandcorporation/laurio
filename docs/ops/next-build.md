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
