import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // 배포 이미지를 얇게 유지한다. 티켓 FE-13(#38)이 이 산출물을 쓴다.
  output: "standalone",
  // 공개 표면은 서버에서 렌더링되어야 색인된다(ADR-0015). 실수로 클라이언트
  // 렌더링이 되면 조용히 깨지므로, e2e 가 JS 를 끈 HTML 을 직접 확인한다.
  reactStrictMode: true,
};

export default nextConfig;
