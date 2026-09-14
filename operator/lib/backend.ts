// 서버 전용. 인증 구역(BFF)이 Django를 부를 때 쓰는 베이스 URL과, 그 요청에
// 실어 보낼 Origin이다(#63, ADR-0019).
//
// frontend/lib/auth/backend.ts와 같은 패턴 — 컨테이너 안에서는 compose 네트워크
// 이름(backend:8000)으로 붙고, 호스트에서 직접 돌릴 때는 로컬 기본값을 쓴다.
export function backendBaseUrl(): string {
  return process.env.CODEMIT_API_BASE_URL ?? "http://127.0.0.1:58000";
}

// 백엔드의 OperatorOriginMiddleware(backend/core/operator_auth.py)가 변경
// 요청의 Origin을 OPERATOR_WEB_ORIGIN 과 비교한다. 브라우저가 이 BFF로 보내는
// 요청과 달리, 이 BFF가 Django로 보내는 요청은 서버 대 서버 호출이라 Origin이
// 자동으로 실리지 않는다 — 그래서 명시적으로 붙여야 한다.
//
// `CODEMIT_OPERATOR_ORIGIN`이 설정돼 있으면(배포 환경) 그 값을 그대로 쓴다 —
// 백엔드가 읽는 `OPERATOR_WEB_ORIGIN`과 정확히 같은 환경변수 이름이다(두 앱이
// 같은 값을 공유해야 한다는 사실 자체를 이름으로 드러낸다, ADR-0019 인수조건
// "declared origin과 백엔드의 expected operator origin이 서로 검증된다").
//
// 비어 있으면(dev) `backendBaseUrl()`을 그대로 쓴다 — 백엔드도 이 값이 비어
// 있을 때 자기가 실제로 연결을 받은 Host 헤더로 기대 오리진을 유도하는데
// (`allowed_operator_origin`, core/operator_auth.py), 이 BFF가 Django에 접속하는
// 목적지 URL이 바로 그 Host 헤더가 된다 — 그래서 같은 값이 된다.
export function operatorOrigin(): string {
  return process.env.CODEMIT_OPERATOR_ORIGIN || backendBaseUrl();
}
