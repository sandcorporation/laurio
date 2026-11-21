"use client";

// 내 제보 상세 (#1241) — 내용·내 스크린샷·처리 글·상태 이력.
import Link from "next/link";
import { useParams } from "next/navigation";

import { FeedbackReportDetail } from "@codemit/bff-client/feedback";

import { PageHeader, PageShell } from "@/app/components/ui";
import { bffClient } from "@/lib/bff/client";

export default function MyFeedbackDetailPage() {
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  return (
    <PageShell>
      <PageHeader title="제보" titleTestId="feedback-title" actions={<Link href="/console/feedback" className="text-[13px] underline">내 제보</Link>} />
      <div className="mt-6">
        {Number.isInteger(id) && id > 0 ? <FeedbackReportDetail client={bffClient} id={id} /> : <p role="alert" className="text-[14px] text-error">찾을 수 없는 제보입니다.</p>}
      </div>
    </PageShell>
  );
}
