import { describe, expect, it } from "vitest";

import { createChecklistMover } from "./checklist-reorder";

type Row = { key: number };

function setup(save: (keys: number[]) => void | Promise<boolean>) {
  const server: Row[] = [{ key: 1 }, { key: 2 }, { key: 3 }];
  let rows: Row[] = [...server];
  const move = createChecklistMover<Row>({
    getRows: () => rows,
    getServerRows: () => server,
    setRows: (next) => {
      rows = next;
    },
    save,
  });
  return { move, rows: () => rows.map((r) => r.key) };
}

function deferred() {
  let resolve!: (ok: boolean) => void;
  const promise = new Promise<boolean>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

describe("체크리스트 순서 옮기기(#670)", () => {
  it("곧바로 새 순서를 보이고 저장을 부른다", () => {
    const saved: number[][] = [];
    const { move, rows } = setup((keys) => {
      saved.push(keys);
    });
    move(3, 0);
    expect(rows()).toEqual([3, 1, 2]);
    expect(saved).toEqual([[3, 1, 2]]);
  });

  it("저장이 실패하면 서버 순서로 돌아온다", async () => {
    const pending = deferred();
    const { move, rows } = setup(() => pending.promise);
    move(1, 2);
    expect(rows()).toEqual([2, 3, 1]);
    pending.resolve(false);
    await pending.promise;
    await Promise.resolve();
    expect(rows()).toEqual([1, 2, 3]);
  });

  it("앞 저장이 끝날 때까지 다음 이동은 막는다", async () => {
    const pending = deferred();
    const calls: number[][] = [];
    const { move, rows } = setup((keys) => {
      calls.push(keys);
      return pending.promise;
    });
    move(1, 1);
    move(1, 2);
    expect(rows()).toEqual([2, 1, 3]);
    expect(calls).toHaveLength(1);
    pending.resolve(true);
    await pending.promise;
    await Promise.resolve();
    move(1, 2);
    expect(rows()).toEqual([2, 3, 1]);
    expect(calls).toHaveLength(2);
  });
});
