"use client";

// 강사 제출 현황의 「완성도 순위」(#883, ADR-0072) — 「완성도 채점」 버튼 → 비용 확인 → 큐에 넣기, 순위 표(펼치면
// 근거), 참여자 공개 스위치. 대상은 참여자별 가장 최근 통과 시도이고 계산·등수는 백엔드가 한다.
import { useState } from "react";

import { Badge, Card, CardHeader, EmptyState, ErrorNote, Num, buttonClass } from "@/app/components/ui";
import { MissingScoringKeyNote } from "@/app/components/MissingScoringKeyNote";
import { updateProblem } from "@/lib/problems/api";
import { BonusScoreEditor } from "@/app/components/BonusScoreEditor";
import { GRADE_LABEL } from "@/lib/problems/grade";
import {
  fetchQualityEstimate,
  rateBonus,
  runQuality,
  type QualityEstimate,
  type QualityItem,
  type QualityRankRow,
} from "@/lib/quality/api";
import { estimateLine, formatPoints, formatQualityTotal } from "@/lib/quality/format";
import { useProblemQuality } from "@/lib/quality/use-quality";

type Confirm =
  | { step: "idle" }
  | { step: "loading" }
  | { step: "ready"; estimate: QualityEstimate }
  | { step: "running" }
  | { step: "error"; message: string };

function itemGradeLabel(item: QualityItem): string {
  return GRADE_LABEL[item.bonus ? "bonus" : item.required ? "required" : "optional"];
}

function QualityRow({
  row,
  open,
  onToggle,
  onRateBonus,
}: {
  row: QualityRankRow;
  open: boolean;
  onToggle: () => void;
  onRateBonus: (submissionId: number, itemId: number, score: number, memo: string) => Promise<string | null>;
}) {
  const testId = `quality-row-${row.submission_id}`;
  return (
    <li data-testid={testId} className="px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-3.5 gap-y-1.5">
        <span data-testid={`${testId}-rank`} className="w-[40px] shrink-0 text-[13.5px] font-semibold">
          <Num>{row.rank}등</Num>
        </span>
        <span data-testid={`${testId}-member`} className="w-[90px] shrink-0 truncate text-[13.5px]">
          {row.display_name}
        </span>
        {row.bonus_needs_rerate ? (
          <span data-testid={`${testId}-bonus-rerate`} className="shrink-0">
            <Badge tone="attention">가산 다시 매김 필요</Badge>
          </span>
        ) : null}
        <span data-testid={`${testId}-completeness`} className="w-[96px] shrink-0 text-[13.5px]">
          <Num>{formatQualityTotal(row.total, row.max_total)}</Num>
        </span>
        <span className="order-5 flex w-full basis-full flex-wrap gap-1.5 sm:order-none sm:w-auto sm:min-w-0 sm:flex-1 sm:basis-0">
          {row.items.map((item) => (
            <span
              key={item.item_id}
              data-testid={`${testId}-item-${item.item_id}`}
              className="max-w-full truncate border border-rule px-1.5 py-0.5 text-[12px] text-ink/70"
            >
              {item.bonus ? `${GRADE_LABEL.bonus} · ` : ""}
              {item.label} <Num className="font-semibold text-ink">{item.bonus && !item.rated ? "–" : item.score}</Num>
            </span>
          ))}
        </span>
        <button
          type="button"
          data-testid={`${testId}-toggle`}
          aria-expanded={open}
          onClick={onToggle}
          className="order-4 ml-auto px-3 py-1.5 text-[12.5px] text-ink/60 underline underline-offset-[3px] hover:text-ink sm:order-none sm:ml-0"
        >
          근거
        </button>
      </div>
      {open ? (
        <ul data-testid={`${testId}-reasons`} className="mt-3 flex flex-col gap-2 border-t border-rule pt-3">
          {row.items.map((item) => (
            <li key={item.item_id} className="flex flex-col gap-0.5 text-[12.5px]">
              <span className="flex flex-wrap items-center gap-2">
                <Badge tone={item.required ? "verified" : "neutral"}>{itemGradeLabel(item)}</Badge>
                <span className="font-medium">{item.label}</span>
                <Num className="text-ink/60">
                  {item.score}/5 · {formatPoints(item.item_points)} / {item.points}점
                </Num>
              </span>
              {item.bonus ? (
                <BonusScoreEditor
                  testId={`${testId}-bonus-${item.item_id}`}
                  label={item.label}
                  initialScore={item.score}
                  initialMemo={item.reasoning}
                  onSave={(score, memo) => onRateBonus(row.submission_id, item.item_id, score, memo)}
                />
              ) : (
                <span className="text-ink/70">{item.reasoning}</span>
              )}
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}

export function QualityRankingCard({
  classId,
  problemId,
  canChangeKey,
}: {
  classId: number;
  problemId: number;
  canChangeKey: boolean;
}) {
  const { state, reload } = useProblemQuality(classId, problemId);
  const [confirm, setConfirm] = useState<Confirm>({ step: "idle" });
  const [openIds, setOpenIds] = useState<ReadonlySet<number>>(new Set());
  const [publicSaving, setPublicSaving] = useState(false);
  const [publicError, setPublicError] = useState(false);
  // 누른 값을 곧바로 보인다 — 저장에 실패하면 서버 값으로 돌아간다.
  const [publicOverride, setPublicOverride] = useState<boolean | null>(null);

  const openConfirm = async () => {
    setConfirm({ step: "loading" });
    const result = await fetchQualityEstimate(classId, problemId);
    setConfirm(result.ok ? { step: "ready", estimate: result.data } : { step: "error", message: "불러오지 못했습니다." });
  };

  const run = async () => {
    setConfirm({ step: "running" });
    const result = await runQuality(classId, problemId);
    if (!result.ok) {
      setConfirm({ step: "error", message: result.detail || "채점을 시작하지 못했습니다." });
      return;
    }
    setConfirm({ step: "idle" });
    reload();
  };

  const togglePublic = async (value: boolean) => {
    setPublicSaving(true);
    setPublicError(false);
    setPublicOverride(value);
    const result = await updateProblem(classId, problemId, { quality_public: value });
    setPublicSaving(false);
    if (!result.ok) {
      setPublicError(true);
      setPublicOverride(null);
    }
    reload();
  };

  // 가산(#905) — 저장하면 순위·합계가 바뀌니 다시 읽는다. 대상 시도가 아니면 서버 문구(409)를 그대로 보인다.
  const rateRowBonus = async (submissionId: number, itemId: number, score: number, memo: string) => {
    const result = await rateBonus(classId, problemId, submissionId, itemId, { score, memo });
    if (!result.ok) return result.detail || "저장하지 못했습니다.";
    reload();
    return null;
  };

  const toggleRow = (id: number) =>
    setOpenIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const board = state.status === "ready" ? state.data : null;

  return (
    <Card>
      <CardHeader title="완성도 순위" />
      <div className="flex flex-wrap items-center gap-3 border-b border-rule px-4 py-3">
        <button
          type="button"
          data-testid="quality-run-button"
          onClick={() => void openConfirm()}
          disabled={confirm.step !== "idle" && confirm.step !== "error"}
          className={buttonClass("primary", "sm")}
        >
          완성도 채점
        </button>
        {board ? (
          <label className="flex items-center gap-2 text-[13px]">
            <input
              type="checkbox"
              data-testid="quality-public-switch"
              checked={publicOverride ?? board.quality_public}
              disabled={publicSaving}
              onChange={(event) => void togglePublic(event.target.checked)}
              className="accent-ink"
            />
            참여자에게 공개
          </label>
        ) : null}
        {board && board.queued_count > 0 ? (
          <span data-testid="quality-queued">
            <Badge tone="neutral">
              채점 중 <Num>{board.queued_count}</Num>
            </Badge>
          </span>
        ) : null}
        {board && board.failed_count > 0 ? (
          <span data-testid="quality-failed" className="flex flex-wrap items-center gap-2 text-[12.5px] text-ink/60">
            <Badge tone="attention">
              완성도 채점 실패 <Num>{board.failed_count}</Num>
            </Badge>
            {board.failed_names.join(", ")}
          </span>
        ) : null}
      </div>

      {publicError ? (
        <div className="px-4 pt-3">
          <ErrorNote>
            <span data-testid="quality-public-error">공개 설정을 바꾸지 못했습니다.</span>
          </ErrorNote>
        </div>
      ) : null}

      {confirm.step === "loading" || confirm.step === "running" ? (
        <p data-testid="quality-confirm-loading" className="border-b border-rule px-4 py-3 text-[13px] text-ink/45">
          불러오는 중...
        </p>
      ) : null}
      {confirm.step === "error" ? (
        <div className="border-b border-rule px-4 py-3">
          <ErrorNote>
            <span data-testid="quality-confirm-error">{confirm.message}</span>
          </ErrorNote>
        </div>
      ) : null}
      {confirm.step === "ready" ? (
        <div data-testid="quality-confirm" className="flex flex-col gap-3 border-b border-rule px-4 py-3">
          {confirm.estimate.blocked_reason === "no_api_key" ? (
            <MissingScoringKeyNote
              classId={classId}
              message="이 클래스의 채점 키 문제로 채점할 수 없습니다 — 클래스 설정에서 확인해주세요."
              noteTestId="quality-no-api-key-note"
              settingsLinkTestId="quality-no-api-key-settings-link"
              actionLabel={canChangeKey ? undefined : null}
            />
          ) : confirm.estimate.blocked_reason === "model_rejected" ? (
            <MissingScoringKeyNote
              classId={classId}
              message="이 키로 쓸 수 없는 채점 모델입니다 — 채점 모델을 바꿔주세요."
              noteTestId="quality-model-rejected-note"
              settingsLinkTestId="quality-model-rejected-settings-link"
              actionLabel="채점 모델 바꾸기"
              settingsAnchor="scoring-model"
            />
          ) : (
            <span data-testid="quality-confirm-line" className="text-[13.5px]">
              {confirm.estimate.new_count === 0 ? "새로 채점할 사람이 없습니다" : estimateLine(confirm.estimate)}
            </span>
          )}
          <div className="flex flex-wrap gap-2">
            {confirm.estimate.blocked_reason === null && confirm.estimate.new_count > 0 ? (
              <button
                type="button"
                data-testid="quality-confirm-run"
                onClick={() => void run()}
                className={buttonClass("primary", "sm")}
              >
                채점
              </button>
            ) : null}
            <button
              type="button"
              data-testid="quality-confirm-cancel"
              onClick={() => setConfirm({ step: "idle" })}
              className={buttonClass("secondary", "sm")}
            >
              {confirm.estimate.blocked_reason === null && confirm.estimate.new_count > 0 ? "취소" : "닫기"}
            </button>
          </div>
        </div>
      ) : null}

      {state.status === "error" ? (
        <div className="px-4 py-3">
          <ErrorNote>
            <span data-testid="quality-error">완성도 순위를 불러오지 못했습니다.</span>
          </ErrorNote>
        </div>
      ) : board === null ? null : board.rows.length === 0 ? (
        <EmptyState>
          <span data-testid="quality-empty">아직 완성도가 없습니다.</span>
        </EmptyState>
      ) : (
        <ol data-testid="quality-list" className="divide-y divide-rule">
          {board.rows.map((row) => (
            <QualityRow
              key={row.submission_id}
              row={row}
              open={openIds.has(row.submission_id)}
              onToggle={() => toggleRow(row.submission_id)}
              onRateBonus={rateRowBonus}
            />
          ))}
        </ol>
      )}
    </Card>
  );
}
