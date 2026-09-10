// 공개 앱(laurio.…)의 오리진 — 강의실은 자기 로그인이 없어(ADR-0038) /login
// 화면이 할 일은 "저기서 로그인하고 오라"고 안내하는 것뿐이다. LAURIO_WEB_ORIGIN을
// 재사용한다 — 이미 배포 환경에서 공개 앱 자신의 Origin 검증이 요구하는 값과
// 같은 값(같은 .env 줄을 나눠 읽는다, LAURIO_OPERATOR_ORIGIN과 같은 원칙)이고,
// "공개 앱이 어디 있는가"라는 같은 사실을 가리킨다.
//
// dev는 이 값을 비워 두므로(다른 두 앱과 같은 이유) 로컬 기본값으로 떨어진다 —
// 이 폴백은 CLAUDE.md 포트 표의 기본값(오프셋 0)이다. 오프셋 워크트리에서는
// docker/compose.dev.yaml이 이 값을 LAURIO_WEB_PORT로 채워 넣는다.
export function publicAppOrigin(): string {
  return process.env.LAURIO_WEB_ORIGIN || "http://127.0.0.1:53000";
}
