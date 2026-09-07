"use client";

// 강사가 제출 목록을 보고, 마감 전에도 소스를 펼쳐 본다 (#211, ADR-0022/0028).
//
// **목록·상세를 훑는 것만으로는 소스가 보이지 않는다.** 이 목록(`GET /assignments/
// {id}/submissions`)은 소스를 아예 담지 않는다 — 「펼치기」 버튼을 눌러야만
// `POST /assignments/{id}/submissions/{submissionId}/source`가 나가고, 그 요청 하나가
// 서버에 `AssignmentSourceReading`을 남긴다(ADR-0022가 Operator에 대해 세운 것과
// 같은 모양). 공모전과 달리 Award가 없어 감출 근거 자체가 없지만(ADR-0028), 대신
// "펼치는 행위"가 있어야 그 기록이 신호가 된다는 규율은 그대로 따른다.
import { useState } from "react";

import { useBackendQuery } from "@laurio/bff-client";

import { bffClient } from "@/lib/bff/client";
import type {
  AssignmentSourceRevealOut,
  AssignmentSubmissionSummaryOut,
} from "@/lib/submissions/types";

type RevealState =
  | { status: "idle" }
  | { status: "revealing" }
  | { status: "revealed"; data: AssignmentSourceRevealOut }
  | { status: "error"; message: string };

function SubmissionRow({ assignmentId, submission }: {
  assignmentId: string;
  submission: AssignmentSubmissionSummaryOut;
}) {
  const [reveal, setReveal] = useState<RevealState>({ status: "idle" });

  async function handleReveal() {
    setReveal({ status: "revealing" });
    const response = await bffClient.post<AssignmentSourceRevealOut>(
      `/api/backend/assignments/${assignmentId}/submissions/${submission.id}/source`,
    );
    if (!response.ok) {
      setReveal({ status: "error", message: response.detail });
      return;
    }
    setReveal({ status: "revealed", data: response.data });
  }

  return (
    <li
      className="flex flex-col gap-2 border border-rule p-3"
      data-testid={`assignment-submission-row-${submission.id}`}
    >
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-sm font-medium" data-testid="assignment-submission-developer">
            {submission.developer_display_name}
          </p>
          <p className="text-xs text-ink/60">
            제출 {new Date(submission.created_at).toLocaleString("ko-KR")}
          </p>
        </div>
        {reveal.status !== "revealed" ? (
          <button
            type="button"
            onClick={() => void handleReveal()}
            disabled={reveal.status === "revealing"}
            data-testid="assignment-submission-reveal-source-button"
            className="w-fit border border-ink px-3 py-1.5 text-xs hover:bg-ink hover:text-paper disabled:opacity-50"
          >
            {reveal.status === "revealing" ? "펼치는 중..." : "소스 펼치기"}
          </button>
        ) : null}
      </div>

      {reveal.status === "idle" || reveal.status === "revealing" ? (
        <p className="text-xs text-ink/60" data-testid="assignment-submission-reveal-notice">
          기본은 접혀 있습니다 — 펼치면 그 열람이 기록되고 학생이 확인할 수 있습니다.
        </p>
      ) : null}

      {reveal.status === "error" && (
        <p role="alert" className="text-xs text-attention" data-testid="assignment-submission-reveal-error">
          {reveal.message}
        </p>
      )}

      {reveal.status === "revealed" && (
        <div className="flex flex-col gap-1" data-testid="assignment-submission-revealed-assets">
          <p className="text-xs text-verified">펼쳤습니다 — 이 열람이 기록되었습니다.</p>
          <ul className="flex flex-col gap-1">
            {reveal.data.assets.map((asset) => (
              <li key={asset.id} className="text-xs" data-testid={`assignment-source-asset-${asset.id}`}>
                <span className="text-ink/60">{asset.label || asset.kind} — </span>
                <a
                  href={asset.url}
                  target="_blank"
                  rel="noreferrer"
                  className="underline"
                  data-testid={`assignment-source-asset-link-${asset.id}`}
                >
                  {asset.kind === "source" ? "다운로드" : asset.url}
                </a>
              </li>
            ))}
          </ul>
          {reveal.data.assets.length === 0 && (
            <p className="text-xs text-ink/60">이 제출에는 아직 소스 자료가 없습니다.</p>
          )}
        </div>
      )}
    </li>
  );
}

export function AssignmentSubmissionSourcePanel({ assignmentId }: { assignmentId: string }) {
  const { state } = useBackendQuery<AssignmentSubmissionSummaryOut[]>(
    bffClient,
    `/api/backend/assignments/${assignmentId}/submissions`,
  );

  return (
    <section className="border-t border-rule pt-4" data-testid="assignment-submission-list-section">
      <h2 className="text-lg font-semibold">제출 목록</h2>
      {state.status === "loading" && (
        <p className="mt-2 text-sm text-ink/60" data-testid="assignment-submission-list-loading">
          불러오는 중...
        </p>
      )}
      {state.status === "error" && (
        <p role="alert" className="mt-2 text-sm text-attention" data-testid="assignment-submission-list-error">
          제출 목록을 불러오지 못했습니다.
        </p>
      )}
      {state.status === "ready" && state.data.length === 0 && (
        <p className="mt-2 text-sm text-ink/60" data-testid="assignment-submission-list-empty">
          아직 제출이 없습니다.
        </p>
      )}
      {state.status === "ready" && state.data.length > 0 && (
        <ul className="mt-2 flex flex-col gap-2" data-testid="assignment-submission-list">
          {state.data.map((submission) => (
            <SubmissionRow key={submission.id} assignmentId={assignmentId} submission={submission} />
          ))}
        </ul>
      )}
    </section>
  );
}
