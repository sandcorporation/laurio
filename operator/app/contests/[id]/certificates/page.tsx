"use client";

// 공모전 하나의 상장 발급 목록과 취소(#1131, 스펙 #1071). 취소는 받는 사람에게 알리지
// 않는다 — 제출 화면에 「취소됨」으로만 보인다.
import Link from "next/link";
import { useParams } from "next/navigation";

import { PageHeader } from "@/app/components/page-header";
import { useSession } from "@/lib/auth/use-session";
import { CertificateTable } from "@/lib/certificates/certificate-table";
import { useContestCertificates } from "@/lib/certificates/use-contest-certificates";

export default function ContestCertificatesPage() {
  const params = useParams<{ id: string }>();
  const contestId = params.id;
  const session = useSession();
  const { state, reload } = useContestCertificates(contestId, session.status === "authenticated");

  if (session.status === "unauthenticated") return null;

  if (session.status === "loading" || state.status === "loading") {
    return (
      <div className="p-4 sm:p-8">
        <p data-testid="certificates-loading">불러오는 중...</p>
      </div>
    );
  }

  return (
    <>
      <PageHeader
        crumb="운영 · 공모전 · 상장"
        title={state.status === "loaded" ? state.list.contest_title : "상장"}
        titleTestId="certificates-heading"
        actions={
          <Link
            href="/contests/free"
            className="border border-rule bg-surface px-2.5 py-1 text-[12px] text-ink"
          >
            무료 공모전
          </Link>
        }
      />
      <div className="flex flex-1 flex-col gap-4 p-4 sm:p-8">
        {state.status === "error" && (
          <p role="alert" data-testid="certificates-error" className="text-[13px] text-attention">
            목록을 불러오지 못했습니다. 잠시 후 다시 시도해주세요.
          </p>
        )}
        {state.status === "loaded" && state.list.certificates.length === 0 && (
          <p data-testid="certificates-empty" className="text-[13px] text-ink/62">
            발급된 상장이 없습니다.
          </p>
        )}
        {state.status === "loaded" && state.list.certificates.length > 0 && (
          <CertificateTable
            contestId={contestId}
            certificates={state.list.certificates}
            onCancelled={reload}
          />
        )}
      </div>
    </>
  );
}
