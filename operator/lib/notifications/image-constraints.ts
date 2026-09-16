// 운영팀 알림 이미지의 형식·크기 제한 — 백엔드
// `backend/notifications/operator_notice_images.py`의 `ALLOWED_CONTENT_TYPES`·
// `MAX_IMAGE_BYTES`를 그대로 화면 쪽에 옮겨 적었다(#424). 실제 강제는 여전히
// 서버(presigned POST 정책)가 한다 — 여기는 네트워크 왕복 없이 「형식·크기가
// 맞지 않으면 이유를 보인다」(#424 AC)를 올리기 전에 보여주기 위한 것뿐이다.
export const ALLOWED_IMAGE_CONTENT_TYPES = ["image/png", "image/jpeg", "image/webp"] as const;
export const MAX_IMAGE_BYTES = 5 * 1024 * 1024;

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${Math.round(kb)}KB`;
  return `${(kb / 1024).toFixed(1)}MB`;
}

export function validateImageFile(file: File): string | null {
  if (!ALLOWED_IMAGE_CONTENT_TYPES.includes(file.type as (typeof ALLOWED_IMAGE_CONTENT_TYPES)[number])) {
    return "png·jpeg·webp 형식만 올릴 수 있습니다.";
  }
  if (file.size > MAX_IMAGE_BYTES) {
    return `이미지는 ${formatFileSize(MAX_IMAGE_BYTES)}까지 올릴 수 있습니다.`;
  }
  return null;
}
