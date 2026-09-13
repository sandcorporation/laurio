"use client";

// 헤더의 세션 슬롯(#93, spec #92). 헤더 전체를 클라이언트 컴포넌트로 만들지
// 않기 위해 세션에 따라 갈리는 부분만 따로 뗀 조각이다(ADR-0015). 헤더는
// 색인 대상 공개 페이지에도 실리므로, 이 슬롯 밖의 나머지(브랜드·공모전 링크·
// 개최 CTA)는 여전히 서버에서 렌더된다.
//
// **세션은 여기서 묻지 않는다(#237).** 예전에는 이 컴포넌트가 직접
// `GET /api/auth/session`을 불렀는데, 헤더의 `NotificationBell`도 자기 조회의
// 401을 되살리려고 같은 경로를 다시 불러 — 방문자 하나가 열어 둔 페이지
// 하나에서 그 경로가 여러 번 불렸다(실측 staging 7회). 지금은 `HeaderSessionZone`이
// 한 번만 묻고 그 결과를 `sessionState`로 내려준다 — 이 컴포넌트는 그것을
// 그대로 그린다.
import Link from "next/link";

import { buttonClass } from "@/lib/ui/classnames";
import type { HeaderSessionState } from "@/lib/auth/header-session-state";

export function SessionSlot({ sessionState }: { sessionState: HeaderSessionState }) {
  // 로딩 중에는 아무 링크도 단언하지 않는다 — 자바스크립트가 없으면(ADR-0015
  // 검증 기법, seam.spec.ts) 이 자리에 영원히 머무르지만, 헤더의 나머지(브랜드·
  // 공모전·개최 CTA)는 서버에서 이미 렌더돼 있어 사이트가 걷는 데는 지장이
  // 없다.
  if (sessionState.status === "loading") {
    return <span data-testid="header-session-loading" aria-hidden="true" />;
  }

  if (sessionState.status === "authenticated") {
    return (
      <Link href="/console" data-testid="header-console-link" className={buttonClass("secondary", "sm")}>
        내 콘솔
      </Link>
    );
  }

  return (
    <Link href="/login" data-testid="header-login-link" className={buttonClass("secondary", "sm")}>
      로그인
    </Link>
  );
}
