// 공모전 제품 스위치(#271)가 꺼지면 개최자 콘솔의 공모전 화면 전부(목록·개최·
// draft 편집·결제·제출 미리보기·인수·지표·심사)를 없는 페이지로 낸다 — 진짜
// 문은 백엔드다.
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { contestProductEnabled } from "@/lib/contest-switch";

// 목록 화면(`page.tsx`)의 탭 제목 — 하위 화면은 각자 제목을 단다(#1478 4).
export const metadata: Metadata = { title: "내 공모전" };

export default function ConsoleContestsLayout({ children }: { children: ReactNode }) {
  if (!contestProductEnabled()) {
    notFound();
  }

  return children;
}
