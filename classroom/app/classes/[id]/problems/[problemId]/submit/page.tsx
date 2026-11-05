"use client";

// 참여자 제출 화면 (#286). 소스 또는 저장소를 내고, 낼 때마다 새 시도가
// 시도 목록에 쌓인다 — 마감도 횟수 상한도 없다(CONTEXT.md 「Problem」).
// 강사 전용 편집 화면(app/classes/[id]/problems/[problemId]/page.tsx)과는
// 다른 라우트다 — 참여자는 문제를 고치지 않고 그 정의를 읽고 낸다.
//
// 시안 v2(#640): 왼쪽에 설명·체크리스트(가장 최근 채점의 판정을 품는다)·내 시도, 오른쪽 360px 에 제출 카드와 진행.
// 실제로 그리는 일은 `ProblemParticipantView`(#325)가 한다 — 문제 만들기/
// 편집의 「미리보기」 탭이 **같은 조각**을 쓴다. 이 파일은 데이터를 불러오고
// 제출 요청을 보내는 배선만 맡는다.
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import type { ChangeEvent, FormEvent } from "react";

import { checkGithubRepositoryUrl } from "@codemit/bff-client/repository-url";

import { ErrorNote, PageShell, buttonClass } from "@/app/components/ui";
import { ContestEntryFields } from "@/app/components/ContestEntryFields";
import { ProblemParticipantView } from "@/app/components/ProblemParticipantView";
import { useMyQuality } from "@/lib/quality/use-quality";
import { useMe } from "@/lib/auth/use-me";
import { useClassroomTabTitle } from "@/lib/rendering/use-tab-title";
import { fetchContestEntryForm, submitAttempt } from "@/lib/submissions/api";
import {
  buildEntryPayload,
  entryBlockedReason,
  initialEntryState,
  offersContestEntry as offersEntry,
  type ContestEntryForm,
  type ContestEntryState,
} from "@/lib/submissions/contest-entry";
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
  // 본인 완성도(#883) — 공개가 꺼졌거나 기록이 없으면 404 라 그리지 않는다. 강사가 학생 화면으로 볼 때는 묻지 않는다.
  const quality = useMyQuality(
    classId,
    problemId,
    state.status === "ready" && !state.data.viewing_as_instructor,
  );
  const me = useMe();

  const [repositoryUrl, setRepositoryUrl] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const targetRef =
    me.status === "ready" ? sourceTargetRef(problemId, me.userId) : null;
  const { state: uploadState, upload } = useSourceUpload(targetRef);

  // 「공모전에도 내기」(#549) — 공모전이 지금 받는 공모전 문제에서 연다. 강사 본인도 낸다(#878).
  const offersContestEntry = state.status === "ready" && offersEntry(state.data.problem);
  const [entryForm, setEntryForm] = useState<ContestEntryForm | null>(null);
  const [entryState, setEntryState] = useState<ContestEntryState | null>(null);
  const loadEntryForm = useCallback(async () => {
    const result = await fetchContestEntryForm(classId, problemId);
    if (result.ok && result.data.accepts_entries) {
      setEntryForm(result.data);
      setEntryState(initialEntryState(result.data));
    } else {
      setEntryForm(null);
      setEntryState(null);
    }
  }, [classId, problemId]);
  useEffect(() => {
    if (offersContestEntry) void loadEntryForm();
  }, [offersContestEntry, loadEntryForm]);

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
    max_source_asset_bytes: maxSourceAssetBytes,
    instructor_problem_status: instructorProblemStatus,
    viewing_as_instructor: viewingAsInstructor,
  } = state.data;
  // 강사가 보는 중이라고 해서 못 내는 것은 아니다(2026-09-17) — 열린 문제면
  // 백엔드가 `submit_blocked_reason`을 비워 내려주고, 그때는 참여자와 같은
  // 제출 경로를 그대로 쓴다. 잠기는 것은 초안·숨김·보관뿐이다.
  const submitLocked = submitBlockedReason !== null;

  const entryOn = entryForm !== null && entryState !== null && entryState.on;
  const entryBlocked = entryOn ? entryBlockedReason(entryForm, entryState) : null;

  async function submitValue(
    submissionFormat: "source" | "repository",
    value: string,
    contentType?: string | null,
  ) {
    setSubmitting(true);
    setSubmitError(null);
    const contestEntry =
      entryForm !== null && entryState !== null ? buildEntryPayload(entryForm, entryState) : null;
    const result = await submitAttempt(classId, problemId, {
      submission_format: submissionFormat,
      value,
      content_type: contentType,
      contest_entry: contestEntry,
    });
    if (result.ok) {
      setRepositoryUrl("");
      reload();
      // 공모전에 냈으면 「이미 낸 제출」이 생겼다 — 칸을 새로 읽어 다음 시도의 확인을 받는다.
      if (contestEntry !== null) void loadEntryForm();
    } else {
      setSubmitError(result.detail);
    }
    setSubmitting(false);
  }

  async function handleRepositorySubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    // 낼 수 없는 상태(초안·숨김·보관)에서는 눌러도 아무 일도 일어나지
    // 않는다 — 백엔드도 같은 이유로 거절하므로 이 잠금은 헛걸음을 줄이는
    // 것일 뿐 유일한 문이 아니다.
    if (submitLocked) return;
    if (entryBlocked) {
      setSubmitError(entryBlocked);
      return;
    }
    // 끝의 .git·슬래시 같은 것은 정리된 주소로 보낸다 — 거부할 모양이면 버튼이 이미 잠겨 있다.
    const repository = checkGithubRepositoryUrl(repositoryUrl);
    if (repository === null || !repository.ok) return;
    await submitValue("repository", repository.url);
  }

  async function handleSourceFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || submitLocked) return;
    if (entryBlocked) {
      // 파일을 올리기 전에 막는다 — 올린 뒤 거절되면 같은 파일을 다시 골라야 한다.
      setSubmitError(entryBlocked);
      return;
    }
    try {
      const uploaded = await upload(file);
      await submitValue("source", uploaded.objectKey, uploaded.contentType);
    } catch {
      // useSourceUpload가 이미 uploadState.error에 이유를 남긴다.
    }
  }

  return (
    <PageShell>
      <ProblemParticipantView
        quality={quality}
        interactive
        backHref={viewingAsInstructor ? `/classes/${classId}` : `/classes/${classId}/problems/mine`}
        eyebrow={className}
        title={problem.title}
        titleTestId="my-problem-title"
        // 강사가 아직 한 번도 안 냈으면 「통과」/「미통과」 어느 쪽도 사실이
        // 아니다 — 미리보기와 같은 이유로 배지 자체를 내지 않는다.
        passed={viewingAsInstructor && submissions.length === 0 ? undefined : problem.passed}
        recommendedDueAt={problem.recommended_due_at}
        dueAt={problem.due_at}
        description={problem.description}
        instructorNote={problem.instructor_note}
        checklistItems={problem.checklist_items}
        hiddenChecklistItemCount={problem.hidden_checklist_item_count}
        syntaxCheckEnabled={problem.syntax_check_enabled}
        gradingStrictness={problem.grading_strictness}
        gradingGuidelineCustomText={problem.grading_guideline_text}
        submissionFormats={problem.submission_formats}
        zipGitHistoryWarning={problem.zip_git_history_warning !== null}
        submissions={submissions}
        viewingAsInstructor={viewingAsInstructor}
        instructorProblemStatus={instructorProblemStatus}
        submitBlockedReason={submitBlockedReason}
        maxSourceAssetBytes={maxSourceAssetBytes}
        repositoryUrl={repositoryUrl}
        onRepositoryUrlChange={setRepositoryUrl}
        onRepositorySubmit={handleRepositorySubmit}
        onSourceFile={handleSourceFile}
        submitting={submitting}
        submitError={submitError}
        uploadStatus={uploadState.status}
        uploadError={uploadState.error}
        contestEntry={
          entryForm !== null && entryState !== null ? (
            <ContestEntryFields
              form={entryForm}
              state={entryState}
              onChange={(next) => {
                setEntryState(next);
                setSubmitError(null);
              }}
              disabled={submitting}
            />
          ) : null
        }
      />
    </PageShell>
  );
}
