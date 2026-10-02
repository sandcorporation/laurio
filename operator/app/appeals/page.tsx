"use client";

// 이의 큐(#66, #423 — 골간으로 옮긴다). 기본은 심판 대기(pending)뿐이다 — "목록은
// 아카이브가 아니라 할 일이다"는 스펙의 요구를 URL의 기본값으로 못 박는다:
// `?status=`가 없거나 모르는 값이면 pending으로 취급한다. 홈(#65)이 이미
// `/appeals?status=pending`으로 링크를 걸어 두었으므로 그 링크와 여기서 정한
// 기본값이 실제로 같은 것을 보장한다.
//
// 시안 `docs/design/operator/Appeal.dc.html`과 `/payouts`(#422)가 세운 골간
// (좌측 내비·상단 바·표·중립 배지)을 그대로 쓴다 — 필터를 select 대신 탭으로,
// 목록을 표로 옮긴 것이 이 화면에서 달라진 부분이다. 라우트 주소·기존
// data-testid는 그대로 둔다(#422/#421 「바꾸지 않는 것」).
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { Badge } from "@/app/components/badge";
import { PageHeader } from "@/app/components/page-header";
import { TableScroll } from "@/app/components/table-scroll";
import { useSession } from "@/lib/auth/use-session";
import { useAppealList } from "@/lib/appeals/use-appeal-list";
import type { AppealStatus } from "@/lib/appeals/types";
import { APPEAL_STATUS_LABELS, appealStatusLabel } from "@/lib/appeals/types";

const STATUS_OPTIONS: Array<{ value: AppealStatus | "all"; label: string }> = [
  { value: "pending", label: APPEAL_STATUS_LABELS.pending },
  { value: "upheld", label: APPEAL_STATUS_LABELS.upheld },
  { value: "rejected", label: APPEAL_STATUS_LABELS.rejected },
  { value: "all", label: "전체" },
];

function parseFilter(raw: string | null): AppealStatus | "all" {
  if (raw === "upheld" || raw === "rejected" || raw === "all") return raw;
  return "pending";
}

function FilterTabs({
  filter,
  onSelect,
}: {
  filter: AppealStatus | "all";
  onSelect: (value: AppealStatus | "all") => void;
}) {
  return (
    <nav data-testid="appeals-status-filter" className="flex flex-wrap gap-2">
      {STATUS_OPTIONS.map((option) => {
        const active = filter === option.value;
        return (
          <button
            key={option.value}
            type="button"
            data-testid={`appeal-filter-${option.value}`}
            aria-current={active ? "true" : undefined}
            onClick={() => onSelect(option.value)}
            className={`border px-3 py-1.5 text-[12.5px] ${
              active ? "border-ink bg-ink text-paper" : "border-rule bg-surface text-ink"
            }`}
          >
            {option.label}
          </button>
        );
      })}
    </nav>
  );
}

const COL = {
  submission: "w-[140px]",
  status: "w-[100px]",
  createdAt: "w-[170px]",
};

function TableHead() {
  return (
    <div className="flex gap-3.5 border-b border-rule px-4 py-2.5 text-[11px] tracking-[0.06em] text-ink/30">
      <div className={COL.submission}>제출물</div>
      <div className={COL.status}>상태</div>
      <div className={COL.createdAt}>접수</div>
      <div className="min-w-0 flex-1">배분</div>
    </div>
  );
}

function AppealsListInner() {
  const session = useSession();
  const router = useRouter();
  const searchParams = useSearchParams();
  const filter = parseFilter(searchParams.get("status"));

  const state = useAppealList(filter, session.status === "authenticated");

  function handleFilterChange(value: AppealStatus | "all") {
    router.replace(value === "pending" ? "/appeals" : `/appeals?status=${value}`);
  }

  if (session.status === "loading") {
    return (
      <div className="p-4 sm:p-8">
        <p data-testid="session-loading">불러오는 중...</p>
      </div>
    );
  }
  if (session.status === "unauthenticated") return null;

  return (
    <>
      <PageHeader
        crumb="할 일 · 이의 심판"
        title="이의 큐"
        titleTestId="appeals-heading"
        description="밀린 이의를 훑고 한 건을 눌러 심판한다."
      />
      <div className="flex flex-1 flex-col gap-4 p-4 sm:p-8">
        <FilterTabs filter={filter} onSelect={handleFilterChange} />

        {state.status === "loading" && <p data-testid="appeals-list-loading">불러오는 중...</p>}

        {state.status === "error" && (
          <p role="alert" data-testid="appeals-list-error">
            불러오지 못했습니다.
          </p>
        )}

        {state.status === "loaded" && state.appeals.length === 0 && (
          <p data-testid="appeals-list-empty">표시할 이의가 없습니다.</p>
        )}

        {state.status === "loaded" && state.appeals.length > 0 && (
          <div data-testid="appeals-list" className="border border-rule bg-surface">
            <TableScroll minWidth={600}>
              <TableHead />
              {state.appeals.map((appeal, i) => (
                <Link
                  key={appeal.id}
                  href={`/appeals/${appeal.id}`}
                  data-testid={`appeal-row-${appeal.id}`}
                  className={`flex items-center gap-3.5 border-b border-rule px-4 py-2.5 text-[13px] ${
                    i % 2 === 1 ? "bg-ink/[2%]" : ""
                  }`}
                >
                  <div
                    className={`${COL.submission} shrink-0 truncate font-mono text-[13px]`}
                    data-testid={`appeal-row-${appeal.id}-submission`}
                  >
                    Submission #{appeal.submission_id}
                  </div>
                  <div className={`${COL.status} shrink-0`}>
                    <Badge tone="neutral" testId={`appeal-row-${appeal.id}-status`}>
                      {appealStatusLabel(appeal.status)}
                    </Badge>
                  </div>
                  <div
                    className={`${COL.createdAt} shrink-0 truncate text-[12.5px] text-ink/62`}
                    data-testid={`appeal-row-${appeal.id}-created-at`}
                  >
                    {new Date(appeal.created_at).toLocaleString("ko-KR")}
                  </div>
                  <div className="min-w-0 flex-1">
                    {/* **이 심판이 돈을 막고 있다**(#74). 배분은 이의가 심판될
                        때까지 기다리므로, 밀린 심판 하나가 그 Contest 참가자
                        전원의 배분을 붙잡는다. 큐를 하나로 유지하되(두 번째
                        큐를 만들지 않는다) 그 행에 표시를 단다. 배분·심판
                        여부 어느 쪽도 "충족/미충족" 판정이 아니므로 중립
                        배지다(#423 scope fence). */}
                    {appeal.is_holding_distribution ? (
                      <Badge tone="neutral" testId={`appeal-row-${appeal.id}-holding`}>
                        배분 보류 중
                      </Badge>
                    ) : null}
                  </div>
                </Link>
              ))}
            </TableScroll>
          </div>
        )}
      </div>
    </>
  );
}

export default function AppealsListPage() {
  // useSearchParams는 Suspense 경계가 필요하다(operator/app/login/login-form.tsx
  // 와 같은 이유 — Next App Router가 정적 셸을 미리 그리려 할 때 이 훅이 그
  // 시도를 막는다).
  return (
    <Suspense fallback={null}>
      <AppealsListInner />
    </Suspense>
  );
}
