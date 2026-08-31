"use client";

// 이의 큐(#66). 기본은 심판 대기(pending)뿐이다 — "목록은 아카이브가 아니라
// 할 일이다"는 스펙의 요구를 URL의 기본값으로 못 박는다: `?status=`가 없거나
// 모르는 값이면 pending으로 취급한다. 홈(#65)이 이미 `/appeals?status=pending`
// 으로 링크를 걸어 두었으므로 그 링크와 여기서 정한 기본값이 실제로 같은
// 것을 보장한다.
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { useSession } from "@/lib/auth/use-session";
import { useAppealList } from "@/lib/appeals/use-appeal-list";
import type { AppealStatus } from "@/lib/appeals/types";
import { APPEAL_STATUS_LABELS } from "@/lib/appeals/types";

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

function AppealsListInner() {
  const session = useSession();
  const router = useRouter();
  const searchParams = useSearchParams();
  const filter = parseFilter(searchParams.get("status"));

  const state = useAppealList(filter, session.status === "authenticated");

  function handleFilterChange(value: string) {
    router.replace(value === "pending" ? "/appeals" : `/appeals?status=${value}`);
  }

  if (session.status === "loading") {
    return (
      <main>
        <p data-testid="session-loading">불러오는 중...</p>
      </main>
    );
  }
  if (session.status === "unauthenticated") return null;

  return (
    <main>
      <h1 data-testid="appeals-heading">이의 큐</h1>

      <label>
        상태
        <select
          data-testid="appeals-status-filter"
          value={filter}
          onChange={(event) => handleFilterChange(event.target.value)}
        >
          {STATUS_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>

      {state.status === "loading" && (
        <p data-testid="appeals-list-loading">불러오는 중...</p>
      )}

      {state.status === "error" && (
        <p role="alert" data-testid="appeals-list-error">
          불러오지 못했습니다.
        </p>
      )}

      {state.status === "loaded" && state.appeals.length === 0 && (
        <p data-testid="appeals-list-empty">표시할 이의가 없습니다.</p>
      )}

      {state.status === "loaded" && state.appeals.length > 0 && (
        <ul data-testid="appeals-list">
          {state.appeals.map((appeal) => (
            <li key={appeal.id}>
              <Link href={`/appeals/${appeal.id}`} data-testid={`appeal-row-${appeal.id}`}>
                <span data-testid={`appeal-row-${appeal.id}-submission`}>
                  Submission #{appeal.submission_id}
                </span>
                <span data-testid={`appeal-row-${appeal.id}-created-at`}>
                  {new Date(appeal.created_at).toLocaleString("ko-KR")}
                </span>
                <span data-testid={`appeal-row-${appeal.id}-status`}>
                  {APPEAL_STATUS_LABELS[appeal.status]}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </main>
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
