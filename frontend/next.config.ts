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
  // 공개 표면은 서버에서 렌더링되어야 색인된다(ADR-0015). 실수로 클라이언트
  // 렌더링이 되면 조용히 깨지므로, e2e 가 JS 를 끈 HTML 을 직접 확인한다.
  reactStrictMode: true,
  webpack: (config, { dev }) => {
    // frontend/e2e/tokens.spec.ts 가 app/tokens.css 를 실제로 편집해 "토큰
    // 파일 하나 교체가 화면을 바꾼다"(FE-02, #27)를 증명한다. dev 컨테이너는
    // 소스를 바인드 마운트로 받는데(docker/compose.dev.yaml), Windows 호스트 →
    // Linux 컨테이너 바인드 마운트에서는 기본 fs 이벤트 감시가 파일 변경을
    // 놓칠 수 있어 폴링으로 강제한다.
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
