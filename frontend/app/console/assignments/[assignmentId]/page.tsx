"use client";

// 과제 상세·수정·열기·잠금·재발급 (#207/#209, ADR-0028/0029).
//
// 네 가지 일을 한 화면에서 한다 — DRAFT일 때 고치고, 「열기」를 누르면
// InviteCode를 받고(`POST /assignments/{id}/open`), 연 뒤에도(ASSIGNMENT_OPEN)
// 제출이 없는 동안은 계속 고치며(`EDITABLE`이 두 상태 모두 True다,
// `contests.assignment_api`), 첫 제출이 들어오면 편집 폼 대신 잠금 안내를 보여준다
// (#209 — 「첫 제출이 문을 닫는다」). 코드가 새면 재발급해 새 진입만 막는다.
// 상금·결제·Award·Escrow는 이 화면 어디에도 나오지 않는다(스펙 #197 인수조건).
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

import { useBackendQuery } from "@laurio/bff-client";
import type { components } from "@laurio/bff-client/schema";

import { bffClient } from "@/lib/bff/client";
import { useSession } from "@/lib/auth/use-session";
import { ASSIGNMENT_STATUS_LABELS } from "@/lib/assignments/use-my-assignments";
import { ScoreSummary } from "@/lib/assignments/score-summary";
import { AssignmentSourceReveal } from "@/lib/assignments/submission-source-panel";
import {
  RequirementChecklistEditor,
  requirementDraftsFromOut,
  requirementDraftsToIn,
  type RequirementDraft,
} from "@/lib/assignments/requirement-checklist-editor";

type AssignmentDetail = components["schemas"]["AssignmentOut"];
type AssignmentSubmissionRow = components["schemas"]["AssignmentSubmissionOut"];

function toDeadlineInputValue(iso: string): string {
  const date = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`;
}

export default function AssignmentDetailPage() {
  const params = useParams<{ assignmentId: string }>();
  const assignmentId = params.assignmentId;
  const session = useSession();
  const { state, reload } = useBackendQuery<AssignmentDetail>(
    bffClient,
    `/api/backend/assignments/${assignmentId}`,
  );
  // 제출 목록과 각 제출의 Score·근거(#210) — 채점 전에는 `score`가 null인 행으로
  // 온다. DRAFT일 때는 항상 빈 목록이다(제출 자체가 있을 수 없다).
  const { state: submissionsState } = useBackendQuery<AssignmentSubmissionRow[]>(
    bffClient,
    `/api/backend/assignments/${assignmentId}/submissions`,
  );

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [deadlineAt, setDeadlineAt] = useState("");
  const [requirementDrafts, setRequirementDrafts] = useState<RequirementDraft[]>([]);
  const [savingEdit, setSavingEdit] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);
  const [opening, setOpening] = useState(false);
  const [openError, setOpenError] = useState<string | null>(null);
  const [reissuing, setReissuing] = useState(false);
  const [reissueError, setReissueError] = useState<string | null>(null);
  const [reissued, setReissued] = useState(false);

  useEffect(() => {
    if (state.status !== "ready") return;
    setTitle(state.data.title);
    setDescription(state.data.description);
    setDeadlineAt(toDeadlineInputValue(state.data.deadline_at));
    setRequirementDrafts(requirementDraftsFromOut(state.data.requirements));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 응답이 새로 도착했을 때만 폼을 되돌린다.
  }, [state.status === "ready" ? state.data.id : null, state.status === "ready" ? state.data.status : null]);

  if (session.status === "unauthenticated") return null;
  if (session.status === "loading" || state.status === "loading") {
    return (
      <main className="p-10">
        <p data-testid="assignment-detail-loading">불러오는 중...</p>
      </main>
    );
  }

  if (state.status === "error") {
    return (
      <main className="p-10">
        <p role="alert" data-testid="assignment-detail-error">
          과제를 불러오지 못했습니다.
        </p>
      </main>
    );
  }

  const assignment = state.data;
  // `is_editable`은 백엔드가 계산해 실어 보낸다(`contests.assignment_api.
  // _get_owned_editable_assignment`가 실제로 막는 것과 정확히 같은 술어) — 화면이
  // `status === "draft" || status === "assignment_open"`처럼 그 규칙을 다시 적으면
  // 안 된다. 그러면 백엔드가 규칙을 하나 더 얹을 때(바로 이 티켓의 "첫 제출이 문을
  // 닫는다") 화면이 따로 갱신되지 않는 한 어긋나 — 게이트는 막는데 화면은 편집
  // 폼을 계속 보여주는 fail-open이 생긴다(#209 코드리뷰 지적).
  const isEditable = assignment.is_editable;
  // 잠금 배너는 "열려 있는데 편집이 안 된다" — 즉 여러 잠김 사유(EDITABLE이 아닌
  // 상태 vs. 첫 제출) 중 「첫 제출이 문을 닫는다」에 해당하는 경우에만 이 문구를
  // 보여준다. ASSIGNMENT_CLOSED처럼 다른 이유로 안 열리는 경우는 애초에 이 화면의
  // "제출 후 잠김" 배너가 설명할 대상이 아니다.
  const isLockedByFirstSubmission = assignment.status === "assignment_open" && !isEditable;

  async function handleSaveEdit() {
    setEditError(null);
    const trimmedTitle = title.trim();
    if (!trimmedTitle) {
      setEditError("제목을 입력해주세요.");
      return;
    }
    if (requirementDrafts.some((r) => r.text.trim() === "")) {
      setEditError("빈 요구사항 항목이 있습니다. 내용을 채우거나 삭제해주세요.");
      return;
    }
    setSavingEdit(true);
    try {
      const response = await bffClient.request<AssignmentDetail>(
        `/api/backend/assignments/${assignmentId}`,
        {
          method: "PATCH",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            title: trimmedTitle,
            description,
            deadline_at: new Date(deadlineAt).toISOString(),
            // 통째 교체다(#217, 백엔드 `AssignmentUpdateIn`) — 편집기에 지금 보이는
            // 목록 그대로가 저장 후의 전체 목록이 된다.
            requirements: requirementDraftsToIn(requirementDrafts),
          }),
        },
      );
      if (!response.ok) {
        setEditError(response.detail);
        return;
      }
      reload();
    } finally {
      setSavingEdit(false);
    }
  }

  async function handleOpen() {
    setOpenError(null);
    setOpening(true);
    try {
      const response = await bffClient.post<AssignmentDetail>(
        `/api/backend/assignments/${assignmentId}/open`,
      );
      if (!response.ok) {
        setOpenError(response.detail);
        return;
      }
      reload();
    } finally {
      setOpening(false);
    }
  }

  async function handleReissue() {
    setReissueError(null);
    setReissued(false);
    setReissuing(true);
    try {
      const response = await bffClient.post<AssignmentDetail>(
        `/api/backend/assignments/${assignmentId}/invite-code/reissue`,
      );
      if (!response.ok) {
        setReissueError(response.detail);
        return;
      }
      setReissued(true);
      reload();
    } finally {
      setReissuing(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-xl flex-col gap-6 p-10">
      <div>
        <p
          className="text-xs font-medium tracking-widest text-ink/60"
          data-testid="assignment-detail-status"
        >
          {ASSIGNMENT_STATUS_LABELS[assignment.status] ?? assignment.status}
        </p>
        <h1 className="text-2xl font-semibold" data-testid="assignment-detail-heading">
          {assignment.title}
        </h1>
      </div>

      {assignment.status === "draft" ? (
        <div className="border border-rule p-4">
          <p className="text-sm text-ink/70">
            아직 열리지 않았습니다. 열면 InviteCode가 발급되어 학생에게 알려줄 수 있습니다.
          </p>
          <button
            type="button"
            onClick={() => void handleOpen()}
            disabled={opening}
            data-testid="assignment-open-button"
            className="mt-3 w-fit border border-ink bg-ink px-6 py-2 text-sm text-paper disabled:opacity-50"
          >
            {opening ? "여는 중..." : "과제 열기"}
          </button>
          {openError && (
            <p role="alert" data-testid="assignment-open-error" className="mt-2 text-sm text-attention">
              {openError}
            </p>
          )}
        </div>
      ) : null}

      {assignment.invite_code ? (
        <div className="border border-rule p-4">
          <p className="text-sm text-ink/70">InviteCode — 학생에게 이 코드만 알려주면 됩니다.</p>
          <p
            className="mt-2 font-mono text-lg font-semibold"
            data-testid="assignment-invite-code"
          >
            {assignment.invite_code}
          </p>
          {/* 학생이 실제로 보게 될 화면을 강사가 미리 확인할 수 있는 링크(#208) —
              InviteCode 로만 닿는 그 화면(app/assignments/[code])의 유일한
              제품 내 진입점이기도 하다. */}
          <a
            href={`/assignments/${assignment.invite_code}`}
            target="_blank"
            rel="noreferrer"
            data-testid="assignment-invite-preview-link"
            className="mt-2 inline-block text-sm underline"
          >
            학생 화면 미리보기
          </a>

          {assignment.status === "assignment_open" ? (
            <div className="mt-4 border-t border-rule pt-4">
              <p className="text-sm text-ink/70">
                코드가 새어 나갔나요? 재발급하면 이 코드는 더 이상 쓸 수 없게 되고 새
                코드가 발급됩니다 — 이미 제출한 학생의 과제물은 그대로 남습니다.
              </p>
              <button
                type="button"
                onClick={() => void handleReissue()}
                disabled={reissuing}
                data-testid="assignment-invite-reissue-button"
                className="mt-3 w-fit border border-ink px-4 py-2 text-sm hover:bg-ink hover:text-paper disabled:opacity-50"
              >
                {reissuing ? "재발급하는 중..." : "InviteCode 재발급"}
              </button>
              {reissued && (
                <p
                  data-testid="assignment-invite-reissue-success"
                  className="mt-2 text-sm text-ink/70"
                >
                  재발급했습니다. 위 코드가 새 코드이고, 이전 코드는 더 이상 쓸 수
                  없습니다.
                </p>
              )}
              {reissueError && (
                <p
                  role="alert"
                  data-testid="assignment-invite-reissue-error"
                  className="mt-2 text-sm text-attention"
                >
                  {reissueError}
                </p>
              )}
            </div>
          ) : null}
        </div>
      ) : null}

      {isLockedByFirstSubmission ? (
        <div className="border-t border-rule pt-6" data-testid="assignment-requirements-locked">
          <p className="text-sm text-attention">
            이미 제출한 학생이 있어 과제 내용을 더 이상 고칠 수 없습니다. 제출 뒤 기준이
            바뀌면 이미 낸 학생이 불리해지기 때문입니다.
          </p>
        </div>
      ) : null}

      {isEditable ? (
        <div className="flex flex-col gap-4 border-t border-rule pt-6">
          <label className="flex flex-col gap-1 text-sm">
            제목
            <input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              maxLength={200}
              data-testid="assignment-edit-title"
              className="border border-rule bg-surface px-3 py-2"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            마감 기한
            <input
              type="datetime-local"
              value={deadlineAt}
              onChange={(event) => setDeadlineAt(event.target.value)}
              data-testid="assignment-edit-deadline"
              className="border border-rule bg-surface px-3 py-2"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            설명
            <textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              rows={3}
              data-testid="assignment-edit-description"
              className="border border-rule bg-surface px-3 py-2"
            />
          </label>

          <RequirementChecklistEditor
            requirements={requirementDrafts}
            onChange={setRequirementDrafts}
            testIdPrefix="assignment-edit-requirement"
          />

          {editError && (
            <p role="alert" data-testid="assignment-edit-error" className="text-sm text-attention">
              {editError}
            </p>
          )}
          <button
            type="button"
            onClick={() => void handleSaveEdit()}
            disabled={savingEdit}
            data-testid="assignment-edit-save"
            className="w-fit border border-ink px-4 py-2 text-sm hover:bg-ink hover:text-paper disabled:opacity-50"
          >
            {savingEdit ? "저장 중..." : "저장"}
          </button>
        </div>
      ) : null}

      {/* 편집 가능한 동안은 위 `RequirementChecklistEditor`가 유일한 목록이다 —
          같은 항목을 여기서 다시 읽기 전용으로 그리면 저장 전 임시 상태와 마지막
          저장 상태가 한 화면에 둘 다 보여 혼동을 준다(#217). 잠긴 뒤(첫 제출 이후·
          마감 후)에는 이 목록이 유일한 표시 자리가 된다. */}
      {!isEditable ? (
        <div className="border-t border-rule pt-4 text-sm text-ink/70">
          <p>Requirement</p>
          <ul className="mt-2 flex flex-col gap-1" data-testid="assignment-requirements">
            {assignment.requirements.map((r) => (
              <li key={r.id} data-testid={`assignment-requirement-${r.id}`}>
                [{r.grade === "required" ? "필수" : "선택"}] {r.text}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <SubmissionsSection state={submissionsState} assignmentId={assignmentId} />
    </main>
  );
}

// 제출 목록과 각 제출의 Score·근거(#210). 소스는 여기 없다 — 소스 열람은
// 명시적으로 펼쳐야 기록과 함께 이루어지는 별도 경로다(#211, ADR-0022).
function SubmissionsSection({
  state,
  assignmentId,
}: {
  state:
    | { status: "loading" }
    | { status: "error" }
    | { status: "ready"; data: AssignmentSubmissionRow[] };
  assignmentId: string;
}) {
  return (
    <div className="border-t border-rule pt-4" data-testid="assignment-submissions-section">
      <p className="text-sm text-ink/70">제출 목록</p>

      {state.status === "loading" && (
        <p className="mt-2 text-sm" data-testid="assignment-submissions-loading">
          불러오는 중...
        </p>
      )}
      {state.status === "error" && (
        <p role="alert" className="mt-2 text-sm text-attention" data-testid="assignment-submissions-error">
          제출 목록을 불러오지 못했습니다.
        </p>
      )}
      {state.status === "ready" && state.data.length === 0 && (
        <p className="mt-2 text-sm text-ink/70" data-testid="assignment-submissions-empty">
          아직 제출한 학생이 없습니다.
        </p>
      )}
      {state.status === "ready" && state.data.length > 0 && (
        <ul className="mt-3 flex flex-col gap-3" data-testid="assignment-submissions-list">
          {state.data.map((row) => (
            <li
              key={row.submission_id}
              className="border border-rule p-4 text-sm"
              data-testid={`assignment-submission-${row.submission_id}`}
            >
              <p className="font-medium" data-testid="assignment-submission-developer">
                {row.developer_display_name}
              </p>
              {row.score === null || row.score === undefined ? (
                <p className="mt-1 text-ink/70" data-testid="assignment-submission-not-scored">
                  아직 채점되지 않았습니다.
                </p>
              ) : (
                <div className="mt-2 flex flex-col gap-2">
                  <ScoreSummary score={row.score} testIdPrefix="assignment-submission-score" />
                </div>
              )}
              {/* 소스는 목록에 담기지 않는다 — 펼쳐야 나오고, 펼치면 기록된다(#211, ADR-0022). */}
              <AssignmentSourceReveal assignmentId={assignmentId} submissionId={row.submission_id} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
