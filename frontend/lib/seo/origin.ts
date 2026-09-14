// 이 앱 자신의 공개 오리진 — `metadataBase`·robots·sitemap 이 절대 URL 을 지을 때
// 쓴다(#394, #391 Implementation Decisions 「공개 앱 메타데이터·SEO」).
//
// `CODEMIT_WEB_ORIGIN`은 배포 환경에서만 채워진다 — dev는 비워 두므로
// (`lib/auth/redirect.ts`와 같은 이유) CLAUDE.md 포트 표의 공개 앱 기본값
// (오프셋 0)으로 떨어진다.
export function webAppOrigin(): string {
  return process.env.CODEMIT_WEB_ORIGIN || "http://127.0.0.1:53000";
}
