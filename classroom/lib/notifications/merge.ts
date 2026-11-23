// 실시간 신호로 다시 불러온 첫 쪽을 지금 목록에 합친다(#1346).
//
// 규칙:
//   - id 가 같은 줄은 다시 불러온 쪽이 이긴다(다른 탭에서 읽음 처리한 결과가
//     실린다). 중복은 생기지 않는다.
//   - 지금 목록에만 있는 줄(「더 보기」로 불러온 아래 줄)은 그대로 둔다.
//   - 새 줄이 여럿 와도 최신순(id 큰 것이 위)으로 한 번에 끼운다. 백엔드가 주는
//     순서(최신순)와 같다.
import type { NotificationRow } from "./api";

export function mergeFirstPage(
  current: NotificationRow[],
  firstPage: NotificationRow[],
): NotificationRow[] {
  const fresh = new Map(firstPage.map((n) => [n.id, n]));
  const kept = current.filter((n) => !fresh.has(n.id));
  return [...firstPage, ...kept].sort((a, b) => b.id - a.id);
}
