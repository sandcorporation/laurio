// 의도적으로 인바운드 링크가 없는 라우트(#166) — 공개 앱의 몫. 조용한 고아를
// 명시적인 결정으로 바꾸는 것이 이 검사의 값이 나오는 지점이다 — 항목을 더할 때는
// 반드시 이유를 적는다. `@codemit/route-audit`의 `defineOrphanRouteSuite`(공유
// 스위트, 두 앱이 같은 로직을 쓴다)가 각 항목이 (a) 실제로 존재하는 라우트이고
// (b) 실제로 인바운드 링크가 없는 라우트인지를 함께 검사한다 — 허용목록이 죽은
// 채 남는 것도, 이미 링크가 생겼는데 그대로 남는 것도 막는다.
import type { OrphanAllowlistEntry } from "@codemit/route-audit";

export const ORPHAN_ALLOWLIST: OrphanAllowlistEntry[] = [
  {
    route: "/dev-tokens",
    reason:
      // SCREEN-LANGUAGE-EXCEPTION: route-audit 도구가 읽는 개발자용 근거 문서이지
      // 사용자에게 렌더링되는 화면 문자열이 아니다 — 이슈 번호가 바로 그 근거다.
      "토큰 배선 증명용 진단 화면(FE-02 #27, #93). 페이지 자신의 주석이 " +
      '"헤더 어디에서도 링크되지 않는다 — 첫 방문자가 걸어서 닿을 이유가 없는 ' +
      // SCREEN-LANGUAGE-EXCEPTION: 위와 같음 — 개발자용 근거 문서.
      '진단 화면"이라고 명시한다. 배포 환경에서는 404다(#93 코드리뷰).',
  },
  {
    route: "/console/dev-upload-demo",
    reason:
      // SCREEN-LANGUAGE-EXCEPTION: 위와 같음 — 개발자용 근거 문서.
      "presigned 업로드(FE-09 #34)의 인수조건을 브라우저 네트워크 관찰로 검증하기 " +
      "위한 개발용 증명 화면. 페이지 자신의 주석이 " +
      '"별도 제품 기능이 아니라... 검증할 수 있는 최소 표면"이라고 명시한다 — ' +
      "실제 제출 폼은 이 페이지가 아니라 components/upload/upload-field.tsx를 직접 쓴다.",
  },
  {
    route: "/oauth/authorize",
    reason:
      // SCREEN-LANGUAGE-EXCEPTION: route-audit 도구가 읽는 개발자용 근거 문서이지
      // 사용자에게 렌더링되는 화면 문자열이 아니다 — 이슈 번호가 바로 그 근거다.
      "공모전 MCP 의 동의 화면(#870, ADR-0070)은 외부 AI 앱이 사용자의 브라우저를 " +
      "보내는 OAuth 인가 주소다 — 인가 서버 메타데이터가 이 주소를 알리고, " +
      "이 앱 안의 <Link>가 이 라우트로 이어질 이유가 없다.",
  },
  {
    route: "/c/[token]",
    reason:
      // SCREEN-LANGUAGE-EXCEPTION: route-audit 도구가 읽는 개발자용 근거 문서이지
      // 사용자에게 렌더링되는 화면 문자열이 아니다 — 이슈 번호가 바로 그 근거다.
      "상장 확인 페이지(#1128, 스펙 #1071)는 상장 PDF 의 QR·확인 주소로만 닿는 곳이다 — " +
      "검색에도 싣지 않으므로(robots·X-Robots-Tag) 이 앱 안의 <Link>가 이어질 이유가 없다.",
  },
  {
    route: "/console/feedback/[id]",
    reason:
      // SCREEN-LANGUAGE-EXCEPTION: route-audit 도구가 읽는 개발자용 근거 문서이지
      // 사용자에게 렌더링되는 화면 문자열이 아니다 — 이슈 번호가 바로 그 근거다.
      "내 제보 상세(#1241)로 가는 링크는 공유 패키지(`@codemit/bff-client/feedback`)의 목록 행이 " +
      "`detailHref` 로 받은 주소를 `<a href>` 에 넣어 낸다 — 이 앱 소스에는 리터럴 링크가 없어 스캐너가 못 본다.",
  },
];
