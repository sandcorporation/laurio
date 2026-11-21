"use client";

// 공모전 하나의 점수 정정(#1183, 스펙 #1178) — 운영자가 플랫폼 오류로 틀린 점수를 골라 정정을 걸고, 진행과 이력을 본다.
import Link from "next/link";
import { useParams } from "next/navigation";

import { PageHeader } from "@/app/components/page-header";
import { useSession } from "@/lib/auth/use-session";
import { CorrectionForm } from "@/lib/score-corrections/correction-form";
import { CorrectionHistory } from "@/lib/score-corrections/correction-history";
import { useScoreCorrections } from "@/lib/score-corrections/use-score-corrections";

export default function ContestScoreCorrectionsPage() {
  const params = useParams<{ id: string }>();
  const contestId = params.id;
  const session = useSession();
  const { state, reload } = useScoreCorrections(contestId, session.status === "authenticated");

  if (session.status === "unauthenticated") return null;

  if (session.status === "loading" || state.status === "loading") {
    return (
      <div className="p-4 sm:p-8">
        <p data-testid="corrections-loading">불러오는 중...</p>
      </div>
    );
  }

  return (
    <>
      <PageHeader
        crumb="운영 · 공모전 · 점수 정정"
        title="점수 정정"
        titleTestId="corrections-heading"
        actions={
          <Link
            href={`/contests/${contestId}/certificates`}
            className="border border-rule bg-surface px-2.5 py-1 text-[12px] text-ink"
          >
            상장
          </Link>
        }
      />
      <div className="flex flex-1 flex-col gap-4 p-4 sm:p-8">
        {state.status === "error" && (
          <p role="alert" data-testid="corrections-error" className="text-[13px] text-attention">
            목록을 불러오지 못했습니다. 잠시 후 다시 시도해주세요.
          </p>
        )}
        {state.status === "loaded" && state.list.submissions.length === 0 && (
          <p data-testid="corrections-empty" className="text-[13px] text-ink/62">
            채점된 제출이 없습니다.
          </p>
        )}
        {state.status === "loaded" && state.list.submissions.length > 0 && (
          <CorrectionForm
            contestId={contestId}
            submissions={state.list.submissions}
            prizeSettled={state.list.prize_settled}
            onRequested={reload}
          />
        )}
        {state.status === "loaded" && state.list.corrections.length > 0 && (
          <CorrectionHistory corrections={state.list.corrections} submissions={state.list.submissions} />
        )}
      </div>
    </>
  );
}
