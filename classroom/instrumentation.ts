// 부팅 시점 설정 가드 (ADR-0016/0019/0037과 같은 원칙, #276/#277). 공개 앱·
// 운영자 앱의 instrumentation.ts와 같은 모양이다 — 배포 환경(staging/production)
// 에서 필수 설정이 비어 있으면 첫 요청을 받기 전에 부팅 자체를 거부한다.
const REQUIRED_IN_DEPLOYED_ENVIRONMENTS: Array<{ name: string; reason: string }> = [
  {
    name: "CODEMIT_CLASSROOM_ORIGIN",
    reason:
      "배포 환경에서는 Origin 검증(lib/auth/origin.ts)이 Host 헤더 유도가 아니라 " +
      "이 값에 의존해야 한다 — 리버스 프록시가 X-Forwarded-Proto를 빠뜨리면 모든 " +
      "변경 요청이 403이 되는 사고를 부팅 시점에 막는다.",
  },
  {
    name: "CODEMIT_API_BASE_URL",
    reason:
      "이 값이 비어 있으면 lib/auth/backend.ts의 backendBaseUrl이 127.0.0.1:58000" +
      "(자기 자신)으로 조용히 폴백해 백엔드로 가는 모든 요청이 연결 거부로 실패한다.",
  },
  {
    name: "CODEMIT_SESSION_COOKIE_DOMAIN",
    reason:
      "부모 도메인을 주지 않으면 lib/auth/cookies.ts가 dev와 동일하게 domain을 " +
      "생략한다 — 공개 앱이 심은 세션 쿠키가 이 서브도메인으로 오지 않아 " +
      "「한 번 로그인하면 두 제품이 다 열린다」는 약속이 깨진다(ADR-0038).",
  },
];

export async function register(): Promise<void> {
  if (process.env.NEXT_RUNTIME !== "nodejs") return;

  const target = process.env.CODEMIT_DEPLOYMENT_TARGET;
  const isDeployed = target === "staging" || target === "production";
  if (!isDeployed) return;

  const missing = REQUIRED_IN_DEPLOYED_ENVIRONMENTS.filter(({ name }) => !process.env[name]);
  if (missing.length === 0) return;

  const detail = missing.map(({ name, reason }) => `- ${name}: ${reason}`).join("\n");
  const message = `CODEMIT_DEPLOYMENT_TARGET=${target} 인데 다음 필수 설정이 비어 있다:\n${detail}`;

  // 공개 앱이 이미 겪은 함정: `throw`만으로는 부팅이 실패하지 않는다 — Next가
  // unhandledRejection으로 로그만 찍고 삼켜 HTTP 서버는 계속 듣고 있는다.
  console.error(message);
  process.exit(1);
}
