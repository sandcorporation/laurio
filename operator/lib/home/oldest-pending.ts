// 「가장 오래 밀린 것」 계산 — 순수 함수(#427, 부모 #421 홈 범위). 이의 큐가 이미
// 건수를 세려고 받아오는 바로 그 목록(`created_at` 포함)에서 가장 오래된 접수
// 시각만 더 뽑는다 — 새 조회를 만들지 않는다(#421 「바꾸지 않는 것」).
export function oldestPendingDays(createdAtList: readonly string[], now: Date = new Date()): number | null {
  if (createdAtList.length === 0) return null;
  const oldest = Math.min(...createdAtList.map((iso) => new Date(iso).getTime()));
  const diffMs = now.getTime() - oldest;
  return Math.max(0, Math.floor(diffMs / (1000 * 60 * 60 * 24)));
}
