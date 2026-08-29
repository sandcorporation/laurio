// 백엔드 응답 본문을 안전하게 읽는다. openapi-fetch가 아니라 raw fetch로 백엔드를
// 프록시할 때는 빈 본문(204, 502 등)에서 res.json()이 그냥 던진다 — 그 경우
// 원인 모를 500으로 화면이 죽는 대신 null로 좁혀 호출부가 대체 메시지를 쓰게 한다.
export async function safeJson(response: Response): Promise<unknown | null> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}
