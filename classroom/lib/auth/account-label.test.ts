// 계정 메뉴가 무엇을 이름으로 쓰는가 (#306 후속).
//
// staging 을 브라우저로 걸어 보다 헤더에 `kakao:5069350637` 이 떠 있는 것을 봤다 —
// 소셜 로그인 계정의 `username` 은 제공자 식별자이고 사람이 읽으라고 만든 값이
// 아니다. 카카오는 이메일을 주지 않을 수 있어서 그 갈래가 실제로 흔하다.
import { describe, expect, it } from "vitest";

import { accountLabel } from "./account-label";

describe("accountLabel", () => {
  it("이메일이 있으면 이메일을 쓴다", () => {
    expect(accountLabel({ username: "kakao:5069350637", email: "a@b.test" })).toBe("a@b.test");
  });

  it("이메일이 없으면 제공자 식별자를 그리지 않는다", () => {
    const label = accountLabel({ username: "kakao:5069350637", email: "" });
    expect(label).not.toContain("kakao:");
    expect(label).not.toContain("5069350637");
    expect(label).toBe("내 계정");
  });

  it("공백뿐인 이메일도 없는 것으로 본다", () => {
    expect(accountLabel({ username: "kakao:1", email: "   " })).toBe("내 계정");
  });

  it("이메일 계정은 그 이메일이 그대로 보인다", () => {
    expect(accountLabel({ username: "someone@example.com", email: "someone@example.com" }))
      .toBe("someone@example.com");
  });
});
