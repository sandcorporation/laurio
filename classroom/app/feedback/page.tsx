"use client";

// 내 제보 목록 (#1242, 스펙 #1237) — 구현은 `@codemit/bff-client/feedback`.
import { FeedbackReportList } from "@codemit/bff-client/feedback";

import { PageHeader, PageShell } from "@/app/components/ui";
import { bffClient } from "@/lib/bff/client";
import { useClassroomTabTitle } from "@/lib/rendering/use-tab-title";

export default function MyFeedbackPage() {
  useClassroomTabTitle({ screenName: "내 제보" });
  return (
    <PageShell>
      <PageHeader title="내 제보" titleTestId="feedback-title" />
      <div className="mt-6 max-w-3xl">
        <FeedbackReportList client={bffClient} detailHref={(id) => `/feedback/${id}`} />
      </div>
    </PageShell>
  );
}
