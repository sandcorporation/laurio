"use client";

// Category 목록의 행 하나(#231). 활성이면 「이름 수정」·「감추기」를, 이미
// 비활성이면 상태만 보여준다 — 되살리는 경로는 이 티켓에 없다(지우지 않고
// 비활성화만 한다는 것은 deliverable-types와 같다).
//
// 이름 수정·감추기 둘 다 이유를 요구한다(정책 변경과 같은 규율, #76) — 그래서
// 버튼 하나로 바로 실행하지 않고, 이유를 적는 인라인 폼을 먼저 연다.
import { useState } from "react";

import { deactivateCategory, renameCategory } from "./actions";
import type { Category } from "./types";

type Mode = "view" | "editing" | "deactivating";

export function CategoryRow({
  category,
  canEdit,
  onChanged,
  onSessionExpired,
}: {
  category: Category;
  canEdit: boolean;
  onChanged: () => void;
  onSessionExpired: () => void;
}) {
  const [mode, setMode] = useState<Mode>("view");
  const [nameInput, setNameInput] = useState(category.name);
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const rowTestId = `category-row-${category.id}`;

  function resetAndClose() {
    setMode("view");
    setReason("");
    setError(null);
    setNameInput(category.name);
  }

  async function handleSaveEdit() {
    setPending(true);
    setError(null);

    const result = await renameCategory(category.id, nameInput, reason);
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

    const result = await deactivateCategory(category.id, reason);
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
      <td data-testid={`${rowTestId}-name`}>
        {mode === "editing" ? (
          <input
            data-testid={`${rowTestId}-edit-name`}
            value={nameInput}
            onChange={(event) => setNameInput(event.target.value)}
          />
        ) : (
          category.name
        )}
      </td>
      <td data-testid={`${rowTestId}-active`}>{category.is_active ? "활성" : "비활성"}</td>
      <td>
        {canEdit && category.is_active && mode === "view" && (
          <>
            <button
              type="button"
              data-testid={`${rowTestId}-edit-button`}
              onClick={() => setMode("editing")}
            >
              이름 수정
            </button>
            <button
              type="button"
              data-testid={`${rowTestId}-deactivate-button`}
              onClick={() => setMode("deactivating")}
            >
              감추기
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
              {pending ? "처리 중..." : "감추기 확정"}
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
