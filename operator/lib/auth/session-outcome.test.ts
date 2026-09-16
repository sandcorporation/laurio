// 세션 확인 응답을 화면이 쓸 상태로 옮기는 규칙(2026-09-16).
//
// **운영자 등급을 잃은 세션이 흰 화면을 만들었다.** 운영자였던 계정이 참가자로
// 내려가면 백엔드는 `/api/operator/me` 에 403(「Operator 권한이 필요합니다」)을
// 낸다 — 세션은 살아 있고 그 사람이 누구인지도 아는데 운영자가 아니라는 뜻이다.
// 그런데 이 앱의 로그인 유도는 401 에서만 돌고(lib/bff/client.ts) 화면은 미인증이면
// 아무것도 그리지 않으므로, 403 은 「보내지도 않고 그리지도 않는」 자리에 떨어졌다.
import { describe, expect, it } from "vitest";

import { sessionOutcomeFor } from "./session-outcome";

describe("세션 확인 응답", () => {
  it("200 은 그대로 통과한다", () => {
    expect(sessionOutcomeFor(200)).toEqual({ status: 200, clearCookie: false });
  });

  it("401 은 쿠키를 지우고 그대로 401 이다 — 로그인으로 보내는 장치가 이걸 본다", () => {
    expect(sessionOutcomeFor(401)).toEqual({ status: 401, clearCookie: true });
  });

  it("403 도 401 로 옮긴다 — 이 세션으로는 운영자 구역에 들어갈 수 없다", () => {
    const outcome = sessionOutcomeFor(403);
    expect(outcome.status).toBe(401);
    expect(outcome.clearCookie).toBe(true);
    expect(outcome.detail).toContain("운영자");
  });

  it("그 밖의 응답은 손대지 않는다 — 쿠키도 지우지 않는다", () => {
    expect(sessionOutcomeFor(500)).toEqual({ status: 500, clearCookie: false });
    expect(sessionOutcomeFor(502)).toEqual({ status: 502, clearCookie: false });
  });
});
