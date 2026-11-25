import { nextMenuIndex } from "./menu-keys";

// WAI-ARIA 탭 목록의 키 규약(#1478 1번) — ←/→ 로 오가되 끝에서 돌아가고, Home/End 는 처음·끝.
// 메뉴(↑↓)와 같은 순환 규칙을 쓰므로 키만 옮겨 menu-keys 에 맡긴다. 다른 키는 null.
export function nextTabIndex(
  key: string,
  current: number,
  count: number,
): number | null {
  if (key === "ArrowRight") return nextMenuIndex("ArrowDown", current, count);
  if (key === "ArrowLeft") return nextMenuIndex("ArrowUp", current, count);
  if (key === "Home" || key === "End")
    return nextMenuIndex(key, current, count);
  return null;
}
