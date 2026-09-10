// 의도적으로 인바운드 링크가 없는 라우트(#166) — 강의실 몫. "/"는 header
// brand가, "/login"은 middleware.ts의 `new URL("/login", ...)`가 각각 링크를
// 낸다.
import type { OrphanAllowlistEntry } from "@laurio/route-audit";

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
    route: "/classes/[id]/problems/[problemId]/submit",
    reason:
      // SCREEN-LANGUAGE-EXCEPTION: 위와 같은 이유 — 개발자용 근거 문서다.
      "참여자 제출 화면(#286)이다 — 참여자가 자기 클래스에서 열린 문제로 들어오는 " +
      "목록(참여자의 「문제 목록」)이 그 티켓의 몫이라 아직 없다. 그때 그 목록이 " +
      "이 라우트로 이어지는 <Link>를 내면 이 항목을 지운다.",
  },
];
