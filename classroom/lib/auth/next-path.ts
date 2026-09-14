// 강의실 쪽 next 검증(#334) — middleware.ts가 `/login?next=<원래 경로>`로 실어
// 보낸 값과 가입 화면(`/join/{code}`)의 "로그인하러 가기" 링크가 붙이는 값을,
// 공개 앱으로 넘기기 전에 이 앱 안의 상대 경로인지 확인한다. 검증 없이 그대로
// 실으면 그 값이 공개 앱의 `next`로 왕복해 돌아올 때(#297 후속) 오픈 리다이렉트
// 표면이 새로 열린다.
//
// frontend/lib/auth/next-path.ts의 isSafeNextPath와 같은 기법이다 — 문자
// 블랙리스트가 아니라 placeholder 오리진을 기준으로 실제 `new URL()` 파싱
// 결과를 본다: backslash가 "/"로 정규화되는 것도, 제어문자가 조용히 제거되는
// 것도 파싱 결과가 그 오리진을 벗어났는지로 구조적으로 잡힌다.
//
// **`string[]`도 받는다** — Next.js App Router의 `searchParams`는 같은 쿼리
// 키가 반복되면(`?next=/a&next=/b`) 배열을 준다. 페이지의 타입 선언
// (`{ next?: string }`)은 이걸 강제하지 않는다 — 그 타입을 믿고
// `next.startsWith(...)`을 바로 부르면 배열에는 그 메서드가 없어 런타임에
// 터진다(코드리뷰 지적, 실제로 재현된다). 배열은 "어느 값이 진짜인지" 판단할
// 근거가 없으므로 안전하지 않은 값으로 취급해 그대로 거부한다.
const SAFE_NEXT_PATH_BASE = "http://codemit-classroom-internal.invalid";

export function isSafeNextPath(next: string | string[] | null | undefined): next is string {
  if (!next) return false;
  if (Array.isArray(next)) return false;
  if (!next.startsWith("/")) return false;

  let resolved: URL;
  try {
    resolved = new URL(next, SAFE_NEXT_PATH_BASE);
  } catch {
    return false;
  }

  return resolved.protocol === "http:" && resolved.host === "codemit-classroom-internal.invalid";
}

export function resolveNextPath(next: string | string[] | null | undefined, fallback = "/"): string {
  return isSafeNextPath(next) ? next : fallback;
}
