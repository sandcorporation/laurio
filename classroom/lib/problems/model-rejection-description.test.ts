import { describe, expect, it } from "vitest";

import {
  defaultModelGroupDescribedBy,
  modelRejectionBadgeId,
  modelRejectionNoteId,
  modelSelectDescribedBy,
} from "./model-rejection-description";

describe("modelSelectDescribedBy", () => {
  it("거부된 모델이면 select 가 배지만 가리킨다 — 묶음 전체(다시 시도 단추 글자)가 아니다(#1441-11)", () => {
    expect(modelSelectDescribedBy("edit", true)).toBe(modelRejectionBadgeId("edit"));
    expect(modelSelectDescribedBy("edit", true)).not.toBe(modelRejectionNoteId("edit"));
  });

  it("거부되지 않았으면 가리킬 것이 없다", () => {
    expect(modelSelectDescribedBy("edit", false)).toBeUndefined();
  });
});

describe("defaultModelGroupDescribedBy (#1441-2)", () => {
  it("거부된 현재 값 줄이 있으면 라디오 묶음이 그 줄을 가리킨다", () => {
    expect(defaultModelGroupDescribedBy(true)).toBe("class-default-model-unavailable");
  });

  it("없으면 가리킬 것이 없다", () => {
    expect(defaultModelGroupDescribedBy(false)).toBeUndefined();
  });
});
