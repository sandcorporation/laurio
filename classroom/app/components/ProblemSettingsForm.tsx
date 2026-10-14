"use client";

// 문제 설정 폼 조각 (#442, 부모 #432) — 제출 형식·채점 모델·추론 강도·채점
// 지침. 새 문제 화면과 수정 화면이 이 조각 하나를 쓴다 — 설정 하나를 더할
// 때 이 파일 한 곳만 고치면 된다. 체크리스트는 두 화면의 저장 방식이 달라
// (새 문제는 함께 저장, 수정은 항목마다 저장) 이 조각에 넣지 않고 각
// 화면에 남긴다.
//
// 시안 v2(#637): 오른쪽 300px 열에 카드 셋으로 놓이고, 화면에는 설명 문장 없이
// 라벨·값·배지·버튼만 둔다. 「모델 거부」 배지·재시도와 실제로 쓰일 모델·추론 강도는
// 이미 저장된 문제가 있는 수정 화면에만 뜻이 있다(#437, #402) — 각각 prop 이 있을 때만 그린다.
import {
  Badge,
  Card,
  CardHeader,
  ErrorNote,
  FieldLabel,
  INPUT_CLASS,
  Note,
  buttonClass,
} from "@/app/components/ui";
import {
  GradingGuidelineEditor,
  type GradingGuidelineValue,
} from "@/app/components/GradingGuidelineEditor";
import { ReasoningModelSwitch } from "@/app/components/ReasoningModelSwitch";
import { ProblemCostLine } from "@/app/components/ScoringCost";
import type { SubmissionFormat } from "@/lib/problems/api";
import { isSelectedModelReasoning, REASONING_EFFORT_OPTIONS } from "@/lib/scoring/reasoning";
import type { ScoringCostState } from "@/lib/scoring/use-scoring-cost";
import type { ScoringModelsState } from "@/lib/scoring/use-scoring-models";

// 「이 모델로 다시 시도」 자리(#437) — 수정 화면에서 `problem.scoring_model_rejected`일
// 때만 넘긴다. 재시도 요청 자체는 화면(공용 변경 도우미를 쓰는 핸들러)이 쥔다.
export type ModelRejectionRetry = {
  retrying: boolean;
  error: string | null;
  onRetry: () => void;
};

export function ProblemSettingsForm({
  testIdPrefix,
  submissionFormats,
  onToggleSubmissionFormat,
  model,
  onModelChange,
  modelsState,
  modelRejection,
  reasoningEffort,
  onReasoningEffortChange,
  defaultModelIsReasoning,
  reasoningSwitch,
  classDefaults,
  costState,
  gradingGuideline,
  onGradingGuidelineChange,
  disabled = false,
}: {
  testIdPrefix: string;
  submissionFormats: SubmissionFormat[];
  onToggleSubmissionFormat: (format: SubmissionFormat, checked: boolean) => void;
  model: string;
  onModelChange: (value: string) => void;
  modelsState: ScoringModelsState;
  /** 「모델 거부」 배지·재시도 버튼(수정 화면만, #437). */
  modelRejection?: ModelRejectionRetry;
  reasoningEffort: string;
  onReasoningEffortChange: (value: string) => void;
  defaultModelIsReasoning: boolean;
  /** 「호환 서버」 클래스일 때만 — 이 문제 자신의 모델의 「추론 모델」 스위치(#602). */
  reasoningSwitch?: { checked: boolean; onChange: (value: boolean) => void };
  /** 클래스 기본 모델·추론 강도 — 「클래스 기본값을 따릅니다」를 풀어 예상 비용을 찾는다(#591). */
  classDefaults: { model: string; reasoningEffort: string } | null;
  /** 이 문제의 예상 채점 비용(#591). */
  costState: ScoringCostState;
  gradingGuideline: GradingGuidelineValue;
  onGradingGuidelineChange: (value: GradingGuidelineValue) => void;
  /** 보관된 클래스의 수정 화면(#438) — 모든 입력과 재시도 버튼을 잠근다.
   *  `<fieldset disabled>` 하나가 안의 입력·선택·버튼을 전부 막는다. */
  disabled?: boolean;
}) {
  const defaultEffortLabel = REASONING_EFFORT_OPTIONS.find((o) => o.value === classDefaults?.reasoningEffort)?.label;
  const effortInheritLabel = defaultEffortLabel ? `클래스 기본값 — ${defaultEffortLabel}` : "클래스 기본값";
  const inheritLabel = classDefaults ? `클래스 기본값 — ${classDefaults.model}` : "클래스 기본값";
  const isReasoning =
    modelsState.status === "ready" &&
    isSelectedModelReasoning(model, modelsState.models, defaultModelIsReasoning, reasoningSwitch?.checked);
  return (
    <fieldset
      disabled={disabled}
      data-testid={`${testIdPrefix}-settings-fieldset`}
      className="contents"
    >
      <Card>
        <CardHeader title="제출 형식" />
        <div className="flex flex-col gap-1.5 p-4">
          <div className="flex flex-col gap-2">
            <label className="flex items-center gap-2.5 text-[13.5px]">
              <input
                type="checkbox"
                checked={submissionFormats.includes("source")}
                onChange={(event) => onToggleSubmissionFormat("source", event.target.checked)}
                data-testid={`${testIdPrefix}-format-source`}
                className="accent-ink"
              />
              zip 파일
            </label>
            <label className="flex items-center gap-2.5 text-[13.5px]">
              <input
                type="checkbox"
                checked={submissionFormats.includes("repository")}
                onChange={(event) => onToggleSubmissionFormat("repository", event.target.checked)}
                data-testid={`${testIdPrefix}-format-repository`}
                className="accent-ink"
              />
              GitHub 저장소
            </label>
          </div>
          {submissionFormats.length === 0 ? (
            <span data-testid={`${testIdPrefix}-format-empty-notice`} className="text-[11.5px] text-attention">
              하나 이상 골라야 합니다.
            </span>
          ) : null}
        </div>
      </Card>

      <Card>
        <CardHeader title="채점 모델" />
        <div className="flex flex-col gap-2.5 p-4">
          {modelRejection ? (
            <Note tone="attention">
              <div data-testid={`${testIdPrefix}-model-rejected-note`} className="flex flex-col gap-2">
                <div className="flex items-center gap-2">
                  <Badge tone="attention">모델 거부</Badge>
                </div>
                <button
                  type="button"
                  data-testid={`${testIdPrefix}-model-retry-button`}
                  disabled={modelRejection.retrying}
                  onClick={modelRejection.onRetry}
                  className={`${buttonClass("secondary", "sm")} self-start`}
                >
                  {modelRejection.retrying ? "다시 시도하는 중..." : "이 모델로 다시 시도"}
                </button>
                {modelRejection.error ? (
                  <ErrorNote>
                    <span data-testid={`${testIdPrefix}-model-retry-error`}>{modelRejection.error}</span>
                  </ErrorNote>
                ) : null}
              </div>
            </Note>
          ) : null}
          <label htmlFor={`${testIdPrefix}-model`} className="sr-only">
            채점 모델
          </label>
          {modelsState.status === "ready" ? (
            <>
              {modelsState.source === "fallback" ? (
                <span data-testid={`${testIdPrefix}-model-unavailable-note`} className="self-start">
                  <Badge>기본 목록</Badge>
                </span>
              ) : null}
              {modelsState.source === "manual" ? (
                // 호환 서버가 모델 목록을 주지 않았다(#601) — 그 서버의 모델 이름을 직접 넣는다.
                <input
                  id={`${testIdPrefix}-model`}
                  data-testid={`${testIdPrefix}-model-input`}
                  value={model}
                  onChange={(event) => onModelChange(event.target.value)}
                  className={`${INPUT_CLASS} font-mono`}
                  placeholder={inheritLabel}
                  maxLength={200}
                />
              ) : (
              <select
                id={`${testIdPrefix}-model`}
                data-testid={`${testIdPrefix}-model-select`}
                value={model}
                onChange={(event) => onModelChange(event.target.value)}
                className={INPUT_CLASS}
              >
                <option value="" data-testid={`${testIdPrefix}-model-option-inherit`}>
                  {inheritLabel}
                </option>
                {modelsState.models.map((option) => (
                  <option
                    key={option.id}
                    value={option.id}
                    data-testid={`${testIdPrefix}-model-option-${option.id}`}
                  >
                    {option.label} · 컨텍스트{" "}
                    {option.context_window
                      ? `${option.context_window.toLocaleString("ko-KR")} 토큰`
                      : "크기 미확인"}
                  </option>
                ))}
              </select>
              )}
            </>
          ) : (
            <p data-testid={`${testIdPrefix}-model-loading`} className="text-[13px] text-ink/45">
              모델 목록을 불러오는 중...
            </p>
          )}
          {reasoningSwitch && model !== "" ? (
            <div className="flex flex-col gap-1.5 border-t border-rule pt-3">
              <ReasoningModelSwitch
                checked={reasoningSwitch.checked}
                onChange={reasoningSwitch.onChange}
                testId={`${testIdPrefix}-reasoning-switch`}
              />
            </div>
          ) : null}
          {isReasoning ? (
            <div className="flex flex-col gap-1.5 border-t border-rule pt-3">
              <label htmlFor={`${testIdPrefix}-reasoning-effort`}>
                <FieldLabel>추론 강도</FieldLabel>
              </label>
              <select
                id={`${testIdPrefix}-reasoning-effort`}
                data-testid={`${testIdPrefix}-reasoning-effort-select`}
                value={reasoningEffort}
                onChange={(event) => onReasoningEffortChange(event.target.value)}
                className={`${INPUT_CLASS} max-w-[200px]`}
              >
                <option value="" data-testid={`${testIdPrefix}-reasoning-effort-option-inherit`}>
                  {effortInheritLabel}
                </option>
                {REASONING_EFFORT_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
          ) : null}
          {modelsState.status === "ready" && classDefaults ? (
            <ProblemCostLine
              state={costState}
              testIdPrefix={testIdPrefix}
              modelId={model || classDefaults.model}
              reasoningEffort={reasoningEffort || classDefaults.reasoningEffort}
            />
          ) : null}
        </div>
      </Card>

      <GradingGuidelineEditor
        value={gradingGuideline}
        onChange={onGradingGuidelineChange}
        testIdPrefix={testIdPrefix}
      />
    </fieldset>
  );
}
