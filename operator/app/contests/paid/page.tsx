"use client";

// 유료 공모전 목록 화면(#1212) — 점수 정정·상장 화면으로 가는 길이다. 무료 목록
// (`../free/page.tsx`)과 같은 분기 순서 — unauthenticated 를 로딩 게이트보다 먼저 검사한다(#69).
import { PageHeader } from "@/app/components/page-header";
import { useSession } from "@/lib/auth/use-session";
import { PaidContestListTable } from "@/lib/paid-contests/list-table";
import { usePaidContests } from "@/lib/paid-contests/use-paid-contests";

export default function PaidContestsPage() {
  const session = useSession();
  const { state } = usePaidContests(session.status === "authenticated");

  if (session.status === "unauthenticated") {
    return null;
  }

  if (session.status === "loading" || state.status === "loading") {
    return (
      <div className="p-4 sm:p-8">
        <p data-testid="paid-contests-loading">불러오는 중...</p>
      </div>
    );
  }

  return (
    <>
      <PageHeader crumb="운영 · 유료 공모전" title="유료 공모전" />
      <div className="flex flex-1 flex-col gap-4 p-4 sm:p-8">
        {state.status === "error" && (
          <p role="alert" data-testid="paid-contests-error" className="text-[13px] text-attention">
            목록을 불러오지 못했습니다. 잠시 후 다시 시도해주세요.
          </p>
        )}
        {state.status === "loaded" && state.contests.length === 0 && (
          <p data-testid="paid-contests-empty" className="text-[13px] text-ink/62">
            유료 공모전이 없습니다.
          </p>
        )}
        {state.status === "loaded" && state.contests.length > 0 && (
          <PaidContestListTable contests={state.contests} />
        )}
      </div>
    </>
  );
}
