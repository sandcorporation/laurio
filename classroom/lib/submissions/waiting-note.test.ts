import { describe, expect, it } from "vitest";

import { waitingNote } from "./waiting-note";

describe("waitingNote", () => {
  it("참여자 — 다시 낼 필요 없다", () => {
    expect(waitingNote("no_api_key", null)).toBe("강사의 채점 설정 때문에 멈췄습니다 — 다시 낼 필요 없습니다");
    expect(waitingNote("model_rejected", undefined)).toBe("강사의 채점 설정 때문에 멈췄습니다 — 다시 낼 필요 없습니다");
  });

  it("소유자 본인 시도 — 넣으면 이어서 채점된다", () => {
    expect(waitingNote("no_api_key", "owner")).toBe("채점 키를 넣으면 이어서 채점됩니다");
    expect(waitingNote("model_rejected", "owner")).toBe("채점 모델을 바꾸면 이어서 채점됩니다");
  });

  it("공동 강사 본인 시도 — 키는 소유자에게 부탁하고, 모델은 스스로 바꾼다(#1425)", () => {
    expect(waitingNote("no_api_key", "co_instructor")).toBe("소유자에게 채점 키를 넣어 달라고 하세요");
    expect(waitingNote("model_rejected", "co_instructor")).toBe("채점 모델을 바꾸면 이어서 채점됩니다");
  });
});
