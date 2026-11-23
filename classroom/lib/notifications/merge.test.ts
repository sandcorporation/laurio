import { describe, expect, it } from "vitest";

import type { NotificationRow } from "./api";
import { mergeFirstPage } from "./merge";

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

describe("mergeFirstPage", () => {
  it("새 알림을 맨 위에 끼우고 아래 줄은 그대로 둔다", () => {
    expect(ids(mergeFirstPage([row(3), row(2), row(1)], [row(4), row(3)]))).toEqual([4, 3, 2, 1]);
  });

  it("여럿이 한꺼번에 와도 최신순으로 한 번에 끼운다", () => {
    expect(ids(mergeFirstPage([row(2), row(1)], [row(5), row(4), row(3), row(2)]))).toEqual([
      5, 4, 3, 2, 1,
    ]);
  });

  it("겹치는 줄은 다시 불러온 쪽이 이긴다", () => {
    const merged = mergeFirstPage([row(2), row(1)], [row(2, { read_at: "2026-09-02T00:00:00Z" })]);
    expect(ids(merged)).toEqual([2, 1]);
    expect(merged[0].read_at).toBe("2026-09-02T00:00:00Z");
  });

  it("더 보기로 불러온 아래 줄을 지우지 않는다", () => {
    expect(ids(mergeFirstPage([row(60), row(59), row(10)], [row(61), row(60)]))).toEqual([
      61, 60, 59, 10,
    ]);
  });
});
