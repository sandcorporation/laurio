import Link from "next/link";

import { Badge } from "@/app/components/badge";

import { freeContestStatusLabel } from "./status-label";
import { operatorNoticeComposeHref } from "./notify-link";
import type { FreeContest } from "./types";

// 무료 공모전 목록 표(#420 — 골간으로 옮긴다, #426/#421) — 수상자 옆에 「운영팀
// 알림 보내기」를 둔다. 수상하지 않은(아직 심사 중이거나 심사 기간 안에 못
// 고르고 끝난) 행은 `winner`가 없어 그 자리가 비어 있다. 상태는 판정(통과·
// 미충족)이 아니라 Contest 의 생애주기 단계라 중립 배지로만 보인다.
const COL = {
  status: "w-[96px]",
  deadline: "w-[168px]",
  winner: "w-[160px]",
  action: "w-[168px]",
};

function TableHead() {
  return (
    <div className="flex gap-3.5 border-b border-rule px-4 py-2.5 text-[11px] tracking-[0.06em] text-ink/30">
      <div className="min-w-0 flex-1">제목</div>
      <div className={`${COL.status} shrink-0`}>상태</div>
      <div className={`${COL.deadline} shrink-0`}>마감</div>
      <div className={`${COL.winner} shrink-0`}>수상자</div>
      <div className={`${COL.action} shrink-0`}>작업</div>
    </div>
  );
}

export function FreeContestListTable({ contests }: { contests: FreeContest[] }) {
  return (
    <div data-testid="free-contest-list-table" className="border border-rule bg-surface">
      <TableHead />
      {contests.map((contest, i) => (
        <div
          key={contest.id}
          data-testid={`free-contest-row-${contest.id}`}
          className={`flex items-center gap-3.5 border-b border-rule px-4 py-2.5 text-[13px] last:border-b-0 ${
            i % 2 === 1 ? "bg-ink/[2%]" : ""
          }`}
        >
          <div className="min-w-0 flex-1 truncate">{contest.title}</div>
          <div className={`${COL.status} shrink-0`}>
            <Badge testId={`free-contest-status-${contest.id}`}>
              {freeContestStatusLabel(contest.status)}
            </Badge>
          </div>
          <div className={`${COL.deadline} shrink-0 truncate font-mono text-[12.5px] text-ink/62`}>
            {new Date(contest.deadline_at).toLocaleString("ko-KR")}
          </div>
          <div
            className={`${COL.winner} shrink-0 truncate`}
            data-testid={`free-contest-winner-${contest.id}`}
          >
            {contest.winner ? contest.winner.nickname || contest.winner.email : "-"}
          </div>
          <div className={`${COL.action} shrink-0`}>
            {contest.winner && (
              <Link
                href={operatorNoticeComposeHref(contest.winner)}
                data-testid={`free-contest-notify-${contest.id}`}
                className="inline-block border border-rule bg-surface px-2.5 py-1 text-[12px] text-ink"
              >
                운영팀 알림 보내기
              </Link>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
