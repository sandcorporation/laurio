"use client";

// 「사용 현황」 아래쪽의 클래스 목록(#493). 숫자는 클래스 전체 기간의 합계이고,
// 행을 누르면 그 클래스의 상세(`/usage/classes/[id]`)로 가며 위에서 고른 기간을
// 주소에 그대로 싣는다. 보관된 클래스는 서버가 이미 뒤로 보내 오고, 여기서는
// 배지만 붙인다. 표 모양은 날짜별 표와 같은 관례다(flex 행·열 너비·줄무늬).
import Link from "next/link";

import { Badge } from "@/app/components/badge";

import { periodQuery, type UsagePeriod } from "./period";
import type { ClassUsage } from "./types";

const COL = {
  created: "w-[92px]",
  count: "w-[60px]",
  problems: "w-[108px]",
  submissions: "w-[64px]",
  students: "w-[72px]",
  rate: "w-[104px]",
};

function seoulDate(iso: string): string {
  // sv-SE 는 YYYY-MM-DD 로 적는다.
  return new Date(iso).toLocaleDateString("sv-SE", { timeZone: "Asia/Seoul" });
}

function Num({ value }: { value: number }) {
  return <span className={`font-mono ${value === 0 ? "text-ink/30" : ""}`}>{value}</span>;
}

function Head() {
  return (
    <div className="flex items-center gap-3.5 border-b border-rule px-4 py-2.5 text-[11px] tracking-[0.06em] text-ink/30">
      <div className="min-w-0 flex-1">클래스</div>
      <div className={`${COL.created} shrink-0`}>만든 날</div>
      <div className={`${COL.count} shrink-0 text-right`}>참여자</div>
      <div className={`${COL.problems} shrink-0 text-right`}>문제 열림·초안·숨김</div>
      <div className={`${COL.submissions} shrink-0 text-right`}>학생 제출</div>
      <div className={`${COL.students} shrink-0 text-right`}>제출한 학생</div>
      <div className={`${COL.rate} shrink-0 text-right`}>참여율</div>
    </div>
  );
}

function Row({ row, index, query }: { row: ClassUsage; index: number; query: string }) {
  const rate = row.participation_rate;
  return (
    <Link
      href={`/usage/classes/${row.id}${query}`}
      data-testid={`usage-class-${row.id}`}
      className={`flex items-center gap-3.5 border-b border-rule px-4 py-2.5 text-[13px] last:border-b-0 hover:bg-ink/[4%] ${
        index % 2 === 1 ? "bg-ink/[2%]" : ""
      }`}
    >
      <div className="flex min-w-0 flex-1 items-center gap-2">
        <span className={`truncate ${row.archived ? "text-ink/62" : ""}`}>{row.name}</span>
        {row.archived && <Badge testId={`usage-class-${row.id}-archived`}>보관됨</Badge>}
      </div>
      <div className={`${COL.created} shrink-0 font-mono text-[12.5px] text-ink/62`}>{seoulDate(row.created_at)}</div>
      <div className={`${COL.count} shrink-0 text-right`} data-testid={`usage-class-${row.id}-participants`}>
        <Num value={row.participants} />
      </div>
      <div className={`${COL.problems} shrink-0 text-right`}>
        <Num value={row.problems_open} />
        <span className="text-ink/30"> · </span>
        <Num value={row.problems_draft} />
        <span className="text-ink/30"> · </span>
        <Num value={row.problems_hidden} />
      </div>
      <div className={`${COL.submissions} shrink-0 text-right`}>
        <Num value={row.submissions} />
      </div>
      <div className={`${COL.students} shrink-0 text-right`}>
        <Num value={row.submitting_students} />
      </div>
      <div className={`${COL.rate} shrink-0 text-right`} data-testid={`usage-class-${row.id}-rate`}>
        {rate === null || rate === undefined ? (
          <span className="text-ink/30">—</span>
        ) : (
          <>
            <span className="font-mono">{Math.round(rate * 100)}%</span>{" "}
            <span className="font-mono text-[11.5px] text-ink/45">
              {row.participants_submitted}/{row.participants}
            </span>
          </>
        )}
      </div>
    </Link>
  );
}

export function ClassUsageList({ classes, period }: { classes: ClassUsage[]; period: UsagePeriod }) {
  const query = periodQuery(period);
  return (
    <div className="overflow-x-auto">
      <div data-testid="usage-class-list" className="min-w-[720px]">
        <Head />
        {classes.map((row, i) => (
          <Row key={row.id} row={row} index={i} query={query} />
        ))}
      </div>
      <p className="border-t border-rule px-4 py-2.5 text-[11.5px] text-ink/45">
        참여자는 강사와 내보낸 학생을 뺀 지금의 학생이고, 참여율은 그중 한 번이라도 낸 사람의 비율이다.
        학생 제출과 제출한 학생에는 내보낸 학생의 것도 들어간다.
      </p>
    </div>
  );
}
