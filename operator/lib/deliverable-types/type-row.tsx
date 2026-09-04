"use client";

// DeliverableType 목록의 행 하나(#80). 활성이면 「수정」·「비활성화」를, 이미
// 비활성이면 상태만 보여준다 — 되살리는 경로는 이 티켓에 없다(지우지 않고
// 비활성화만 한다는 것이 이 티켓의 전부다).
//
// 수정·비활성화 둘 다 이유를 요구한다(정책 변경과 같은 규율, #76) — 그래서
// 버튼 하나로 바로 실행하지 않고, 이유를 적는 인라인 폼을 먼저 연다.
import { useState } from "react";

import { parseIntegerFieldInput } from "@/lib/forms/parse-integer-field-input";
import { deactivateDeliverableType, updateMinimumPrize } from "./actions";
import type { DeliverableType } from "./types";

type Mode = "view" | "editing" | "deactivating";

export function TypeRow({
  type,
  canEdit,
  onChanged,
  onSessionExpired,
}: {
  type: DeliverableType;
  canEdit: boolean;
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
    <tr data-testid={rowTestId}>
      <td data-testid={`${rowTestId}-name`}>{type.name}</td>
      <td data-testid={`${rowTestId}-minimum-prize`}>
        {mode === "editing" ? (
          <input
            data-testid={`${rowTestId}-edit-minimum-prize`}
            value={minimumPrizeInput}
            onChange={(event) => setMinimumPrizeInput(event.target.value)}
          />
        ) : (
          type.minimum_prize
        )}
      </td>
      <td data-testid={`${rowTestId}-active`}>{type.is_active ? "활성" : "비활성"}</td>
      <td>
        {canEdit && type.is_active && mode === "view" && (
          <>
            <button
              type="button"
              data-testid={`${rowTestId}-edit-button`}
              onClick={() => setMode("editing")}
            >
              최소 제안 상금 수정
            </button>
            <button
              type="button"
              data-testid={`${rowTestId}-deactivate-button`}
              onClick={() => setMode("deactivating")}
            >
              비활성화
            </button>
          </>
        )}

        {mode === "editing" && (
          <div data-testid={`${rowTestId}-edit-form`}>
            <label>
              이유
              <input
                data-testid={`${rowTestId}-edit-reason`}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
              />
            </label>
            <button
              type="button"
              data-testid={`${rowTestId}-edit-save`}
              onClick={handleSaveEdit}
              disabled={pending}
            >
              {pending ? "저장 중..." : "저장"}
            </button>
            <button type="button" onClick={resetAndClose} disabled={pending}>
              취소
            </button>
          </div>
        )}

        {mode === "deactivating" && (
          <div data-testid={`${rowTestId}-deactivate-form`}>
            <label>
              이유
              <input
                data-testid={`${rowTestId}-deactivate-reason`}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
              />
            </label>
            <button
              type="button"
              data-testid={`${rowTestId}-deactivate-confirm`}
              onClick={handleConfirmDeactivate}
              disabled={pending}
            >
              {pending ? "처리 중..." : "비활성화 확정"}
            </button>
            <button type="button" onClick={resetAndClose} disabled={pending}>
              취소
            </button>
          </div>
        )}

        {error && (
          <p role="alert" data-testid={`${rowTestId}-error`}>
            {error}
          </p>
        )}
      </td>
    </tr>
  );
}
