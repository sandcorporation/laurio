// 의도적으로 인바운드 링크가 없는 라우트(#166) — 강의실 몫. 지금은 없다: "/"는
// header brand가, "/login"은 middleware.ts의 `new URL("/login", ...)`가 각각
// 링크를 낸다.
import type { OrphanAllowlistEntry } from "@laurio/route-audit";

export const ORPHAN_ALLOWLIST: OrphanAllowlistEntry[] = [];
