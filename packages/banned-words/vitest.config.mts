// 순수 함수 시임(#161, ADR-0026) — 이 패키지는 react·next 어느 것도 임포트하지
// 않는다(데이터 목록 + 문자열 포함 검사 하나뿐이다), 그래도 다른 패키지들과 같은
// 가드를 걸어 둔다 — 나중에 누가 실수로 브라우저 전용 의존성을 끌어와도 그 자리에서
// 막힌다.
import { defineConfig } from "vitest/config";

import { pureModuleGuard } from "../../vitest.shared.mts";

export default defineConfig({
  plugins: [pureModuleGuard()],
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
