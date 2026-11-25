"use client";

// 이름을 적던 중 클래스 접근을 잃었을 때, 저장되지 않은 값을 안내 곁에 남긴다(#1447 11).
// 읽기 전용 칸이라 고르거나 복사할 수 있고, 복사 단추는 한 번에 담는다.
import { useState } from "react";

import { ErrorNote, FieldLabel, INPUT_CLASS, Note, buttonClass } from "@/app/components/ui";
import type { ClassNamesPatch } from "@/lib/classes/name-patch";

export function UnsavedNames({ patch, error }: { patch: ClassNamesPatch; error: string | null }) {
  const [copyResult, setCopyResult] = useState("");
  const rows: { id: string; label: string; value: string }[] = [];
  if (patch.name !== undefined) rows.push({ id: "name", label: "클래스 이름", value: patch.name });
  if (patch.instructor_display_name !== undefined) {
    rows.push({ id: "instructor", label: "내 강사 이름", value: patch.instructor_display_name });
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(rows.map((r) => r.value).join("\n"));
      setCopyResult("복사했습니다.");
    } catch {
      setCopyResult("복사하지 못했습니다. 값을 직접 선택해 복사하세요.");
    }
  }

  return (
    <div className="mt-4" data-testid="class-unsaved-names">
      <Note tone="warning">
        <div className="flex flex-col gap-2.5">
          <span>저장되지 않은 값</span>
          {rows.map((row) => (
            <div key={row.id} className="flex flex-col gap-1">
              <label htmlFor={`class-unsaved-${row.id}`}>
                <FieldLabel>{row.label}</FieldLabel>
              </label>
              <input
                id={`class-unsaved-${row.id}`}
                data-testid={`class-unsaved-${row.id}`}
                readOnly
                value={row.value}
                className={INPUT_CLASS}
              />
            </div>
          ))}
          <div className="flex items-center gap-3">
            <button type="button" data-testid="class-unsaved-copy" onClick={copy} className={buttonClass("secondary", "sm")}>
              복사
            </button>
            <span role="status" data-testid="class-unsaved-copy-result" className="text-[12.5px] text-ink/60">
              {copyResult}
            </span>
          </div>
          {error ? (
            <ErrorNote>
              <span data-testid="class-unsaved-error">{error}</span>
            </ErrorNote>
          ) : null}
        </div>
      </Note>
    </div>
  );
}
