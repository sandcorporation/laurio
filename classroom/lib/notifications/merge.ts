// 알림 목록에 서버에서 온 쪽을 합친다 — 실시간 신호로 다시 불러온 첫 쪽(#1346)과
// 「더 보기」의 다음 쪽이 같은 규칙을 쓴다(#1380).
//
// 규칙:
//   - id 로 중복을 없앤다. 겹치는 줄은 새로 온 쪽이 이긴다(다른 탭에서 읽음
//     처리한 결과가 실린다). 다만 읽음은 되돌리지 않는다 — 읽기 전에 만들어진
//     응답이 늦게 올 수 있고, 서버는 `read_at` 을 비우지 않는다.
//   - 지금 목록에만 있는 줄은 그대로 둔다.
//   - 순서는 서버 정렬 키 그대로다: `created_at` 내림차순, 같으면 id 내림차순.
//   - 합치는 대상은 요청을 보낼 때가 아니라 **응답이 온 때의 목록**이다.
import type { NotificationRow } from "./api";

// `created_at` 은 서버의 UTC `isoformat()` 문자열이라 글자 순서가 시각 순서다.
// `Date` 로 바꾸면 마이크로초가 잘려 서버 순서와 갈린다.
function byServerOrder(a: NotificationRow, b: NotificationRow): number {
  if (a.created_at !== b.created_at) return a.created_at < b.created_at ? 1 : -1;
  return b.id - a.id;
}

export function mergePage(current: NotificationRow[], page: NotificationRow[]): NotificationRow[] {
  const byId = new Map(current.map((n) => [n.id, n]));
  for (const n of page) {
    const readAt = n.read_at ?? byId.get(n.id)?.read_at ?? null;
    byId.set(n.id, { ...n, read_at: readAt });
  }
  return [...byId.values()].sort(byServerOrder);
}

export type NotificationList = { items: NotificationRow[]; nextCursor: string | null };
type NextPage = { items: NotificationRow[]; next: string | null };
/** 호출 시점의 목록을 받아 바꾼다 — 화면의 함수형 `setState` 가 이 모양이다. */
export type UpdateList = (change: (current: NotificationList) => NotificationList) => void;

/** 「더 보기」 — `after` 다음 쪽을 불러와 합친다. `null`(실패)이면 아무것도 바꾸지 않는다. */
export async function loadNextPage(
  after: string,
  fetchPage: (after: string) => Promise<NextPage | null>,
  update: UpdateList,
): Promise<void> {
  const page = await fetchPage(after);
  if (!page) return;
  update((current) => ({ items: mergePage(current.items, page.items), nextCursor: page.next }));
}
