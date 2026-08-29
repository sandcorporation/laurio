// JWT payload를 서명 검증 없이 읽는다 — **인가 판단에는 절대 쓰지 않는다.**
//
// 실제 서명·만료·블랙리스트 검증은 항상 백엔드(accounts.middleware.
// JWTAuthenticationMiddleware, accounts.tokens.decode_token)가 한다. 여기서는
// "리프레시가 필요해 보이는 시점"을 미리 알아채 화면이 끊기지 않게 하는 낙관적
// 판단에만 쓴다. 잘못 판단해도(시계 오차, 위조된 payload 등) 안전한 방향으로만
// 어긋난다 — exp를 못 읽으면 만료로 취급해(fail-closed) 리프레시나 재로그인을
// 유도할 뿐, 위조된 토큰을 유효한 것처럼 통과시키는 방향으로는 어긋나지 않는다
// (Authorization 헤더에 그대로 실려 백엔드로 가고, 백엔드가 서명을 검증해 최종
// 판정한다).

export function decodeJwtPayload(token: string): Record<string, unknown> | null {
  const parts = token.split(".");
  if (parts.length !== 3) return null;

  try {
    const normalized = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = normalized.padEnd(normalized.length + ((4 - (normalized.length % 4)) % 4), "=");
    const json = Buffer.from(padded, "base64").toString("utf-8");
    const payload = JSON.parse(json) as unknown;
    return typeof payload === "object" && payload !== null
      ? (payload as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

// skewSeconds: 백엔드 요청 왕복 사이에 만료가 걸리는 걸 막는 여유분이다. 너무 크면
// 아직 유효한 토큰을 조기에 버려 불필요한 리프레시가 늘고, 너무 작으면 "방금 유효
// 판정했는데 백엔드에서 401" 레이스가 늘어난다 — 액세스 토큰 TTL 기본값이 5분
// (backend/config/settings.py ACCESS_TOKEN_TTL)인 것에 비해 5초는 무시할 수 있는
// 비율이라 이 값으로 둔다.
export function isExpired(token: string, skewSeconds = 5): boolean {
  const payload = decodeJwtPayload(token);
  const exp = payload?.exp;
  if (typeof exp !== "number") return true;
  return Date.now() / 1000 >= exp - skewSeconds;
}
