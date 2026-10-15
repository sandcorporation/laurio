// 공유 BFF 패키지의 공개 표면 (ADR-0021). 여기서 내보내는 것은 전부 "검사하는
// 코드"다 — 허용목록의 내용, 인증 방식(JWT vs 세션 쿠키)은 각 앱에 남는다.
export { sanitizeBackendPath, assembleAndVerifyBackendPath } from "./path-safety";
export { isAllowedPath } from "./allowlist";
export { assertSameOrigin } from "./origin";
export { forwardRequest, extractForwardBody, buildForwardHeaders } from "./forward";
export { probeBackendHealth, type BackendProbe } from "./health-probe";
export { retryWhileConnectionRefused, DEFAULT_DELAYS_MS } from "./connect-retry";
