"use client";

// 채점 지침 편집 영역 (#386, 부모 #385, CONTEXT.md 「채점 지침」) — 새 문제·
// 문제 편집 화면이 함께 쓴다. 대부분의 문제는 기본값(「보통」)으로 충분하니
// 필요할 때만 펼치는 접이식 카드다(#385 User Story 2).
import { useState } from "react";

import { Card, FieldLabel, INPUT_CLASS } from "@/app/components/ui";
import {
  GRADING_STRICTNESS_OPTIONS,
  gradingGuidelineText,
  gradingStrictnessLabel,
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
  const [open, setOpen] = useState(false);
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
      <button
        type="button"
        data-testid={`${testIdPrefix}-grading-guideline-toggle`}
        aria-expanded={open}
        onClick={() => setOpen((prev) => !prev)}
        className="flex w-full items-center justify-between px-4 py-3 text-left"
      >
        <span className="text-[13.5px] font-semibold">채점 지침</span>
        <span className="text-[12px] text-ink/45">
          {gradingStrictnessLabel(value.grading_strictness)} · {open ? "접기" : "펼치기"}
        </span>
      </button>

      {open ? (
        <div
          data-testid={`${testIdPrefix}-grading-guideline-panel`}
          className="flex flex-col gap-3 border-t border-rule p-4"
        >
          <p className="text-[11.5px] leading-relaxed text-ink/45">
            체크리스트 항목을 얼마나 글자 그대로 따질지 정합니다 — 참여자도 문제 화면에서
            이 지침을 봅니다. 지침을 바꿔도 이미 매긴 판정은 그대로 남고, 새로 들어오는
            시도부터 새 지침을 탑니다.
          </p>

          <fieldset className="flex flex-col gap-1.5">
            <legend>
              <FieldLabel>단계</FieldLabel>
            </legend>
            <div className="flex flex-col gap-2 pt-1">
              {GRADING_STRICTNESS_OPTIONS.map((option) => (
                <label key={option.value} className="flex items-center gap-2.5 text-[13.5px]">
                  <input
                    type="radio"
                    name={`${testIdPrefix}-grading-strictness`}
                    data-testid={`${testIdPrefix}-grading-strictness-${option.value}`}
                    checked={value.grading_strictness === option.value}
                    onChange={() => handleStrictnessChange(option.value)}
                    className="accent-ink"
                  />
                  {option.label}
                </label>
              ))}
            </div>
          </fieldset>

          {value.grading_strictness === "custom" ? (
            <div className="flex flex-col gap-1.5">
              <label htmlFor={`${testIdPrefix}-grading-guideline-text`}>
                <FieldLabel>직접 입력한 지침</FieldLabel>
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
                rows={3}
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
          ) : (
            <p
              data-testid={`${testIdPrefix}-grading-guideline-preset-text`}
              className="text-[12.5px] leading-relaxed text-ink/60"
            >
              {gradingGuidelineText(value.grading_strictness, "")}
            </p>
          )}
        </div>
      ) : null}
    </Card>
  );
}
