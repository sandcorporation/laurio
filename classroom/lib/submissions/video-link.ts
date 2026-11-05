// 시연 영상 링크(`video_link`, #910·#921) — 제출 전에 주소 모양을 미리 막는다.
//
// 정본은 백엔드 `submissions/video_link.py` 이고, 공개 앱 `frontend/lib/submissions/video-link.ts`
// 가 같은 규칙을 쓴다. 이 앱은 워크스페이스 공유 패키지가 아직 없어(새 패키지는 Dockerfile 둘과
// compose 볼륨까지 손으로 더해야 한다) 검사 함수 하나만 복사했다 — 규칙을 바꾸면 세 곳을 함께 고친다.

const VIDEO_LINK_MAX_LENGTH = 2000;

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
