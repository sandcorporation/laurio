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
// 항목을 함께 추가해뒀다 — FE-13(#38)이 compose.staging.yaml/compose.prod.yaml에
// frontend 서비스를 붙이며 LAURIO_DEPLOYMENT_TARGET을 주입하는 순간부터 이
// 가드가 즉시 작동한다.
//
// FE-13(#38) 추가 — LAURIO_API_BASE_URL도 같은 이유로 여기 합류한다.
// lib/api/client.ts·lib/auth/backend.ts·app/healthz/route.ts 셋 다
// `process.env.LAURIO_API_BASE_URL ?? "http://127.0.0.1:58000"` 폴백을 쓴다.
// dev(compose 네트워크 안에서 backend 호스트명이 항상 해석된다)에는 그 폴백이
// 무해하지만, 배포 환경에서 이 값이 빠지면 프론트가 자기 자신의 루프백으로
// 로그인·조회·제출 요청을 쏘려 하며 전부 연결 거부로 조용히 죽는다 — 502가
// 아니라 "이유를 알 수 없는 500/타임아웃"으로 보인다. LAURIO_WEB_ORIGIN과 같은
// 자리에서 같은 원칙으로 막는다: 값이 비어 있으면 첫 요청 전에 부팅을 거부한다.
//
// 두 검사를 한 번에 모아 던진다 — 이 파일이 "배포 환경 필수 설정"의 유일한
// 집합소여야 한다는 지침(#38) 그대로다. 앞으로 배포 전용 필수값이 늘어나면
// 여기 배열에 추가한다.
const REQUIRED_IN_DEPLOYED_ENVIRONMENTS: Array<{ name: string; reason: string }> = [
  {
    name: "LAURIO_WEB_ORIGIN",
    reason:
      "배포 환경에서는 Origin 검증(lib/auth/origin.ts)이 Host 헤더 유도가 아니라 " +
      "이 값에 의존해야 한다 — 리버스 프록시가 X-Forwarded-Proto를 빠뜨리면 모든 " +
      "변경 요청이 403이 되는 사고를 부팅 시점에 막는다.",
  },
  {
    name: "LAURIO_API_BASE_URL",
    reason:
      "이 값이 비어 있으면 lib/api/client.ts·lib/auth/backend.ts·app/healthz/route.ts가 " +
      "모두 127.0.0.1:58000(자기 자신)으로 조용히 폴백해 로그인·조회·제출이 전부 " +
      "연결 거부로 실패한다 — 배포 환경에서는 실제 backend 주소를 명시적으로 요구한다.",
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

  // FE-13(#38) 발견: `throw` 만으로는 부팅이 실패하지 않는다 — standalone
  // 산출물의 `node server.js`(compose.staging/prod.yaml이 실제로 도는 그 실행
  // 파일)로 직접 재현해 확인했다. register()의 에러는 Next가 "unhandledRejection"
  // 으로 로그만 찍고 삼켜, HTTP 서버는 계속 듣고 있다가 모든 요청에 이유 없는
  // 500을 낸다 — 컨테이너는 Up 상태로 남고 `restart: unless-stopped`도 재시작할
  // 계기를 못 잡는다. 이건 이 티켓의 핵심 인수조건("부팅 시점에 시끄럽게
  // 실패한다")을 문자 그대로 어긴다 — 시끄럽긴 하지만 실패하지 않는다. 그래서
  // 로그를 남긴 뒤 `process.exit(1)`로 직접 프로세스를 끊는다 — backend가
  // `manage.py check`의 비정상 종료 코드로 부팅을 막는 것과 같은 결과를
  // Next.js의 삼킴을 우회해서 만든다.
  console.error(message);
  process.exit(1);
}
