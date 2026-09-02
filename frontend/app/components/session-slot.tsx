"use client";

// 헤더의 세션 슬롯(#93, spec #92) — 헤더 전체를 클라이언트 컴포넌트로 만들지
// 않기 위해 세션에 따라 갈리는 부분만 따로 뗀 조각이다(ADR-0015). 헤더는
// 색인 대상 공개 페이지에도 실리므로, 이 슬롯 밖의 나머지(브랜드·공모전 링크·
// 개최 CTA)는 여전히 서버에서 렌더된다.
//
// `lib/auth/use-session.ts`를 그대로 쓰지 않는다 — 그 훅은 인증 구역
// (app/console/**)을 지키려고 "세션이 없으면 /login 으로 보낸다"를 내장하고
// 있다. 헤더는 공개 페이지에도 서므로 로그인 안 한 방문자가 정상이다 — 그
// 상태를 리다이렉트가 아니라 "로그인" 링크로 보여줘야 한다.
//
// 그래도 fetch 는 맨 것을 쓰지 않고 `sessionFetch`(lib/auth/client-fetch.ts)를
// 쓴다(#93 코드리뷰). 액세스가 만료된 채 `/console` 진입 직후처럼, 이 슬롯과
// `useSession`(console/page.tsx)이 같은 순간 같은 401 을 동시에 만나면 리프레시
// 토큰은 1회용이라 몫이 갈린다 — 맨 fetch 로 진 쪽은 되살리지 못한 401 을 그대로
// "비로그인"으로 굳혀버려, 로그인한 사용자에게 경로가 바뀔 때까지 "로그인"이
// 뜨는 결과를 냈다(직접 재현해 확인했다). `sessionFetch`는 401 을 만나면 단일
// 비행으로 세션을 되살린 뒤 재시도해 이 경합을 흡수한다.
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { sessionFetch } from "@/lib/auth/client-fetch";

type SlotState = "loading" | "authenticated" | "unauthenticated";

export function SessionSlot() {
  const [state, setState] = useState<SlotState>("loading");
  // 헤더는 루트 레이아웃에 살아서 페이지 이동에도 마운트가 유지된다(Next
  // App Router) — 로그인 직후 `/console` 로 클라이언트 내비게이션해도 이
  // 컴포넌트는 그대로 남는다. 그래서 마운트 시 한 번뿐인 effect로는 로그인
  // 전에 확인한 "비로그인" 상태가 영영 굳어버린다. `pathname` 을 의존성에
  // 넣어 경로가 바뀔 때마다(=로그인·로그아웃 직후 이동 포함) 다시 확인한다 —
  // `lib/auth/use-session.ts` 가 인증 구역에서 쓰는 것과 같은 관용구다.
  const pathname = usePathname();

  useEffect(() => {
    let cancelled = false;

    sessionFetch("/api/auth/session", { cache: "no-store" })
      .then((res) => {
        if (cancelled) return;
        setState(res.ok ? "authenticated" : "unauthenticated");
      })
      .catch(() => {
        if (!cancelled) setState("unauthenticated");
      });

    return () => {
      cancelled = true;
    };
  }, [pathname]);

  // 로딩 중에는 아무 링크도 단언하지 않는다 — 자바스크립트가 없으면(ADR-0015
  // 검증 기법, seam.spec.ts) 이 자리에 영원히 머무르지만, 헤더의 나머지(브랜드·
  // 공모전·개최 CTA)는 서버에서 이미 렌더돼 있어 사이트가 걷는 데는 지장이
  // 없다.
  if (state === "loading") {
    return <span data-testid="header-session-loading" aria-hidden="true" />;
  }

  if (state === "authenticated") {
    return (
      <Link
        href="/console"
        data-testid="header-console-link"
        className="rounded-sm border border-rule px-3 py-1.5 text-sm hover:border-ink"
      >
        내 콘솔
      </Link>
    );
  }

  return (
    <Link
      href="/login"
      data-testid="header-login-link"
      className="rounded-sm border border-rule px-3 py-1.5 text-sm hover:border-ink"
    >
      로그인
    </Link>
  );
}
