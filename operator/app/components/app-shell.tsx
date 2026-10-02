"use client";

// 골간 뼈대(#422, 부모 #421) — 왼쪽 내비 + 본문. 로그인 화면(#427)은 인증 전이라
// 계정·큐 배지를 보일 것이 없으므로 이 뼈대를 두르지 않는다 — 자기만의 가운데
// 카드 레이아웃을 쓴다(`app/login/login-form.tsx`).
//
// 좁은 화면(`md` 미만)에서는 내비가 머리 줄로 접히고(#523) 이 뼈대가 세로로 쌓인다 —
// 머리 줄 아래에 본문. 메뉴가 열린 동안 본문은 `inert` 라 키보드 포커스가 덮개
// 뒤로 들어가지 않는다(`sidebar.tsx` 의 약속).
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";

import type { ThemePreference } from "@/lib/theme/preference";

import { Sidebar } from "./sidebar";

const NO_SHELL_PATHS = new Set(["/login"]);

export function AppShell({
  children,
  themePreference,
}: {
  children: ReactNode;
  themePreference: ThemePreference;
}) {
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);

  if (NO_SHELL_PATHS.has(pathname)) {
    return <>{children}</>;
  }

  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      <Sidebar themePreference={themePreference} menuOpen={menuOpen} onMenuOpenChange={setMenuOpen} />
      <div inert={menuOpen} className="flex min-w-0 flex-1 flex-col">
        {children}
      </div>
    </div>
  );
}
