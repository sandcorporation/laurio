"use client";

// DeliverableType 목록의 행 하나(#80, #425 — 골간 표 조각으로 옮긴다). 활성이면
// 「수정」·「비활성화」를, 이미 비활성이면 상태만 보여준다 — 되살리는 경로는
// 이 티켓에 없다(지우지 않고 비활성화만 한다는 것이 이 티켓의 전부다). 활성
// 여부는 판정(통과·미충족)이 아니라 상태 정보라 중립 배지에 글자로만 갈린다
// (spec #421 user story 17).
//
// 수정·비활성화 둘 다 이유를 요구한다(정책 변경과 같은 규율, #76) — 그래서
// 버튼 하나로 바로 실행하지 않고, 이유를 적는 인라인 폼을 먼저 연다.
import { useState } from "react";

import { Badge } from "@/app/components/badge";
import { parseIntegerFieldInput } from "@/lib/forms/parse-integer-field-input";

import { deactivateDeliverableType, updateMinimumPrize } from "./actions";
import type { DeliverableType } from "./types";

type Mode = "view" | "editing" | "deactivating";

export function TypeRow({
  type,
  canEdit,
  zebra,
  onChanged,
  onSessionExpired,
}: {
  type: DeliverableType;
  canEdit: boolean;
  zebra: boolean;
  onChanged: () => void;
  onSessionExpired: () => void;
}) {
  const [mode, setMode] = useState<Mode>("view");
  const [minimumPrizeInput, setMinimumPrizeInput] = useState(String(type.minimum_prize));
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const rowTestId = `deliverable-type-row-${type.id}`;

  function resetAndClose() {
    setMode("view");
    setReason("");
    setError(null);
    setMinimumPrizeInput(String(type.minimum_prize));
  }

  async function handleSaveEdit() {
    setPending(true);
    setError(null);

    // `Number("")`가 NaN이 아니라 0이라는 함정 때문에(코드리뷰 지적) 빈
    // 입력칸이 조용히 "최소 제안 상금 0원"으로 저장될 뻔했다 — 그러면 그
    // 종류의 "상금미달" 배지 판정이 사실상 꺼진다. parseIntegerFieldInput이
    // 빈 문자열·숫자 아닌 문자열을 구분해, 서버의 422로 명시적으로 거절되게
    // 한다(policy-editor.tsx와 같은 방어를 여기서 다시 손으로 만들지 않는다).
    const parsed = parseIntegerFieldInput(minimumPrizeInput);
    const result = await updateMinimumPrize(
      type.id,
      parsed.valid ? parsed.value : (parsed.raw as unknown as number),
      reason,
    );
    setPending(false);

    if (!result.ok) {
      if (result.code === "unauthorized") {
        onSessionExpired();
        return;
      }
      setError(result.detail);
      return;
    }

    setMode("view");
    setReason("");
    onChanged();
  }

  async function handleConfirmDeactivate() {
    setPending(true);
    setError(null);

    const result = await deactivateDeliverableType(type.id, reason);
    setPending(false);

    if (!result.ok) {
      if (result.code === "unauthorized") {
        onSessionExpired();
        return;
      }
      setError(result.detail);
      return;
    }

    setMode("view");
    setReason("");
    onChanged();
  }

  return (
    <div
      data-testid={rowTestId}
      className={`flex flex-col gap-2 border-b border-rule px-4 py-2.5 text-[13px] last:border-b-0 ${
        zebra ? "bg-ink/[2%]" : ""
      }`}
    >
      <div className="flex items-center gap-3.5">
        <div className="min-w-0 flex-1 truncate" data-testid={`${rowTestId}-name`}>
          {type.name}
        </div>
        <div className="w-[140px] shrink-0 text-right" data-testid={`${rowTestId}-minimum-prize`}>
          {mode === "editing" ? (
            <input
              data-testid={`${rowTestId}-edit-minimum-prize`}
              value={minimumPrizeInput}
              onChange={(event) => setMinimumPrizeInput(event.target.value)}
              className="w-full border border-rule bg-paper px-2 py-1 text-right font-mono text-[13px] text-ink"
            />
          ) : (
            <span className="font-mono">{type.minimum_prize}</span>
          )}
        </div>
        <div className="w-[70px] shrink-0" data-testid={`${rowTestId}-active`}>
          <Badge>{type.is_active ? "활성" : "비활성"}</Badge>
        </div>
        <div className="flex w-[220px] shrink-0 justify-end gap-2">
          {canEdit && type.is_active && mode === "view" && (
            <>
              <button
                type="button"
                data-testid={`${rowTestId}-edit-button`}
                onClick={() => setMode("editing")}
                className="border border-rule bg-surface px-2.5 py-1 text-[12px] text-ink"
              >
                최소 제안 상금 수정
              </button>
              <button
                type="button"
                data-testid={`${rowTestId}-deactivate-button`}
                onClick={() => setMode("deactivating")}
                className="border border-rule bg-surface px-2.5 py-1 text-[12px] text-ink"
              >
                비활성화
              </button>
            </>
          )}
        </div>
      </div>

      {mode === "editing" && (
        <div data-testid={`${rowTestId}-edit-form`} className="flex items-center gap-2">
          <label className="flex items-center gap-1.5 text-[12.5px] text-ink/62">
            이유
            <input
              data-testid={`${rowTestId}-edit-reason`}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              className="border border-rule bg-paper px-2 py-1 text-[12.5px] text-ink"
            />
          </label>
          <button
            type="button"
            data-testid={`${rowTestId}-edit-save`}
            onClick={handleSaveEdit}
            disabled={pending}
            className="border border-ink bg-ink px-2.5 py-1 text-[12px] text-paper disabled:opacity-50"
          >
            {pending ? "저장 중..." : "저장"}
          </button>
          <button
            type="button"
            onClick={resetAndClose}
            disabled={pending}
            className="border border-rule bg-surface px-2.5 py-1 text-[12px] text-ink disabled:opacity-50"
          >
            취소
          </button>
        </div>
      )}

      {mode === "deactivating" && (
        <div data-testid={`${rowTestId}-deactivate-form`} className="flex items-center gap-2">
          <label className="flex items-center gap-1.5 text-[12.5px] text-ink/62">
            이유
            <input
              data-testid={`${rowTestId}-deactivate-reason`}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              className="border border-rule bg-paper px-2 py-1 text-[12.5px] text-ink"
            />
          </label>
          <button
            type="button"
            data-testid={`${rowTestId}-deactivate-confirm`}
            onClick={handleConfirmDeactivate}
            disabled={pending}
            className="border border-attention bg-attention px-2.5 py-1 text-[12px] text-paper disabled:opacity-50"
          >
            {pending ? "처리 중..." : "비활성화 확정"}
          </button>
          <button
            type="button"
            onClick={resetAndClose}
            disabled={pending}
            className="border border-rule bg-surface px-2.5 py-1 text-[12px] text-ink disabled:opacity-50"
          >
            취소
          </button>
        </div>
      )}

      {error && (
        <p role="alert" data-testid={`${rowTestId}-error`} className="text-[12px] text-attention">
          {error}
        </p>
      )}
    </div>
  );
}
