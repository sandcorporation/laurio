// 허용목록 검사 함수 (ADR-0016/0021, 운영자 앱 04 #62로 공유 패키지에 옮김).
//
// **목록을 인자로 받는다 — 이 파일에는 어떤 경로 문자열도 없다.** 공개 앱과
// 운영자 앱이 서로 다른 것만 통과시킨다는 사실(ADR-0021)은 각 앱이 자기
// 허용목록 파일을 갖는 것으로 성립한다. 검사하는 로직(문자열 접두어 비교)만
// 공유하면, 허용목록을 합치고 싶은 유혹이 와도 합칠 자리 자체가 없다 — 목록은
// 언제나 호출부에서 온다.
export function isAllowedPath(pathname: string, allowlist: readonly string[]): boolean {
  return allowlist.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
}
