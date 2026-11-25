import { describe, expect, it } from "vitest";

import type { NotificationRow } from "./api";
import { loadNextPage, mergePage, type NotificationList } from "./merge";

function row(id: number, overrides: Partial<NotificationRow> = {}): NotificationRow {
  return {
    id,
    notification_type: "classroom_submission_scored",
    is_transactional: true,
    is_promotional: false,
    status: "not_dispatched",
    scheduled_for: null,
    created_at: "2026-09-01T00:00:00Z",
    context: {},
    dispatches: [],
    read_at: null,
    ...overrides,
  };
}

const ids = (rows: NotificationRow[]) => rows.map((n) => n.id);

describe("mergePage", () => {
  it("새 알림을 맨 위에 끼우고 아래 줄은 그대로 둔다", () => {
    expect(ids(mergePage([row(3), row(2), row(1)], [row(4), row(3)]))).toEqual([4, 3, 2, 1]);
  });

  it("여럿이 한꺼번에 와도 최신순으로 한 번에 끼운다", () => {
    expect(ids(mergePage([row(2), row(1)], [row(5), row(4), row(3), row(2)]))).toEqual([
      5, 4, 3, 2, 1,
    ]);
  });

  it("서버 정렬 키(created_at, id 내림차순) 그대로 늘어놓는다", () => {
    const later = row(1, { created_at: "2026-09-01T00:00:00.500000+00:00" });
    const earlier = row(2, { created_at: "2026-09-01T00:00:00+00:00" });
    const sameMicro = row(3, { created_at: "2026-09-01T00:00:00.500001+00:00" });
    expect(ids(mergePage([earlier], [sameMicro, later]))).toEqual([3, 1, 2]);
    expect(ids(mergePage([row(1)], [row(2)]))).toEqual([2, 1]);
  });

  it("늦게 온 응답이 읽음 표시를 되돌리지 않는다", () => {
    const merged = mergePage([row(1, { read_at: "2026-09-02T00:00:00Z" })], [row(1)]);
    expect(merged[0].read_at).toBe("2026-09-02T00:00:00Z");
  });

  it("겹치는 줄은 다시 불러온 쪽이 이긴다", () => {
    const merged = mergePage([row(2), row(1)], [row(2, { read_at: "2026-09-02T00:00:00Z" })]);
    expect(ids(merged)).toEqual([2, 1]);
    expect(merged[0].read_at).toBe("2026-09-02T00:00:00Z");
  });

  it("더 보기로 불러온 아래 줄을 지우지 않는다", () => {
    expect(ids(mergePage([row(60), row(59), row(10)], [row(61), row(60)]))).toEqual([
      61, 60, 59, 10,
    ]);
  });
});

// 「더 보기」 요청이 날아가 있는 동안의 목록 — `during` 이 그 사이에 끼어드는 갱신이다(#1380).
async function loadMoreWhile(
  start: NotificationList,
  nextPage: NotificationRow[],
  during: (list: NotificationList) => NotificationList,
): Promise<NotificationList> {
  let list = start;
  let respond!: () => void;
  const pending = loadNextPage(
    start.nextCursor!,
    () =>
      new Promise((resolve) => {
        respond = () => resolve({ items: nextPage, next: "cursor-3" });
      }),
    (change) => {
      list = change(list);
    },
  );
  list = during(list);
  respond();
  await pending;
  return list;
}

describe("loadNextPage", () => {
  const start: NotificationList = { items: [row(4), row(3)], nextCursor: "cursor-2" };

  it("불러오는 중에 첫 쪽이 갱신돼도 새 알림이 빠지지 않는다", async () => {
    const list = await loadMoreWhile(start, [row(2), row(1)], (current) => ({
      ...current,
      items: mergePage(current.items, [row(6), row(5), row(4)]),
    }));
    expect(ids(list.items)).toEqual([6, 5, 4, 3, 2, 1]);
    expect(list.nextCursor).toBe("cursor-3");
  });

  it("갱신된 첫 쪽과 다음 쪽이 겹쳐도 중복이 없다", async () => {
    const list = await loadMoreWhile(start, [row(2), row(1)], (current) => ({
      ...current,
      items: mergePage(current.items, [row(4), row(2)]),
    }));
    expect(ids(list.items)).toEqual([4, 3, 2, 1]);
  });

  it("불러오는 중에 읽음 처리한 줄이 안 읽음으로 돌아가지 않는다", async () => {
    const readAt = "2026-09-02T00:00:00Z";
    const list = await loadMoreWhile(start, [row(2)], (current) => ({
      ...current,
      items: current.items.map((n) => ({ ...n, read_at: readAt })),
    }));
    expect(list.items.find((n) => n.id === 4)?.read_at).toBe(readAt);
  });

  it("실패하면 목록과 커서를 그대로 둔다", async () => {
    let touched = false;
    await loadNextPage(
      "cursor-2",
      async () => null,
      () => {
        touched = true;
      },
    );
    expect(touched).toBe(false);
  });
});
