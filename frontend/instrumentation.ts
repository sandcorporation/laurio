// 부팅 시점 설정 가드 (ADR-0016 — 코드리뷰 지적 수정).
//
// backend/config/settings.py의 IS_DEPLOYED_ENVIRONMENT 가드와 같은 원칙을
// 프론트엔드에도 세운다: 배포 환경(staging/production)에서 필수 설정이
// 비어 있으면 첫 요청을 받기 전에 부팅 자체를 거부한다 — "설정이 비어 있는
// 채로 조용히 뜬다"는 실패 모드를 애초에 없앤다.
//
// LAURIO_WEB_ORIGIN이 그 대상이다. lib/auth/origin.ts의 assertSameOrigin은
// 이 값이 없으면 요청의 Host 헤더로 오리진을 유도하는 폴백을 쓰는데, 그
// 폴백은 dev(리버스 프록시 없이 컨테이너 포트를 직접 노출)에는 맞지만
// 배포 환경에서 TLS 종단 리버스 프록시가 X-Forwarded-Proto를 빠뜨리면
// (또는 Host 헤더가 프록시 뒤에서 내부 주소로 바뀌면) 유도된 오리진이
// 브라우저가 보낸 Origin과 어긋난다 — CSRF 방어가 fail-closed라 보안
// 구멍은 아니지만, 그 순간부터 모든 POST/PUT/PATCH/DELETE가 403이 되어
// 로그인부터 아무것도 안 된다. 폴백에 기대지 말고, 배포 환경에서는 이
// 값을 명시적으로 요구한다.
//
// Next.js가 이 파일의 register()를 서버 프로세스 시작 시 정확히 한 번
// 호출한다(Node.js 런타임 인스턴스마다). 여기서 에러를 던지면 프로세스가
// 그대로 죽는다 — backend의 `${VAR:?...}` compose 가드, JWT_SIGNING_KEY
// 부팅 가드와 같은 "설정이 없으면 뜨지 않는다" 규율을 그대로 반복한다.
//
// docker/staging.env.example, docker/prod.env.example에 LAURIO_WEB_ORIGIN
// 항목을 함께 추가해뒀다 — 이 값을 소비할 frontend 서비스 자체는 아직
// compose.staging.yaml/compose.prod.yaml에 없다(FE-13, #38이 붙인다).
// 그 티켓이 LAURIO_DEPLOYMENT_TARGET을 frontend 컨테이너에 주입하는 순간
// 이 가드가 즉시 작동한다 — 별도로 이 파일을 다시 손볼 필요가 없다.
export async function register(): Promise<void> {
  if (process.env.NEXT_RUNTIME !== "nodejs") return;

  const target = process.env.LAURIO_DEPLOYMENT_TARGET;
  const isDeployed = target === "staging" || target === "production";

  if (isDeployed && !process.env.LAURIO_WEB_ORIGIN) {
    throw new Error(
      `LAURIO_DEPLOYMENT_TARGET=${target} 인데 LAURIO_WEB_ORIGIN 이 비어 있다. ` +
        "배포 환경에서는 Origin 검증(lib/auth/origin.ts)이 Host 헤더 유도가 아니라 " +
        "이 값에 의존해야 한다 — 리버스 프록시가 X-Forwarded-Proto를 빠뜨리면 모든 " +
        "변경 요청이 403이 되는 사고를 부팅 시점에 막는다.",
    );
  }
}
