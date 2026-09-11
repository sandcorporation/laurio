// 백엔드 응답 본문을 안전하게 읽는다 — 공개 앱(frontend/lib/auth/http.ts)과 같은
// 계약이다. raw fetch로 백엔드를 직접 부를 때는 빈 본문에서 res.json()이 그냥
// 던진다.
export async function safeJson(response: Response): Promise<unknown | null> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}
