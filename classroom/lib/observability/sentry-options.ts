// 오류 수집(GlitchTip) 설정을 한 곳에서 만든다(2026-09-16).
//
// 받는 쪽은 sentry.io 가 아니라 우리가 띄운 GlitchTip 이다 — 수업 제출물·이름·
// 이메일을 다루는 서비스라 오류 본문이 바깥 업체로 나가지 않는 편이 낫다. SDK 는
// 같으므로 DSN 만 그쪽을 가리킨다.
//
// **DSN 이 없으면 켜지 않는다** — dev 와 CI 는 값을 주지 않으므로 SDK 가 꺼진 채로
// 돈다(네트워크를 치지 않는다).
//
// **세션 리플레이와 성능 추적은 켜지 않는다.** GlitchTip 은 리플레이를 받지 못하고,
// 리플레이는 화면을 통째로 녹화해 개인정보가 함께 나간다 — 「오류만 보낸다」가 이
// 도입의 전제다. 그래서 `sendDefaultPii` 도 끈 채로 둔다(요청 헤더·쿠키·IP 를 붙이지
// 않는다). 사용자 식별은 백엔드가 내부 id 하나로만 한다.
//
// 이 파일은 세 앱(frontend·operator·classroom)에 같은 내용으로 복사돼 있다 —
// 토큰·로고와 같은 방식이다(공유 패키지로 빼지 않는 이유는 CLAUDE.md
// 「프론트엔드」의 손으로 관리되는 목록 셋 참고).

/** SDK 를 켤 때 쓸 설정. DSN 이 비어 있으면 null — 그러면 켜지 않는다. */
export function buildSentryOptions(env: Record<string, string | undefined>): {
  dsn: string;
  environment: string;
  release: string | undefined;
  tracesSampleRate: number;
  sendDefaultPii: false;
} | null {
  const dsn = (env.NEXT_PUBLIC_SENTRY_DSN ?? "").trim();
  if (dsn === "") return null;
  const release = (env.NEXT_PUBLIC_SENTRY_RELEASE ?? "").trim();
  return {
    dsn,
    environment: (env.NEXT_PUBLIC_SENTRY_ENVIRONMENT ?? "").trim() || "development",
    release: release === "" ? undefined : release,
    tracesSampleRate: 0,
    sendDefaultPii: false,
  };
}
