// 공개 앱(frontend/lib/auth/jwt.ts)과 같은 낙관적 판정이다 — 서명 검증 없이 exp만
// 본다. **인가 판단에는 쓰지 않는다.** 실제 서명·만료·블랙리스트 검증은 언제나
// 백엔드(accounts.middleware.JWTAuthenticationMiddleware)가 한다.

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

export function isExpired(token: string, skewSeconds = 5): boolean {
  const payload = decodeJwtPayload(token);
  const exp = payload?.exp;
  if (typeof exp !== "number") return true;
  return Date.now() / 1000 >= exp - skewSeconds;
}
