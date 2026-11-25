import { describe, expect, it } from "vitest";

import { submitRejectedAsBlocked } from "./submit-blocked";

describe("submitRejectedAsBlocked", () => {
  it("403·404 를 막힘으로 본다", () => {
    expect(submitRejectedAsBlocked({ ok: false, status: 403 })).toBe(true);
    expect(submitRejectedAsBlocked({ ok: false, status: 404 })).toBe(true);
    expect(submitRejectedAsBlocked({ ok: false, status: 422 })).toBe(false);
    expect(submitRejectedAsBlocked({ ok: false, status: 0 })).toBe(false);
    expect(submitRejectedAsBlocked({ ok: true, status: 200 })).toBe(false);
  });
});
