// 공개 앱(codemit.…)의 오리진 — 강의실은 자기 로그인이 없어(ADR-0038) /login
// 화면이 할 일은 "저기서 로그인하고 오라"고 안내하는 것뿐이다. CODEMIT_WEB_ORIGIN을
// 재사용한다 — 이미 배포 환경에서 공개 앱 자신의 Origin 검증이 요구하는 값과
// 같은 값(같은 .env 줄을 나눠 읽는다, CODEMIT_OPERATOR_ORIGIN과 같은 원칙)이고,
// "공개 앱이 어디 있는가"라는 같은 사실을 가리킨다.
//
// dev는 이 값을 비워 두므로(다른 두 앱과 같은 이유) 로컬 기본값으로 떨어진다 —
// 이 폴백은 CLAUDE.md 포트 표의 기본값(오프셋 0)이다. 오프셋 워크트리에서는
// docker/compose.dev.yaml이 이 값을 CODEMIT_WEB_PORT로 채워 넣는다.
export function publicAppOrigin(): string {
  return process.env.CODEMIT_WEB_ORIGIN || "http://127.0.0.1:53000";
}

/**
 * 이 앱의 공개 오리진 — 로그인이 끝나고 **여기로 돌아오라**고 공개 앱에 알릴 때 쓴다
 * (#297 후속).
 *
 * 배포 환경에서는 `CODEMIT_CLASSROOM_ORIGIN` 이 보장된다(설정이 비면 부팅이
 * 거부된다, instrumentation.ts). dev 는 그 값을 비워 두므로 요청의 Host 로
 * 되돌린다 — 워크트리마다 포트가 달라(docker/dev-env.sh) 고정값을 쓸 수 없다.
 *
 * 이 값을 그대로 믿는 쪽은 아무도 없다: 공개 앱이 자기 허용목록과 대조해
 * 통과한 것만 복귀 목적지로 쓴다(frontend/lib/auth/sibling-origins.ts).
 */
export function classroomOrigin(host: string | null, proto: string | null): string | null {
  const configured = process.env.CODEMIT_CLASSROOM_ORIGIN;
  if (configured && configured.trim() !== "") return configured.trim();
  if (!host) return null;
  return `${proto === "https" ? "https" : "http"}://${host}`;
}
