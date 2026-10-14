"use client";

// 문제 편집 오른쪽 열 끝의 글자 링크 셋 — 다른 클래스로 복사 · 템플릿으로 공개 · 문제 삭제 (#637).
//
// 학기에 한 번 하는 일이라 카드를 상시로 두지 않는다(시안 v2). 링크를 누르면 **그 자리에서**
// 펼치고, 같은 링크를 다시 누르거나 다른 링크를 누르면 접는다. 펼친 안의 확인 흐름(삭제는 제목을
// 다시 쳐야 열린다, 공개는 보일 이름을 받는다)은 예전 카드와 같다.
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import { Badge, ErrorNote, FieldLabel, INPUT_CLASS, Note, buttonClass } from "@/app/components/ui";
import { selectCopyTargets } from "@/lib/classes/copy-targets";
import { isDeleteConfirmationTyped } from "@/lib/classes/delete-confirmation";
import { useMyClasses } from "@/lib/classes/use-my-classes";
import { checkDisplayNameForBannedWords } from "@/lib/members/display-name-check";
import { useMutationRequest } from "@/lib/mutations/use-mutation-request";
import { publishProblemAsTemplate, takedownProblemTemplate } from "@/lib/problem-templates/api";
import { liveTemplateFrom, type LiveTemplate } from "@/lib/problem-templates/live-state";
import { copyProblem, deleteProblem, type ProblemRow } from "@/lib/problems/api";

type Panel = "copy" | "publish" | "delete";

const LINK_CLASS = "text-[12.5px] text-ink/60 underline-offset-2 hover:text-ink hover:underline";

export function ProblemSideActions({
  classId,
  problemId,
  problem,
  isArchived,
  reload,
}: {
  classId: number;
  problemId: number;
  problem: ProblemRow;
  isArchived: boolean;
  reload: () => void;
}) {
  const [open, setOpen] = useState<Panel | null>(null);
  const followsContest = problem.contest !== null;
  const toggle = (panel: Panel) => setOpen((prev) => (prev === panel ? null : panel));

  return (
    <div data-testid="problem-side-actions" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <button type="button" data-testid="copy-problem-open" aria-expanded={open === "copy"} onClick={() => toggle("copy")} className={LINK_CLASS}>
          다른 클래스로 복사
        </button>
        {followsContest ? null : (
          <>
            <span aria-hidden className="text-ink/25">
              ·
            </span>
            <button type="button" data-testid="publish-template-open" aria-expanded={open === "publish"} onClick={() => toggle("publish")} className={LINK_CLASS}>
              템플릿으로 공개
            </button>
          </>
        )}
        <span aria-hidden className="text-ink/25">
          ·
        </span>
        {isArchived ? (
          <span data-testid="delete-problem-archived" className="text-[12.5px] text-ink/40">
            보관된 클래스라 지울 수 없습니다
          </span>
        ) : !problem.deletable ? (
          <span data-testid="delete-problem-blocked" className="text-[12.5px] text-ink/40">
            시도가 있어 지울 수 없습니다
          </span>
        ) : (
          <button type="button" data-testid="delete-problem-open" aria-expanded={open === "delete"} onClick={() => toggle("delete")} className={`${LINK_CLASS} hover:text-attention`}>
            문제 삭제
          </button>
        )}
      </div>

      {open === "copy" ? <CopyPanel classId={classId} problemId={problemId} /> : null}
      {open === "publish" && !followsContest ? (
        <PublishPanel classId={classId} problemId={problemId} problem={problem} reload={reload} />
      ) : null}
      {open === "delete" && problem.deletable && !isArchived ? (
        <DeletePanel classId={classId} problemId={problemId} problem={problem} onCancel={() => setOpen(null)} />
      ) : null}
    </div>
  );
}

function PanelFrame({ children }: { children: React.ReactNode }) {
  return <div className="flex flex-col gap-2.5 border border-rule bg-surface p-4">{children}</div>;
}

function CopyPanel({ classId, problemId }: { classId: number; problemId: number }) {
  const router = useRouter();
  const myClassesState = useMyClasses();
  const [targetClassId, setTargetClassId] = useState("");
  const copyMutation = useMutationRequest();

  function handleCopy(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void copyMutation.run(() => copyProblem(classId, problemId, Number(targetClassId)), {
      fallbackMessage: "문제를 복사하지 못했습니다. 잠시 후 다시 시도해주세요.",
      onSuccess: (copy) => router.push(`/classes/${copy.classroom_id}/problems/${copy.id}`),
    });
  }

  if (myClassesState.status !== "ready") {
    return (
      <PanelFrame>
        <p data-testid="copy-problem-classes-loading" className="text-[13px] text-ink/45">
          불러오는 중...
        </p>
      </PanelFrame>
    );
  }
  const selection = selectCopyTargets(myClassesState.classes.filter((c) => c.id !== classId));
  return (
    <PanelFrame>
      {selection.kind === "no-classes" ? (
        <p data-testid="copy-problem-no-target" className="text-[13px] text-ink/45">
          다른 클래스 없음
        </p>
      ) : selection.kind === "all-archived" ? (
        <p data-testid="copy-problem-all-archived" className="text-[13px] text-ink/45">
          복사할 수 있는 클래스 없음 — 모두 보관됨
        </p>
      ) : (
        <form onSubmit={handleCopy} className="flex flex-col gap-2.5">
          <label htmlFor="copy-problem-target">
            <FieldLabel>대상 클래스</FieldLabel>
          </label>
          <select
            id="copy-problem-target"
            data-testid="copy-problem-target-select"
            value={targetClassId}
            onChange={(event) => setTargetClassId(event.target.value)}
            className={INPUT_CLASS}
          >
            <option value="" data-testid="copy-problem-target-option-empty">
              클래스를 선택하세요
            </option>
            {selection.classes.map((c) => (
              <option key={c.id} value={c.id} data-testid={`copy-problem-target-option-${c.id}`}>
                {c.name}
              </option>
            ))}
          </select>
          <button
            type="submit"
            data-testid="copy-problem-submit"
            disabled={copyMutation.pending || targetClassId === ""}
            className={buttonClass("secondary")}
          >
            {copyMutation.pending ? "복사하는 중..." : "복사"}
          </button>
        </form>
      )}
      {copyMutation.error ? (
        <ErrorNote>
          <span data-testid="copy-problem-error">{copyMutation.error}</span>
        </ErrorNote>
      ) : null}
    </PanelFrame>
  );
}

function PublishPanel({
  classId,
  problemId,
  problem,
  reload,
}: {
  classId: number;
  problemId: number;
  problem: ProblemRow;
  reload: () => void;
}) {
  const [publisherDisplayName, setPublisherDisplayName] = useState("");
  const publishMutation = useMutationRequest();
  const takedownMutation = useMutationRequest();
  // 지금 가져갈 수 있는 템플릿(없으면 null → 공개 폼이 뜬다). 서버가 진실의 출처이고, 공개·내리기
  // 응답도 같은 함수로 읽는다. **내려간 템플릿은 「있다」가 아니다**(2026-09-16) — 판단은
  // `lib/problem-templates/live-state.ts` 한 곳에 있고, 「방금 내렸다」는 폼을 막지 않는 배지로 따로 뜬다.
  const [liveTemplate, setLiveTemplate] = useState<LiveTemplate>(liveTemplateFrom(problem.published_template));
  const [justTakenDown, setJustTakenDown] = useState(false);
  useEffect(() => {
    setLiveTemplate(liveTemplateFrom(problem.published_template));
  }, [problem.published_template]);

  function handlePublish(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = publisherDisplayName.trim();
    // 제출을 누르는 순간에만 검사한다 — 서버가 진짜 문이다(spec #474, #477).
    const bannedWordMessage = checkDisplayNameForBannedWords(trimmed);
    if (bannedWordMessage) {
      publishMutation.setError(bannedWordMessage);
      return;
    }
    void publishMutation.run(() => publishProblemAsTemplate(classId, problemId, trimmed), {
      fallbackMessage: "템플릿으로 공개하지 못했습니다. 잠시 후 다시 시도해주세요.",
      reload,
      onSuccess: (template) => {
        setLiveTemplate(liveTemplateFrom(template));
        setJustTakenDown(false);
      },
    });
  }

  function handleTakedown() {
    if (!liveTemplate) return;
    void takedownMutation.run(() => takedownProblemTemplate(liveTemplate.shareCode), {
      fallbackMessage: "내리지 못했습니다. 잠시 후 다시 시도해주세요.",
      reload,
      onSuccess: (template) => {
        setLiveTemplate(liveTemplateFrom(template));
        setJustTakenDown(true);
      },
    });
  }

  return (
    <PanelFrame>
      {liveTemplate ? (
        <div className="flex flex-col gap-2">
          <span data-testid="publish-template-done" className="self-start">
            <Badge tone="verified">공개됨</Badge>
          </span>
          <div className="flex flex-wrap items-center gap-2">
            <Link
              href={`/templates/${liveTemplate.shareCode}`}
              data-testid="publish-template-share-link"
              className="min-w-0 flex-1 break-all border border-rule bg-paper px-3 py-2 font-mono text-[12.5px] hover:underline"
            >
              /templates/{liveTemplate.shareCode}
            </Link>
            <button
              type="button"
              data-testid="publish-template-takedown"
              onClick={handleTakedown}
              disabled={takedownMutation.pending}
              className={buttonClass("danger", "sm")}
            >
              {takedownMutation.pending ? "내리는 중..." : "내리기"}
            </button>
          </div>
        </div>
      ) : (
        <>
          {justTakenDown ? (
            <span data-testid="publish-template-taken-down" className="self-start">
              <Badge>내려짐</Badge>
            </span>
          ) : null}
          <form onSubmit={handlePublish} className="flex flex-col gap-2.5">
            <label htmlFor="publish-template-name">
              <FieldLabel>공개할 때 보일 이름</FieldLabel>
            </label>
            <input
              id="publish-template-name"
              data-testid="publish-template-name-input"
              value={publisherDisplayName}
              onChange={(event) => setPublisherDisplayName(event.target.value)}
              required
              className={INPUT_CLASS}
            />
            <button
              type="submit"
              data-testid="publish-template-submit"
              disabled={publishMutation.pending || publisherDisplayName.trim() === ""}
              className={buttonClass("secondary")}
            >
              {publishMutation.pending ? "공개하는 중..." : "템플릿으로 공개"}
            </button>
          </form>
        </>
      )}
      {takedownMutation.error ? (
        <ErrorNote>
          <span data-testid="publish-template-takedown-error">{takedownMutation.error}</span>
        </ErrorNote>
      ) : null}
      {publishMutation.error ? (
        <ErrorNote>
          <span data-testid="publish-template-error">{publishMutation.error}</span>
        </ErrorNote>
      ) : null}
    </PanelFrame>
  );
}

function DeletePanel({
  classId,
  problemId,
  problem,
  onCancel,
}: {
  classId: number;
  problemId: number;
  problem: ProblemRow;
  onCancel: () => void;
}) {
  // 삭제 — 없던 일로 한다(#430/#431, ADR-0050). 클래스 삭제와 같은 절차다: 지워질 것을 먼저 말하고
  // 제목을 다시 입력해야 열린다. 백엔드가 판정해 내려준 `problem.deletable` 을 그대로 믿는다.
  const router = useRouter();
  const [typedTitle, setTypedTitle] = useState("");
  const deleteMutation = useMutationRequest();

  function handleDelete() {
    void deleteMutation.run(() => deleteProblem(classId, problemId), {
      fallbackMessage: "문제를 지우지 못했습니다.",
      onSuccess: () => router.push(`/classes/${classId}`),
    });
  }

  return (
    <PanelFrame>
      <Note tone="attention">
        <span data-testid="delete-problem-warning">
          지우면 체크리스트 항목 {problem.checklist_items.length}개가 함께 사라지고 되돌릴 수 없습니다.
        </span>
      </Note>
      <label htmlFor="delete-problem-confirm-input">
        <FieldLabel>
          제목 <b className="text-ink">{problem.title}</b> 을 그대로 입력
        </FieldLabel>
      </label>
      <input
        id="delete-problem-confirm-input"
        data-testid="delete-problem-confirm-input"
        value={typedTitle}
        onChange={(event) => setTypedTitle(event.target.value)}
        className={INPUT_CLASS}
        autoComplete="off"
      />
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          data-testid="delete-problem-confirm"
          onClick={handleDelete}
          disabled={!isDeleteConfirmationTyped(problem.title, typedTitle) || deleteMutation.pending}
          className={buttonClass("dangerFilled", "sm")}
        >
          {deleteMutation.pending ? "지우는 중..." : "정말 삭제"}
        </button>
        <button
          type="button"
          data-testid="delete-problem-cancel"
          onClick={() => {
            setTypedTitle("");
            deleteMutation.setError(null);
            onCancel();
          }}
          disabled={deleteMutation.pending}
          className={buttonClass("secondary", "sm")}
        >
          취소
        </button>
      </div>
      {deleteMutation.error ? (
        <ErrorNote>
          <span data-testid="delete-problem-error">{deleteMutation.error}</span>
        </ErrorNote>
      ) : null}
    </PanelFrame>
  );
}
