// 순수 함수 시임(ADR-0026) — `detail` 번역처럼 react 없이 도는 파일만 대상으로 한다(#1390).
import { defineConfig } from "vitest/config";

import { pureModuleGuard } from "../../vitest.shared.mts";

export default defineConfig({
  plugins: [pureModuleGuard()],
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
