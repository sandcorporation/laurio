// 고아 라우트를 기계가 잡는다(#166) — #164·#165가 같은 버그의 두 사례였다: 화면은
// 있고 API도 잘 도는데 제품 안에서 아무도 링크하지 않는다. e2e·백엔드 테스트 둘 다
// `page.goto(...)`/`request.get(...)`으로 URL을 직접 치므로 원리적으로 이걸 못 본다.
//
// route-scan.ts가 (1) `app/**/page.tsx`에서 라우트 목록을 만들고 (2) 소스 전체에서
// 링크를 내는 표현(href·push·replace·redirect·redirectToPath·new URL)을 모아
// 세그먼트 단위로 대조한다 — 자세한 알고리즘과 한계는 그 파일 상단 주석 참고.
import * as path from "node:path";
import { describe, expect, test } from "vitest";

import { ORPHAN_ALLOWLIST } from "./allowlist";
import { extractLinkSegments, findOrphanRoutes, listPageRoutes } from "./route-scan";

// __dirname은 frontend/lib/routes — 앱 루트(frontend/)까지 두 단계 위.
const APP_ROOT = path.resolve(__dirname, "..", "..");
const APP_DIR = path.join(APP_ROOT, "app");

describe("고아 라우트 검사 (#166)", () => {
  const routes = listPageRoutes(APP_DIR);
  const links = extractLinkSegments(APP_ROOT);
  const orphans = findOrphanRoutes(routes, links);
  const orphanDisplays = new Set(orphans.map((r) => r.display));
  const allowlistedRoutes = new Set(ORPHAN_ALLOWLIST.map((entry) => entry.route));

  test("라우트 목록이 비어 있지 않다 (스캔 자체가 깨진 경우를 잡는다)", () => {
    expect(routes.length).toBeGreaterThan(0);
  });

  test("인바운드 링크가 없는 라우트는 허용목록에 있어야 한다", () => {
    const unexpectedOrphans = orphans
      .map((r) => r.display)
      .filter((display) => !allowlistedRoutes.has(display));

    expect(unexpectedOrphans).toEqual([]);
  });

  test("허용목록이 썩지 않았다 — 각 항목은 실존하는 라우트이고 실제로 고아다", () => {
    const allRouteDisplays = new Set(routes.map((r) => r.display));

    for (const entry of ORPHAN_ALLOWLIST) {
      expect(
        allRouteDisplays.has(entry.route),
        `허용목록의 "${entry.route}"가 더 이상 라우트로 존재하지 않는다 — 죽은 항목을 지워라`,
      ).toBe(true);

      expect(
        orphanDisplays.has(entry.route),
        `허용목록의 "${entry.route}"에 이제 인바운드 링크가 생겼다 — 허용목록에서 지워도 된다`,
      ).toBe(true);
    }
  });
});
