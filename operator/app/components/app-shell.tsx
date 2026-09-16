"use client";

// 골간 뼈대(#422, 부모 #421) — 왼쪽 내비 + 본문. 로그인 화면은 아직 옮기지
// 않았고(#421 「화면을 옮기는 순서」 4단계) 인증 전이라 계정·큐 배지를 보일
// 것이 없으므로 이 뼈대를 두르지 않는다.
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
