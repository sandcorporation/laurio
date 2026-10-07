import path from "node:path";

import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // 배포 이미지를 얇게 유지한다. 티켓 FE-13(#38)이 이 산출물을 쓴다.
  //
  // 주의: standalone 은 심볼릭 링크를 만들기 때문에 Windows 호스트에서 `pnpm build`
  // 가 EPERM 으로 실패한다(개발자 모드/관리자 권한이 없으면). 코드 문제가 아니라
  // 호스트 제약이다 — 리눅스인 컨테이너와 CI 에서는 정상이다. Windows 에서 빌드를
  // 확인하려면 컨테이너 안에서 돌린다:
  //   docker compose -f docker/compose.dev.yaml exec frontend pnpm build
  output: "standalone",
  // 저장소 루트가 pnpm 워크스페이스가 됐다(운영자 앱 04 #62) — Next가 파일
  // 추적(file tracing)의 기준을 자동으로 워크스페이스 루트(락파일이 있는 곳)로
  // 잡으므로, standalone 산출물이 `frontend/` 하위 구조를 그대로 보존한다
  // (`.next/standalone/frontend/server.js`). 명시하지 않아도 Next가 같은 값을
  // 추론하지만, 그 추론이 "다른 락파일을 찾았다"는 경고에 흔들리지 않도록 여기서
  // 고정한다 — docker/frontend.Dockerfile의 runner 스테이지가 이 경로를 그대로
  // 안다.
  outputFileTracingRoot: path.join(__dirname, ".."),
  // packages/bff-shared는 별도로 빌드되지 않는 워크스페이스 소스 패키지다
  // (main이 ./src/index.ts를 직접 가리킨다) — Next의 webpack/SWC 로더가 이
  // 패키지도 앱 코드처럼 컴파일하게 한다.
  transpilePackages: [
    "@codemit/banned-words",
    "@codemit/bff-shared",
    "@codemit/bff-client",
    "@codemit/markdown",
  ],
  // 공개 표면은 서버에서 렌더링되어야 색인된다(ADR-0015). 실수로 클라이언트
  // 렌더링이 되면 조용히 깨지므로, e2e 가 JS 를 끈 HTML 을 직접 확인한다.
  reactStrictMode: true,
  // 미들웨어의 request.url 을 NextURL 로 정규화하지 않는다(#622) — 정규화는 쿼리 안
  // 127.0.0.1 을 localhost 로 바꿔 로그인 next 의 OAuth redirect_uri 를 깬다.
  skipMiddlewareUrlNormalize: true,
  webpack: (config, { dev }) => {
    // dev 컨테이너는 소스를 바인드 마운트로 받는데(docker/compose.dev.yaml),
    // Windows 호스트 → Linux 컨테이너 바인드 마운트에서는 기본 fs 이벤트 감시가
    // 파일 변경을 놓칠 수 있어 폴링으로 강제한다. 이 설정이 처음 들어온 이유는
    // `frontend/e2e/tokens.spec.ts` 가 app/tokens.css 를 실제로 편집했기
    // 때문이었지만(FE-02, #27), 그 스펙은 01a4ae3 에서 지워졌다 — 설정은 남긴다:
    // 바인드 마운트 위의 핫리로드가 그 스펙 없이도 같은 이유로 필요하다.
    if (dev) {
      config.watchOptions = {
        ...config.watchOptions,
        poll: 1000,
        aggregateTimeout: 300,
      };
    }
    return config;
  },
};

export default nextConfig;
