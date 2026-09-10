// 순수 함수 시임 — 공개 앱·운영자 앱의 vitest.config.mts와 같은 규약이다.
import { defineConfig } from "vitest/config";

import { pureModuleGuard } from "../vitest.shared.mts";

export default defineConfig({
  plugins: [pureModuleGuard()],
  test: {
    environment: "node",
    include: ["lib/**/*.test.ts"],
  },
});
