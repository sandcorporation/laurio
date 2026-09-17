import { describe, expect, it } from "vitest";

import { BackendError } from "../backend/client";

import { resolveMutationErrorMessage } from "./mutation-error";

describe("resolveMutationErrorMessage", () => {
  it("BackendError면 서버가 준 문구를 그대로 쓴다", () => {
    const err = new BackendError(422, "필수 항목을 하나 이상 추가해야 열 수 있습니다");
    expect(resolveMutationErrorMessage(err, "기본 문구")).toBe(
      "필수 항목을 하나 이상 추가해야 열 수 있습니다",
    );
  });

  it("BackendError가 아니면 기본 문구를 쓴다", () => {
    expect(resolveMutationErrorMessage(new TypeError("network"), "기본 문구")).toBe("기본 문구");
    expect(resolveMutationErrorMessage("문자열 오류", "기본 문구")).toBe("기본 문구");
    expect(resolveMutationErrorMessage(undefined, "기본 문구")).toBe("기본 문구");
  });
});
