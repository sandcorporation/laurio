import { describe, expect, it } from "vitest";

import type { ApiFailure } from "@codemit/bff-client";

import { resolveMutationErrorMessage } from "./mutation-error";

function failure(overrides: Partial<ApiFailure>): ApiFailure {
  return { ok: false, status: 422, code: "validation", detail: "", ...overrides };
}

describe("resolveMutationErrorMessage", () => {
  it("서버가 응답한 실패면 그 detail을 그대로 쓴다", () => {
    const result = failure({ detail: "필수 항목을 하나 이상 추가해야 열 수 있습니다" });
    expect(resolveMutationErrorMessage(result, "기본 문구")).toBe(
      "필수 항목을 하나 이상 추가해야 열 수 있습니다",
    );
  });

  it("네트워크 실패면 기본 문구를 쓴다", () => {
    const result = failure({ status: 0, code: "network", detail: "요청을 처리하지 못했습니다." });
    expect(resolveMutationErrorMessage(result, "기본 문구")).toBe("기본 문구");
  });
});
