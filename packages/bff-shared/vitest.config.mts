// 순수 함수 시임(#161, ADR-0026) — 공유 BFF 패키지의 검사 함수만 대상으로 한다.
//
// `pureModuleGuard()`가 react·next(next/server 제외) 임포트를 자리에서 거부한다
// (../../vitest.shared.mts 주석 참고). origin.ts는 `next/server`의 NextRequest·
// NextResponse를 쓰지만 그건 예외 목록에 있다 — 앱 없이 Node에서 동일하게
// 동작하는 Fetch API 래퍼이기 때문이다.
import { defineConfig } from "vitest/config";

import { pureModuleGuard } from "../../vitest.shared.mts";

export default defineConfig({
  plugins: [pureModuleGuard()],
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
