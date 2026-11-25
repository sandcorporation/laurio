// 「만들고 바로 열기」가 필수 항목 때문에만 꺼졌을 때의 이유(#1436-2). 다른 까닭(제목·형식 등)으로
// 이미 꺼졌으면 그 까닭이 먼저라 이 이유를 대지 않는다.
export function openBlockedReason({
  createDisabled,
  hasRequiredItem,
}: {
  createDisabled: boolean;
  hasRequiredItem: boolean;
}): string | null {
  return !createDisabled && !hasRequiredItem ? "필수 항목이 없어 아직 열 수 없습니다." : null;
}

// 꺼진 단추의 이유를 보이는 글로 두고 `aria-describedby` 가 가리키는 id(#1441-1).
export const OPEN_BLOCKED_REASON_ID = "new-problem-open-blocked-reason";
