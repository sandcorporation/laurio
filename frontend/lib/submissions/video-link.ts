// 시연 영상 링크(`video_link`, #910) — 주소 검사와 유튜브 임베드.
//
// 백엔드 `submissions/video_link.py` 가 정본이고 이 파일은 같은 규칙으로 미리 막는다.
// iframe 의 src 는 **받은 URL 이 아니라 뽑은 id 로 만든다** — 주소 모양이 무엇이든 임베드가
// 가리키는 곳은 `youtube-nocookie.com/embed/<11자 id>` 하나뿐이다.

const VIDEO_LINK_MAX_LENGTH = 2000;
const YOUTUBE_ID = /^[A-Za-z0-9_-]{11}$/;
const YOUTUBE_HOSTS = new Set([
  "youtube.com",
  "www.youtube.com",
  "m.youtube.com",
  "youtu.be",
  "www.youtu.be",
]);

export const VIDEO_LINK_SHAPE_MESSAGE =
  "http:// 또는 https:// 로 시작하는 주소만 받습니다(아이디·비밀번호가 든 주소는 안 됩니다).";

function parse(raw: string): URL | null {
  const value = raw.trim();
  if (!value || value.length > VIDEO_LINK_MAX_LENGTH) return null;
  try {
    return new URL(value);
  } catch {
    return null;
  }
}

/** http(s)·호스트 있음·사용자 정보 없음 — 백엔드 `is_safe_video_link` 와 같다. */
export function isSafeVideoLink(raw: string): boolean {
  const url = parse(raw);
  if (url === null) return false;
  if (url.protocol !== "http:" && url.protocol !== "https:") return false;
  if (!url.hostname) return false;
  // `https://@host` 처럼 빈 사용자 정보도 거절한다(URL 은 그것을 username "" 로 지운다).
  return url.username === "" && url.password === "" && !raw.trim().split("//")[1]?.split("/")[0]?.includes("@");
}

/** 유튜브 영상 id. 유튜브 주소가 아니거나 id 모양이 이상하면 null. */
export function youtubeVideoId(raw: string): string | null {
  if (!isSafeVideoLink(raw)) return null;
  const url = parse(raw)!;
  const host = url.hostname.toLowerCase();
  if (!YOUTUBE_HOSTS.has(host)) return null;

  let candidate: string | null = null;
  if (host.endsWith("youtu.be")) {
    candidate = url.pathname.split("/")[1] ?? null;
  } else if (url.pathname === "/watch") {
    candidate = url.searchParams.get("v");
  } else if (url.pathname.startsWith("/shorts/")) {
    candidate = url.pathname.split("/")[2] ?? null;
  }
  return candidate !== null && YOUTUBE_ID.test(candidate) ? candidate : null;
}

/** 임베드 주소 — id 와 시작 초(정수)만 들어간다. */
export function youtubeEmbedUrl(id: string, startSeconds = 0): string | null {
  if (!YOUTUBE_ID.test(id)) return null;
  const base = `https://www.youtube-nocookie.com/embed/${id}`;
  const start = Math.floor(startSeconds);
  return Number.isFinite(start) && start > 0 ? `${base}?start=${start}` : base;
}

/** 확인 위치의 시각 → 초. `1:23`·`01:02:03`·`83`·`1m23s`·`1h2m3s`. 못 읽으면 null. */
export function timestampSeconds(raw: string): number | null {
  const value = raw.trim().toLowerCase();
  if (/^\d+$/.test(value)) return Number(value);
  const clock = /^(?:(\d{1,2}):)?(\d{1,3}):(\d{1,2})$/.exec(value);
  if (clock) {
    return Number(clock[1] ?? 0) * 3600 + Number(clock[2]) * 60 + Number(clock[3]);
  }
  const units = /^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$/.exec(value);
  if (units && (units[1] || units[2] || units[3])) {
    return Number(units[1] ?? 0) * 3600 + Number(units[2] ?? 0) * 60 + Number(units[3] ?? 0);
  }
  return null;
}
