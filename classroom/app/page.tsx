// 강의실 루트(#395, #391 Implementation Decisions 「강의실 랜딩」). 로그인
// 쿠키 유무로 갈린다 — 없으면 서버에서 그린 랜딩(비로그인 강사가 검색으로
// 들어온다, `components/landing.tsx`), 있으면 지금까지의 「내 클래스」
// (`components/classroom-home.tsx`, 클라이언트 컴포넌트). 가드
// (`middleware.ts`)는 루트만 인증 구역에서 빼 두고, 같은 판정 함수
// (`lib/landing/decide-root-view.ts`)를 여기서 다시 써서 실제로 무엇을
// 그릴지 정한다 — "이 요청을 랜딩으로 보낼지"의 최종 결정권은 SSR 인 이
// 파일에 있다.
//
// **랜딩은 SSR이다**(ADR-0017 위험 1) — 클라이언트 컴포넌트로 만들면 색인이
// 조용히 깨진다. `cookies()`를 읽으므로 Next가 이미 매 요청 렌더로 다루지만
// (프리렌더 대상에서 빠진다), `lib/auth/cookies.ts`를 거쳐 배포 설정
// (`CODEMIT_SESSION_COOKIE_DOMAIN` 등)에도 닿으므로 명시적으로 선언한다
// (#297, `lib/rendering/runtime-config.test.ts`).
export const dynamic = "force-dynamic";

import type { Metadata } from "next";
import { cookies } from "next/headers";

import { hasSessionCookie } from "@/lib/auth/cookies";
import { decideRootView } from "@/lib/landing/decide-root-view";

import ClassroomHome from "./components/classroom-home";
import { Landing, LANDING_DESCRIPTION, LANDING_TITLE } from "./components/landing";

async function rootView() {
  const store = await cookies();
  return decideRootView({ pathname: "/", hasSessionCookie: hasSessionCookie(store) });
}

// **랜딩만 색인을 연다**(#395) — 레이아웃 기본(`app/layout.tsx`의
// `robots: { index: false, follow: false }`)을 이 메타데이터가 덮는다.
// 「내 클래스」로 갈리면 빈 객체를 돌려 그 기본값을 그대로 둔다.
export async function generateMetadata(): Promise<Metadata> {
  const view = await rootView();
  if (view !== "landing") return {};

  return {
    title: LANDING_TITLE,
    description: LANDING_DESCRIPTION,
    robots: { index: true, follow: true },
    alternates: { canonical: "/" },
    openGraph: { title: LANDING_TITLE, description: LANDING_DESCRIPTION, type: "website" },
  };
}

export default async function ClassroomRoot() {
  const view = await rootView();
  return view === "my-classes" ? <ClassroomHome /> : <Landing />;
}
