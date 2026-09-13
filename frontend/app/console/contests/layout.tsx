// 공모전 제품 스위치(#271)가 꺼지면 개최자 콘솔의 공모전 화면 전부(목록·개최·
// draft 편집·결제·제출 미리보기·인수·지표·심사)를 없는 페이지로 낸다 — 진짜
// 문은 백엔드다.
import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { contestProductEnabled } from "@/lib/contest-switch";

export default function ConsoleContestsLayout({ children }: { children: ReactNode }) {
  if (!contestProductEnabled()) {
    notFound();
  }

  return children;
}
