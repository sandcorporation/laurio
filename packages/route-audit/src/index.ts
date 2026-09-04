// 고아 라우트 검사 패키지의 공개 표면(#166) — `packages/bff-shared`의 index.ts와
// 같은 이유로 여기서 내보내는 것은 전부 "검사하는 코드"다. 허용목록의 내용(경로
// 문자열과 이유)은 각 앱의 `lib/routes/allowlist.ts`에 남는다.
export {
  listPageRoutes,
  extractLinkSegments,
  findOrphanRoutes,
} from "./route-scan";
export type { RouteEntry, RouteSegment, LinkSegment, OrphanAllowlistEntry } from "./route-scan";
export { defineOrphanRouteSuite } from "./orphan-suite";
export type { OrphanRouteSuiteOptions } from "./orphan-suite";
