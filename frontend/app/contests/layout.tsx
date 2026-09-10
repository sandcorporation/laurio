// 공모전 제품 스위치(#271)가 꺼지면 `/contests`·`/contests/[id]`를 통째로 없는
// 페이지로 낸다 — 진짜 문은 백엔드(`core.contest_switch`)이고, 이 레이아웃은
// 진입점을 감출 뿐이다("깨진 화면이 아니라 없는 페이지", 이슈 #271 user story
// 11). 이 서브트리 아래 두 라우트(목록·상세) 모두 이 레이아웃을 거치므로
// 각 페이지가 따로 스위치를 확인하지 않아도 된다.
import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { contestProductEnabled } from "@/lib/contest-switch";

export default function ContestsLayout({ children }: { children: ReactNode }) {
  if (!contestProductEnabled()) {
    notFound();
  }

  return children;
}
