"use client";

// 클래스 상세의 머리(#633, 시안 v2) — 눈썹 크럼 「내 클래스 › 이름」, 제목 옆 상태 배지, 오른쪽에
// 통계 바(참여자·문제·평균 달성률)와 「클래스 설정」. 통계는 클래스 응답의 집계(#632)를 그대로 쓴다.
//
// 「복사해서 새로 열기」·「보관하기」·「보관 되돌리기」는 설정의 「보관과 삭제」 구획(`#class-archive`)으로
// 옮겼다(#636). 보관된 클래스는 복사가 주 행동이라 「클래스 설정」이 그 구획으로 곧장 가는 주 버튼이다.
import Link from "next/link";

import { Badge, buttonClass } from "@/app/components/ui";
import type { ClassRow } from "@/lib/classes/api";
import { achievementTone } from "@/lib/problems/achievement";

const TONE_TEXT = { verified: "text-verified", attention: "text-attention", ink: "text-ink" } as const;

function Stat({ label, value, testId, valueClass = "" }: { label: string; value: string; testId: string; valueClass?: string }) {
  return (
    <div className="flex flex-col gap-0.5 px-4 py-2.5" data-testid={testId}>
      <span className="text-[11px] tracking-[0.06em] text-ink/45">{label}</span>
      <span className={`font-mono text-[16px] font-semibold ${valueClass}`}>{value}</span>
    </div>
  );
}

export function ClassStatBar({ classroom }: { classroom: ClassRow }) {
  const rate = classroom.average_pass_rate;
  return (
    <div data-testid="class-stat-bar" className="flex divide-x divide-rule border border-rule bg-surface">
      <Stat label="참여자" value={String(classroom.member_count)} testId="class-stat-members" />
      <Stat label="문제" value={String(classroom.problem_count)} testId="class-stat-problems" />
      <Stat
        label="평균 달성률"
        value={rate === null ? "—" : `${Math.round(rate * 100)}%`}
        testId="class-stat-average-rate"
        valueClass={rate === null ? "text-ink/45" : TONE_TEXT[achievementTone(rate)]}
      />
    </div>
  );
}

export function ClassHead({ classroom }: { classroom: ClassRow }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
      <div className="flex min-w-0 flex-col gap-1.5">
        <div className="text-[11px] tracking-[0.08em] text-ink/45">
          <Link href="/" className="hover:text-ink">
            내 클래스
          </Link>{" "}
          › {classroom.name}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <h1 data-testid="classroom-detail-heading" className="text-[22px] font-semibold tracking-[-0.01em]">
            {classroom.name}
          </h1>
          <span data-testid="classroom-detail-status">
            <Badge tone={classroom.archived ? "neutral" : "verified"}>{classroom.archived ? "보관됨" : "진행중"}</Badge>
          </span>
          {classroom.role === "co_instructor" ? (
            <span data-testid="classroom-detail-co-instructor-badge">
              <Badge>공동 강사</Badge>
            </span>
          ) : null}
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-end gap-x-6 gap-y-3">
        <Link
          href={`/classes/${classroom.id}/settings${classroom.archived ? "#class-archive" : ""}`}
          data-testid="class-settings-link"
          className={buttonClass(classroom.archived ? "primary" : "secondary", "sm")}
        >
          클래스 설정
        </Link>
        <ClassStatBar classroom={classroom} />
      </div>
    </div>
  );
}
