import Link from "next/link";

import { Badge } from "@/app/components/badge";
import { TableScroll } from "@/app/components/table-scroll";
import { freeContestStatusLabel } from "@/lib/free-contests/status-label";

import type { PaidContest } from "./types";

// 유료 공모전 목록 표(#1212) — 각 줄에서 상장·점수 정정 화면으로 간다. 수상자·알림 칸은
// 무료 공모전 목록 것이라 없다(유료는 순위·배분이 정정 화면 뒤에 있다).
const COL = {
  status: "w-[96px]",
  deadline: "w-[200px]",
  prize: "w-[120px]",
  action: "w-[180px]",
};

const LINK_CLASS = "inline-block border border-rule bg-surface px-2.5 py-1 text-[12px] text-ink";

function TableHead() {
  return (
    <div className="flex gap-3.5 border-b border-rule px-4 py-2.5 text-[11px] tracking-[0.06em] text-ink/30">
      <div className="min-w-0 flex-1">제목</div>
      <div className={`${COL.status} shrink-0`}>상태</div>
      <div className={`${COL.deadline} shrink-0`}>마감</div>
      <div className={`${COL.prize} shrink-0 text-right`}>상금</div>
      <div className={`${COL.action} shrink-0`}>작업</div>
    </div>
  );
}

export function PaidContestListTable({ contests }: { contests: PaidContest[] }) {
  return (
    <div data-testid="paid-contest-list-table" className="border border-rule bg-surface">
      <TableScroll minWidth={800}>
        <TableHead />
        {contests.map((contest, i) => (
          <div
            key={contest.id}
            data-testid={`paid-contest-row-${contest.id}`}
            className={`flex items-center gap-3.5 border-b border-rule px-4 py-2.5 text-[13px] last:border-b-0 ${
              i % 2 === 1 ? "bg-ink/[2%]" : ""
            }`}
          >
            <div className="min-w-0 flex-1 truncate">{contest.title}</div>
            <div className={`${COL.status} shrink-0`}>
              <Badge testId={`paid-contest-status-${contest.id}`}>
                {freeContestStatusLabel(contest.status)}
              </Badge>
            </div>
            <div className={`${COL.deadline} shrink-0 truncate font-mono text-[12.5px] text-ink/62`}>
              {new Date(contest.deadline_at).toLocaleString("ko-KR")}
            </div>
            <div className={`${COL.prize} shrink-0 text-right font-mono text-[12.5px]`}>
              {contest.prize.toLocaleString("ko-KR")}원
            </div>
            <div className={`${COL.action} flex shrink-0 gap-2`}>
              <Link
                href={`/contests/${contest.id}/certificates`}
                data-testid={`paid-contest-certificates-${contest.id}`}
                className={LINK_CLASS}
              >
                상장
              </Link>
              <Link
                href={`/contests/${contest.id}/score-corrections`}
                data-testid={`paid-contest-corrections-${contest.id}`}
                className={LINK_CLASS}
              >
                점수 정정
              </Link>
            </div>
          </div>
        ))}
      </TableScroll>
    </div>
  );
}
