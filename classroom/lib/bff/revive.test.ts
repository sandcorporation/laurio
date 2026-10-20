// 강의실 클라이언트가 401 에 `/api/auth/session` 으로 세션을 되살린다(#767) — 리프레시
// 회전 경합에서 진 요청의 401 하나로 켜 둔 탭이 로그인으로 튕기지 않게 하는 자리다.
// `client.ts` 는 "use client" 모듈이라 이 러너에서 직접 임포트하지 않고 원문을 읽는다.
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, test } from "vitest";

describe("classroom bffClient (#767)", () => {
  test("createBffClient 에 /api/auth/session 을 부르는 revive 를 준다", () => {
    const source = readFileSync(join(__dirname, "client.ts"), "utf-8");
    const call = source.match(/createBffClient\(\{([\s\S]*?)\n\}\);/)?.[1] ?? "";

    expect(call).toMatch(/revive:\s*\(\)\s*=>\s*fetch\("\/api\/auth\/session"/);
    expect(call).toContain("onUnauthorized: goToLogin");
  });
});
