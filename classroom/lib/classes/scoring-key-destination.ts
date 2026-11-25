// 「채점 키」 알림을 열었을 때 갈 곳 — 알림 문구는 받은 때의 것이라 그대로 두고, 여는 때의 역할로
// 고른다(#1426). 소유권을 넘긴 뒤의 공동 강사에게 설정은 읽기만 되는 화면이라 보내지 않는다.
export function scoringKeyDestination(classId: number, role: "owner" | "co_instructor"): string {
  return role === "owner" ? `/classes/${classId}/settings#scoring-key` : `/classes/${classId}`;
}
