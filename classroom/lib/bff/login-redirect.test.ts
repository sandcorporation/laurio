import { describe, expect, it } from "vitest";

import { createLoginRedirect } from "@codemit/bff-client/login-redirect";

function fakeNavigator(path = "/classes?tab=mine") {
  const replaced: string[] = [];
  return { replaced, navigator: { currentPath: () => path, replace: (url: string) => replaced.push(url) } };
}

describe("createLoginRedirect (#501)", () => {
  it("한 화면의 요청 둘이 함께 401 을 받아도 로그인으로의 이동은 한 번이다", () => {
    const { replaced, navigator } = fakeNavigator();
    const goToLogin = createLoginRedirect({ navigator, now: () => 1_000 });

    goToLogin(); // 「내 클래스」
    goToLogin(); // 헤더 알림 벨

    expect(replaced).toEqual(["/login?next=%2Fclasses%3Ftab%3Dmine"]);
  });

  it("창이 지나면 다시 보낸다 — 이동이 취소돼 페이지가 남아도 다음 만료 때 막히지 않는다", () => {
    const { replaced, navigator } = fakeNavigator("/");
    let clock = 0;
    const goToLogin = createLoginRedirect({ navigator, now: () => clock, windowMs: 3_000 });

    goToLogin();
    clock = 2_999;
    goToLogin();
    clock = 3_000;
    goToLogin();

    expect(replaced).toHaveLength(2);
  });
});
