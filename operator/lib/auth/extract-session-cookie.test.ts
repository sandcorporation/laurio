// extractSessionCookieValue의 이름 경계를 전수로 덮는다(#162) — 접두어로만
// 겹치는 다른 쿠키를 집지 않는지, 값에 구분자("="·";")가 섞여도 흔들리지 않는지.
import { describe, expect, test } from "vitest";

import { extractSessionCookieValue } from "./extract-session-cookie";
import { SESSION_COOKIE_NAME } from "./cookies";

function responseWithSetCookies(setCookieHeaders: string[]): Response {
  const headers = new Headers();
  for (const raw of setCookieHeaders) headers.append("set-cookie", raw);
  return { headers } as unknown as Response;
}

describe("extractSessionCookieValue — 이름 경계(전수)", () => {
  test("Set-Cookie가 하나도 없으면 null", () => {
    expect(extractSessionCookieValue(responseWithSetCookies([]))).toBeNull();
  });

  test("대상 쿠키 하나만 있으면 그 값을 그대로 뽑는다", () => {
    expect(
      extractSessionCookieValue(responseWithSetCookies([`${SESSION_COOKIE_NAME}=abc123; Path=/; HttpOnly`])),
    ).toBe("abc123");
  });

  test("여러 Set-Cookie 중 대상이 섞여 있어도(순서 무관) 찾아낸다", () => {
    expect(
      extractSessionCookieValue(
        responseWithSetCookies([
          "csrftoken=xyz; Path=/",
          `${SESSION_COOKIE_NAME}=abc123; Path=/; HttpOnly`,
          "other=1; Path=/",
        ]),
      ),
    ).toBe("abc123");
  });

  test("대상 쿠키가 없으면 다른 쿠키가 몇 개든 null", () => {
    expect(
      extractSessionCookieValue(
        responseWithSetCookies(["csrftoken=xyz; Path=/", "other=1; Path=/"]),
      ),
    ).toBeNull();
  });

  describe("이름 경계 — 접두어·부분 문자열로 겹치는 다른 쿠키를 집지 않는다", () => {
    test("대상 이름을 접두어로만 가진 더 긴 이름은 무시한다", () => {
      expect(
        extractSessionCookieValue(
          responseWithSetCookies([`${SESSION_COOKIE_NAME}_extra=should-not-match; Path=/`]),
        ),
      ).toBeNull();
    });

    test("대상 이름을 접미어로만 가진(다른 접두어가 붙은) 쿠키는 무시한다", () => {
      expect(
        extractSessionCookieValue(
          responseWithSetCookies([`other_${SESSION_COOKIE_NAME}=should-not-match; Path=/`]),
        ),
      ).toBeNull();
    });

    test("접두어로만 겹치는 쿠키와 진짜 대상이 함께 있으면 진짜 것만 고른다", () => {
      expect(
        extractSessionCookieValue(
          responseWithSetCookies([
            `${SESSION_COOKIE_NAME}_extra=decoy; Path=/`,
            `${SESSION_COOKIE_NAME}=real-value; Path=/`,
          ]),
        ),
      ).toBe("real-value");
    });
  });

  describe("값에 구분자가 섞여도 흔들리지 않는다", () => {
    test("값 안에 '=' 문자가 더 있어도(base64 패딩 등) 첫 '='만 이름/값 경계로 쓴다", () => {
      expect(
        extractSessionCookieValue(
          responseWithSetCookies([`${SESSION_COOKIE_NAME}=YWJjMTIz==; Path=/`]),
        ),
      ).toBe("YWJjMTIz==");
    });

    test("쿠키 속성이 ';'로 이어져도 값에 섞이지 않는다", () => {
      expect(
        extractSessionCookieValue(
          responseWithSetCookies([`${SESSION_COOKIE_NAME}=abc123; Path=/; HttpOnly; SameSite=Lax`]),
        ),
      ).toBe("abc123");
    });

    test("값이 URL 인코딩되어 있으면 디코드해서 돌려준다", () => {
      expect(
        extractSessionCookieValue(
          responseWithSetCookies([`${SESSION_COOKIE_NAME}=${encodeURIComponent("a+b/c")}; Path=/`]),
        ),
      ).toBe("a+b/c");
    });

    test("값이 비어 있으면 null(빈 값은 세션이 아니다)", () => {
      expect(
        extractSessionCookieValue(responseWithSetCookies([`${SESSION_COOKIE_NAME}=; Path=/`])),
      ).toBeNull();
    });

    test("'='가 아예 없는 Set-Cookie 항목은 건너뛰고 나머지에서 찾는다", () => {
      expect(
        extractSessionCookieValue(
          responseWithSetCookies(["malformed-no-equals", `${SESSION_COOKIE_NAME}=abc123; Path=/`]),
        ),
      ).toBe("abc123");
    });

    test("이름 앞뒤 공백은 트림 후 비교한다", () => {
      expect(
        extractSessionCookieValue(responseWithSetCookies([` ${SESSION_COOKIE_NAME} =abc123; Path=/`])),
      ).toBe("abc123");
    });
  });
});
