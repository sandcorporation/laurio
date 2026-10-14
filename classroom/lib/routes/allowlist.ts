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
    route: "/invite/[token]",
    reason:
      // SCREEN-LANGUAGE-EXCEPTION: route-audit 도구가 읽는 개발자용 근거 문서이지
      // 사용자에게 렌더링되는 화면 문자열이 아니다 — 이슈 번호가 바로 그 근거다.
      "공동 강사 초대 링크(#561)는 강사가 클래스 상세에서 복사해 앱 밖으로 건네는 " +
      "주소다 — 가입 링크와 같이 이 앱 안의 <Link>가 이 라우트로 이어질 이유가 없다.",
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
  {
    route: "/classes/[id]/members",
    reason:
      // SCREEN-LANGUAGE-EXCEPTION: route-audit 도구가 읽는 개발자용 근거 문서이지
      // 사용자에게 렌더링되는 화면 문자열이 아니다 — 이슈 번호가 바로 그 근거다.
      "참여자 명단 화면은 클래스 상세의 참여자 탭으로 합쳐졌다(#634) — 예전 주소를 " +
      "북마크한 사람만 밟고, 이 라우트는 /classes/<id>?tab=participants 로 리다이렉트만 " +
      "한다. 이 앱 안의 <Link>가 이 라우트로 이어질 이유가 없다.",
  },
  {
    route: "/oauth/authorize",
    reason:
      // SCREEN-LANGUAGE-EXCEPTION: route-audit 도구가 읽는 개발자용 근거 문서이지
      // 사용자에게 렌더링되는 화면 문자열이 아니다 — 이슈 번호가 바로 그 근거다.
      "연결된 앱의 동의 화면(#512, ADR-0052)은 외부 AI 앱이 강사의 브라우저를 " +
      "보내는 OAuth 인가 주소다 — 인가 서버 메타데이터가 이 주소를 알리고, " +
      "이 앱 안의 <Link>가 이 라우트로 이어질 이유가 없다.",
  },
];
