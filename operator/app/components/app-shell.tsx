"use client";

// 골간 뼈대(#422, 부모 #421) — 왼쪽 내비 + 본문. 로그인 화면(#427)은 인증 전이라
// 계정·큐 배지를 보일 것이 없으므로 이 뼈대를 두르지 않는다 — 자기만의 가운데
// 카드 레이아웃을 쓴다(`app/login/login-form.tsx`).
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

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

  if (NO_SHELL_PATHS.has(pathname)) {
    return <>{children}</>;
  }

  return (
    <div className="flex min-h-screen">
      <Sidebar themePreference={themePreference} />
      <div className="flex min-w-0 flex-1 flex-col">{children}</div>
    </div>
  );
}
