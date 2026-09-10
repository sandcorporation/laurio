// 고아 라우트를 기계가 잡는다(#166) — 강의실 인스턴스화. 공개 앱
// (frontend/lib/routes/orphan-routes.test.ts)·운영자 앱과 같은 스위트를 부른다.
import * as path from "node:path";

import { defineOrphanRouteSuite } from "@laurio/route-audit";

import { ORPHAN_ALLOWLIST } from "./allowlist";

// __dirname은 classroom/lib/routes — 앱 루트(classroom/)까지 두 단계 위.
const APP_ROOT = path.resolve(__dirname, "..", "..");

defineOrphanRouteSuite({
  appRoot: APP_ROOT,
  allowlist: ORPHAN_ALLOWLIST,
  appLabel: "강의실",
});
