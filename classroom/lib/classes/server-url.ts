// 호환 서버 주소 판정 — 브라우저 기본 풍선(type=url) 대신 앱 문장으로 말한다(#1455 3번).
export const SERVER_URL_MESSAGE = "서버 주소를 https://llm.example.com/v1 꼴로 넣어 주세요.";

export type ServerUrlResult = { ok: true; url: string } | { ok: false; message: string };

/** 빠진 스킴은 https:// 로 받아 주고, 주소로 읽을 수 없거나 http(s) 가 아니면 거절한다. */
export function normalizeServerUrl(input: string): ServerUrlResult {
  const trimmed = input.trim();
  const refused: ServerUrlResult = { ok: false, message: SERVER_URL_MESSAGE };
  if (trimmed === "" || /\s/.test(trimmed)) return refused;
  const candidate = /^[a-z][a-z0-9+.-]*:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
  try {
    const parsed = new URL(candidate);
    if ((parsed.protocol !== "https:" && parsed.protocol !== "http:") || parsed.hostname === "") return refused;
  } catch {
    return refused;
  }
  return { ok: true, url: candidate };
}
