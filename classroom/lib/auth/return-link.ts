// 계정 메뉴가 공개 앱으로 건너갈 때 붙이는 복귀 주소 (#306, 소비하는 쪽은 #307).
// 이 앱은 자기 로그인이 없어(ADR-0038) 프로필은 공개 앱의 화면으로 보낸다 — 탈퇴는
// 그 프로필 화면 맨 아래에서만 들어간다(메뉴에 두면 누를 때마다 흠칫하게 만든다)
// (docs/features/classroom.md). `from_origin`이 실제로 우리 형제 오리진인지는
// 공개 앱이 자기 설정과 대조해 판정한다(frontend/lib/auth/sibling-origins.ts의
// resolveSiblingOrigin) — 이 함수는 값을 실어 보낼 뿐 검증하지 않는다.
function withFromOrigin(basePath: string, publicOrigin: string, classroomOrigin: string): string {
  const url = new URL(basePath, publicOrigin);
  url.searchParams.set("from_origin", classroomOrigin);
  return url.toString();
}

export function buildProfileUrl(publicOrigin: string, classroomOrigin: string): string {
  return withFromOrigin("/console/profile", publicOrigin, classroomOrigin);
}
