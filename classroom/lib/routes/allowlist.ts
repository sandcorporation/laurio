// 의도적으로 인바운드 링크가 없는 라우트(#166) — 강의실 몫. "/"는 header
// brand가, "/login"은 middleware.ts의 `new URL("/login", ...)`가 각각 링크를
// 낸다.
import type { OrphanAllowlistEntry } from "@codemit/route-audit";

export const ORPHAN_ALLOWLIST: OrphanAllowlistEntry[] = [
  {
    route: "/join/[code]",
    reason:
      // SCREEN-LANGUAGE-EXCEPTION: route-audit 도구가 읽는 개발자용 근거 문서이지
      // 사용자에게 렌더링되는 화면 문자열이 아니다 — 이슈 번호가 바로 그 근거다.
      "가입 링크(#279/#280)는 강사가 클래스 상세에서 복사해 앱 밖으로 내보내는 " +
      "주소다 — 이 앱 안의 <Link>가 이 라우트로 이어질 이유가 없다.",
  },
  {
    route: "/class-templates",
    reason:
      // SCREEN-LANGUAGE-EXCEPTION: route-audit 도구가 읽는 개발자용 근거 문서이지
      // 사용자에게 렌더링되는 화면 문자열이 아니다 — 이슈 번호가 바로 그 근거다.
      "공유 코드를 지운 주소를 친 사람만 밟는다(#350) — 목록 링크는 전부 " +
      "/class-templates/<공유코드>로 이어지고, 이 라우트는 /templates?kind=class로 " +
      "리다이렉트만 한다. 이 앱 안의 <Link>가 이 라우트로 이어질 이유가 없다.",
  },
];
