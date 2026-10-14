"use client";

// 채점 지침 편집 영역 (#386, 부모 #385, CONTEXT.md 「채점 지침」) — 새 문제·
// 문제 편집 화면이 함께 쓴다. 시안 v2(#637)는 접지 않고 단계 칩 한 줄로 둔다.
import { useState } from "react";

import { Card, CardHeader, INPUT_CLASS } from "@/app/components/ui";
import {
  GRADING_STRICTNESS_OPTIONS,
  gradingGuidelineText,
} from "@/lib/problems/grading-guideline";
import type { GradingStrictness } from "@/lib/problems/grading-guideline";

export type GradingGuidelineValue = {
  grading_strictness: GradingStrictness;
  grading_guideline_text: string;
};

/** 직접 입력인데 문장이 비어 있으면 저장할 수 없다(#386 AC) — 호출부가 이
 *  값을 저장 버튼의 `disabled`에 함께 건다. */
export function isGradingGuidelineValid(value: GradingGuidelineValue): boolean {
  return value.grading_strictness !== "custom" || value.grading_guideline_text.trim() !== "";
}

export function GradingGuidelineEditor({
  value,
  onChange,
  testIdPrefix,
}: {
  value: GradingGuidelineValue;
  onChange: (next: GradingGuidelineValue) => void;
  testIdPrefix: string;
}) {
  // 직접 입력으로 바꾸는 순간 칸을 "마지막으로 골랐던 단계의 문장"으로
  // 미리 채운다(#386 AC) — 그 대상을 기억해 둔다. 편집 화면이 이미
  // "custom"으로 문제를 불러왔으면 미리 채울 대상이 없으니 "보통"을
  // 기본으로 둔다(어차피 이미 문장이 있어 다시 채우지 않는다).
  const [lastPresetStrictness, setLastPresetStrictness] = useState<
    Exclude<GradingStrictness, "custom">
  >(value.grading_strictness === "custom" ? "normal" : value.grading_strictness);

  const isEmptyCustom = value.grading_strictness === "custom" && value.grading_guideline_text.trim() === "";

  function handleStrictnessChange(next: GradingStrictness) {
    if (next === "custom") {
      onChange({
        grading_strictness: "custom",
        grading_guideline_text: gradingGuidelineText(lastPresetStrictness, ""),
      });
      return;
    }
    setLastPresetStrictness(next);
    onChange({ grading_strictness: next, grading_guideline_text: "" });
  }

  return (
    <Card>
      <CardHeader title="채점 지침" />
      <div data-testid={`${testIdPrefix}-grading-guideline-panel`} className="flex flex-col gap-3 p-4">
        <fieldset className="flex flex-wrap gap-1.5">
          <legend className="sr-only">채점 지침 단계</legend>
          {GRADING_STRICTNESS_OPTIONS.map((option) => {
            const checked = value.grading_strictness === option.value;
            return (
              <label
                key={option.value}
                className={`cursor-pointer border px-2.5 py-1 text-[12.5px] has-[:focus-visible]:outline has-[:focus-visible]:outline-1 has-[:focus-visible]:outline-ink ${
                  checked ? "border-ink bg-ink text-paper" : "border-rule hover:bg-paper"
                }`}
              >
                <input
                  type="radio"
                  name={`${testIdPrefix}-grading-strictness`}
                  data-testid={`${testIdPrefix}-grading-strictness-${option.value}`}
                  checked={checked}
                  onChange={() => handleStrictnessChange(option.value)}
                  className="sr-only"
                />
                {option.label}
              </label>
            );
          })}
        </fieldset>

        {value.grading_strictness === "custom" ? (
          <div className="flex flex-col gap-1.5">
            <label htmlFor={`${testIdPrefix}-grading-guideline-text`} className="sr-only">
              직접 입력한 지침
            </label>
            <textarea
              id={`${testIdPrefix}-grading-guideline-text`}
              data-testid={`${testIdPrefix}-grading-guideline-text-input`}
              value={value.grading_guideline_text}
              onChange={(event) =>
                onChange({
                  grading_strictness: "custom",
                  grading_guideline_text: event.target.value,
                })
              }
              rows={4}
              className={`${INPUT_CLASS} resize-y`}
              placeholder="예: 함수 이름은 solve 여야 하지만 출력 형식은 자유"
            />
            {isEmptyCustom ? (
              <span
                data-testid={`${testIdPrefix}-grading-guideline-empty-notice`}
                className="text-[11.5px] text-attention"
              >
                문장을 적어야 저장할 수 있습니다.
              </span>
            ) : null}
          </div>
        ) : null}
      </div>
    </Card>
  );
}
