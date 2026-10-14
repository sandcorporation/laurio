"use client";

// 클래스 상세의 탭 줄(#633) — 「문제 · 참여자 · 강사」. 탭은 주소(`?tab=`)가 말한다(`detail-tab.ts`).
import Link from "next/link";

import { DETAIL_TABS, DETAIL_TAB_LABEL, detailTabHref, type DetailTab } from "@/lib/classes/detail-tab";

export function ClassDetailTabs({ classId, active }: { classId: number; active: DetailTab }) {
  return (
    <div role="tablist" aria-label="클래스 상세 탭" className="flex items-end gap-0.5 border-b border-rule">
      {DETAIL_TABS.map((tab) => (
        <Link
          key={tab}
          href={detailTabHref(classId, tab)}
          role="tab"
          scroll={false}
          aria-selected={active === tab}
          data-testid={`detail-tab-${tab}`}
          className={
            active === tab
              ? "-mb-px border border-rule border-b-surface bg-surface px-[18px] py-[9px] text-[13.5px] font-medium"
              : "px-[18px] py-[9px] text-[13.5px] text-ink/60 hover:text-ink"
          }
        >
          {DETAIL_TAB_LABEL[tab]}
        </Link>
      ))}
    </div>
  );
}
