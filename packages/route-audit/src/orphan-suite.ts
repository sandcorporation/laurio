// 고아 라우트 검사의 vitest 스위트 본체(#166) — 공개 앱·운영자 앱이 이 함수 하나를
// 부르는 것으로 같은 세 가지 단언(허용되지 않은 고아 없음·허용목록 죽은 항목 없음·
// 허용목록 낡은 항목 없음)을 공유한다. 앱마다 갈리면 안 될 게 시험 로직이 아니라
// "어느 디렉터리를 훑는지"·"허용목록에 뭐가 들었는지" 둘뿐이라는 것을 코드로 강제한다
// — route-scan.ts 상단 주석 참고.
import { describe, expect, test } from "vitest";

import { extractLinkSegments, findOrphanRoutes, listPageRoutes } from "./route-scan";
import type { OrphanAllowlistEntry } from "./route-scan";

export interface OrphanRouteSuiteOptions {
  /** 앱 루트 디렉터리(예: frontend/, operator/) — 그 바로 아래 `app/`을 라우트
   * 목록으로, 디렉터리 전체를 링크 소스(components·lib·middleware.ts 등 포함)로 쓴다. */
  appRoot: string;
  allowlist: OrphanAllowlistEntry[];
  /** 테스트 제목에 붙일 앱 이름. 두 앱의 실패 로그를 한 CI 잡 출력에서 구분하기 위함. */
  appLabel: string;
}

export function defineOrphanRouteSuite(options: OrphanRouteSuiteOptions): void {
  const { appRoot, allowlist, appLabel } = options;
  const appDir = `${appRoot}/app`;

  describe(`고아 라우트 검사 (#166, ${appLabel})`, () => {
    const routes = listPageRoutes(appDir);
    const links = extractLinkSegments(appRoot);
    const orphans = findOrphanRoutes(routes, links);
    const orphanDisplays = new Set(orphans.map((r) => r.display));
    const allowlistedRoutes = new Set(allowlist.map((entry) => entry.route));

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

      for (const entry of allowlist) {
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
}
