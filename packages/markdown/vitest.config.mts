// 순수 함수 시임 — `packages/bff-shared/vitest.config.mts` 와 같은 규약이다.
//
// **대상은 파싱과 파일 이름 계산뿐이다.** 그리는 쪽(`view.tsx`·`client.tsx`)은
// react 를 임포트하므로 `pureModuleGuard()` 가 여기서 거부한다 — 그건 실행 중인
// 앱을 치는 e2e 의 몫이다(ADR-0017/0021/0026).
import { defineConfig } from "vitest/config";

import { pureModuleGuard } from "../../vitest.shared.mts";

export default defineConfig({
  plugins: [pureModuleGuard()],
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
