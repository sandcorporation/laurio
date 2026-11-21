"use client";

// 제보 상세 (#1243, 스펙 #1237) — 내용, 스크린샷(열 때마다 짧게 발급), 화면 주소·브라우저, 상태 바꾸기·처리 글, 이력.
// 상태를 바꾸는 것은 상위 등급만이고, 바꾸면 제보자의 벨에 알림이 간다.
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { useBackendQuery } from "@codemit/bff-client";

import { Badge } from "@/app/components/badge";
import { PageHeader } from "@/app/components/page-header";
import { Panel } from "@/app/components/panel";
import { bffClient } from "@/lib/bff/client";
import { useSession } from "@/lib/auth/use-session";
import {
  APP_OPTIONS,
  KIND_OPTIONS,
  STATUS_OPTIONS,
  type FeedbackStatus,
  type ReportDetail,
  formatDateTime,
  labelOf,
} from "@/lib/feedback-reports/types";

const BUTTON = "bg-ink px-3 py-1.5 text-[12.5px] text-paper disabled:opacity-50";

export default function FeedbackReportDetailPage() {
  const session = useSession();
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const valid = Number.isInteger(id) && id > 0;
  const { state, reload } = useBackendQuery<ReportDetail>(
    bffClient,
    session.status === "authenticated" && valid ? `/api/backend/operator/feedback-reports/${id}` : null,
  );

  const [nextStatus, setNextStatus] = useState<FeedbackStatus>("in_progress");
  const [note, setNote] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const currentStatus = state.status === "ready" ? state.data.status : null;
  useEffect(() => {
    if (currentStatus) setNextStatus(currentStatus === "received" ? "in_progress" : "deployed");
  }, [currentStatus]);

  if (session.status === "unauthenticated") return null;
  if (session.status === "loading") {
    return (
      <div className="p-4 sm:p-8">
        <p data-testid="session-loading">불러오는 중...</p>
      </div>
    );
  }
  const canEdit = session.user.is_superuser;

  async function change() {
    setPending(true);
    setError(null);
    const result = await bffClient.post<ReportDetail>(`/api/backend/operator/feedback-reports/${id}/status`, {
      status: nextStatus,
      note,
    });
    setPending(false);
    if (!result.ok) {
      setError(result.detail);
      return;
    }
    setNote("");
    reload();
  }

  return (
    <>
      <PageHeader
        crumb="운영 · 제보"
        title={`제보 #${valid ? id : ""}`}
        titleTestId="feedback-report-heading"
        actions={
          <Link href="/feedback-reports" className="border border-rule bg-surface px-3 py-1.5 text-[12.5px]">
            목록
          </Link>
        }
      />
      <div className="flex flex-1 flex-col gap-[18px] p-4 sm:p-8">
        {!valid && <p role="alert" className="text-[13px] text-attention">찾을 수 없는 제보입니다.</p>}
        {state.status === "error" && (
          <p role="alert" data-testid="feedback-report-error" className="text-[13px] text-attention">
            {state.failure.detail}
          </p>
        )}
        {state.status === "ready" && (
          <>
            <Panel title="내용">
              <dl className="grid grid-cols-[7rem_minmax(0,1fr)] gap-x-4 gap-y-1.5 px-[15px] py-[14px] text-[13px]">
                <dt className="text-ink/45">상태</dt>
                <dd><Badge testId="feedback-report-status">{labelOf(STATUS_OPTIONS, state.data.status)}</Badge></dd>
                <dt className="text-ink/45">갈래</dt>
                <dd>{labelOf(KIND_OPTIONS, state.data.kind)}</dd>
                <dt className="text-ink/45">앱</dt>
                <dd>{labelOf(APP_OPTIONS, state.data.app)}</dd>
                <dt className="text-ink/45">보낸 사람</dt>
                <dd className="break-all">{state.data.reporter_email}</dd>
                <dt className="text-ink/45">받은 시각</dt>
                <dd>{formatDateTime(state.data.received_at)}</dd>
                <dt className="text-ink/45">화면 주소</dt>
                <dd className="break-all" data-testid="feedback-report-page-url">{state.data.page_url || "-"}</dd>
                <dt className="text-ink/45">브라우저</dt>
                <dd className="break-words" data-testid="feedback-report-user-agent">{state.data.user_agent || "-"}</dd>
                <dt className="text-ink/45">화면 크기</dt>
                <dd>{state.data.screen_width && state.data.screen_height ? `${state.data.screen_width} × ${state.data.screen_height}` : "-"}</dd>
              </dl>
              <p data-testid="feedback-report-body" className="whitespace-pre-wrap border-t border-rule px-[15px] py-[14px] text-[13.5px]">{state.data.body}</p>
            </Panel>

            {state.data.has_screenshot && (
              <Panel title="스크린샷">
                <div className="px-[15px] py-[14px]">
                  {state.data.screenshot_url ? (
                    // eslint-disable-next-line @next/next/no-img-element -- 짧게 발급된 비공개 주소다.
                    <img src={state.data.screenshot_url} alt="제보 스크린샷" data-testid="feedback-report-screenshot" className="max-h-[70vh] w-auto max-w-full border border-rule" />
                  ) : (
                    <p data-testid="feedback-report-screenshot-gone" className="text-[13px] text-ink/62">보관 기한이 지나 지웠습니다.</p>
                  )}
                </div>
              </Panel>
            )}

            <Panel title="상태 바꾸기">
              <div className="flex flex-col gap-3 px-[15px] py-[14px]">
                {!canEdit && (
                  <p role="alert" data-testid="feedback-report-edit-forbidden" className="text-[13px] text-attention">
                    상태를 바꾸려면 상위 등급 Operator 권한이 필요합니다. 지금은 조회만 가능합니다.
                  </p>
                )}
                {state.data.resolution_note && (
                  <p data-testid="feedback-report-resolution" className="whitespace-pre-wrap text-[13px]">
                    <span className="text-ink/45">처리 글 · </span>{state.data.resolution_note}
                  </p>
                )}
                {canEdit && (
                  <>
                    <label className="flex flex-col gap-[3px] text-[11.5px] text-ink/45">
                      상태
                      <select data-testid="feedback-report-next-status" value={nextStatus} onChange={(event) => setNextStatus(event.target.value as FeedbackStatus)} className="w-40 border border-rule bg-paper px-2 py-1.5 text-[13px] text-ink">
                        {STATUS_OPTIONS.map((option) => (
                          <option key={option.value} value={option.value}>{option.label}</option>
                        ))}
                      </select>
                    </label>
                    <label className="flex flex-col gap-[3px] text-[11.5px] text-ink/45">
                      처리 글
                      <textarea data-testid="feedback-report-note" value={note} maxLength={4000} rows={3} onChange={(event) => setNote(event.target.value)} className="border border-rule bg-paper p-2 text-[13px] text-ink" />
                    </label>
                    <div>
                      <button type="button" data-testid="feedback-report-change" onClick={change} disabled={pending} className={BUTTON}>
                        {pending ? "처리 중..." : "상태 바꾸기"}
                      </button>
                    </div>
                    {error && <p role="alert" data-testid="feedback-report-change-error" className="text-[12.5px] text-attention">{error}</p>}
                  </>
                )}
              </div>
            </Panel>

            <Panel title="이력">
              <ol data-testid="feedback-report-history" className="flex flex-col">
                {state.data.history.map((change, index) => (
                  <li key={index} className="flex flex-wrap gap-x-3 gap-y-0.5 border-b border-rule px-[15px] py-2.5 text-[13px] last:border-b-0">
                    <span className="tabular-nums text-ink/62">{formatDateTime(change.changed_at)}</span>
                    <span>
                      {change.from_status ? `${labelOf(STATUS_OPTIONS, change.from_status)} → ` : ""}
                      {labelOf(STATUS_OPTIONS, change.to_status)}
                    </span>
                    <span className="text-ink/62">{change.actor}</span>
                    {change.note && <span className="min-w-0 break-words">{change.note}</span>}
                  </li>
                ))}
              </ol>
            </Panel>
          </>
        )}
      </div>
    </>
  );
}
