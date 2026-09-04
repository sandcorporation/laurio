// 고아 라우트를 기계가 잡는다(#166) — 운영자 앱 인스턴스화. #164·#165가 같은 버그의
// 두 사례였다: 화면은 있고 API도 잘 도는데 제품 안에서 아무도 링크하지 않는다.
// e2e·백엔드 테스트 둘 다 `page.goto(...)`/`request.get(...)`으로 URL을 직접 치므로
// 원리적으로 이걸 못 본다.
//
// 스캐너와 스위트 본체는 `@laurio/route-audit`(공개 앱·운영자 앱 공유, #166 코드리뷰)에
// 있다 — 여기 남는 것은 어느 디렉터리를 훑는지(`appRoot`)와 이 앱의 허용목록뿐이다.
import * as path from "node:path";

import { defineOrphanRouteSuite } from "@laurio/route-audit";

import { ORPHAN_ALLOWLIST } from "./allowlist";

// __dirname은 operator/lib/routes — 앱 루트(operator/)까지 두 단계 위.
const APP_ROOT = path.resolve(__dirname, "..", "..");

defineOrphanRouteSuite({
  appRoot: APP_ROOT,
  allowlist: ORPHAN_ALLOWLIST,
  appLabel: "운영자 앱",
});
