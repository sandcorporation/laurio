import { describe, expect, it } from "vitest";

import { loggedInDestination } from "./login-destination";

const CLASSROOM = "https://classroom.example.test";

describe("loggedInDestination", () => {
  it("next 가 없으면 홈", () => {
    expect(loggedInDestination(null, null, null)).toBe("/");
  });

  it("next 가 있으면 그리로 — 쿼리까지", () => {
    expect(loggedInDestination("/console/contests?tab=a", null, null)).toBe("/console/contests?tab=a");
  });

  it("바깥 주소 next 는 홈", () => {
    expect(loggedInDestination("//evil.example.test/x", null, null)).toBe("/");
    expect(loggedInDestination("https://evil.example.test/x", null, null)).toBe("/");
  });

  it("허용된 형제 오리진이면 그 앱의 next 로", () => {
    expect(loggedInDestination("/classes/3", CLASSROOM, CLASSROOM)).toBe(`${CLASSROOM}/classes/3`);
  });

  it("허용되지 않은 next_origin 이면 그 next 를 버리고 홈", () => {
    expect(loggedInDestination("/classes/3", "https://evil.example.test", null)).toBe("/");
  });
});
