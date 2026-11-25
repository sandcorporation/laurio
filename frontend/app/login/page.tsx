import type { Metadata } from "next";
import { cookies } from "next/headers";

import { ACCESS_COOKIE, REFRESH_COOKIE, isDeployedEnvironment } from "@/lib/auth/cookies";
import { readGithubOAuthConfig } from "@/lib/auth/github";
import { readGoogleOAuthConfig } from "@/lib/auth/google";
import { LOGIN_BOUNCE_COOKIE, isAutoContinueStopped, shouldCheckSessionOnLogin } from "@/lib/auth/login-auto-continue";

import LoginForm from "./login-form";

export const metadata: Metadata = { title: "로그인" };

// 서버 컴포넌트다 — dev seed 폼을 보일지, GitHub·구글 버튼을 실제 링크로 그릴지는
// 여기서 서버가 결정한다(#95, spec #92 / #189). client_id·secret 자체는 절대
// 클라이언트 컴포넌트로 내려주지 않는다 — "설정돼 있는가"라는 boolean 하나만
// prop으로 넘긴다(readGithubOAuthConfig/readGoogleOAuthConfig가 이미 이 판정을
// 하고 있어 authorize 라우트와 정확히 같은 기준을 쓴다 — 카카오와 달리
// 배포 환경에서도 필수가 아니다: 사람이 GitHub·구글 OAuth 앱을 등록하기 전까지는
// 여기서 false가 나오고, 등록해 이 프로세스의 환경변수를 채우면 코드를 더
// 고치지 않아도 true가 된다).
// 배포 환경(production)에서 로그인 우회가 실려 나가는 것이 불편한 것보다
// 나쁘다는 판단이라, 클라이언트에서 process.env를 읽는 게 아니라(브라우저에는
// 값이 없다) 요청마다 서버가 판정해 prop으로 내려준다.
//
// **이 페이지는 정적 프리렌더 대상이 아니어야 한다**(코드리뷰 지적 — 리뷰어가
// 실물 컨테이너로 재현했다). 이 컴포넌트에 동적 API 호출이 없으면 Next가
// `next build` 시점에 한 번 렌더해 결과를 정적 HTML로 굳힌다 — 그러면
// isDeployedEnvironment()가 런타임(배포 컨테이너)이 아니라 빌드 환경의
// CODEMIT_DEPLOYMENT_TARGET을 보고, 빌드 환경이 보통 그 값을 안 주므로
// showDevSeedForm이 true로 굳어 production 이미지에 dev 로그인 우회가 정적
// 자산으로 그대로 실린다(실제로 `docker build --target runner` 산출물의
// `/login` 라우트가 `○`(static)로 표시되고 이미지 안 login.html에
// showDevSeedForm":true가 박혀 있는 것으로 확인됐다). `force-dynamic`으로
// 매 요청마다 다시 렌더해 컨테이너가 실제로 뜬 배포 환경의 값을 보게 한다.
export const dynamic = "force-dynamic";

type SearchParams = { next?: string | string[]; next_origin?: string | string[]; error?: string | string[] };

const single = (value: string | string[] | undefined) => (typeof value === "string" ? value : null);

// 로그인한 사람에게는 폼 대신 목적지로 넘긴다(#1388 T3, lib/auth/login-auto-continue.ts).
// 여기서는 세션 쿠키가 **있는지**만 본다 — 산 세션인지는 화면이 `/api/auth/session` 으로
// 백엔드에 묻는다. 쿠키가 없으면 그 요청도 하지 않는다.
export default async function LoginPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const params = await searchParams;
  const jar = await cookies();
  const autoContinueInput = {
    hasSessionCookie: Boolean(jar.get(ACCESS_COOKIE)?.value || jar.get(REFRESH_COOKIE)?.value),
    error: single(params.error),
    bounced: jar.has(LOGIN_BOUNCE_COOKIE),
    next: single(params.next),
    nextOrigin: single(params.next_origin),
  };
  return (
    <LoginForm
      checkSessionFirst={shouldCheckSessionOnLogin(autoContinueInput)}
      autoContinueStopped={isAutoContinueStopped(autoContinueInput)}
      showDevSeedForm={!isDeployedEnvironment()}
      githubConfigured={readGithubOAuthConfig() !== null}
      googleConfigured={readGoogleOAuthConfig() !== null}
    />
  );
}
