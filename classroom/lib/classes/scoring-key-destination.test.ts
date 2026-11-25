import { describe, expect, it } from "vitest";

import { scoringKeyDestination } from "./scoring-key-destination";

describe("scoringKeyDestination", () => {
  it("소유자는 설정의 채점 연결 구획으로 간다", () => {
    expect(scoringKeyDestination(7, "owner")).toBe("/classes/7/settings#scoring-key");
  });

  it("공동 강사는 설정이 아니라 클래스 화면으로 간다 — 거기서 할 수 있는 일이 없다", () => {
    expect(scoringKeyDestination(7, "co_instructor")).toBe("/classes/7");
  });
});
