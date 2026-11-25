import { normalizeDetail } from "../../../packages/bff-client/src/result";
import { describe, expect, it } from "vitest";

import { DEVELOPER_PROFILE_DESCRIPTION, PROFILE_FIELD_LABELS } from "./field-labels";

describe("PROFILE_FIELD_LABELS", () => {
  it("표시 이름 상한 422 가 칸 이름을 단다(#1426)", () => {
    const detail = [
      { type: "string_too_long", loc: ["body", "payload", "display_name"], msg: "x", ctx: { max_length: 100 } },
    ];
    expect(normalizeDetail(detail, undefined, PROFILE_FIELD_LABELS)).toBe("표시 이름: 100자까지 쓸 수 있습니다.");
  });
});

describe("DEVELOPER_PROFILE_DESCRIPTION", () => {
  it("자리표시자가 글자 그대로 나오지 않는다(#1426)", () => {
    expect(DEVELOPER_PROFILE_DESCRIPTION).not.toMatch(/[{}]/);
  });
});
