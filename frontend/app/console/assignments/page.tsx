"use client";

// 「내 과제」 (#207, ADR-0028/0029) — 출제자가 연/만든 Assignment 목록.
//
// `/console/contests`(내 공모전)와 같은 자리지만 상금·결제·Award·Escrow에 닿는
// 것이 하나도 없다(스펙 #197 인수조건) — 행마다 보여주는 것은 상태와 InviteCode
// 뿐이다. 인증 구역이므로 SSR 하지 않는다(ADR-0015).
import Link from "next/link";

import { useSession } from "@/lib/auth/use-session";
import {
  ASSIGNMENT_STATUS_LABELS,
  type AssignmentRow,
  useMyAssignments,
} from "@/lib/assignments/use-my-assignments";

export default function MyAssignmentsPage() {
  const session = useSession();
  const state = useMyAssignments();

  if (session.status === "unauthenticated") return null;
  if (session.status === "loading" || state.status === "loading") {
    return (
      <main className="p-10">
        <p data-testid="my-assignments-loading">불러오는 중...</p>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-3xl p-10">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold" data-testid="my-assignments-heading">
          내 과제
        </h1>
        <Link
          href="/console/assignments/new"
          data-testid="my-assignments-new-link"
          className="rounded-sm border border-ink px-3 py-1.5 text-sm hover:bg-ink hover:text-paper"
        >
          과제 만들기
        </Link>
      </div>

      {state.status === "error" ? (
        <p className="mt-6 text-attention" data-testid="my-assignments-error">
          과제 목록을 불러오지 못했습니다. 잠시 후 다시 시도해주세요.
        </p>
      ) : state.rows.length === 0 ? (
        <p className="mt-6" data-testid="my-assignments-empty">
          아직 만든 과제가 없습니다.
        </p>
      ) : (
        <ul className="mt-6 flex flex-col gap-3" data-testid="my-assignments-list">
          {state.rows.map((row) => (
            <AssignmentRowCard key={row.id} row={row} />
          ))}
        </ul>
      )}
    </main>
  );
}

function AssignmentRowCard({ row }: { row: AssignmentRow }) {
  return (
    <li
      className="rounded border border-subtle p-4"
      data-testid={`my-assignment-row-${row.id}`}
      data-status={row.status}
    >
      <p className="text-sm text-muted" data-testid={`my-assignment-row-${row.id}-status`}>
        {ASSIGNMENT_STATUS_LABELS[row.status] ?? row.status}
      </p>
      <Link
        className="mt-1 block text-lg"
        href={`/console/assignments/${row.id}`}
        data-testid={`my-assignment-row-${row.id}-detail`}
      >
        {row.title}
      </Link>
      <p className="mt-1 text-sm text-muted">
        마감 {new Date(row.deadline_at).toLocaleString("ko-KR")}
      </p>
      {row.invite_code ? (
        <p
          className="mt-1 font-mono text-xs text-ink/70"
          data-testid={`my-assignment-row-${row.id}-invite-code`}
        >
          코드: {row.invite_code}
        </p>
      ) : null}
    </li>
  );
}
