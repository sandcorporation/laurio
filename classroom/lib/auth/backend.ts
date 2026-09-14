// 서버 전용. 이 앱이 Django를 부를 때 쓰는 베이스 URL이다 — 공개 앱·운영자 앱과
// 같은 패턴(각 앱의 lib/auth/backend.ts 참고).
export function backendBaseUrl(): string {
  return process.env.CODEMIT_API_BASE_URL ?? "http://127.0.0.1:58000";
}

// 실시간 신호 SSE 전용 베이스 URL(ADR-0046, #379) — 같은 backend 이미지를
// ASGI로 띄우는 별도 서비스다(`docker/compose.dev.yaml`의 `events`
// 서비스). 기존 API(`backendBaseUrl`)와 프로세스가 다르다 — SSE 연결
// 하나가 동기 gunicorn 워커 풀을 붙잡지 않게 하려는 것이 이 분리의 이유라,
// 강의실 BFF도 스트림 경로만 이쪽으로 보내야 그 분리가 실제로 뜻이 있다
// (`lib/proxy/forward.ts`).
export function eventsBaseUrl(): string {
  return process.env.CODEMIT_EVENTS_BASE_URL ?? "http://127.0.0.1:58001";
}
