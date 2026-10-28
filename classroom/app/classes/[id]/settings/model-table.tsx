"use client";

// 기본 모델 라디오 표(#636, 시안 v2) — 드롭다운을 대신한다. 줄마다 이름(mono)·컨텍스트·시도 1건
// 예상 비용(호환 서버는 토큰)이고, 비용은 서버가 셈한 비용 표(`useScoringCost`, #591·#617)의 줄을
// 그대로 쓴다. 지금 저장된 기본값이 맨 위, 나머지는 「모델 N개 더 보기」 뒤에 접힌다.
import { useState } from "react";

import { Badge } from "@/app/components/ui";
import { findCostRow, modelCostCell } from "@/lib/scoring/cost";
import type { ScoringModelRow } from "@/lib/scoring/use-scoring-models";
import type { ScoringCostState } from "@/lib/scoring/use-scoring-cost";

const VISIBLE_WHEN_FOLDED = 3;

/** 400000 → 「400K」, 1048576 → 「1M」. 모르는 모델은 「—」. */
export function formatContext(tokens: number | null): string {
  if (tokens === null) return "—";
  if (tokens >= 1_000_000) return `${Math.round(tokens / 100_000) / 10}M`.replace(".0M", "M");
  return `${Math.round(tokens / 1_000)}K`;
}

export function DefaultModelTable({
  models,
  savedModel,
  selected,
  onSelect,
  costState,
  reasoningEffort,
}: {
  models: ScoringModelRow[];
  // 서버에 저장된 기본 모델 — 맨 위로 올리고 「클래스 기본값」 표식을 단다.
  savedModel: string;
  selected: string;
  onSelect: (modelId: string) => void;
  costState: ScoringCostState;
  reasoningEffort: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const savedInList = models.some((model) => model.id === savedModel);
  const ordered = [...models].sort((a, b) => Number(b.id === savedModel) - Number(a.id === savedModel));
  const foldedCount = Math.max(0, ordered.length - VISIBLE_WHEN_FOLDED);
  // 접혀 있어도 지금 고른 모델은 보인다 — 고른 것이 숨으면 무엇을 저장하는지 알 수 없다.
  const visible = expanded
    ? ordered
    : ordered.filter((model, index) => index < VISIBLE_WHEN_FOLDED || model.id === selected);
  const hiddenCount = ordered.length - visible.length;

  return (
    <div data-testid="class-default-model-table" role="radiogroup" aria-label="기본 모델" className="border border-rule">
      {savedInList ? null : (
        // 연결을 바꾼 뒤 저장된 값이 그 연결의 목록에 없으면(#601) 고를 수 없는 줄로 먼저 말한다.
        <div data-testid="class-default-model-unavailable" className="flex items-center gap-3 border-b border-rule px-4 py-2.5">
          <span className="font-mono text-[13.5px]">{savedModel}</span>
          <Badge tone="attention">이 연결에서 쓸 수 없음</Badge>
        </div>
      )}
      {visible.map((model, index) => {
        const isSelected = model.id === selected;
        const estimate = costState.status === "ready" ? costState.estimate : null;
        // 호환 서버는 단가를 몰라 토큰만 어림한다 — 서버가 지금 설정(추론 스위치 포함)의 한 줄만 주므로 모든
        // 줄이 그 어림을 쓴다. OpenAI 키는 모델마다 줄이 있다.
        const row = estimate === null ? null : estimate.unit === "tokens" ? (estimate.rows[0] ?? null) : findCostRow(estimate, model.id, reasoningEffort);
        const cost = estimate === null ? "—" : modelCostCell(estimate, row);
        const prefix = estimate?.unit === "tokens" || isSelected ? "시도 1건 " : "";
        return (
          <label
            key={model.id}
            className={`flex cursor-pointer flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 ${
              index === 0 && savedInList ? "" : "border-t border-rule"
            } ${isSelected ? "bg-paper" : ""}`}
          >
            <input
              type="radio"
              name="class-default-model"
              value={model.id}
              checked={isSelected}
              onChange={() => onSelect(model.id)}
              data-testid={`scoring-model-option-${model.id}`}
              className="accent-ink"
            />
            <span className="min-w-[11rem] flex-1">
              <span className="block font-mono text-[13.5px]">{model.id}</span>
              {model.id === savedModel ? <span className="block text-[11.5px] text-ink/45">클래스 기본값</span> : null}
            </span>
            <span className="w-[72px] text-right" data-testid={`scoring-model-context-${model.id}`}>
              <span className="block font-mono text-[12.5px] text-ink/60">{formatContext(model.context_window)}</span>
              <span className="block text-[11px] text-ink/30">컨텍스트</span>
            </span>
            <span
              data-testid={`scoring-model-cost-${model.id}`}
              className="w-[130px] whitespace-nowrap text-right text-[12.5px] text-ink/60"
            >
              {prefix}
              {cost}
            </span>
          </label>
        );
      })}
      {foldedCount > 0 ? (
        <button
          type="button"
          data-testid="class-default-model-more"
          aria-expanded={expanded}
          onClick={() => setExpanded((open) => !open)}
          className="block w-full border-t border-rule px-4 py-2.5 text-left text-[12px] text-ink/45 hover:text-ink"
        >
          {expanded ? "접기" : `모델 ${hiddenCount > 0 ? hiddenCount : foldedCount}개 더 보기`}
        </button>
      ) : null}
    </div>
  );
}
