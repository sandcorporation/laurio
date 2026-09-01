// `?next=` open redirect 방어 (코드리뷰 지적). 로그인 화면은 미들웨어가 붙인
// `next` 쿼리 파라미터로 로그인 뒤 돌아갈 경로를 받는데, 그 값은 URL을 통해
// 사용자가 직접 조작할 수 있는 입력이다 — 운영자에게
// `/login?next=https://evil.example`류 링크를 보내는 피싱 경로를 막는다.
//
// 같은 오리진의 절대경로("/"로 시작)만 허용한다. 전부 거부하는 변형:
//   - "https://evil.example/..."      완전한 외부 URL
//   - "//evil.example/..."            프로토콜 상대 URL — 브라우저가 현재
//                                      프로토콜을 그대로 붙여 외부로 보낸다
//   - "/\evil.example" 류             일부 파서가 역슬래시를 슬래시로 취급해
//                                      "//evil.example"과 같은 효과를 낸다
//   - 제어 문자가 섞인 값             일부 파서가 제어 문자를 조용히 건너뛰어
//                                      위 우회를 다시 열 수 있다(예: 탭이 낀
//                                      "/\t/evil.example")

function hasControlCharacter(value: string): boolean {
  for (let i = 0; i < value.length; i += 1) {
    if (value.charCodeAt(i) <= 0x1f) return true;
  }
  return false;
}

export function sanitizeNextPath(raw: string | null): string {
  if (!raw) return "/";
  if (!raw.startsWith("/")) return "/";
  if (raw.startsWith("//")) return "/";
  if (raw.includes("\\")) return "/";
  if (hasControlCharacter(raw)) return "/";
  return raw;
}
