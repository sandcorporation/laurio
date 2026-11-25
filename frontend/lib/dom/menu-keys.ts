// WAI-ARIA 메뉴 단추의 키 규약(#1465 1번) — ↑↓ 로 오가되 끝에서 돌아가고, Home/End 는 처음·끝.
// 다른 키는 null 이라 호출한 쪽이 건드리지 않는다.
export function nextMenuIndex(key: string, current: number, count: number): number | null {
  if (count <= 0) return null;
  if (key === "ArrowDown") return (current + 1) % count;
  if (key === "ArrowUp") return (current - 1 + count) % count;
  if (key === "Home") return 0;
  if (key === "End") return count - 1;
  return null;
}
