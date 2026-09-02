import { isDeployedEnvironment } from "@/lib/auth/cookies";

import LoginForm from "./login-form";

// 서버 컴포넌트다 — dev seed 폼을 보일지는 여기서 서버가 결정한다(#95, spec #92).
// 배포 환경(staging/production)에서 로그인 우회가 실려 나가는 것이 불편한 것보다
// 나쁘다는 판단이라, 클라이언트에서 process.env를 읽는 게 아니라(빌드 시점에
// 굳어 배포마다 다시 빌드해야 하고, NEXT_PUBLIC_ 없이는 애초에 브라우저에 값이
// 없다) 요청마다 서버가 판정해 prop으로 내려준다.
//
// **이 페이지는 정적 프리렌더 대상이 아니어야 한다**(코드리뷰 지적 — 리뷰어가
// 실물 컨테이너로 재현했다). 이 컴포넌트에 동적 API 호출이 없으면 Next가
// `next build` 시점에 한 번 렌더해 결과를 정적 HTML로 굳힌다 — 그러면
// isDeployedEnvironment()가 런타임(배포 컨테이너)이 아니라 빌드 환경의
// LAURIO_DEPLOYMENT_TARGET을 보고, 빌드 환경이 보통 그 값을 안 주므로
// showDevSeedForm이 true로 굳어 production 이미지에 dev 로그인 우회가 정적
// 자산으로 그대로 실린다(실제로 `docker build --target runner` 산출물의
// `/login` 라우트가 `○`(static)로 표시되고 이미지 안 login.html에
// showDevSeedForm":true가 박혀 있는 것으로 확인됐다). `force-dynamic`으로
// 매 요청마다 다시 렌더해 컨테이너가 실제로 뜬 배포 환경의 값을 보게 한다.
export const dynamic = "force-dynamic";

export default function LoginPage() {
  return <LoginForm showDevSeedForm={!isDeployedEnvironment()} />;
}
