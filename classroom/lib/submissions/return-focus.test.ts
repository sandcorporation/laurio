import { describe, expect, it } from "vitest";

import type { SubmitBlockedReason } from "./api";
import { returnAction, type ReturnAction, type ReturnState } from "./return-focus";

const base: ReturnState = { status: "ready", lost: false, hadForm: true, reason: null, focusAtBody: true, hasDraft: false };
const RELEASED = "문제가 다시 열려 제출할 수 있습니다.";
const act = (s: Partial<ReturnState>) => returnAction({ ...base, ...s });

// 한 사건씩 적용해 전이를 걷는 도우미 — 이전 판단의 lost 를 다음 입력으로 넘긴다.
function walk(events: Partial<ReturnState>[]): ReturnAction[] {
  let lost = false;
  return events.map((e) => {
    const r = returnAction({ ...base, ...e, lost });
    lost = r.lost;
    return r;
  });
}

describe("returnAction 전이 표", () => {
  it("loading 은 아무것도 바꾸지 않는다", () => {
    expect(act({ status: "loading", lost: true })).toEqual({ lost: true, note: null, focus: "none" });
  });
  it("숨김(notFound) — 폼이 보였으면 lost, 안내는 비운다", () => {
    expect(act({ status: "notFound", hadForm: true })).toEqual({ lost: true, note: "", focus: "none" });
    expect(act({ status: "notFound", hadForm: false })).toEqual({ lost: false, note: "", focus: "none" });
  });
  it("오류는 lost 를 지우지 않고 안내만 비운다", () => {
    expect(act({ status: "error", lost: true })).toEqual({ lost: true, note: "", focus: "none" });
  });
  it("열림 복귀 — 초점이 body 면 입력 칸, 없으면 제목, 밖이면 그대로, 안내는 채운다", () => {
    expect(act({ lost: true, hasDraft: true })).toEqual({ lost: false, note: RELEASED, focus: "draft" });
    expect(act({ lost: true })).toEqual({ lost: false, note: RELEASED, focus: "title" });
    expect(act({ lost: true, focusAtBody: false })).toEqual({ lost: false, note: RELEASED, focus: "none" });
  });
  for (const reason of ["archived", "expelled", "left", "hidden"] as NonNullable<SubmitBlockedReason>[]) {
    it(`막힘(${reason}) 복귀 — 안내 문구는 비우고, body 면 막힘 안내로, 밖이면 그대로`, () => {
      expect(act({ lost: true, reason })).toEqual({ lost: false, note: "", focus: "blocked-note" });
      expect(act({ lost: true, reason, focusAtBody: false })).toEqual({ lost: false, note: "", focus: "none" });
    });
  }
  it("숨김을 겪지 않은 막힘·열림은 초점을 건드리지 않는다", () => {
    expect(act({ reason: "archived" })).toEqual({ lost: false, note: "", focus: "none" });
    expect(act({})).toEqual({ lost: false, note: "", focus: "none" });
  });

  it("연달은 두 사건: 숨김 → (사이 조회 없이) 보관 복귀 → 막힘 안내로 초점", () => {
    const [hide, back] = walk([{ status: "notFound" }, { reason: "archived" }]);
    expect(hide.lost).toBe(true);
    expect(back).toEqual({ lost: false, note: "", focus: "blocked-note" });
  });
  it("오류→회복: 숨김 → 오류 → 열림이면 초점 복구와 안내가 이어진다", () => {
    const r = walk([{ status: "notFound" }, { status: "error" }, { reason: null }]);
    expect(r[2]).toEqual({ lost: false, note: RELEASED, focus: "title" });
  });
  it("오류→회복(막힘): 숨김 → 오류 → 보관이면 막힘 안내로", () => {
    expect(walk([{ status: "notFound" }, { status: "error" }, { reason: "archived" }])[2].focus).toBe("blocked-note");
  });
  it("같은 완료 반복: 열림 → 다시 숨김(안내 비움) → 다시 열림 이 매번 채워진다", () => {
    const r = walk([{ status: "notFound" }, {}, { status: "notFound" }, {}]);
    expect([r[1].note, r[2].note, r[3].note]).toEqual([RELEASED, "", RELEASED]);
  });
  it("되돌림: 열림 → 보관 → 보관 해제는 다시 숨기지 않는 한 초점을 옮기지 않는다", () => {
    const r = walk([{ status: "notFound" }, {}, { reason: "archived" }, {}]);
    expect(r[2]).toEqual({ lost: false, note: "", focus: "none" });
    expect(r[3]).toEqual({ lost: false, note: "", focus: "none" });
  });
  it("되돌림: 숨김 → 보관 복귀 → 다시 숨김 → 열림 은 두 번째도 복구한다", () => {
    const r = walk([{ status: "notFound" }, { reason: "archived" }, { status: "notFound" }, {}]);
    expect(r[1].focus).toBe("blocked-note");
    expect(r[3]).toEqual({ lost: false, note: RELEASED, focus: "title" });
  });
});
