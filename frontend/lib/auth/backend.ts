// 서버 전용. 인증 구역(BFF)이 Django를 부를 때 쓰는 베이스 URL이다.
//
// `lib/api/client.ts`(공개 표면 전용, FE-03)와 같은 패턴을 그대로 따른다 —
// 컨테이너 안에서는 compose 네트워크 이름(backend:8000)으로 붙고, 호스트에서
// 직접 돌릴 때는 로컬 기본값을 쓴다. `app/healthz/route.ts`도 같은 함수를 따로
// 갖고 있다 — 셋 다 라우트 핸들러/미들웨어 전용이라 서로 import하지 않아도
// 결합도가 생기지 않는다(공개 클라이언트와 인증 클라이언트를 같은 모듈에 묶으면
// 그 자체가 ADR-0015 경계를 흐리게 한다).
export function backendBaseUrl(): string {
  return process.env.CODEMIT_API_BASE_URL ?? "http://127.0.0.1:58000";
}
