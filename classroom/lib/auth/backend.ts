// 서버 전용. 이 앱이 Django를 부를 때 쓰는 베이스 URL이다 — 공개 앱·운영자 앱과
// 같은 패턴(각 앱의 lib/auth/backend.ts 참고).
export function backendBaseUrl(): string {
  return process.env.LAURIO_API_BASE_URL ?? "http://127.0.0.1:58000";
}
