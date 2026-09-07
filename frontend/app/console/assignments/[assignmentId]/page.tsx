"use client";

// 과제 상세·수정·열기 (#207, ADR-0028/0029).
//
// 세 가지 일을 한 화면에서 한다 — DRAFT일 때 고치고, 「열기」를 누르면
// InviteCode를 받고(`POST /assignments/{id}/open`), 연 뒤에도(ASSIGNMENT_OPEN)
// 계속 고칠 수 있다(`EDITABLE`이 두 상태 모두 True다, `contests.assignment_api`).
// 상금·결제·Award·Escrow는 이 화면 어디에도 나오지 않는다(스펙 #197 인수조건).
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

import { useBackendQuery } from "@laurio/bff-client";
import type { components } from "@laurio/bff-client/schema";

import { bffClient } from "@/lib/bff/client";
import { useSession } from "@/lib/auth/use-session";
import { ASSIGNMENT_STATUS_LABELS } from "@/lib/assignments/use-my-assignments";

type AssignmentDetail = components["schemas"]["AssignmentOut"];

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

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [deadlineAt, setDeadlineAt] = useState("");
  const [savingEdit, setSavingEdit] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);
  const [opening, setOpening] = useState(false);
  const [openError, setOpenError] = useState<string | null>(null);

  useEffect(() => {
    if (state.status !== "ready") return;
    setTitle(state.data.title);
    setDescription(state.data.description);
    setDeadlineAt(toDeadlineInputValue(state.data.deadline_at));
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
  const isEditable = assignment.status === "draft" || assignment.status === "assignment_open";

  async function handleSaveEdit() {
    setEditError(null);
    const trimmedTitle = title.trim();
    if (!trimmedTitle) {
      setEditError("제목을 입력해주세요.");
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
    </main>
  );
}
