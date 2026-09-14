"use client";

// 참여자 제출 화면 (#286). 소스 또는 저장소를 내고, 낼 때마다 새 시도가
// 시도 목록에 쌓인다 — 마감도 횟수 상한도 없다(CONTEXT.md 「Problem」).
// 강사 전용 편집 화면(app/classes/[id]/problems/[problemId]/page.tsx)과는
// 다른 라우트다 — 참여자는 문제를 고치지 않고 그 정의를 읽고 낸다.
//
// 실제로 그리는 일은 `ProblemParticipantView`(#325)가 한다 — 문제 만들기/
// 편집의 「미리보기」 탭이 **같은 조각**을 쓴다. 이 파일은 데이터를 불러오고
// 제출 요청을 보내는 배선만 맡는다.
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import type { ChangeEvent, FormEvent } from "react";

import { ErrorNote, PageShell, buttonClass } from "@/app/components/ui";
import { ProblemParticipantView } from "@/app/components/ProblemParticipantView";
import { BackendError } from "@/lib/backend/client";
import { useMe } from "@/lib/auth/use-me";
import { submitAttempt } from "@/lib/submissions/api";
import { useMyProblem } from "@/lib/submissions/use-my-problem";
import { useSourceUpload } from "@/lib/submissions/use-source-upload";

function sourceTargetRef(problemId: number, userId: number): string {
  return `classroom-submission:${problemId}:${userId}:source`;
}

// 문제 목록으로 돌아가는 길(#328) — 이 화면 전에는 브랜드를 눌러도(참여자에게
// 빈 강사 홈으로 가거나) 브라우저 뒤로 가기뿐이었다. `/mine`은 강사 전용
// 상세와 달리 참여자에게 실제로 존재하는 화면이라 안전하게 돌아갈 수 있다.
function BackToMyProblems({ classId }: { classId: number }) {
  return (
    <p className="mb-4">
      <Link
        href={`/classes/${classId}/problems/mine`}
        data-testid="my-problem-back-link"
        className={buttonClass("secondary", "sm")}
      >
        문제 목록으로
      </Link>
    </p>
  );
}

export default function ProblemSubmitPage() {
  const params = useParams<{ id: string; problemId: string }>();
  const classId = Number(params.id);
  const problemId = Number(params.problemId);
  const { state, reload } = useMyProblem(classId, problemId);
  const me = useMe();

  const [repositoryUrl, setRepositoryUrl] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const targetRef =
    me.status === "ready" ? sourceTargetRef(problemId, me.userId) : null;
  const { state: uploadState, upload } = useSourceUpload(targetRef);

  if (state.status === "loading") {
    return (
      <PageShell>
        <p data-testid="my-problem-loading" className="text-[13.5px] text-ink/45">불러오는 중...</p>
      </PageShell>
    );
  }

  if (state.status === "notFound") {
    return (
      <PageShell>
        <BackToMyProblems classId={classId} />
        <h1 data-testid="my-problem-not-found" className="text-[22px] font-semibold">
          문제를 찾을 수 없습니다
        </h1>
      </PageShell>
    );
  }

  if (state.status === "error") {
    return (
      <PageShell>
        <BackToMyProblems classId={classId} />
        <ErrorNote>
          <span data-testid="my-problem-error">문제 정보를 불러오지 못했습니다.</span>
        </ErrorNote>
      </PageShell>
    );
  }

  const {
    class_name: className,
    problem,
    submissions,
    member_expelled: memberExpelled,
    archived,
  } = state.data;

  async function submitValue(
    submissionFormat: "source" | "repository",
    value: string,
    contentType?: string | null,
  ) {
    setSubmitting(true);
    setSubmitError(null);
    try {
      await submitAttempt(classId, problemId, {
        submission_format: submissionFormat,
        value,
        content_type: contentType,
      });
      setRepositoryUrl("");
      reload();
    } catch (err) {
      setSubmitError(err instanceof BackendError ? err.message : "제출하지 못했습니다.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleRepositorySubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await submitValue("repository", repositoryUrl.trim());
  }

  async function handleSourceFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    try {
      const uploaded = await upload(file);
      await submitValue("source", uploaded.objectKey, uploaded.contentType);
    } catch {
      // useSourceUpload가 이미 uploadState.error에 이유를 남긴다.
    }
  }

  return (
    <PageShell>
      <BackToMyProblems classId={classId} />
      <ProblemParticipantView
        interactive
        eyebrow={className}
        title={problem.title}
        titleTestId="my-problem-title"
        passed={problem.passed}
        description={problem.description}
        checklistItems={problem.checklist_items}
        gradingStrictness={problem.grading_strictness}
        gradingGuidelineCustomText={problem.grading_guideline_text}
        submissionFormats={problem.submission_formats}
        submissions={submissions}
        memberExpelled={memberExpelled}
        archived={archived}
        repositoryUrl={repositoryUrl}
        onRepositoryUrlChange={setRepositoryUrl}
        onRepositorySubmit={handleRepositorySubmit}
        onSourceFile={handleSourceFile}
        submitting={submitting}
        submitError={submitError}
        uploadStatus={uploadState.status}
        uploadError={uploadState.error}
      />
    </PageShell>
  );
}
