"use client";

// 제보 목록 (#1243, 스펙 #1237) — 상태·앱·갈래로 거르고, 받은 시각 차례(최신 먼저)다.
// 조회는 일반 등급도 된다. 줄을 누르면 상세에서 상태를 바꾼다.
import Link from "next/link";
import { useState } from "react";

import { useBackendQuery } from "@codemit/bff-client";

import { Badge } from "@/app/components/badge";
import { PageHeader } from "@/app/components/page-header";
import { Panel } from "@/app/components/panel";
import { TableScroll } from "@/app/components/table-scroll";
import { bffClient } from "@/lib/bff/client";
import { useSession } from "@/lib/auth/use-session";
import {
  APP_OPTIONS,
  KIND_OPTIONS,
  STATUS_OPTIONS,
  type ReportRow,
  formatDateTime,
  labelOf,
} from "@/lib/feedback-reports/types";

const SELECT = "border border-rule bg-paper px-2 py-1.5 text-[13px] text-ink";

export default function FeedbackReportsPage() {
  const session = useSession();
  const [status, setStatus] = useState("");
  const [app, setApp] = useState("");
  const [kind, setKind] = useState("");

  const query = new URLSearchParams();
  if (status) query.set("status", status);
  if (app) query.set("app", app);
  if (kind) query.set("kind", kind);
  const path =
    session.status === "authenticated" ? `/api/backend/operator/feedback-reports?${query.toString()}` : null;
  const { state } = useBackendQuery<ReportRow[]>(bffClient, path);

  if (session.status === "unauthenticated") return null;
  if (session.status === "loading") {
    return (
      <div className="p-4 sm:p-8">
        <p data-testid="session-loading">불러오는 중...</p>
      </div>
    );
  }

  const filter = (label: string, value: string, set: (next: string) => void, options: ReadonlyArray<{ value: string; label: string }>) => (
    <label className="flex flex-col gap-[3px] text-[11.5px] text-ink/45">
      {label}
      <select data-testid={`feedback-filter-${label}`} value={value} onChange={(event) => set(event.target.value)} className={SELECT}>
        <option value="">전체</option>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );

  return (
    <>
      <PageHeader crumb="운영 · 제보" title="제보" titleTestId="feedback-reports-heading" />
      <div className="flex flex-1 flex-col gap-[18px] p-4 sm:p-8">
        <div className="flex flex-wrap gap-3">
          {filter("상태", status, setStatus, STATUS_OPTIONS)}
          {filter("앱", app, setApp, APP_OPTIONS)}
          {filter("갈래", kind, setKind, KIND_OPTIONS)}
        </div>
        <Panel title="받은 제보">
          {state.status === "loading" && <p className="px-[15px] py-[14px] text-[13px] text-ink/62">불러오는 중...</p>}
          {state.status === "error" && (
            <p role="alert" data-testid="feedback-reports-error" className="px-[15px] py-[14px] text-[13px] text-attention">
              {state.failure.detail}
            </p>
          )}
          {state.status === "ready" && state.data.length === 0 && (
            <p data-testid="feedback-reports-empty" className="px-[15px] py-[14px] text-[13px] text-ink/62">
              제보가 없습니다.
            </p>
          )}
          {state.status === "ready" && state.data.length > 0 && (
            <div data-testid="feedback-reports-table">
              <TableScroll minWidth={760}>
                <div className="flex gap-3.5 border-b border-rule px-4 py-2.5 text-[11px] tracking-[0.06em] text-ink/30">
                  <div className="w-[130px] shrink-0">받은 시각</div>
                  <div className="w-[60px] shrink-0">갈래</div>
                  <div className="w-[70px] shrink-0">앱</div>
                  <div className="w-[80px] shrink-0">상태</div>
                  <div className="w-[180px] shrink-0">보낸 사람</div>
                  <div className="min-w-0 flex-1">내용</div>
                </div>
                {state.data.map((report) => (
                  <Link
                    key={report.id}
                    href={`/feedback-reports/${report.id}`}
                    data-testid={`feedback-report-row-${report.id}`}
                    className="flex items-center gap-3.5 border-b border-rule px-4 py-2.5 text-[13px] hover:bg-paper"
                  >
                    <div className="w-[130px] shrink-0 tabular-nums">{formatDateTime(report.received_at)}</div>
                    <div className="w-[60px] shrink-0">{labelOf(KIND_OPTIONS, report.kind)}</div>
                    <div className="w-[70px] shrink-0">{labelOf(APP_OPTIONS, report.app)}</div>
                    <div className="w-[80px] shrink-0">
                      <Badge testId={`feedback-report-row-${report.id}-status`}>{labelOf(STATUS_OPTIONS, report.status)}</Badge>
                    </div>
                    <div className="w-[180px] shrink-0 truncate">{report.reporter_email}</div>
                    <div className="min-w-0 flex-1 truncate">{report.body}</div>
                  </Link>
                ))}
              </TableScroll>
            </div>
          )}
        </Panel>
      </div>
    </>
  );
}
