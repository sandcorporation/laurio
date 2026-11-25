import { describe, expect, it } from "vitest";

import { modelRejectionNoteId, modelSelectDescribedBy } from "./model-rejection-description";

describe("modelSelectDescribedBy", () => {
  it("거부된 모델이면 select 가 배지 묶음을 가리킨다", () => {
    expect(modelSelectDescribedBy("edit", true)).toBe(modelRejectionNoteId("edit"));
  });

  it("거부되지 않았으면 가리킬 것이 없다", () => {
    expect(modelSelectDescribedBy("edit", false)).toBeUndefined();
  });
});
