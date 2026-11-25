// 강의실 `/login`(app/login/route.ts)이 보낼 공개 앱 로그인 주소를 짓는다(#1388).
//
// 강의실은 자기 로그인 폼이 없다(ADR-0038). `/login` 은 화면 없이 곧장 공개 앱
// 로그인으로 307 하고, 이 함수가 그 `Location` 을 짓는 한 곳이다 — 진입점(미들웨어,
// 가입·초대 링크, BFF 401, 랜딩 CTA, 계정 메뉴)은 모두 `/login` 을 가리키고 검증은
// 여기 남는다.
//
// - `next` 는 `requestUrl` 을 직접 파싱해 `getAll("next")` 로 읽는다. `request.nextUrl`
//   은 쿼리 안의 127.0.0.1 을 localhost 로 바꿔 OAuth `redirect_uri` 를 망가뜨린다
//   (#622, login-next.ts). 값이 둘 이상이면 어느 쪽이 진짜인지 모르므로 배열로 넘겨
//   `resolveNextPath` 가 거부하게 한다(→ "/").
// - `next` 는 이 앱 안의 상대 경로만 싣는다(next-path.ts). 공개 앱은 `next_origin` 을
//   자기 허용목록과 완전 일치로 대조한다(frontend/lib/auth/sibling-origins.ts).
// - 복귀 오리진을 모르면(설정도 Host 도 없음 — 운영에서는 부팅이 막아 생기지 않는다)
//   `next`·`next_origin` 을 **둘 다** 싣지 않는다. 강의실 경로를 오리진 없이 실으면
//   공개 앱이 자기 경로로 읽어 404 가 난다. 그 사고는 `reportMissingOrigin` 으로 알린다.
import { resolveNextPath } from "./next-path";
import { classroomOrigin, publicAppOrigin } from "./public-app";

export type BuildPublicLoginUrlInput = {
  requestUrl: string;
  host: string | null;
  proto: string | null;
  reportMissingOrigin?: (message: string) => void;
};

export function buildPublicLoginUrl({
  requestUrl,
  host,
  proto,
  reportMissingOrigin,
}: BuildPublicLoginUrlInput): string {
  const login = new URL("/login", publicAppOrigin());
  const origin = classroomOrigin(host, proto);
  if (!origin) {
    reportMissingOrigin?.(
      "classroom /login: 복귀 오리진을 모른다(CODEMIT_CLASSROOM_ORIGIN 과 Host 가 모두 없다) — next·next_origin 없이 보낸다",
    );
    return login.toString();
  }

  const values = new URL(requestUrl).searchParams.getAll("next");
  const next = values.length > 1 ? values : values[0];
  login.searchParams.set("next_origin", origin);
  login.searchParams.set("next", resolveNextPath(next));
  return login.toString();
}
