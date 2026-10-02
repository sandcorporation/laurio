"use client";

// Category 목록의 행 하나(#231, #425 — 골간 표 조각으로 옮긴다). 활성이면
// 「이름 수정」·「감추기」를, 이미 비활성이면 상태만 보여준다 — 되살리는
// 경로는 이 티켓에 없다(지우지 않고 비활성화만 한다는 것은 deliverable-types와
// 같다). 활성 여부는 판정(통과·미충족)이 아니라 상태 정보라 중립 배지에 글자로만
// 갈린다(spec #421 user story 17) — 배지 색을 이 화면에서 새로 쓰지 않는다.
//
// 이름 수정·감추기 둘 다 이유를 요구한다(정책 변경과 같은 규율, #76) — 그래서
// 버튼 하나로 바로 실행하지 않고, 이유를 적는 인라인 폼을 먼저 연다.
import { useState } from "react";

import { Badge } from "@/app/components/badge";

import { deactivateCategory, renameCategory } from "./actions";
import type { Category } from "./types";

type Mode = "view" | "editing" | "deactivating";

export function CategoryRow({
  category,
  canEdit,
  zebra,
  onChanged,
  onSessionExpired,
}: {
  category: Category;
  canEdit: boolean;
  zebra: boolean;
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
    <div
      data-testid={rowTestId}
      className={`flex flex-col gap-2 border-b border-rule px-4 py-2.5 text-[13px] last:border-b-0 ${
        zebra ? "bg-ink/[2%]" : ""
      }`}
    >
      <div className="flex items-center gap-3.5">
        <div className="min-w-0 flex-1 truncate" data-testid={`${rowTestId}-name`}>
          {mode === "editing" ? (
            <input
              data-testid={`${rowTestId}-edit-name`}
              value={nameInput}
              onChange={(event) => setNameInput(event.target.value)}
              className="w-full border border-rule bg-paper px-2 py-1 text-[13px] text-ink"
            />
          ) : (
            category.name
          )}
        </div>
        <div className="w-[70px] shrink-0" data-testid={`${rowTestId}-active`}>
          <Badge>{category.is_active ? "활성" : "비활성"}</Badge>
        </div>
        <div className="flex w-[220px] shrink-0 justify-end gap-2">
          {canEdit && category.is_active && mode === "view" && (
            <>
              <button
                type="button"
                data-testid={`${rowTestId}-edit-button`}
                onClick={() => setMode("editing")}
                className="border border-rule bg-surface px-2.5 py-1 text-[12px] text-ink"
              >
                이름 수정
              </button>
              <button
                type="button"
                data-testid={`${rowTestId}-deactivate-button`}
                onClick={() => setMode("deactivating")}
                className="border border-rule bg-surface px-2.5 py-1 text-[12px] text-ink"
              >
                감추기
              </button>
            </>
          )}
        </div>
      </div>

      {mode === "editing" && (
        <div data-testid={`${rowTestId}-edit-form`} className="flex flex-wrap items-center gap-2">
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
        <div data-testid={`${rowTestId}-deactivate-form`} className="flex flex-wrap items-center gap-2">
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
            {pending ? "처리 중..." : "감추기 확정"}
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
