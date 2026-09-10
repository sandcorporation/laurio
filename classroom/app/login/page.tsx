// 강의실은 자기 로그인을 갖지 않는다(ADR-0038) — 회원은 공개 앱과 공유한다. 이
// 화면은 공개 앱의 로그인으로 안내만 한다: 거기서 로그인하면 부모 도메인 쿠키가
// 이 앱에도 실려, 다시 이 링크를 눌러 돌아오면 middleware.ts가 통과시킨다.
//
// next를 그대로 전달하지 않는다 — lib/auth/next-path.ts(공개 앱)의 isSafeNextPath는
// 같은 오리진 상대 경로만 허용해 다른 서브도메인(classroom.laurio.…)으로의
// 복귀를 구조적으로 막는다(오픈 리다이렉트 방지, 그 파일 상단 주석 참고). 그
// 검사를 느슨하게 하지 않는다 — 대신 사람이 로그인 후 직접 이 화면으로 돌아오게
// 안내한다.
import { publicAppOrigin } from "@/lib/auth/public-app";

export default function ClassroomLoginPage() {
  const loginUrl = `${publicAppOrigin()}/login`;

  return (
    <main>
      <h1 data-testid="classroom-login-heading">로그인이 필요합니다</h1>
      <p data-testid="classroom-login-guide">
        강의실은 Laurio 계정을 그대로 씁니다. 아래 링크에서 로그인한 뒤 이 화면으로
        돌아와 주세요.
      </p>
      <p>
        <a href={loginUrl} data-testid="classroom-login-link">
          Laurio 로그인으로 이동
        </a>
      </p>
    </main>
  );
}
