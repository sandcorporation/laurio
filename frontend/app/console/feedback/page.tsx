"use client";

// 내 제보 목록 (#1241, 스펙 #1237) — 구현은 `@codemit/bff-client/feedback`.
import { FeedbackReportList } from "@codemit/bff-client/feedback";

import { PageHeader, PageShell } from "@/app/components/ui";
import { bffClient } from "@/lib/bff/client";

export default function MyFeedbackPage() {
  return (
    <PageShell>
      <PageHeader title="내 제보" titleTestId="feedback-title" />
      <div className="mt-6">
        <FeedbackReportList client={bffClient} detailHref={(id) => `/console/feedback/${id}`} />
      </div>
    </PageShell>
  );
}
