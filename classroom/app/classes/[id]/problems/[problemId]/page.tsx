"use client";

// 문제 편집 (#282/#283/#285, 시안 v2 #637). 1200px 틀 안의 두 열 — 왼쪽은 제목·설명·체크리스트,
// 오른쪽 300px 은 상태·제출 형식·채점 모델·채점 지침과 끝의 글자 링크 셋(복사·템플릿 공개·삭제).
// 머리에 「저장」이 있고(제목·설명·제출 형식·채점 모델·채점 지침을 저장), 체크리스트는 항목마다 바로 저장된다.
import { MarkdownView } from "@codemit/markdown";
import Link from "next/link";

import {
  Badge,
  Card,
  CardHeader,
  EmptyState,
  ErrorNote,
  FieldLabel,
  INPUT_CLASS,
  Note,
  PageShell,
  buttonClass,
} from "@/app/components/ui";
import { ChecklistRows } from "@/app/components/ChecklistRows";
import { isGradingGuidelineValid, type GradingGuidelineValue } from "@/app/components/GradingGuidelineEditor";
import { MarkdownEditor } from "@/app/components/MarkdownEditor";
import { ProblemParticipantView } from "@/app/components/ProblemParticipantView";
import { ProblemSettingsForm } from "@/app/components/ProblemSettingsForm";
import { ProblemSideActions } from "@/app/components/ProblemSideActions";
import { TwoColumnFrame } from "@/app/components/TwoColumnFrame";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import { useClass } from "@/lib/classes/use-class";
import { checkPublicTextForBannedWords } from "@/lib/moderation/public-text-check";
import { useMutationRequest } from "@/lib/mutations/use-mutation-request";
import {
  createChecklistItem,
  deleteChecklistItem,
  hideProblem,
  openProblem,
  reopenProblem,
  reorderChecklistItems,
  updateChecklistItem,
  updateProblem,
  type ProblemTransitionBlockedReason,
  type SubmissionFormat,
} from "@/lib/problems/api";
import { useProblem } from "@/lib/problems/use-problem";
import { useClassroomTabTitle } from "@/lib/rendering/use-tab-title";
import { useScoringCost } from "@/lib/scoring/use-scoring-cost";
import { useScoringModels } from "@/lib/scoring/use-scoring-models";
import { useSubmissionCount } from "@/lib/submissions/use-submission-count";

const STATUS_LABEL: Record<string, string> = {
  draft: "초안",
  open: "열림",
  hidden: "숨김",
};

// 전이가 막힌 이유를 버튼 자리에 그대로 보일 문장으로 바꾼다(#440 AC) —
// 순수 함수라 화면 밖에 둔다. "archived"는 클래스 상세·체크리스트가 이미
// 쓰는 문구와 같은 문장이다(같은 뜻은 같은 말로).
function transitionBlockedReasonText(reason: Exclude<ProblemTransitionBlockedReason, null>): string {
  return reason === "archived"
    ? "이 클래스는 보관되어 바꿀 수 없습니다."
    : "필수 항목을 하나 이상 추가해야 열 수 있습니다.";
}

export default function EditProblemPage() {
  const params = useParams<{ id: string; problemId: string }>();
  const classId = Number(params.id);
  // 미리보기 눈썹이 참여자 화면과 같이 클래스 이름을 말한다(#372 후속, 새 문제 화면과 같다).
  const { state: classState } = useClass(classId);
  const previewEyebrow = classState.status === "ready" ? classState.classroom.name : "";
  const problemId = Number(params.problemId);
  const router = useRouter();

  const { state, reload } = useProblem(classId, problemId);
  const { state: modelsState } = useScoringModels(classId);
  const costState = useScoringCost(classId, problemId);
  const submissionCount = useSubmissionCount(classId, problemId);

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  // 공모전 문제의 수업용 안내(#548) — 제목·설명은 공모전을 따라가 고칠 수 없으므로 이 칸에 덧붙인다.
  const [instructorNote, setInstructorNote] = useState("");
  const [submissionFormats, setSubmissionFormats] = useState<SubmissionFormat[]>(["source"]);
  const [model, setModel] = useState("");
  const [reasoningEffort, setReasoningEffort] = useState("");
  // 「호환 서버」의 「추론 모델」 스위치(#602) — 이 문제 자신의 모델에만 뜻이 있다.
  const [modelIsReasoning, setModelIsReasoning] = useState(false);
  // 채점 지침(#386) — 불러온 문제 값으로 아래 effect가 채운다.
  const [gradingGuideline, setGradingGuideline] = useState<GradingGuidelineValue>({
    grading_strictness: "normal",
    grading_guideline_text: "",
  });
  // 본문 저장(제목·설명·제출 형식·채점 모델·추론 강도·채점 지침) — 공용
  // 변경 도우미(#442)를 거친다. 오류·불러오는 중 표시가 자리마다 갈려
  // 아래 나머지 변경도 각자 자기 훅 인스턴스를 든다.
  const mainSave = useMutationRequest();
  // 「이 모델로 다시 시도」(#437) — 본문 저장과 별개 상태다, 모델 칸 옆의
  // 작은 버튼 하나가 이 요청만 보낸다.
  const retryModelMutation = useMutationRequest();

  const [newItemLabel, setNewItemLabel] = useState("");
  const [newItemRequired, setNewItemRequired] = useState(true);
  // 체크리스트 조작(추가·항목 저장·필수 토글·삭제·순서 바꾸기·문법 검사
  // 켬끔)은 오류 표시 자리(`checklist-error`)를 공유해 한 훅으로 묶는다.
  const checklistMutation = useMutationRequest();
  const openMutation = useMutationRequest();
  // 「숨기기」는 한 번 더 확인을 받는다(#405 AC) — 이미 낸 참여자가 어떻게
  // 되는지 알고 누르게 하기 위해서다. 다른 버튼들과 달리 클릭 한 번으로
  // 바로 실행하지 않는다.
  const [confirmingHide, setConfirmingHide] = useState(false);
  const hideMutation = useMutationRequest();
  const reopenMutation = useMutationRequest();

  // 「작성」/「미리보기」 탭(#325) — 새 문제 화면과 같은 자리다.
  const [tab, setTab] = useState<"write" | "preview">("write");

  useClassroomTabTitle({
    screenName: "문제 편집",
    className: classState.status === "ready" ? classState.classroom.name : undefined,
    problemTitle: state.status === "ready" ? state.problem.title : undefined,
  });

  useEffect(() => {
    if (state.status === "ready") {
      setTitle(state.problem.title);
      setDescription(state.problem.description);
      setInstructorNote(state.problem.instructor_note);
      setSubmissionFormats(state.problem.submission_formats);
      setModel(state.problem.model);
      setReasoningEffort(state.problem.reasoning_effort);
      setModelIsReasoning(state.problem.model_is_reasoning);
      setGradingGuideline({
        grading_strictness: state.problem.grading_strictness,
        grading_guideline_text: state.problem.grading_guideline_text,
      });
    }
  }, [state]);

  if (state.status === "loading") {
    return (
      <PageShell>
        <p data-testid="edit-problem-loading" className="text-[13.5px] text-ink/45">불러오는 중...</p>
      </PageShell>
    );
  }

  if (state.status === "error") {
    return (
      <PageShell>
        <p data-testid="edit-problem-error" className="text-[15px]">문제를 찾을 수 없습니다.</p>
      </PageShell>
    );
  }

  const { problem } = state;
  // 보관된 클래스는 읽기 전용이다(#438) — 이 화면의 모든 변경 버튼이 이
  // 값 하나로 갈린다. 서버도 같은 요청을 403으로 거절하므로(`classroom.
  // participation.assert_class_mutable`), 이 disable 은 편의일 뿐 문 자체는
  // 여전히 백엔드다.
  const isArchived = classState.status === "ready" && classState.classroom.archived;
  // 공모전 문제(#548) — 제목·설명·체크리스트는 공모전을 따라가고 여기서 고칠 수 없다.
  const contest = problem.contest;
  const followsContest = contest !== null;
  const archivedReason = "이 클래스는 보관되어 바꿀 수 없습니다.";
  // 지금 상태에서 나갈 수 있는 전이 — 그래프가 상태마다 간선을 하나만
  // 두므로(#440) 배열의 유일한 원소만 본다. 문제가 끝 상태를 갖지 않는
  // 이상(지금은 없다) 언제나 하나다.
  const transition = problem.available_transitions[0];

  function toggleSubmissionFormat(format: SubmissionFormat, checked: boolean) {
    setSubmissionFormats((prev) =>
      checked ? [...prev, format].filter((f, i, arr) => arr.indexOf(f) === i) : prev.filter((f) => f !== format),
    );
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!isGradingGuidelineValid(gradingGuideline)) return;
    // 제출을 누르는 순간에만 검사한다 — 타이핑 중에는 부르지 않는다(spec
    // #474, #479). 서버가 진짜 문이라 여기서 걸러도 걸러지지 않아도 서버가
    // 같은 이유로 다시 거절한다.
    const titleBannedWordMessage = checkPublicTextForBannedWords(title.trim(), "제목");
    if (titleBannedWordMessage) {
      mainSave.setError(titleBannedWordMessage);
      return;
    }
    const noteBannedWordMessage = checkPublicTextForBannedWords(instructorNote, "수업용 안내");
    if (followsContest && noteBannedWordMessage) {
      mainSave.setError(noteBannedWordMessage);
      return;
    }
    const descriptionBannedWordMessage = checkPublicTextForBannedWords(description, "설명");
    if (descriptionBannedWordMessage) {
      mainSave.setError(descriptionBannedWordMessage);
      return;
    }
    void mainSave.run(
      () =>
        updateProblem(classId, problemId, {
          // 공모전 문제는 제목·설명을 보내지 않는다 — 서버가 거절한다(#548). 대신 수업용 안내를 보낸다.
          ...(followsContest ? { instructor_note: instructorNote } : { title: title.trim(), description }),
          submission_formats: submissionFormats,
          // 모델 값을 불러온 값과 다를 때만 보낸다(#437) — 백엔드는 이 필드가
          // 오면 값이 같아도 「모델 거부」 표시를 푼다(#403 AC), 그래서 제목
          // 만 고쳐 저장해도 매번 이 필드를 함께 보내면 거부 표시가 강사가
          // 손대지 않았는데도 풀려 버린다. 거부된 모델로 새 시도가 헛되이
          // 다시 채점되는 것을 막는다. 같은 모델로 다시 시도하려면 모델
          // 칸의 「이 모델로 다시 시도」(`handleRetryModel`)를 쓴다.
          ...(model !== problem.model ? { model } : {}),
          reasoning_effort: reasoningEffort,
          // 스위치는 값이 바뀌었을 때만 보낸다 — 바뀌면 서버가 그 모델을 다시 시험한다(#602).
          ...(modelIsReasoning !== problem.model_is_reasoning ? { model_is_reasoning: modelIsReasoning } : {}),
          grading_strictness: gradingGuideline.grading_strictness,
          grading_guideline_text: gradingGuideline.grading_guideline_text,
        }),
      {
        fallbackMessage: "문제를 저장하지 못했습니다. 잠시 후 다시 시도해주세요.",
        reload,
        onSuccess: () => router.push(`/classes/${classId}`),
      },
    );
  }

  function handleRetryModel() {
    // 벤더 쪽 문제가 풀렸다고 강사가 판단하면 모델을 바꾸지 않고도 거부
    // 표시를 풀 수 있다(#437) — 모델 필드만 보낸다(지금 저장된 값 그대로,
    // 편집 중인 선택값과 무관하다).
    void retryModelMutation.run(() => updateProblem(classId, problemId, { model: problem.model }), {
      fallbackMessage: "다시 시도하지 못했습니다. 잠시 후 다시 시도해주세요.",
      reload,
    });
  }

  function handleAddItem(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    // 제출을 누르는 순간에만 검사한다(spec #474, #479) — 서버가 진짜 문이다.
    const bannedWordMessage = checkPublicTextForBannedWords(newItemLabel.trim(), "체크리스트 항목");
    if (bannedWordMessage) {
      checklistMutation.setError(bannedWordMessage);
      return;
    }
    void checklistMutation.run(
      () => createChecklistItem(classId, problemId, { label: newItemLabel.trim(), required: newItemRequired }),
      {
        fallbackMessage: "항목을 추가하지 못했습니다. 잠시 후 다시 시도해주세요.",
        reload,
        onSuccess: () => {
          setNewItemLabel("");
          setNewItemRequired(true);
        },
      },
    );
  }

  function handleItemLabelSave(itemId: number, label: string) {
    // 입력칸이 포커스를 잃는 순간이 이 화면의 "제출"이다(spec #474, #479) —
    // 서버가 진짜 문이다.
    const bannedWordMessage = checkPublicTextForBannedWords(label, "체크리스트 항목");
    if (bannedWordMessage) {
      checklistMutation.setError(bannedWordMessage);
      return;
    }
    void checklistMutation.run(() => updateChecklistItem(classId, problemId, itemId, { label }), {
      fallbackMessage: "항목을 저장하지 못했습니다. 잠시 후 다시 시도해주세요.",
      reload,
    });
  }

  function handleItemRequiredToggle(itemId: number, required: boolean) {
    // 열린·숨긴 문제의 마지막 필수 항목을 필수 해제하면 422가 온다(#440) —
    // 그 문구를 그대로 보여준다, 화면이 다시 판단하지 않는다.
    void checklistMutation.run(() => updateChecklistItem(classId, problemId, itemId, { required }), {
      fallbackMessage: "항목을 저장하지 못했습니다. 잠시 후 다시 시도해주세요.",
      reload,
    });
  }

  function handleItemDelete(itemId: number) {
    // 열린·숨긴 문제의 마지막 필수 항목 삭제도 422다(#440) — 그 문구를
    // 그대로 보여준다.
    void checklistMutation.run(() => deleteChecklistItem(classId, problemId, itemId), {
      fallbackMessage: "항목을 지우지 못했습니다. 잠시 후 다시 시도해주세요.",
      reload,
    });
  }

  function handleSyntaxCheckToggle(enabled: boolean) {
    void checklistMutation.run(() => updateProblem(classId, problemId, { syntax_check_enabled: enabled }), {
      fallbackMessage: "설정을 저장하지 못했습니다. 잠시 후 다시 시도해주세요.",
      reload,
    });
  }

  // 성공 여부를 돌려준다 — 실패하면 줄이 서버 순서로 돌아오고(#670), 다른 탭에서 바뀐 항목도
  // 받도록 다시 불러온다(`useMutationRequest` 는 실패에 다시 불러오지 않는다).
  async function handleReorder(orderedKeys: (string | number)[]): Promise<boolean> {
    let saved = false;
    await checklistMutation.run(() => reorderChecklistItems(classId, problemId, orderedKeys as number[]), {
      fallbackMessage: "순서를 바꾸지 못했습니다. 다시 시도해주세요.",
      reload,
      onSuccess: () => {
        saved = true;
      },
    });
    if (!saved) reload();
    return saved;
  }

  function handleOpen() {
    void openMutation.run(() => openProblem(classId, problemId), {
      fallbackMessage: "문제를 열지 못했습니다. 잠시 후 다시 시도해주세요.",
      reload,
    });
  }

  function handleHide() {
    void hideMutation.run(() => hideProblem(classId, problemId), {
      fallbackMessage: "문제를 숨기지 못했습니다. 잠시 후 다시 시도해주세요.",
      reload,
      onSuccess: () => setConfirmingHide(false),
    });
  }

  function handleReopen() {
    void reopenMutation.run(() => reopenProblem(classId, problemId), {
      fallbackMessage: "문제를 다시 열지 못했습니다. 잠시 후 다시 시도해주세요.",
      reload,
    });
  }

  const statusTone = problem.status === "open" ? "verified" : problem.status === "hidden" ? "attention" : "neutral";
  const classLabel = classState.status === "ready" ? `${classState.classroom.name} › ` : "";

  return (
    <PageShell>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-1.5">
          <div className="text-[11px] tracking-[0.08em] text-ink/45">
            {classLabel}문제 {problem.order + 1}
          </div>
          <div className="flex min-w-0 flex-wrap items-center gap-3">
            <h1 data-testid="edit-problem-heading" className="min-w-0 break-words text-[22px] font-semibold tracking-[-0.01em]">
              {problem.title}
            </h1>
            <span data-testid="edit-problem-status-badge">
              <Badge tone={statusTone}>{STATUS_LABEL[problem.status]}</Badge>
            </span>
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          {/* 참여자가 실제로 걷는 그 주소를 그대로 연다(#429) — 상태와 무관하게 항상 보인다. */}
          <Link
            href={`/classes/${classId}/problems/${problemId}/submit`}
            data-testid="view-as-student-link"
            className={buttonClass()}
          >
            학생 화면으로
          </Link>
          <Link
            href={`/classes/${classId}/problems/${problemId}/submissions`}
            data-testid="problem-submissions-link"
            className={buttonClass()}
          >
            제출 현황{submissionCount === null ? "" : <span className="ml-1.5 font-mono text-ink/60">{submissionCount}</span>}
          </Link>
          <button
            type="submit"
            form="edit-problem-form"
            data-testid="edit-problem-submit"
            disabled={
              isArchived ||
              mainSave.pending ||
              title.trim() === "" ||
              submissionFormats.length === 0 ||
              !isGradingGuidelineValid(gradingGuideline)
            }
            className={buttonClass("primary")}
          >
            {mainSave.pending ? "저장하는 중..." : "저장"}
          </button>
        </div>
      </div>

      {isArchived ? (
        <div className="mb-5">
          <Note tone="attention">
            <span data-testid="edit-problem-archived-note">{archivedReason}</span>
          </Note>
        </div>
      ) : null}
      {mainSave.error ? (
        <div className="mb-5">
          <ErrorNote>
            <span data-testid="edit-problem-error-message">{mainSave.error}</span>
          </ErrorNote>
        </div>
      ) : null}

      <div className="flex flex-col gap-5">
        <div role="tablist" aria-label="문제 편집 화면" className="flex items-end gap-0.5 border-b border-rule">
          {(
            [
              ["write", "작성", "edit-problem-tab-write"],
              ["preview", "미리보기", "edit-problem-tab-preview"],
            ] as const
          ).map(([key, label, testId]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={tab === key}
              data-testid={testId}
              onClick={() => setTab(key)}
              className={
                tab === key
                  ? "-mb-px border border-rule border-b-surface bg-surface px-4 py-2 text-[13.5px] font-medium"
                  : "px-4 py-2 text-[13.5px] text-ink/60 hover:text-ink"
              }
            >
              {label}
            </button>
          ))}
        </div>

        <div data-testid="edit-problem-write-panel" className={tab === "write" ? "block" : "hidden"}>
          <TwoColumnFrame
            sideTestId="edit-problem-side-rail"
            main={
              <>
                <Card>
                  {contest !== null ? (
                    <div
                      data-testid="edit-problem-contest-note"
                      className="flex flex-wrap items-center gap-2 border-b border-rule bg-surface px-4 py-3"
                    >
                      <Badge>공모전 문제</Badge>
                      <Badge tone={contest.accepts_entries ? "verified" : "attention"}>
                        {contest.accepts_entries ? "공모전에 낼 수 있음" : "공모전 마감"}
                      </Badge>
                    </div>
                  ) : null}
                  <form id="edit-problem-form" onSubmit={handleSubmit} className="flex flex-col gap-5 p-4">
                    <div className="flex flex-col gap-1.5">
                      <label htmlFor="problem-title">
                        <FieldLabel>제목</FieldLabel>
                      </label>
                      <input
                        id="problem-title"
                        data-testid="edit-problem-title-input"
                        value={title}
                        onChange={(event) => setTitle(event.target.value)}
                        required
                        disabled={isArchived || followsContest}
                        className={INPUT_CLASS}
                      />
                    </div>

                    {/* 참여자 화면과 같은 순서 — 수업용 안내가 설명 위다. */}
                    {followsContest ? (
                      <div className="flex flex-col gap-1.5">
                        <FieldLabel>수업용 안내</FieldLabel>
                        {isArchived ? (
                          <div data-testid="edit-problem-instructor-note-readonly" className="border border-rule bg-paper px-4 py-3">
                            {instructorNote.trim() === "" ? (
                              <p className="text-[13px] text-ink/45">—</p>
                            ) : (
                              <MarkdownView markdown={instructorNote} fileBaseName={title} />
                            )}
                          </div>
                        ) : (
                          <MarkdownEditor
                            id="problem-instructor-note"
                            label="수업용 안내"
                            testId="edit-problem-instructor-note-input"
                            value={instructorNote}
                            onChange={setInstructorNote}
                          />
                        )}
                      </div>
                    ) : null}

                    <div className="flex flex-col gap-1.5">
                      <FieldLabel>설명</FieldLabel>
                      {isArchived || followsContest ? (
                        // 보관된 클래스는 읽기 전용이다(#438) — Toast UI 에디터에는 읽기 전용 모드가 없어
                        // 참여자가 보는 것과 같은 렌더러로 보여준다. 공모전 문제의 설명도 공모전을
                        // 따라가므로 같은 모양으로 읽기만 한다(#548).
                        <div data-testid="edit-problem-description-readonly" className="border border-rule bg-paper px-4 py-3">
                          {description.trim() === "" ? (
                            <p className="text-[13px] text-ink/45">—</p>
                          ) : (
                            <MarkdownView markdown={description} fileBaseName={title} />
                          )}
                        </div>
                      ) : (
                        <MarkdownEditor
                          id="problem-description"
                          label="설명"
                          testId="edit-problem-description-input"
                          value={description}
                          onChange={setDescription}
                        />
                      )}
                    </div>
                  </form>
                </Card>

                <Card>
                  <CardHeader title="체크리스트" />
                  <div
                    data-testid="syntax-check-toggle-row"
                    className="flex flex-wrap items-center justify-between gap-3 border-b border-rule bg-paper px-4 py-2.5"
                  >
                    <span className="flex items-center gap-2 text-[13px]">
                      <Badge>기본</Badge> 소스에 문법 오류가 없다
                    </span>
                    <label className="flex shrink-0 items-center gap-1.5 text-[12.5px]">
                      <input
                        type="checkbox"
                        data-testid="syntax-check-enabled-input"
                        checked={problem.syntax_check_enabled}
                        disabled={isArchived}
                        onChange={(event) => handleSyntaxCheckToggle(event.target.checked)}
                        className="accent-attention"
                      />
                      켜짐
                    </label>
                  </div>
                  {problem.checklist_items.length === 0 ? (
                    <EmptyState>
                      <span data-testid="checklist-empty-state">항목 없음</span>
                    </EmptyState>
                  ) : (
                    <ChecklistRows
                      items={problem.checklist_items.map((item) => ({
                        key: item.id,
                        label: item.label,
                        required: item.required,
                      }))}
                      listTestId="checklist-items"
                      rowTestId={(item) => `checklist-item-${item.key}`}
                      readOnly={isArchived}
                      lockedStructure={followsContest}
                      labelMode={{ kind: "commit", onCommit: (key, label) => handleItemLabelSave(key as number, label) }}
                      onReorder={handleReorder}
                      onRequiredChange={(key, required) => handleItemRequiredToggle(key as number, required)}
                      onDelete={(key) => handleItemDelete(key as number)}
                    />
                  )}

                  {followsContest ? (
                    <div className="border-t border-rule px-4 py-3" data-testid="checklist-follows-contest-note">
                      <Badge>공모전 요구사항</Badge>
                    </div>
                  ) : (
                    <form onSubmit={handleAddItem} className="flex items-center gap-2.5 border-t border-rule px-4 py-3">
                      <label htmlFor="new-item-label" className="sr-only">
                        새 항목
                      </label>
                      <input
                        id="new-item-label"
                        data-testid="new-checklist-item-label-input"
                        value={newItemLabel}
                        onChange={(event) => setNewItemLabel(event.target.value)}
                        required
                        disabled={isArchived}
                        placeholder="새 항목"
                        className={`${INPUT_CLASS} min-w-0 flex-1`}
                      />
                      <button
                        type="button"
                        data-testid="new-checklist-item-required-input"
                        aria-pressed={newItemRequired}
                        aria-label={`새 항목 ${newItemRequired ? "필수" : "선택"}`}
                        disabled={isArchived}
                        onClick={() => setNewItemRequired((prev) => !prev)}
                        className="shrink-0"
                      >
                        <Badge tone={newItemRequired ? "verified" : "neutral"}>{newItemRequired ? "필수" : "선택"}</Badge>
                      </button>
                      <button
                        type="submit"
                        data-testid="new-checklist-item-submit"
                        disabled={isArchived || newItemLabel.trim() === ""}
                        className={buttonClass("primary", "sm")}
                      >
                        추가
                      </button>
                    </form>
                  )}

                  {checklistMutation.error ? (
                    <div className="border-t border-rule p-4">
                      <ErrorNote>
                        <span data-testid="checklist-error">{checklistMutation.error}</span>
                      </ErrorNote>
                    </div>
                  ) : null}
                </Card>
              </>
            }
            side={
              <>
                <Card>
                  <CardHeader title="상태" />
                  <div className="flex flex-col gap-3 p-4">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <Badge tone={statusTone}>{STATUS_LABEL[problem.status]}</Badge>
                      {/* 서버가 준 전이 표(#440, `problem.available_transitions`)가 버튼을 그린다 — 화면은
                          상태별로 다시 계산하지 않는다. 그래프가 상태마다 나가는 간선을 하나만 두므로 첫
                          원소만 본다. */}
                      {transition?.blocked_reason ? (
                        <span
                          data-testid={`problem-transition-blocked-${transition.name}`}
                          className="text-[12.5px] text-ink/50"
                        >
                          {transitionBlockedReasonText(transition.blocked_reason)}
                        </span>
                      ) : transition?.name === "open" ? (
                        <button type="button" data-testid="open-problem-button" onClick={handleOpen} className={buttonClass("primary", "sm")}>
                          문제 열기
                        </button>
                      ) : transition?.name === "hide" ? (
                        <button
                          type="button"
                          data-testid="hide-problem-button"
                          onClick={() => setConfirmingHide(true)}
                          className={buttonClass("danger", "sm")}
                        >
                          숨기기
                        </button>
                      ) : transition?.name === "reopen" ? (
                        <button type="button" data-testid="reopen-problem-button" onClick={handleReopen} className={buttonClass("primary", "sm")}>
                          다시 열기
                        </button>
                      ) : null}
                    </div>
                    {confirmingHide ? (
                      // 숨기기 전 한 번 더 확인한다(#405 AC "결과를 알고 숨기기 위해서다").
                      <Note tone="attention">
                        <div className="flex flex-col gap-2.5">
                          <span data-testid="hide-problem-confirm-notice">
                            숨기면 참여자 목록에서 빠지고 새로 낼 수 없습니다. 이미 낸 참여자는 자기 시도와 판정을 계속 볼 수 있습니다.
                          </span>
                          <div className="flex gap-2">
                            <button type="button" data-testid="hide-problem-confirm" onClick={handleHide} className={buttonClass("danger", "sm")}>
                              숨기기
                            </button>
                            <button
                              type="button"
                              data-testid="hide-problem-cancel"
                              onClick={() => {
                                setConfirmingHide(false);
                                hideMutation.setError(null);
                              }}
                              className={buttonClass("secondary", "sm")}
                            >
                              취소
                            </button>
                          </div>
                        </div>
                      </Note>
                    ) : null}
                    {openMutation.error ? (
                      <ErrorNote>
                        <span data-testid="open-problem-error">{openMutation.error}</span>
                      </ErrorNote>
                    ) : null}
                    {hideMutation.error ? (
                      <ErrorNote>
                        <span data-testid="hide-problem-error">{hideMutation.error}</span>
                      </ErrorNote>
                    ) : null}
                    {reopenMutation.error ? (
                      <ErrorNote>
                        <span data-testid="reopen-problem-error">{reopenMutation.error}</span>
                      </ErrorNote>
                    ) : null}
                  </div>
                </Card>

                <ProblemSettingsForm
                  testIdPrefix="edit-problem"
                  submissionFormats={submissionFormats}
                  onToggleSubmissionFormat={toggleSubmissionFormat}
                  model={model}
                  onModelChange={setModel}
                  modelsState={modelsState}
                  modelRejection={
                    problem.scoring_model_rejected
                      ? {
                          retrying: retryModelMutation.pending,
                          error: retryModelMutation.error,
                          onRetry: handleRetryModel,
                        }
                      : undefined
                  }
                  reasoningEffort={reasoningEffort}
                  onReasoningEffortChange={setReasoningEffort}
                  defaultModelIsReasoning={
                    classState.status === "ready" ? classState.classroom.default_model_is_reasoning : false
                  }
                  reasoningSwitch={
                    classState.status === "ready" &&
                    classState.classroom.scoring_connection_kind === "compatible_server"
                      ? { checked: modelIsReasoning, onChange: setModelIsReasoning }
                      : undefined
                  }
                  classDefaults={
                    classState.status === "ready"
                      ? {
                          model: classState.classroom.default_model,
                          reasoningEffort: classState.classroom.default_reasoning_effort,
                        }
                      : null
                  }
                  costState={costState}
                  gradingGuideline={gradingGuideline}
                  disabled={isArchived}
                  onGradingGuidelineChange={setGradingGuideline}
                />

                <ProblemSideActions
                  classId={classId}
                  problemId={problemId}
                  problem={problem}
                  isArchived={isArchived}
                  reload={reload}
                />
              </>
            }
          />
        </div>

        <div
          data-testid="edit-problem-preview-panel"
          className={tab === "preview" ? "flex w-full flex-col gap-4" : "hidden"}
        >
          {problem.status !== "open" && !problem.checklist_items.some((item) => item.required) ? (
            <Note tone="attention">
              <span data-testid="edit-problem-preview-not-ready-notice">필수 항목이 없어 아직 열 수 없습니다.</span>
            </Note>
          ) : null}
          <div className="border border-rule bg-paper p-6">
            <ProblemParticipantView
              interactive={false}
              headingLevel="h2"
              eyebrow={previewEyebrow}
              title={title.trim() === "" ? "(제목 없음)" : title}
              description={description}
              instructorNote={followsContest ? instructorNote : ""}
              checklistItems={problem.checklist_items}
              syntaxCheckEnabled={problem.syntax_check_enabled}
              gradingStrictness={gradingGuideline.grading_strictness}
              gradingGuidelineCustomText={gradingGuideline.grading_guideline_text}
              submissionFormats={submissionFormats}
              submissions={[]}
            />
          </div>
        </div>
      </div>
    </PageShell>
  );
}
