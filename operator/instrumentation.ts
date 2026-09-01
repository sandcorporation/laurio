// 부팅 시점 설정 가드 (#63, ADR-0019 — frontend/instrumentation.ts와 같은 원칙).
//
// 배포 환경(staging/production)에서 필수 설정이 비어 있으면 첫 요청을 받기 전에
// 부팅 자체를 거부한다. backend/config/settings.py의 OPERATOR_WEB_ORIGIN 가드가
// "LAURIO_OPERATOR_ORIGIN이 배포 환경에서 비어 있으면 부팅을 거부한다"고 이미
// 정했다 — 이 앱도 자기 쪽에서 같은 값을 요구해야, 둘 중 하나만 잊혀 "한쪽은
// 있는데 한쪽은 없어 모든 요청이 조용히 403"이 되는 사고(README의 "이미 두 번
// 맞은 실패")를 부팅 시점에 막는다.
const REQUIRED_IN_DEPLOYED_ENVIRONMENTS: Array<{ name: string; reason: string }> = [
  {
    name: "LAURIO_OPERATOR_ORIGIN",
    reason:
      "배포 환경에서는 Origin 검증(lib/backend.ts의 operatorOrigin)이 Host 헤더 " +
      "유도가 아니라 이 값에 의존해야 한다 — 백엔드의 OPERATOR_WEB_ORIGIN과 어긋나면 " +
      "로그인을 포함한 모든 변경 요청이 403이 되고, 그 실패는 로그를 남기지 않는다.",
  },
  {
    name: "LAURIO_API_BASE_URL",
    reason:
      "이 값이 비어 있으면 lib/backend.ts의 backendBaseUrl이 127.0.0.1:58000(자기 " +
      "자신)으로 조용히 폴백해 로그인·조회가 전부 연결 거부로 실패한다.",
  },
];

export async function register(): Promise<void> {
  if (process.env.NEXT_RUNTIME !== "nodejs") return;

  const target = process.env.LAURIO_DEPLOYMENT_TARGET;
  const isDeployed = target === "staging" || target === "production";
  if (!isDeployed) return;

  const missing = REQUIRED_IN_DEPLOYED_ENVIRONMENTS.filter(({ name }) => !process.env[name]);
  if (missing.length === 0) return;

  const detail = missing.map(({ name, reason }) => `- ${name}: ${reason}`).join("\n");
  const message = `LAURIO_DEPLOYMENT_TARGET=${target} 인데 다음 필수 설정이 비어 있다:\n${detail}`;

  // frontend/instrumentation.ts가 이미 겪은 함정: `throw`만으로는 부팅이
  // 실패하지 않는다 — Next가 unhandledRejection으로 로그만 찍고 삼켜 HTTP
  // 서버는 계속 듣고 있는다. 그래서 로그를 남긴 뒤 process.exit(1)로 직접
  // 프로세스를 끊는다.
  console.error(message);
  process.exit(1);
}
