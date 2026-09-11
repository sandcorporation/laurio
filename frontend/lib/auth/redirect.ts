// 우리 화면으로 되돌리는 리다이렉트 (#95, spec #92).
//
// **컨테이너 안의 Next는 자기가 어떤 공개 주소로 불렸는지 모른다.** 스테이징에서
// 카카오 로그인을 끝내면 브라우저가 `https://0.0.0.0:3000/console`로 튕겼다 —
// 콜백이 `new URL(request.url).origin`으로 절대 URL을 지었는데, 리버스 프록시
// 뒤의 standalone Next에서 그 값이 공개 도메인이 아니라 바인드 주소였기 때문이다.
//
// 그래서 오리진을 짓지 않는다. **상대 Location은 브라우저가 자기가 친 주소를
// 기준으로 푼다** — 그게 언제나 맞는 공개 오리진이고, 환경변수도 프록시의
// X-Forwarded-* 설정도 필요 없다. 운영자 앱의 미들웨어가 이미 그렇게 동작해서
// 같은 스테이징에서 멀쩡했다는 것이 이 선택의 근거다.
//
// `LAURIO_WEB_ORIGIN`을 읽는 방법도 있지만 그건 dev에 없는 값이라(배포에서만
// instrumentation.ts가 강제한다) 폴백이 필요하고, 그 폴백이 정확히 지금 깨진
// 코드다 — 테스트가 dev에서 그 분기를 관찰할 수 없게 된다.
import { NextResponse } from "next/server";

// Location 헤더에 넣을 값은 **반드시 같은 오리진 경로**여야 한다. 호출부는
// isSafeNextPath(lib/auth/next-path.ts)를 통과한 값이나 이 파일이 짓는 고정
// 경로만 넘긴다.
export function redirectToPath(path: string): NextResponse {
  return new NextResponse(null, { status: 307, headers: { Location: path } });
}

export function loginPathWithError(
  error: string,
  next: string,
  nextOrigin: string | null = null,
): string {
  const params = new URLSearchParams({ error, next });
  // 실패해도 **돌아갈 곳을 잃지 않는다**(#297 후속). 이걸 빠뜨리면 강의실에서 온
  // 사람이 한 번 실패한 뒤 다시 로그인에 성공해도 공개 앱에 남는다 — 브라우저로
  // 걷다가 실제로 그 상태를 봤다(dev 는 카카오 자격증명이 없어 첫 시도가 늘
  // oauth_unconfigured 로 돌아온다).
  if (nextOrigin) params.set("next_origin", nextOrigin);
  return `/login?${params.toString()}`;
}
