import { describe, expect, it } from "vitest";

import { selectCopyTargets } from "./copy-targets";

type Fixture = { id: number; archived: boolean };

describe("selectCopyTargets", () => {
  it("후보가 하나도 없으면 no-classes", () => {
    expect(selectCopyTargets<Fixture>([])).toEqual({ kind: "no-classes" });
  });

  it("전부 보관됐으면 all-archived", () => {
    const classes: Fixture[] = [
      { id: 1, archived: true },
      { id: 2, archived: true },
    ];
    expect(selectCopyTargets(classes)).toEqual({ kind: "all-archived" });
  });

  it("보관된 것을 걸러 진행중인 것만 ready 로 낸다", () => {
    const active: Fixture = { id: 2, archived: false };
    const classes: Fixture[] = [{ id: 1, archived: true }, active];
    expect(selectCopyTargets(classes)).toEqual({ kind: "ready", classes: [active] });
  });

  it("전부 진행중이면 순서 그대로 ready", () => {
    const classes: Fixture[] = [
      { id: 1, archived: false },
      { id: 2, archived: false },
    ];
    expect(selectCopyTargets(classes)).toEqual({ kind: "ready", classes });
  });
});
