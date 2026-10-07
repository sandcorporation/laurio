// 로그인으로 보낼 때 돌아올 자리(`next`)를 요청 원문에서 짓는다(#622).
//
// `request.nextUrl`(NextURL)을 쓰면 안 된다 — Next 는 URL 문자열에서 처음 나오는
// 127.x.x.x·[::1] 을 `localhost` 로 바꿔 파싱하는데, 그 첫 자리가 쿼리 안의
// `redirect_uri=http://127.0.0.1:…` 이면 로그인 뒤 돌아온 요청의 redirect_uri 가
// 등록값과 글자가 달라져 OAuth 동의가 거절된다. `request.url` 을 우리가 직접 파싱하면
// 쿼리는 바이트 그대로 남는다.
export function loginNextPath(requestUrl: string): string {
  const u = new URL(requestUrl);
  return u.pathname + u.search;
}
