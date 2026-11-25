import { describe, expect, it } from "vitest";

import { reloadAfterNameSave } from "./name-save-outcome";

describe("reloadAfterNameSave", () => {
  it("저장이 됐으면 다시 읽는다 — 저장된 값으로 칸을 맞춘다", () => {
    expect(reloadAfterNameSave(null)).toBe(true);
  });

  it("검증·서버 오류로 실패하면 다시 읽지 않는다 — 적던 값이 지워지지 않는다(#1447 11)", () => {
    expect(reloadAfterNameSave({ status: 422 })).toBe(false);
    expect(reloadAfterNameSave({ status: 500 })).toBe(false);
    expect(reloadAfterNameSave({ status: 0 })).toBe(false);
  });

  it("접근을 잃어 실패하면 다시 읽는다 — 접근 안내가 뜨고 초안은 그 곁에 남는다", () => {
    expect(reloadAfterNameSave({ status: 404 })).toBe(true);
    expect(reloadAfterNameSave({ status: 403 })).toBe(true);
  });
});
