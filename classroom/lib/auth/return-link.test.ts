// 계정 메뉴가 공개 앱으로 건너갈 때 붙이는 복귀 주소 (#306). 공개 앱의
// `/console/profile`은 이 앱의 자기 로그인이 없는(ADR-0038)
// 화면이라 그 화면으로 사람을 보낼 뿐이지만, 돌아올 방법이 없으면 뒤로
// 가기 말고는 길이 없다(#307). 그 복귀 주소를 실어 보내는 조립 로직만 여기
// 순수 함수로 둔다 — 실제 오리진 검증(공개 앱의 resolveSiblingOrigin)은
// 받는 쪽 책임이고, 이 함수는 "이 오리진에서 왔다"는 사실만 쿼리에 싣는다.
import { describe, expect, it } from "vitest";

import { buildProfileUrl } from "./return-link";

describe("buildProfileUrl", () => {
  it("공개 앱 프로필 주소에 이 앱의 오리진을 from_origin으로 싣는다", () => {
    const url = buildProfileUrl("http://127.0.0.1:53000", "http://127.0.0.1:53002");
    expect(url).toBe(
      "http://127.0.0.1:53000/console/profile?from_origin=http%3A%2F%2F127.0.0.1%3A53002",
    );
  });
});

describe("buildProfileUrl — 떠난 화면", () => {
  it("현재 경로·쿼리를 from_path 로 싣는다", () => {
    const url = new URL(
      buildProfileUrl("http://127.0.0.1:53000", "http://127.0.0.1:53002", "/classes/7?tab=participants"),
    );
    expect(url.searchParams.get("from_origin")).toBe("http://127.0.0.1:53002");
    expect(url.searchParams.get("from_path")).toBe("/classes/7?tab=participants");
  });

  it.each(["//evil.example/x", "https://evil.example/x", "javascript:alert(1)", "/\\evil.example", "classes/7", ""])(
    "안전하지 않은 경로 %j 는 싣지 않는다",
    (path) => {
      const url = new URL(buildProfileUrl("http://127.0.0.1:53000", "http://127.0.0.1:53002", path));
      expect(url.searchParams.has("from_path")).toBe(false);
    },
  );
});
