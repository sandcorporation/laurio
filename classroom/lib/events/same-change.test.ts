import { describe, expect, it } from "vitest";

import { changeRev, createSameChangeFilter } from "./same-change";

const instructors = (classId: number, rev?: number) => ({
  kind: "instructors-changed",
  payload: rev === undefined ? { class_id: classId } : { class_id: classId, rev },
});
const participation = (classId: number, rev?: number) => ({
  kind: "participation-changed",
  payload: rev === undefined ? { class_id: classId } : { class_id: classId, rev },
});

describe("changeRev", () => {
  it("본문의 변경 번호를 읽고, 없거나 숫자가 아니면 모른다", () => {
    expect(changeRev({ class_id: 1, rev: 7 })).toBe(7);
    expect(changeRev({ class_id: 1 })).toBeNull();
    expect(changeRev({ class_id: 1, rev: "7" })).toBeNull();
  });
});

describe("createSameChangeFilter", () => {
  it("같은 변경 번호의 두 번째 신호는 종류가 달라도, 어느 쪽이 먼저 와도 이미 읽은 변경이다", () => {
    const participationFirst = createSameChangeFilter();
    expect(participationFirst(participation(1, 5))).toBe(false);
    expect(participationFirst(instructors(1, 5))).toBe(true);

    const instructorsFirst = createSameChangeFilter();
    expect(instructorsFirst(instructors(1, 5))).toBe(false);
    expect(instructorsFirst(participation(1, 5))).toBe(true);
  });

  it("더 큰 번호는 새 변경이고, 늦게 닿은 작은 번호는 큰 번호의 재조회가 이미 담는다", () => {
    const seen = createSameChangeFilter();
    expect(seen(instructors(1, 5))).toBe(false);
    expect(seen(instructors(1, 6))).toBe(false);
    expect(seen(participation(1, 5))).toBe(true);
  });

  it("번호 없는 신호(옛 서버)는 늘 읽는다", () => {
    const seen = createSameChangeFilter();
    expect(seen(instructors(1))).toBe(false);
    expect(seen(participation(1))).toBe(false);
  });

  it("클래스마다 따로 센다", () => {
    const seen = createSameChangeFilter();
    expect(seen(instructors(1, 5))).toBe(false);
    expect(seen(instructors(2, 5))).toBe(false);
  });
});
