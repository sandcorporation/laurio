import { describe, expect, it } from "vitest";

import { defaultCopyTarget, selectCopyTargets } from "./copy-targets";

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

describe("defaultCopyTarget", () => {
  it("고를 수 있는 것이 정확히 하나면 그것을 낸다", () => {
    const only: Fixture = { id: 7, archived: false };
    expect(defaultCopyTarget([only])).toEqual(only);
  });

  it("보관된 것을 걸러 하나만 남으면 그것을 낸다", () => {
    const active: Fixture = { id: 2, archived: false };
    expect(defaultCopyTarget([{ id: 1, archived: true }, active])).toEqual(active);
  });

  it("둘 이상이면 고르지 않는다 — 사람이 고른다", () => {
    const classes: Fixture[] = [
      { id: 1, archived: false },
      { id: 2, archived: false },
    ];
    expect(defaultCopyTarget(classes)).toBeNull();
  });

  it("고를 것이 없으면 null", () => {
    expect(defaultCopyTarget([])).toBeNull();
  });

  it("전부 보관됐으면 null", () => {
    expect(defaultCopyTarget([{ id: 1, archived: true }])).toBeNull();
  });
});
