// 계정 메뉴가 공개 앱으로 건너갈 때 붙이는 복귀 주소 (#306). 공개 앱의
// `/console/profile`·`/console/withdraw`는 이 앱의 자기 로그인이 없는(ADR-0038)
// 화면이라 그 두 화면으로 사람을 보낼 뿐이지만, 돌아올 방법이 없으면 뒤로
// 가기 말고는 길이 없다(#307). 그 복귀 주소를 실어 보내는 조립 로직만 여기
// 순수 함수로 둔다 — 실제 오리진 검증(공개 앱의 resolveSiblingOrigin)은
// 받는 쪽 책임이고, 이 함수는 "이 오리진에서 왔다"는 사실만 쿼리에 싣는다.
import { describe, expect, it } from "vitest";

import { buildProfileUrl, buildWithdrawUrl } from "./return-link";

describe("buildProfileUrl", () => {
  it("공개 앱 프로필 주소에 이 앱의 오리진을 from_origin으로 싣는다", () => {
    const url = buildProfileUrl("http://127.0.0.1:53000", "http://127.0.0.1:53002");
    expect(url).toBe(
      "http://127.0.0.1:53000/console/profile?from_origin=http%3A%2F%2F127.0.0.1%3A53002",
    );
  });
});

describe("buildWithdrawUrl", () => {
  it("공개 앱 탈퇴 주소에 이 앱의 오리진을 from_origin으로 싣는다", () => {
    const url = buildWithdrawUrl("https://laurio.example.test", "https://classroom.laurio.example.test");
    expect(url).toBe(
      "https://laurio.example.test/console/withdraw?from_origin=" +
        "https%3A%2F%2Fclassroom.laurio.example.test",
    );
  });
});
