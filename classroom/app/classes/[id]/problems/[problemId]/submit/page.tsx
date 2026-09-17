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
import { useClassroomTabTitle } from "@/lib/rendering/use-tab-title";
import { submitAttempt } from "@/lib/submissions/api";
import { useMyProblem } from "@/lib/submissions/use-my-problem";
import { useSourceUpload } from "@/lib/submissions/use-source-upload";

function sourceTargetRef(problemId: number, userId: number): string {
  return `classroom-submission:${problemId}:${userId}:source`;
}

// 문제 목록으로 돌아가는 길(#328) — 이 화면 전에는 브랜드를 눌러도(참여자에게
// 빈 강사 홈으로 가거나) 브라우저 뒤로 가기뿐이었다. `/mine`은 강사 전용
// 상세와 달리 참여자에게 실제로 존재하는 화면이라 안전하게 돌아갈 수 있다.
//
// **강사가 「학생 화면으로」 연 경우에는 그 주소가 강사에게 없다**(#429) —
// `/problems/mine`은 `ClassMember`를 요구하는데 강사는 보통 그 클래스의
// 참여자가 아니라 이 링크를 눌러도 404로 되돌아온다. 그래서 `href`를 받는
// 자리를 열어 두고, 강사가 보고 있을 때는 문제 편집 화면으로 돌려보낸다.
function BackToMyProblems({ classId, href }: { classId: number; href?: string }) {
  return (
    <p className="mb-4">
      <Link
        href={href ?? `/classes/${classId}/problems/mine`}
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

  useClassroomTabTitle({
    screenName: "문제 제출",
    className: state.status === "ready" ? state.data.class_name : undefined,
    problemTitle: state.status === "ready" ? state.data.problem.title : undefined,
  });

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
    submit_blocked_reason: submitBlockedReason,
    instructor_problem_status: instructorProblemStatus,
  } = state.data;
  const viewingAsInstructor = submitBlockedReason === "viewing_as_instructor";

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
    // 강사가 「학생 화면으로」 연 화면이다 — 제출 칸은 보이되 눌러도 아무
    // 일도 일어나지 않는다(#429). 백엔드도 강사(비참여자)의 제출을 404로
    // 거절하므로 이 잠금은 헛걸음을 줄이는 것일 뿐 유일한 문이 아니다.
    if (viewingAsInstructor) return;
    await submitValue("repository", repositoryUrl.trim());
  }

  async function handleSourceFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || viewingAsInstructor) return;
    try {
      const uploaded = await upload(file);
      await submitValue("source", uploaded.objectKey, uploaded.contentType);
    } catch {
      // useSourceUpload가 이미 uploadState.error에 이유를 남긴다.
    }
  }

  return (
    <PageShell>
      <BackToMyProblems
        classId={classId}
        href={viewingAsInstructor ? `/classes/${classId}` : undefined}
      />
      <ProblemParticipantView
        interactive
        eyebrow={className}
        title={problem.title}
        titleTestId="my-problem-title"
        // 강사 시점에는 시도가 애초에 없어 「통과」/「미통과」 어느 쪽도
        // 사실이 아니다 — 미리보기와 같은 이유로 배지 자체를 내지 않는다.
        passed={viewingAsInstructor ? undefined : problem.passed}
        description={problem.description}
        checklistItems={problem.checklist_items}
        syntaxCheckEnabled={problem.syntax_check_enabled}
        gradingStrictness={problem.grading_strictness}
        gradingGuidelineCustomText={problem.grading_guideline_text}
        submissionFormats={problem.submission_formats}
        submissions={submissions}
        viewingAsInstructor={viewingAsInstructor}
        instructorProblemStatus={instructorProblemStatus}
        submitBlockedReason={submitBlockedReason}
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
