// frontend/lib/auth/http.ts와 같은 이유 — 백엔드 응답 본문을 안전하게 읽는다.
// 빈 본문(204 등)에서 res.json()이 던지는 것을 원인 모를 500 대신 null로 좁힌다.
export async function safeJson(response: Response): Promise<unknown | null> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}
