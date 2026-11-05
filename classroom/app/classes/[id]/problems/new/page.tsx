"use client";

// 새 문제 (#282, #315, #327). 제목·설명·제출 형식·채점 모델과 함께 체크리스트 항목을 그
// 자리에서 적는다 — 만들기 요청 하나가 문제와 항목을 함께 만든다. 항목이
// 준비됐으면(필수 항목이 하나 이상) 그 자리에서 바로 열 수도 있다. 마감을
// 넣을 자리는 애초에 없다.
import { useParams, useRouter } from "next/navigation";
import { useRef, useState } from "react";
import type { FormEvent } from "react";

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
import { isGradingGuidelineValid, type GradingGuidelineValue } from "@/app/components/GradingGuidelineEditor";
import { ChecklistRows } from "@/app/components/ChecklistRows";
import { TwoColumnFrame } from "@/app/components/TwoColumnFrame";
import { MarkdownEditor } from "@/app/components/MarkdownEditor";
import { ProblemParticipantView } from "@/app/components/ProblemParticipantView";
import { ProblemDueCard } from "@/app/components/ProblemDueCard";
import { ProblemSettingsForm } from "@/app/components/ProblemSettingsForm";
import { ProblemImportSheet } from "@/app/components/ProblemImportSheet";
import { useClass } from "@/lib/classes/use-class";
import { checkPublicTextForBannedWords } from "@/lib/moderation/public-text-check";
import { GRADABILITY_FORM_NOTE, stashWarnings } from "@/lib/problems/gradability";
import { createProblem, type ProblemRow, type SubmissionFormat } from "@/lib/problems/api";
import {
  DUE_ORDER_MESSAGE,
  EMPTY_DUE_DRAFT,
  dueDraftToIso,
  dueOrderViolated,
  type DueDraft,
} from "@/lib/problems/due-dates";
import { useScoringCost } from "@/lib/scoring/use-scoring-cost";
import { useScoringModels } from "@/lib/scoring/use-scoring-models";

type DraftChecklistItem = {
  key: number;
  label: string;
  required: boolean;
};

export default function NewProblemPage() {
  const params = useParams<{ id: string }>();
  const classId = Number(params.id);
  // 미리보기 눈썹이 참여자 화면과 같이 클래스 이름을 말한다(#372 후속). 불러오는 중에는
  // 비워 둔다 — 「클래스」 같은 자리표시를 잠깐 보였다 바꾸면 깜빡임만 는다.
  const { state: classState } = useClass(classId);
  const costState = useScoringCost(classId);
  const previewEyebrow = classState.status === "ready" ? classState.classroom.name : "";
  const router = useRouter();

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  // 체크박스 둘(#373) — 최소 하나는 켜져 있어야 저장할 수 있다.
  const [submissionFormats, setSubmissionFormats] = useState<SubmissionFormat[]>(["source"]);
  // 빈 문자열이 「클래스 기본값을 따릅니다」다 — 편집 화면(#285)과 같은 값이다.
  const [model, setModel] = useState("");
  // 빈 문자열이 「클래스 기본값을 따릅니다」다 — `model`과 같은 관례(#402).
  const [reasoningEffort, setReasoningEffort] = useState("");
  // 「호환 서버」의 「추론 모델」 스위치(#602) — 이 문제 자신의 모델에만 뜻이 있다.
  const [modelIsReasoning, setModelIsReasoning] = useState(false);
  const { state: modelsState } = useScoringModels(classId);
  // 채점 지침(#386) — 기본은 「보통」, 백엔드 기본값과 같다.
  const [gradingGuideline, setGradingGuideline] = useState<GradingGuidelineValue>({
    grading_strictness: "normal",
    grading_guideline_text: "",
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 권장 기한·마감(#770) — 빈 상태가 기본 모습. 권장이 마감 뒤면 만들지 않고 두 칸을 붉게 둔다.
  const [recommendedDue, setRecommendedDue] = useState<DueDraft>(EMPTY_DUE_DRAFT);
  const [dueDraft, setDueDraft] = useState<DueDraft>(EMPTY_DUE_DRAFT);
  const [dueOrderRefused, setDueOrderRefused] = useState(false);
  // 「작성」/「미리보기」 탭(#325) — 참여자 화면 전체를 보여주는 쪽은 그
  // 자리에서 저장하지 않고 지금 상태를 그대로 비춘다(아래 렌더에서
  // `ProblemParticipantView`에 이 컴포넌트의 상태를 직접 넘긴다).
  const [tab, setTab] = useState<"write" | "preview">("write");

  // 「이미 있는 문제로 시작하기」(#326) — 대상 클래스는 묻지 않는다, 지금
  // 이 클래스(`classId`)로 곧장 들어온다. 시트가 스스로 가져오기까지 끝내고
  // 나면 이 화면(빈 초안 폼)은 더 볼 일이 없다 — 가져온 문제의 편집
  // 화면으로 곧장 보낸다.
  const [pickerOpen, setPickerOpen] = useState(false);
  // 「공모전에서 들여오기」(#548) — 템플릿과 같은 자리, 들여온 뒤 그 문제의 편집 화면으로 간다.

  function handleImported(problem: ProblemRow) {
    router.push(`/classes/${classId}/problems/${problem.id}`);
  }

  const nextKeyRef = useRef(0);
  const [items, setItems] = useState<DraftChecklistItem[]>([]);
  const [newItemLabel, setNewItemLabel] = useState("");
  const [newItemRequired, setNewItemRequired] = useState(true);
  // 문법 검사 기본 항목의 켜짐 여부(#410) — 기본은 켜짐이다.
  const [syntaxCheckEnabled, setSyntaxCheckEnabled] = useState(true);

  const hasRequiredItem = items.some((item) => item.required);

  function toggleSubmissionFormat(format: SubmissionFormat, checked: boolean) {
    setSubmissionFormats((prev) =>
      checked ? [...prev, format].filter((f, i, arr) => arr.indexOf(f) === i) : prev.filter((f) => f !== format),
    );
  }

  function handleAddItem(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const label = newItemLabel.trim();
    if (label === "") return;
    setItems((prev) => [...prev, { key: nextKeyRef.current++, label, required: newItemRequired }]);
    setNewItemLabel("");
    setNewItemRequired(true);
  }

  function handleItemLabelChange(key: number, label: string) {
    setItems((prev) => prev.map((item) => (item.key === key ? { ...item, label } : item)));
  }

  function handleItemRequiredChange(key: number, required: boolean) {
    setItems((prev) => prev.map((item) => (item.key === key ? { ...item, required } : item)));
  }

  function handleItemDelete(key: number) {
    setItems((prev) => prev.filter((item) => item.key !== key));
  }

  function handleReorder(orderedKeys: (string | number)[]) {
    setItems((prev) => {
      const byKey = new Map(prev.map((item) => [item.key, item]));
      return orderedKeys.flatMap((key) => {
        const item = byKey.get(key as number);
        return item ? [item] : [];
      });
    });
  }

  async function submitProblem(open: boolean) {
    if (title.trim() === "") return;
    if (!isGradingGuidelineValid(gradingGuideline)) return;
    // 제출을 누르는 순간에만 검사한다 — 타이핑 중에는 부르지 않는다(spec
    // #474, #479). 서버가 진짜 문이라 여기서 걸러도 걸러지지 않아도 서버가
    // 같은 이유로 다시 거절한다.
    const titleBannedWordMessage = checkPublicTextForBannedWords(title.trim(), "제목");
    if (titleBannedWordMessage) {
      setError(titleBannedWordMessage);
      return;
    }
    const descriptionBannedWordMessage = checkPublicTextForBannedWords(description, "설명");
    if (descriptionBannedWordMessage) {
      setError(descriptionBannedWordMessage);
      return;
    }
    for (const item of items) {
      const itemBannedWordMessage = checkPublicTextForBannedWords(item.label, "체크리스트 항목");
      if (itemBannedWordMessage) {
        setError(itemBannedWordMessage);
        return;
      }
    }
    if (dueOrderViolated(recommendedDue, dueDraft)) {
      setDueOrderRefused(true);
      return;
    }
    setSubmitting(true);
    setError(null);
    const result = await createProblem(classId, {
      recommended_due_at: dueDraftToIso(recommendedDue),
      due_at: dueDraftToIso(dueDraft),
      title: title.trim(),
      description,
      submission_formats: submissionFormats,
      model,
      reasoning_effort: reasoningEffort,
      model_is_reasoning: model !== "" && modelIsReasoning,
      grading_strictness: gradingGuideline.grading_strictness,
      grading_guideline_text: gradingGuideline.grading_guideline_text,
      checklist_items: items.map((item) => ({ label: item.label, required: item.required })),
      syntax_check_enabled: syntaxCheckEnabled,
      open,
    });
    if (result.ok) {
      // 방금 만든 항목 가운데 채점이 확인할 수 없을 수 있는 것(#810) — 상세 화면이 한 번 보인다.
      stashWarnings(window.sessionStorage, result.data.id, result.data.gradability_warnings ?? []);
      router.push(`/classes/${classId}/problems/${result.data.id}`);
    } else {
      setError(result.detail);
      setSubmitting(false);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void submitProblem(false);
  }

  function handleCreateAndOpen() {
    void submitProblem(true);
  }

  if (classState.status === "ready" && classState.classroom.archived) {
    // 클래스 상세는 이 화면으로 가는 링크 자체를 감추지만(#438), 주소를 직접
    // 열면 여기까지 온다 — 서버도 같은 요청을 403으로 거절하므로 폼을 아예
    // 보여주지 않고 이유만 말한다.
    return (
      <PageShell>
        <PageHeader eyebrow="클래스 · 문제" title="새 문제" titleTestId="new-problem-heading" />
        <Note tone="attention">
          <span data-testid="new-problem-archived-note">
            이 클래스는 보관되어 새 문제를 만들 수 없습니다 — 보관을 되돌린 뒤에 할 수 있습니다.
          </span>
        </Note>
      </PageShell>
    );
  }

  const createDisabled =
    submitting || title.trim() === "" || submissionFormats.length === 0 || !isGradingGuidelineValid(gradingGuideline);
  const classLabel = classState.status === "ready" ? `${classState.classroom.name} › ` : "";

  return (
    <PageShell>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-1.5">
          <div className="text-[11px] tracking-[0.08em] text-ink/45">{classLabel}문제</div>
          <h1 data-testid="new-problem-heading" className="text-[22px] font-semibold tracking-[-0.01em]">
            새 문제
          </h1>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          <button
            type="button"
            data-testid="open-problem-import"
            onClick={() => setPickerOpen(true)}
            className={buttonClass("secondary")}
          >
            문제 가져오기
          </button>
          <button
            type="submit"
            form="new-problem-form"
            data-testid="new-problem-submit"
            disabled={createDisabled}
            className={buttonClass("secondary")}
          >
            {submitting ? "만드는 중..." : "만들기"}
          </button>
          <button
            type="button"
            data-testid="new-problem-create-and-open-submit"
            disabled={createDisabled || !hasRequiredItem}
            onClick={handleCreateAndOpen}
            className={buttonClass("primary")}
          >
            {submitting ? "만드는 중..." : "만들고 바로 열기"}
          </button>
        </div>
      </div>

      {error ? (
        <div className="mb-5">
          <ErrorNote>
            <span data-testid="new-problem-error">{error}</span>
          </ErrorNote>
        </div>
      ) : null}

      <div className="flex flex-col gap-5">
        <div role="tablist" aria-label="새 문제 화면" className="flex items-end gap-0.5 border-b border-rule">
          {(
            [
              ["write", "작성", "new-problem-tab-write"],
              ["preview", "미리보기", "new-problem-tab-preview"],
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

        <div data-testid="new-problem-write-panel" className={tab === "write" ? "block" : "hidden"}>
          <TwoColumnFrame
            sideTestId="new-problem-side-rail"
            main={
              <>
                <Card>
                  <form id="new-problem-form" onSubmit={handleSubmit} className="flex flex-col gap-5 p-4">
                    <div className="flex flex-col gap-1.5">
                      <label htmlFor="problem-title">
                        <FieldLabel>제목</FieldLabel>
                      </label>
                      <input
                        id="problem-title"
                        data-testid="new-problem-title-input"
                        value={title}
                        onChange={(event) => setTitle(event.target.value)}
                        required
                        className={INPUT_CLASS}
                        placeholder="예: fetch 로 목록 그리기"
                      />
                    </div>

                    <div className="flex flex-col gap-1.5">
                      <FieldLabel>설명</FieldLabel>
                      <MarkdownEditor
                        id="problem-description"
                        label="설명"
                        testId="new-problem-description-input"
                        value={description}
                        onChange={setDescription}
                        placeholder="무엇을 만들어야 하는지, 그리고 무엇이 이 문제의 핵심인지."
                      />
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
                        checked={syntaxCheckEnabled}
                        onChange={(event) => setSyntaxCheckEnabled(event.target.checked)}
                        className="accent-attention"
                      />
                      켜짐
                    </label>
                  </div>
                  {items.length === 0 ? (
                    <EmptyState>
                      <span data-testid="new-problem-checklist-empty-state">항목 없음</span>
                    </EmptyState>
                  ) : (
                    <ChecklistRows
                      items={items.map((item) => ({ key: item.key, label: item.label, required: item.required }))}
                      listTestId="new-problem-checklist-items"
                      rowTestId={(_item, index) => `new-problem-checklist-item-${index}`}
                      labelMode={{ kind: "change", onChange: (key, label) => handleItemLabelChange(key as number, label) }}
                      onReorder={handleReorder}
                      onRequiredChange={(key, required) => handleItemRequiredChange(key as number, required)}
                      onDelete={(key) => handleItemDelete(key as number)}
                    />
                  )}

                  <form onSubmit={handleAddItem} className="flex flex-wrap items-center gap-2.5 border-t border-rule px-4 py-3">
                    <label htmlFor="new-item-label" className="sr-only">
                      새 항목
                    </label>
                    <input
                      id="new-item-label"
                      data-testid="new-problem-new-checklist-item-label-input"
                      value={newItemLabel}
                      onChange={(event) => setNewItemLabel(event.target.value)}
                      placeholder="새 항목"
                      className={`${INPUT_CLASS} min-w-0 flex-1`}
                    />
                    <button
                      type="button"
                      data-testid="new-problem-new-checklist-item-required-input"
                      aria-pressed={newItemRequired}
                      aria-label={`새 항목 ${newItemRequired ? "필수" : "선택"}`}
                      onClick={() => setNewItemRequired((prev) => !prev)}
                      className="shrink-0"
                    >
                      <Badge tone={newItemRequired ? "verified" : "neutral"}>{newItemRequired ? "필수" : "선택"}</Badge>
                    </button>
                    <button
                      type="submit"
                      data-testid="new-problem-new-checklist-item-submit"
                      disabled={newItemLabel.trim() === ""}
                      className={buttonClass("primary", "sm")}
                    >
                      추가
                    </button>
                    <p data-testid="new-problem-checklist-gradability-note" className="basis-full text-[12px] text-ink/60">
                      {GRADABILITY_FORM_NOTE}
                    </p>
                  </form>
                </Card>
              </>
            }
            side={
              <>
                <ProblemDueCard
                  testIdPrefix="new-problem"
                  recommended={recommendedDue}
                  due={dueDraft}
                  onRecommendedChange={(next) => {
                    setRecommendedDue(next);
                    setDueOrderRefused(false);
                  }}
                  onDueChange={(next) => {
                    setDueDraft(next);
                    setDueOrderRefused(false);
                  }}
                  invalid={dueOrderRefused || error === DUE_ORDER_MESSAGE}
                />
                <ProblemSettingsForm
                testIdPrefix="new-problem"
                submissionFormats={submissionFormats}
                onToggleSubmissionFormat={toggleSubmissionFormat}
                model={model}
                onModelChange={setModel}
                modelsState={modelsState}
                reasoningEffort={reasoningEffort}
                onReasoningEffortChange={setReasoningEffort}
                defaultModelIsReasoning={
                  classState.status === "ready" ? classState.classroom.default_model_is_reasoning : false
                }
                reasoningSwitch={
                  classState.status === "ready" && classState.classroom.scoring_connection_kind === "compatible_server"
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
                onGradingGuidelineChange={setGradingGuideline}
              />
              </>
            }
          />
        </div>

        <div
          data-testid="new-problem-preview-panel"
          className={tab === "preview" ? "flex w-full flex-col gap-4" : "hidden"}
        >
          {!hasRequiredItem ? (
            <Note tone="attention">
              <span data-testid="new-problem-preview-not-ready-notice">필수 항목이 없어 아직 열 수 없습니다.</span>
            </Note>
          ) : null}
          <div className="border border-rule bg-paper p-6">
            <ProblemParticipantView
              interactive={false}
              headingLevel="h2"
              eyebrow={previewEyebrow}
              title={title.trim() === "" ? "(제목 없음)" : title}
              description={description}
              checklistItems={items.map((item) => ({
                id: item.key,
                label: item.label,
                required: item.required,
              }))}
              syntaxCheckEnabled={syntaxCheckEnabled}
              gradingStrictness={gradingGuideline.grading_strictness}
              gradingGuidelineCustomText={gradingGuideline.grading_guideline_text}
              submissionFormats={submissionFormats}
              submissions={[]}
            />
          </div>
        </div>
      </div>

      {pickerOpen ? (
        <ProblemImportSheet
          classId={classId}
          onClose={() => setPickerOpen(false)}
          onImported={handleImported}
        />
      ) : null}
    </PageShell>
  );
}
