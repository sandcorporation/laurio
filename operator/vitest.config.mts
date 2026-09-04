// 순수 함수 시임(#160, ADR-0026) — 운영자 앱의 순수 모듈만 대상으로 한다.
//
// `environment: "node"`가 기본값이라 DOM 전역(window·document)이 애초에 없다 — 참조하는
// 순간 ReferenceError로 터진다. `pureModuleGuard()`가 react·next(next/server 제외)
// 임포트를 자리에서 거부한다(../vitest.shared.mts 주석 참고). 대상은 `lib/**` 아래의
// `*.test.ts`뿐이다 — e2e는 `frontend/e2e/operator/**/*.spec.ts`로 확장자 자체가
// 갈려 있어 이 러너와 절대 겹치지 않는다.
import { defineConfig } from "vitest/config";

import { pureModuleGuard } from "../vitest.shared.mts";

export default defineConfig({
  plugins: [pureModuleGuard()],
  test: {
    environment: "node",
    include: ["lib/**/*.test.ts"],
  },
});
