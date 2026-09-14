// 이 앱 자신의 공개 오리진 — `metadataBase`·robots·sitemap 이 절대 URL 을
// 지을 때 쓴다(#395, #391 Implementation Decisions 「강의실 랜딩」). 로그인
// 복귀 목적지를 계산하는 `lib/auth/public-app.ts`의 `classroomOrigin(host,
// proto)`와 달리 요청 컨텍스트가 필요 없다 — 정적으로 알려진 배포 설정
// 하나만 있으면 된다(공개 앱의 `frontend/lib/seo/origin.ts`와 같은 모양).
//
// `CODEMIT_CLASSROOM_ORIGIN`은 배포 환경에서만 채워진다 — dev는 비워 두므로
// CLAUDE.md 포트 표의 강의실 기본값(오프셋 0)으로 떨어진다.
export function classroomAppOrigin(): string {
  return process.env.CODEMIT_CLASSROOM_ORIGIN || "http://127.0.0.1:53002";
}
