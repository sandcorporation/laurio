import path from "node:path";

import type { NextConfig } from "next";

// 강의실(#276, ADR-0037) — 공개 앱·운영자 앱과 같은 워크스페이스 기반 standalone
// 설정이다. SSR을 요구받지 않는다(ADR-0015는 공개 표면에만 SSR을 요구했고, 이
// 앱은 로그인한 사람만 보므로 색인될 이유가 없다 — 운영자 앱과 같은 이유,
// ADR-0021).
const nextConfig: NextConfig = {
  output: "standalone",
  outputFileTracingRoot: path.join(__dirname, ".."),
  transpilePackages: ["@laurio/bff-shared", "@laurio/bff-client"],
  reactStrictMode: true,
  webpack: (config, { dev }) => {
    // 운영자 앱과 같은 이유 — dev 컨테이너가 소스를 바인드 마운트로 받는데,
    // Windows 호스트 → Linux 컨테이너 바인드 마운트에서는 기본 fs 이벤트 감시가
    // 파일 변경을 놓칠 수 있어 폴링으로 강제한다.
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
