import path from "node:path";

import type { NextConfig } from "next";

// 운영자 앱(#63, ADR-0019/0021) — 공개 앱(frontend/next.config.ts)과 같은
// 워크스페이스 기반 standalone 설정이다. SSR 을 요구받지 않는다(ADR-0015 는
// 공개 표면에만 SSR 을 요구했고, 이 앱은 색인될 이유가 없다 — ADR-0021).
const nextConfig: NextConfig = {
  output: "standalone",
  // frontend/next.config.ts와 같은 이유 — 워크스페이스 루트를 명시해 standalone
  // 산출물이 "operator/server.js"처럼 워크스페이스 상대 경로를 그대로 보존하게
  // 한다. docker/operator.Dockerfile의 runner 스테이지가 이 경로를 그대로 안다.
  outputFileTracingRoot: path.join(__dirname, ".."),
  transpilePackages: ["@laurio/bff-shared"],
  reactStrictMode: true,
};

export default nextConfig;
