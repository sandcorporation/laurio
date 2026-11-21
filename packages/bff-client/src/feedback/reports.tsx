"use client";

// 「내 제보」 목록·상세 (#1241). 목록은 갈래·상태·받은 시각, 상세는 내용·내 스크린샷·처리 글·상태 이력.

import { useEffect, useState } from "react";

import type { BffClient } from "../client";
import { useBackendQuery } from "../hooks";
import {
  APP_LABELS,
  KIND_LABELS,
  STATUS_LABELS,
  type FeedbackReportListOut,
  type FeedbackReportOut,
  fetchScreenshotUrl,
  formatReceivedAt,
} from "./api";

const REPORTS_PATH = "/api/backend/feedback/reports";

export function FeedbackReportList({ client, detailHref }: { client: BffClient; detailHref: (id: number) => string }) {
  const { state } = useBackendQuery<FeedbackReportListOut[]>(client, REPORTS_PATH);
  if (state.status === "loading") return <p className="text-[14px] text-ink/60">불러오는 중</p>;
  if (state.status === "error") return <p role="alert" className="text-[14px] text-error">{state.failure.detail}</p>;
  if (state.data.length === 0) return <p data-testid="feedback-empty" className="text-[14px] text-ink/60">보낸 제보가 없습니다.</p>;
  return (
    <ul data-testid="feedback-report-list" className="flex flex-col border border-rule bg-surface">
      {state.data.map((report) => (
        <li key={report.id} className="border-b border-rule last:border-b-0">
          <a href={detailHref(report.id)} data-testid="feedback-report-row" className="flex flex-wrap items-baseline gap-x-4 gap-y-1 px-4 py-3 hover:bg-paper">
            <span className="text-[13px]">{KIND_LABELS[report.kind] ?? report.kind}</span>
            <span data-testid="feedback-report-status" className="border border-rule px-2 text-[12px]">{STATUS_LABELS[report.status] ?? report.status}</span>
            <span className="min-w-0 flex-1 truncate text-[14px]">{report.body}</span>
            <span className="text-[12px] text-ink/60">{formatReceivedAt(report.received_at)}</span>
          </a>
        </li>
      ))}
    </ul>
  );
}

function Screenshot({ client, id }: { client: BffClient; id: number }) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let alive = true;
    void fetchScreenshotUrl(client, id).then((result) => {
      if (!alive) return;
      if (result.ok) setUrl(result.data.download_url);
      else setFailed(true);
    });
    return () => {
      alive = false;
    };
  }, [client, id]);
  if (failed) return <p className="text-[13px] text-error">스크린샷을 불러오지 못했습니다.</p>;
  if (!url) return null;
  // eslint-disable-next-line @next/next/no-img-element -- 짧게 발급된 비공개 주소다.
  return <img src={url} alt="내 스크린샷" data-testid="feedback-screenshot" className="max-h-[60vh] w-auto max-w-full border border-rule" />;
}

export function FeedbackReportDetail({ client, id }: { client: BffClient; id: number }) {
  const { state } = useBackendQuery<FeedbackReportOut>(client, `${REPORTS_PATH}/${id}`);
  if (state.status === "loading") return <p className="text-[14px] text-ink/60">불러오는 중</p>;
  if (state.status === "error") return <p role="alert" className="text-[14px] text-error">{state.failure.detail}</p>;
  const report = state.data;
  return (
    <div data-testid="feedback-report-detail" className="flex flex-col gap-4">
      <dl className="grid grid-cols-[6rem_1fr] gap-x-4 gap-y-1 text-[14px]">
        <dt className="text-ink/60">갈래</dt>
        <dd>{KIND_LABELS[report.kind] ?? report.kind}</dd>
        <dt className="text-ink/60">앱</dt>
        <dd>{APP_LABELS[report.app] ?? report.app}</dd>
        <dt className="text-ink/60">상태</dt>
        <dd data-testid="feedback-detail-status">{STATUS_LABELS[report.status] ?? report.status}</dd>
        <dt className="text-ink/60">받은 시각</dt>
        <dd>{formatReceivedAt(report.received_at)}</dd>
        {report.page_url && (
          <>
            <dt className="text-ink/60">화면</dt>
            <dd className="break-all">{report.page_url}</dd>
          </>
        )}
      </dl>
      <p className="whitespace-pre-wrap border border-rule bg-surface p-3 text-[14px]">{report.body}</p>
      {report.has_screenshot && <Screenshot client={client} id={report.id} />}
      {report.resolution_note && (
        <section className="flex flex-col gap-1">
          <h2 className="text-[13px] text-ink/60">처리 글</h2>
          <p data-testid="feedback-resolution" className="whitespace-pre-wrap border border-rule bg-surface p-3 text-[14px]">{report.resolution_note}</p>
        </section>
      )}
      <section className="flex flex-col gap-1">
        <h2 className="text-[13px] text-ink/60">이력</h2>
        <ol data-testid="feedback-history" className="flex flex-col gap-1 text-[13px]">
          {report.history.map((change, index) => (
            <li key={index}>
              {formatReceivedAt(change.changed_at)} · {change.from_status ? `${STATUS_LABELS[change.from_status] ?? change.from_status} → ` : ""}
              {STATUS_LABELS[change.to_status] ?? change.to_status}
              {change.note ? ` — ${change.note}` : ""}
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
