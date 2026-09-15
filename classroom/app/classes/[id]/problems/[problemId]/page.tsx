"use client";

// 문제 편집 (#282/#283/#285). 제목·설명·제출 형식·채점 모델에 이어
// 체크리스트(필수·선택 항목과 순서)를 여기서 관리하고, 초안을 연다.
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
  PageHeader,
  PageShell,
  buttonClass,
} from "@/app/components/ui";
import {
  GradingGuidelineEditor,
  isGradingGuidelineValid,
  type GradingGuidelineValue,
} from "@/app/components/GradingGuidelineEditor";
import { MarkdownEditor } from "@/app/components/MarkdownEditor";
import { ProblemParticipantView } from "@/app/components/ProblemParticipantView";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import { BackendError } from "@/lib/backend/client";
import { selectCopyTargets } from "@/lib/classes/copy-targets";
import { useClass } from "@/lib/classes/use-class";
import { useMyClasses } from "@/lib/classes/use-my-classes";
import { publishProblemAsTemplate, takedownProblemTemplate } from "@/lib/problem-templates/api";
import {
  copyProblem,
  createChecklistItem,
  deleteChecklistItem,
  hideProblem,
  openProblem,
  reopenProblem,
  reorderChecklistItems,
  updateChecklistItem,
  updateProblem,
  type SubmissionFormat,
} from "@/lib/problems/api";
import { useProblem } from "@/lib/problems/use-problem";
import { useClassroomTabTitle } from "@/lib/rendering/use-tab-title";
import { isSelectedModelReasoning, REASONING_EFFORT_OPTIONS } from "@/lib/scoring/reasoning";
import { useScoringModels } from "@/lib/scoring/use-scoring-models";

// 화면이 실제로 그리는 값만 담는다(#333, 클래스 설정 화면의
// `PublishedTemplateState`와 같은 이유) — 전체 템플릿 응답에서 이 둘만 쓴다.
type PublishedTemplateState = { share_code: string; taken_down: boolean };

const STATUS_LABEL: Record<string, string> = {
  draft: "초안",
  open: "열림",
  hidden: "숨김",
};

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
  const myClassesState = useMyClasses();

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [submissionFormats, setSubmissionFormats] = useState<SubmissionFormat[]>(["source"]);
  const [model, setModel] = useState("");
  const [reasoningEffort, setReasoningEffort] = useState("");
  // 채점 지침(#386) — 불러온 문제 값으로 아래 effect가 채운다.
  const [gradingGuideline, setGradingGuideline] = useState<GradingGuidelineValue>({
    grading_strictness: "normal",
    grading_guideline_text: "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [newItemLabel, setNewItemLabel] = useState("");
  const [newItemRequired, setNewItemRequired] = useState(true);
  const [checklistError, setChecklistError] = useState<string | null>(null);
  const [openError, setOpenError] = useState<string | null>(null);
  // 「숨기기」는 한 번 더 확인을 받는다(#405 AC) — 이미 낸 참여자가 어떻게
  // 되는지 알고 누르게 하기 위해서다. 다른 버튼들과 달리 클릭 한 번으로
  // 바로 실행하지 않는다.
  const [confirmingHide, setConfirmingHide] = useState(false);
  const [hideError, setHideError] = useState<string | null>(null);
  const [reopenError, setReopenError] = useState<string | null>(null);

  const [targetClassId, setTargetClassId] = useState("");
  const [copying, setCopying] = useState(false);
  const [copyError, setCopyError] = useState<string | null>(null);

  const [publisherDisplayName, setPublisherDisplayName] = useState("");
  const [publishing, setPublishing] = useState(false);
  const [publishError, setPublishError] = useState<string | null>(null);
  const [publishedTemplate, setPublishedTemplate] = useState<PublishedTemplateState | null>(null);

  const [takingDown, setTakingDown] = useState(false);
  const [takedownError, setTakedownError] = useState<string | null>(null);

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
      setSubmissionFormats(state.problem.submission_formats);
      setModel(state.problem.model);
      setReasoningEffort(state.problem.reasoning_effort);
      setGradingGuideline({
        grading_strictness: state.problem.grading_strictness,
        grading_guideline_text: state.problem.grading_guideline_text,
      });
      // 새로고침해도 공개 상태(공유 링크·「내리기」)가 보이도록 서버가
      // 내려준 「지금 살아 있는 템플릿」으로 맞춘다(#333) — 예전에는 이
      // 상태가 화면 안에만 있어 새로고침하면 사라지고 폼이 다시 떠 같은
      // 문제가 두 번 공개됐다.
      setPublishedTemplate(
        state.problem.published_template
          ? { share_code: state.problem.published_template.share_code, taken_down: false }
          : null,
      );
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

  function toggleSubmissionFormat(format: SubmissionFormat, checked: boolean) {
    setSubmissionFormats((prev) =>
      checked ? [...prev, format].filter((f, i, arr) => arr.indexOf(f) === i) : prev.filter((f) => f !== format),
    );
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!isGradingGuidelineValid(gradingGuideline)) return;
    setSaving(true);
    setError(null);
    try {
      await updateProblem(classId, problemId, {
        title: title.trim(),
        description,
        submission_formats: submissionFormats,
        model,
        reasoning_effort: reasoningEffort,
        grading_strictness: gradingGuideline.grading_strictness,
        grading_guideline_text: gradingGuideline.grading_guideline_text,
      });
      reload();
      router.push(`/classes/${classId}`);
    } catch {
      setError("문제를 저장하지 못했습니다. 잠시 후 다시 시도해주세요.");
    } finally {
      setSaving(false);
    }
  }

  async function handleAddItem(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setChecklistError(null);
    try {
      await createChecklistItem(classId, problemId, {
        label: newItemLabel.trim(),
        required: newItemRequired,
      });
      setNewItemLabel("");
      setNewItemRequired(true);
      reload();
    } catch {
      setChecklistError("항목을 추가하지 못했습니다. 잠시 후 다시 시도해주세요.");
    }
  }

  async function handleItemLabelSave(itemId: number, label: string) {
    setChecklistError(null);
    try {
      await updateChecklistItem(classId, problemId, itemId, { label });
      reload();
    } catch {
      setChecklistError("항목을 저장하지 못했습니다. 잠시 후 다시 시도해주세요.");
    }
  }

  async function handleItemRequiredToggle(itemId: number, required: boolean) {
    setChecklistError(null);
    try {
      await updateChecklistItem(classId, problemId, itemId, { required });
      reload();
    } catch {
      setChecklistError("항목을 저장하지 못했습니다. 잠시 후 다시 시도해주세요.");
    }
  }

  async function handleItemDelete(itemId: number) {
    setChecklistError(null);
    try {
      await deleteChecklistItem(classId, problemId, itemId);
      reload();
    } catch {
      setChecklistError("항목을 지우지 못했습니다. 잠시 후 다시 시도해주세요.");
    }
  }

  async function handleSyntaxCheckToggle(enabled: boolean) {
    setChecklistError(null);
    try {
      await updateProblem(classId, problemId, { syntax_check_enabled: enabled });
      reload();
    } catch {
      setChecklistError("설정을 저장하지 못했습니다. 잠시 후 다시 시도해주세요.");
    }
  }

  async function handleItemMove(itemId: number, direction: "up" | "down") {
    const items = problem.checklist_items;
    const index = items.findIndex((i) => i.id === itemId);
    const swapWith = direction === "up" ? index - 1 : index + 1;
    if (index < 0 || swapWith < 0 || swapWith >= items.length) return;

    const reordered = [...items];
    [reordered[index], reordered[swapWith]] = [reordered[swapWith], reordered[index]];

    setChecklistError(null);
    try {
      await reorderChecklistItems(
        classId,
        problemId,
        reordered.map((i) => i.id),
      );
      reload();
    } catch {
      setChecklistError("순서를 바꾸지 못했습니다. 다시 시도해주세요.");
    }
  }

  async function handleCopy(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCopyError(null);
    setCopying(true);
    try {
      const copy = await copyProblem(classId, problemId, Number(targetClassId));
      router.push(`/classes/${copy.classroom_id}/problems/${copy.id}`);
    } catch (err) {
      setCopyError(
        err instanceof BackendError ? err.message : "문제를 복사하지 못했습니다. 잠시 후 다시 시도해주세요.",
      );
    } finally {
      setCopying(false);
    }
  }

  async function handlePublish(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPublishError(null);
    setPublishing(true);
    try {
      const template = await publishProblemAsTemplate(classId, problemId, publisherDisplayName.trim());
      setPublishedTemplate({ share_code: template.share_code, taken_down: template.taken_down });
    } catch {
      setPublishError("템플릿으로 공개하지 못했습니다. 잠시 후 다시 시도해주세요.");
    } finally {
      setPublishing(false);
    }
  }

  async function handleTakedown() {
    if (!publishedTemplate) return;
    setTakedownError(null);
    setTakingDown(true);
    try {
      const template = await takedownProblemTemplate(publishedTemplate.share_code);
      setPublishedTemplate({ share_code: template.share_code, taken_down: template.taken_down });
    } catch {
      setTakedownError("내리지 못했습니다. 잠시 후 다시 시도해주세요.");
    } finally {
      setTakingDown(false);
    }
  }

  async function handleOpen() {
    setOpenError(null);
    try {
      await openProblem(classId, problemId);
      reload();
    } catch (err) {
      if (err instanceof BackendError) {
        setOpenError(err.message);
      } else {
        setOpenError("문제를 열지 못했습니다. 잠시 후 다시 시도해주세요.");
      }
    }
  }

  async function handleHide() {
    setHideError(null);
    try {
      await hideProblem(classId, problemId);
      setConfirmingHide(false);
      reload();
    } catch (err) {
      if (err instanceof BackendError) {
        setHideError(err.message);
      } else {
        setHideError("문제를 숨기지 못했습니다. 잠시 후 다시 시도해주세요.");
      }
    }
  }

  async function handleReopen() {
    setReopenError(null);
    try {
      await reopenProblem(classId, problemId);
      reload();
    } catch (err) {
      if (err instanceof BackendError) {
        setReopenError(err.message);
      } else {
        setReopenError("문제를 다시 열지 못했습니다. 잠시 후 다시 시도해주세요.");
      }
    }
  }

  return (
    <PageShell>
      <PageHeader
        eyebrow="클래스 · 문제"
        title="문제 편집"
        titleTestId="edit-problem-heading"
        actions={
          <>
            <Badge
              tone={
                problem.status === "open"
                  ? "verified"
                  : problem.status === "hidden"
                    ? "attention"
                    : "neutral"
              }
            >
              {STATUS_LABEL[problem.status]}
            </Badge>
            <Link
              href={`/classes/${classId}/problems/${problemId}/submissions`}
              data-testid="problem-submissions-link"
              className={buttonClass()}
            >
              제출 현황 보기
            </Link>
            {problem.status === "draft" ? (
              <button
                type="button"
                data-testid="open-problem-button"
                onClick={handleOpen}
                className={buttonClass("primary")}
              >
                문제 열기
              </button>
            ) : problem.status === "open" ? (
              <button
                type="button"
                data-testid="hide-problem-button"
                onClick={() => setConfirmingHide(true)}
                className={buttonClass("danger")}
              >
                숨기기
              </button>
            ) : (
              <button
                type="button"
                data-testid="reopen-problem-button"
                onClick={handleReopen}
                className={buttonClass("primary")}
              >
                다시 열기
              </button>
            )}
          </>
        }
      />

      <div className="flex flex-col gap-5">
        <div
          role="tablist"
          aria-label="문제 편집 화면"
          className="flex items-end gap-0.5 border-b border-rule"
        >
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

        <div
          data-testid="edit-problem-write-panel"
          className={tab === "write" ? "flex flex-col gap-5" : "hidden"}
        >
        {problem.status === "open" ? (
          // 이미 열린 문제는 참여자가 이미 시도했을 수 있다. 체크리스트를 고쳐도
          // 지난 점수는 남고 달성률만 새 기준으로 다시 셈된다는 것을 미리
          // 알린다(CONTEXT.md 「Problem」).
          <Note tone="attention">
            <span data-testid="edit-problem-open-notice">
              이미 열린 문제입니다. 체크리스트를 바꿔도 지난 시도의 점수는 그대로 남고 달성률만 새
              기준으로 다시 계산됩니다.
            </span>
          </Note>
        ) : null}
        {problem.status === "hidden" ? (
          // 숨긴 문제는 낸 적 있는 참여자에게 읽기 전용으로만 남는다(#405,
          // CONTEXT.md 「Problem」) — 강사가 편집·미리보기·제출 현황은
          // 지금처럼 그대로 쓸 수 있다는 것을 알린다.
          <Note tone="attention">
            <span data-testid="edit-problem-hidden-notice">
              숨긴 문제입니다. 참여자 목록에서 빠졌고 새로 낼 수 없지만, 이미 낸 참여자는 자기
              시도와 판정을 계속 봅니다.
            </span>
          </Note>
        ) : null}
        {openError ? (
          <ErrorNote>
            <span data-testid="open-problem-error">{openError}</span>
          </ErrorNote>
        ) : null}
        {confirmingHide ? (
          // 숨기기 전 한 번 더 확인한다(#405 AC "결과를 알고 숨기기 위해서다").
          <Note tone="attention">
            <div className="flex flex-col gap-2.5">
              <span data-testid="hide-problem-confirm-notice">
                숨기면 참여자 목록에서 빠지고 새로 낼 수 없습니다. 이미 낸 참여자는 자기 시도와
                판정을 계속 볼 수 있습니다. 숨기시겠습니까?
              </span>
              <div className="flex gap-2">
                <button
                  type="button"
                  data-testid="hide-problem-confirm"
                  onClick={handleHide}
                  className={buttonClass("danger", "sm")}
                >
                  숨기기
                </button>
                <button
                  type="button"
                  data-testid="hide-problem-cancel"
                  onClick={() => {
                    setConfirmingHide(false);
                    setHideError(null);
                  }}
                  className={buttonClass("secondary", "sm")}
                >
                  취소
                </button>
              </div>
            </div>
          </Note>
        ) : null}
        {hideError ? (
          <ErrorNote>
            <span data-testid="hide-problem-error">{hideError}</span>
          </ErrorNote>
        ) : null}
        {reopenError ? (
          <ErrorNote>
            <span data-testid="reopen-problem-error">{reopenError}</span>
          </ErrorNote>
        ) : null}

        {/* 본문 폭은 다른 화면과 같다(1200px 틀). 화면이 충분히 넓으면(1840px~) 채점 모델·
            채점 지침·다른 클래스로 복사·템플릿으로 공개 카드를 **틀 바깥** 오른쪽 여백에
            300px 열로 걸고 스크롤을 따라오게 한다 — 그러면 설명 에디터가 틀 폭을 다 쓴다.
            그보다 좁으면 한 열로 쌓여 그 카드들이 체크리스트 아래로 내려간다.
            (2026-09-15: 1024px 부터 380px 열이 틀 안을 차지해 에디터가 약 750px 로 좁았고,
            틀을 1600px 로 넓혀 보았으나 이 화면만 폭이 달라 어색했다.) */}
        <div className="relative flex flex-col gap-5">
          <div className="flex min-w-0 flex-1 flex-col gap-5">
            <Card>
              <CardHeader title="문제" />
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
                    className={INPUT_CLASS}
                  />
                </div>

                <div className="flex flex-col gap-1.5">
                  <FieldLabel>설명</FieldLabel>
                  <MarkdownEditor
                    id="problem-description"
                    label="설명"
                    testId="edit-problem-description-input"
                    value={description}
                    onChange={setDescription}
                  />
                </div>

                <fieldset className="flex flex-col gap-1.5">
                  <legend>
                    <FieldLabel>제출 형식</FieldLabel>
                  </legend>
                  <div className="flex flex-col gap-2 pt-1">
                    <label className="flex items-center gap-2.5 text-[13.5px]">
                      <input
                        type="checkbox"
                        checked={submissionFormats.includes("source")}
                        onChange={(event) => toggleSubmissionFormat("source", event.target.checked)}
                        data-testid="edit-problem-format-source"
                        className="accent-ink"
                      />
                      zip 파일
                    </label>
                    <label className="flex items-center gap-2.5 text-[13.5px]">
                      <input
                        type="checkbox"
                        checked={submissionFormats.includes("repository")}
                        onChange={(event) => toggleSubmissionFormat("repository", event.target.checked)}
                        data-testid="edit-problem-format-repository"
                        className="accent-ink"
                      />
                      GitHub 저장소
                    </label>
                  </div>
                  <span className="text-[11.5px] leading-relaxed text-ink/45">
                    둘 다 고르면 참여자는 낼 때마다 그중 하나를 고릅니다. 형식을 꺼도 그
                    형식으로 이미 낸 시도와 점수는 그대로 남습니다.
                  </span>
                  {submissionFormats.length === 0 ? (
                    <span
                      data-testid="edit-problem-format-empty-notice"
                      className="text-[11.5px] text-attention"
                    >
                      하나 이상 골라야 합니다.
                    </span>
                  ) : null}
                </fieldset>

              </form>
            </Card>

            <Card>
              <CardHeader title="체크리스트" hint="필수를 전부 충족하면 「통과」 · 바뀔 때마다 바로 저장됩니다" />
              <div
                data-testid="syntax-check-toggle-row"
                className="flex flex-wrap items-center justify-between gap-3 border-b border-rule bg-surface px-4 py-3"
              >
                <div className="flex flex-col gap-0.5">
                  <span className="flex items-center gap-1.5 text-[13px] font-medium">
                    <Badge>기본</Badge> 소스에 문법 오류가 없다
                  </span>
                  <span className="text-[12px] text-ink/45">
                    의사코드처럼 실행되는 코드가 아닌 문제라면 끄세요.
                  </span>
                </div>
                <label className="flex shrink-0 items-center gap-1.5 text-[12.5px]">
                  <input
                    type="checkbox"
                    data-testid="syntax-check-enabled-input"
                    checked={problem.syntax_check_enabled}
                    onChange={(event) => handleSyntaxCheckToggle(event.target.checked)}
                    className="accent-attention"
                  />
                  켜짐
                </label>
              </div>
              {problem.checklist_items.length === 0 ? (
                <EmptyState>
                  <span data-testid="checklist-empty-state">
                    아직 항목이 없습니다. 아래에서 새 항목을 추가해 보세요.
                  </span>
                </EmptyState>
              ) : (
                <ul data-testid="checklist-items" className="divide-y divide-rule">
                  {problem.checklist_items.map((item, index) => (
                    <li
                      key={item.id}
                      data-testid={`checklist-item-${item.id}`}
                      className="flex flex-wrap items-center gap-2 px-4 py-3"
                    >
                      <span className="w-4 shrink-0 font-mono text-[11.5px] text-ink/30">{index + 1}</span>
                      <input
                        data-testid={`checklist-item-${item.id}-label-input`}
                        defaultValue={item.label}
                        onBlur={(event) => {
                          if (event.target.value.trim() !== "" && event.target.value !== item.label) {
                            handleItemLabelSave(item.id, event.target.value.trim());
                          }
                        }}
                        className={`${INPUT_CLASS} min-w-[200px] flex-1`}
                      />
                      <label className="flex shrink-0 items-center gap-1.5 text-[12.5px]">
                        <input
                          type="checkbox"
                          data-testid={`checklist-item-${item.id}-required-input`}
                          checked={item.required}
                          onChange={(event) => handleItemRequiredToggle(item.id, event.target.checked)}
                          className="accent-attention"
                        />
                        필수
                      </label>
                      <span className="flex shrink-0 gap-1">
                        <button
                          type="button"
                          data-testid={`checklist-item-${item.id}-move-up`}
                          disabled={index === 0}
                          onClick={() => handleItemMove(item.id, "up")}
                          className={buttonClass("secondary", "sm")}
                        >
                          위로
                        </button>
                        <button
                          type="button"
                          data-testid={`checklist-item-${item.id}-move-down`}
                          disabled={index === problem.checklist_items.length - 1}
                          onClick={() => handleItemMove(item.id, "down")}
                          className={buttonClass("secondary", "sm")}
                        >
                          아래로
                        </button>
                        <button
                          type="button"
                          data-testid={`checklist-item-${item.id}-delete`}
                          onClick={() => handleItemDelete(item.id)}
                          className={buttonClass("danger", "sm")}
                        >
                          삭제
                        </button>
                      </span>
                    </li>
                  ))}
                </ul>
              )}

              <form onSubmit={handleAddItem} className="flex flex-wrap items-center gap-2 border-t border-rule p-4">
                <label htmlFor="new-item-label" className="sr-only">
                  새 항목
                </label>
                <input
                  id="new-item-label"
                  data-testid="new-checklist-item-label-input"
                  value={newItemLabel}
                  onChange={(event) => setNewItemLabel(event.target.value)}
                  required
                  placeholder="새 항목 — 채점이 이 문장으로 판정합니다"
                  className={`${INPUT_CLASS} min-w-[220px] flex-1`}
                />
                <label className="flex shrink-0 items-center gap-1.5 text-[12.5px]">
                  <input
                    type="checkbox"
                    data-testid="new-checklist-item-required-input"
                    checked={newItemRequired}
                    onChange={(event) => setNewItemRequired(event.target.checked)}
                    className="accent-attention"
                  />
                  필수
                </label>
                <button
                  type="submit"
                  data-testid="new-checklist-item-submit"
                  disabled={newItemLabel.trim() === ""}
                  className={buttonClass("primary", "sm")}
                >
                  추가
                </button>
              </form>

              {checklistError ? (
                <div className="border-t border-rule p-4">
                  <ErrorNote>
                    <span data-testid="checklist-error">{checklistError}</span>
                  </ErrorNote>
                </div>
              ) : null}
            </Card>
          </div>

          {/* 1840px~: 화면에 고정해 늘 보인다. 틀(1200px)의 본문 오른쪽 끝(50%+576px)에서
              24px 떨어진 자리부터 300px — 본문 줄 안의 sticky 는 카드 넷의 높이가 줄 높이와
              비슷해 따라올 여지가 없었다. 화면보다 길면 열 안에서 스크롤한다. */}
          <div>
          <div
            data-testid="edit-problem-side-rail"
            className="flex w-full flex-col gap-5 min-[1840px]:fixed min-[1840px]:top-24 min-[1840px]:left-[calc(50%+600px)] min-[1840px]:max-h-[calc(100vh-7.5rem)] min-[1840px]:w-[300px] min-[1840px]:overflow-y-auto"
          >
            <Card>
              <CardHeader title="채점 모델" />
              <div className="flex flex-col gap-2.5 p-4">
                <label htmlFor="problem-model" className="sr-only">
                  채점 모델
                </label>
                {modelsState.status === "ready" ? (
                  <>
                    {modelsState.source === "fallback" ? (
                      <Note>
                        <span data-testid="edit-problem-model-unavailable-note">
                          {modelsState.unavailableReason === "no_api_key"
                            ? "키를 넣으면 이 키로 쓸 수 있는 모델을 보여드립니다 — 지금은 기본 목록입니다."
                            : "지금은 모델 목록을 확인할 수 없어 기본 목록을 보여드립니다."}
                        </span>
                      </Note>
                    ) : null}
                    <select
                      id="problem-model"
                      data-testid="edit-problem-model-select"
                      value={model}
                      onChange={(event) => setModel(event.target.value)}
                      className={INPUT_CLASS}
                    >
                      <option value="" data-testid="edit-problem-model-option-inherit">
                        클래스 기본값을 따릅니다
                      </option>
                      {modelsState.models.map((option) => (
                        <option
                          key={option.id}
                          value={option.id}
                          data-testid={`edit-problem-model-option-${option.id}`}
                        >
                          {option.label} · 컨텍스트{" "}
                          {option.context_window
                            ? `${option.context_window.toLocaleString("ko-KR")} 토큰`
                            : "크기 미확인"}
                        </option>
                      ))}
                    </select>
                  </>
                ) : (
                  <p data-testid="edit-problem-model-loading" className="text-[13px] text-ink/45">
                    모델 목록을 불러오는 중...
                  </p>
                )}
                {model === "" ? (
                  <p data-testid="edit-problem-model-effective" className="text-[12.5px] text-ink/60">
                    실제로 쓰일 모델: <span className="font-mono">{problem.effective_model}</span>
                  </p>
                ) : null}
                <span className="text-[11.5px] leading-relaxed text-ink/45">
                  문제 설명이 길면 컨텍스트가 작은 모델은 뒷부분이 잘린 채 채점됩니다 — 그래서
                  문제마다 다른 모델을 고를 수 있습니다.
                </span>
                {modelsState.status === "ready" &&
                isSelectedModelReasoning(
                  model,
                  modelsState.models,
                  classState.status === "ready" ? classState.classroom.default_model_is_reasoning : false,
                ) ? (
                  <div className="flex flex-col gap-1.5 border-t border-rule pt-3">
                    <label htmlFor="edit-problem-reasoning-effort">
                      <FieldLabel>추론 강도</FieldLabel>
                    </label>
                    <select
                      id="edit-problem-reasoning-effort"
                      data-testid="edit-problem-reasoning-effort-select"
                      value={reasoningEffort}
                      onChange={(event) => setReasoningEffort(event.target.value)}
                      className={`${INPUT_CLASS} max-w-[200px]`}
                    >
                      <option value="" data-testid="edit-problem-reasoning-effort-option-inherit">
                        클래스 기본값을 따릅니다
                      </option>
                      {REASONING_EFFORT_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                    {reasoningEffort === "" ? (
                      <p
                        data-testid="edit-problem-reasoning-effort-effective"
                        className="text-[12.5px] text-ink/60"
                      >
                        실제로 적용될 추론 강도: {problem.effective_reasoning_effort}
                      </p>
                    ) : null}
                    <span className="text-[11.5px] leading-relaxed text-ink/45">
                      높을수록 느리고 채점 예산을 더 씁니다.
                    </span>
                  </div>
                ) : null}
              </div>
            </Card>

            <GradingGuidelineEditor
              value={gradingGuideline}
              onChange={setGradingGuideline}
              testIdPrefix="edit-problem"
            />

            <Card>
              <CardHeader title="다른 클래스로 복사" />
              <div className="flex flex-col gap-2.5 p-4">
                {myClassesState.status === "ready" ? (
                  (() => {
                    const otherClasses = myClassesState.classes.filter((c) => c.id !== classId);
                    const selection = selectCopyTargets(otherClasses);
                    if (selection.kind === "no-classes") {
                      return (
                        <p data-testid="copy-problem-no-target" className="text-[13px] text-ink/45">
                          복사할 다른 클래스가 없습니다.
                        </p>
                      );
                    }
                    if (selection.kind === "all-archived") {
                      return (
                        <p data-testid="copy-problem-all-archived" className="text-[13px] text-ink/45">
                          다른 클래스가 모두 보관되어 있어 복사할 수 없습니다.
                        </p>
                      );
                    }
                    return (
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
                          disabled={copying || targetClassId === ""}
                          className={buttonClass("secondary")}
                        >
                          {copying ? "복사하는 중..." : "복사"}
                        </button>
                      </form>
                    );
                  })()
                ) : (
                  <p data-testid="copy-problem-classes-loading" className="text-[13px] text-ink/45">
                    클래스 목록을 불러오는 중...
                  </p>
                )}
                {copyError ? (
                  <ErrorNote>
                    <span data-testid="copy-problem-error">{copyError}</span>
                  </ErrorNote>
                ) : null}
                <span className="text-[11.5px] leading-relaxed text-ink/45">
                  체크리스트와 채점 설정이 함께 옵니다. 제출물·점수는 따라오지 않고, 복사본은
                  대상 클래스에서 초안으로 들어옵니다.
                </span>
              </div>
            </Card>

            <Card>
              <CardHeader title="템플릿으로 공개" hint="다른 강사에게 공유" />
              <div className="flex flex-col gap-2.5 p-4">
                {publishedTemplate ? (
                  <div className="flex flex-col gap-2">
                    {publishedTemplate.taken_down ? (
                      <p data-testid="publish-template-taken-down" className="flex items-center gap-2.5 text-[13px]">
                        <Badge tone="neutral">내려짐</Badge>
                        <span className="text-ink/60">더 이상 다른 강사가 가져갈 수 없습니다.</span>
                      </p>
                    ) : (
                      <>
                        <p data-testid="publish-template-done" className="text-[13px] leading-relaxed">
                          공개되었습니다. 아래 주소를 다른 강사에게 전달하세요.
                        </p>
                        <div className="flex flex-wrap items-center gap-2">
                          <Link
                            href={`/templates/${publishedTemplate.share_code}`}
                            data-testid="publish-template-share-link"
                            className="min-w-0 flex-1 break-all border border-rule bg-surface px-3 py-2 font-mono text-[12.5px] hover:underline"
                          >
                            /templates/{publishedTemplate.share_code}
                          </Link>
                          <button
                            type="button"
                            data-testid="publish-template-takedown"
                            onClick={handleTakedown}
                            disabled={takingDown}
                            className={buttonClass("danger", "sm")}
                          >
                            {takingDown ? "내리는 중..." : "내리기"}
                          </button>
                        </div>
                      </>
                    )}
                    {takedownError ? (
                      <ErrorNote>
                        <span data-testid="publish-template-takedown-error">{takedownError}</span>
                      </ErrorNote>
                    ) : null}
                  </div>
                ) : (
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
                      placeholder="계정 이름과 달라도 됩니다"
                      className={INPUT_CLASS}
                    />
                    <button
                      type="submit"
                      data-testid="publish-template-submit"
                      disabled={publishing || publisherDisplayName.trim() === ""}
                      className={buttonClass("secondary")}
                    >
                      {publishing ? "공개하는 중..." : "템플릿으로 공개"}
                    </button>
                  </form>
                )}
                {publishError ? (
                  <ErrorNote>
                    <span data-testid="publish-template-error">{publishError}</span>
                  </ErrorNote>
                ) : null}
                <span className="text-[11.5px] leading-relaxed text-ink/45">
                  공개하는 순간 사본이 떠집니다 — 이후 이 문제를 고치거나 클래스를 지워도
                  템플릿은 그대로입니다. 채점 모델은 담기지 않습니다.
                </span>
              </div>
            </Card>
          </div>
          </div>
        </div>

        {/* 저장은 화면 맨 아래 하나다 — 새 문제 화면(「만들기」)과 같은 자리. 예전엔
            「문제」 카드 끝에 있어 체크리스트보다 위에 섰고, 그 버튼이 함께 저장하는
            채점 모델은 체크리스트 아래 오른쪽 카드라 모델만 바꾸고 나가면 조용히
            반영되지 않았다. 체크리스트는 여전히 항목마다 바로 저장된다(카드 머리에
            적어 둔다) — 이 버튼은 제목·설명·제출 형식·채점 모델을 저장한다. */}
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="submit"
            form="edit-problem-form"
            data-testid="edit-problem-submit"
            disabled={
              saving ||
              title.trim() === "" ||
              submissionFormats.length === 0 ||
              !isGradingGuidelineValid(gradingGuideline)
            }
            className={buttonClass("primary")}
          >
            {saving ? "저장하는 중..." : "저장"}
          </button>
        </div>

        {error ? (
          <ErrorNote>
            <span data-testid="edit-problem-error-message">{error}</span>
          </ErrorNote>
        ) : null}
        </div>

        <div
          data-testid="edit-problem-preview-panel"
          className={tab === "preview" ? "flex w-full flex-col gap-4" : "hidden"}
        >
          <div className="border border-rule bg-surface p-3 text-[12.5px] leading-relaxed text-ink/60">
            <b className="font-medium text-ink">참여자가 보는 화면 그대로입니다.</b> 아직 저장하지
            않은 내용도 지금 상태 그대로 비춥니다.
          </div>
          {problem.status !== "open" && !problem.checklist_items.some((item) => item.required) ? (
            <Note tone="attention">
              <span data-testid="edit-problem-preview-not-ready-notice">
                필수 체크리스트 항목이 하나도 없어 아직 열 수 없는 상태입니다 — 이대로 열면 무엇을
                「통과」로 볼지가 정해지지 않습니다.
              </span>
            </Note>
          ) : null}
          <div className="border border-rule bg-paper p-6">
            <ProblemParticipantView
              interactive={false}
              headingLevel="h2"
              eyebrow={previewEyebrow}
              title={title.trim() === "" ? "(제목 없음)" : title}
              description={description}
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
