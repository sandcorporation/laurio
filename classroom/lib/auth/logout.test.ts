import { describe, expect, it } from "vitest";

import { AFTER_LOGOUT_PATH } from "./logout";

describe("로그아웃 뒤 목적지 (#1388)", () => {
  it("강의실 랜딩(/)이다 — 공개 앱 로그인 폼으로 보내는 /login 이 아니다", () => {
    expect(AFTER_LOGOUT_PATH).toBe("/");
  });
});
