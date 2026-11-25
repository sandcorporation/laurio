"use client";

// 클래스 상세의 탭 줄(#633) — 「문제 · 참여자 · 강사」. 탭은 주소(`?tab=`)가 말한다(`detail-tab.ts`).
import Link from "next/link";

import { useTablist } from "@/app/components/use-tablist";
import {
  DETAIL_TABS,
  DETAIL_TAB_LABEL,
  detailTabHref,
  type DetailTab,
} from "@/lib/classes/detail-tab";

// 탭 줄과 아래 패널이 같은 id 를 쓰도록 고정한다(패널은 page.tsx 가 그린다).
export const CLASS_DETAIL_TAB_ID = "class-detail";

export function classDetailPanelProps(active: DetailTab) {
  return {
    id: `${CLASS_DETAIL_TAB_ID}-panel`,
    role: "tabpanel" as const,
    "aria-labelledby": `${CLASS_DETAIL_TAB_ID}-tab-${active}`,
  };
}

export function ClassDetailTabs({
  classId,
  active,
}: {
  classId: number;
  active: DetailTab;
}) {
  const { listProps, tabProps } = useTablist(active, {
    id: CLASS_DETAIL_TAB_ID,
  });
  return (
    <div
      {...listProps}
      aria-label="클래스 상세 탭"
      className="flex items-end gap-0.5 border-b border-rule"
    >
      {DETAIL_TABS.map((tab) => (
        <Link
          key={tab}
          href={detailTabHref(classId, tab)}
          {...tabProps(tab)}
          scroll={false}
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
