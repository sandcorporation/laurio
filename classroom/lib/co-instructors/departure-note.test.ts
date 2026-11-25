import { describe, expect, it } from "vitest";

import { departureNote, departureNotes, parseDeparture, rosterChangeNote, vanishedInstructors } from "./departure-note";

describe("departure note", () => {
  it("떠남과 내보냄을 가른다", () => {
    expect(departureNote("박조교", true)).toBe("박조교님이 클래스를 떠났습니다");
    expect(departureNote("박조교", false)).toBe("박조교님이 클래스에서 내보내졌습니다");
  });
  it("신호 본문을 읽고 모양이 틀리면 버린다", () => {
    expect(parseDeparture({ departed: { co_instructor_id: 3, display_name: "박", left: true } })).toEqual({
      coInstructorId: 3,
      displayName: "박",
      left: true,
    });
    expect(parseDeparture({ departed: { co_instructor_id: "3" } })).toBeNull();
    expect(parseDeparture({})).toBeNull();
  });
  it("사라진 줄을 찾고 신호가 없는 줄은 말하지 않는다", () => {
    const vanished = vanishedInstructors(new Map([[1, "가"], [2, "나"]]), new Set([2]));
    expect(vanished).toEqual([{ id: 1, name: "가" }]);
    expect(departureNotes(vanished, new Map())).toBe("");
    expect(departureNotes(vanished, new Map([[1, { coInstructorId: 1, displayName: "가", left: true }]]))).toBe(
      "가님이 클래스를 떠났습니다",
    );
  });
});

describe("rosterChangeNote", () => {
  it("떠남과 초대 수락이 한 응답에 같이 오면 한 문장으로 모은다", () => {
    expect(rosterChangeNote("가님이 클래스를 떠났습니다", ["나"])).toEqual({
      kind: "departed",
      text: "가님이 클래스를 떠났습니다. 나 님이 초대를 수락했습니다",
    });
  });
  it("하나만 오면 그 종류 그대로", () => {
    expect(rosterChangeNote("", ["나", "다"])).toEqual({ kind: "accepted", text: "나, 다 님이 초대를 수락했습니다" });
    expect(rosterChangeNote("가님이 클래스를 떠났습니다", [])).toEqual({ kind: "departed", text: "가님이 클래스를 떠났습니다" });
    expect(rosterChangeNote("", [])).toBeNull();
  });
});
