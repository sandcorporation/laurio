import { isDeployedEnvironment } from "@/lib/auth/cookies";

import LoginForm from "./login-form";

// 서버 컴포넌트다 — dev seed 폼을 보일지는 여기서 서버가 결정한다(#95, spec #92).
// 배포 환경(staging/production)에서 로그인 우회가 실려 나가는 것이 불편한 것보다
// 나쁘다는 판단이라, 클라이언트에서 process.env를 읽는 게 아니라(빌드 시점에
// 굳어 배포마다 다시 빌드해야 하고, NEXT_PUBLIC_ 없이는 애초에 브라우저에 값이
// 없다) 요청마다 서버가 판정해 prop으로 내려준다.
export default function LoginPage() {
  return <LoginForm showDevSeedForm={!isDeployedEnvironment()} />;
}
