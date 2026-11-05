"use client";

// 체크리스트 항목 줄 — 끌기 손잡이·번호·라벨·필수/선택/가산 배지·배점(1~10, #904)·삭제 (#637).
//
// 문제 편집(항목마다 즉시 저장)과 새 문제(초안, 만들 때 함께 저장)가 이 줄 하나를 쓴다.
// 두 화면은 저장 시점만 다르고 줄의 모양과 순서 바꾸기는 같다.
//
// **순서 바꾸기는 끌기와 키보드 둘 다다.** 손잡이(⋮⋮)를 끌어 놓거나, 손잡이에 포커스를 두고
// 위·아래 화살표를 누른다. 끌기는 네이티브 HTML drag 라 의존성이 없다 — 포인터 없는 환경의
// 길이 키보드다. 줄은 바뀐 순서를 곧바로 보이고(`onReorder` 가 서버 저장을 시작한다), 부모가
// 새 `items` 를 내려주면 그 값으로 다시 맞춘다. `onReorder` 가 `Promise<boolean>` 을 돌려주면
// 그 저장이 끝날 때까지 다음 이동을 막고, 실패하면 `items`(서버 순서)로 되돌린다(#670 —
// `lib/problems/checklist-reorder.ts`).
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

import { Badge, INPUT_CLASS, buttonClass } from "@/app/components/ui";
import { type ChecklistReorderSave, createChecklistMover } from "@/lib/problems/checklist-reorder";
import { BONUS_RATER_LABEL, type ChecklistGrade, GRADE_LABEL, nextGrade } from "@/lib/problems/grade";

export type ChecklistRowItem = { key: string | number; label: string; grade: ChecklistGrade; points: number; hidden?: boolean };

/** 등급 배지 버튼 — 누를 때마다 필수 → 선택 → 가산(#905). 가산이면 「강사가 매김」이 붙는다. */
export function GradeToggle({
  grade,
  onChange,
  testId,
  ariaPrefix,
  disabled = false,
}: {
  grade: ChecklistGrade;
  onChange: (grade: ChecklistGrade) => void;
  testId: string;
  ariaPrefix: string;
  disabled?: boolean;
}): ReactNode {
  return (
    <button
      type="button"
      data-testid={testId}
      data-grade={grade}
      aria-pressed={grade === "required"}
      aria-label={`${ariaPrefix} ${GRADE_LABEL[grade]}`}
      title={grade === "bonus" ? BONUS_RATER_LABEL : undefined}
      disabled={disabled}
      onClick={() => onChange(nextGrade(grade))}
      className="flex shrink-0 items-center gap-1.5 disabled:cursor-not-allowed"
    >
      <Badge tone={grade === "required" ? "verified" : "neutral"}>{GRADE_LABEL[grade]}</Badge>
      {/* 좁은 화면에서는 항목 칸을 지키려고 배지만 둔다(#905). */}
      {grade === "bonus" ? <span className="hidden text-xs text-ink/60 sm:inline">{BONUS_RATER_LABEL}</span> : null}
    </button>
  );
}

/** 배점 선택지 — 1~10 정수(#904). 완성도에만 쓴다. */
export const POINTS_OPTIONS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10] as const;

export function ChecklistRows({
  items,
  rowTestId,
  listTestId,
  readOnly = false,
  lockedStructure = false,
  labelMode,
  onReorder,
  onGradeChange,
  onPointsChange,
  onHiddenChange,
  onDelete,
}: {
  items: ChecklistRowItem[];
  /** 줄 하나의 testid 접두 — `-label-input`·`-required-input`·`-delete`·`-drag-handle` 이 붙는다. */
  rowTestId: (item: ChecklistRowItem, index: number) => string;
  listTestId: string;
  /** 보관된 클래스 — 모든 입력을 잠근다. */
  readOnly?: boolean;
  /** 공모전 문제 — 라벨·필수·순서·삭제 모두 공모전을 따라간다. */
  lockedStructure?: boolean;
  /** 라벨 칸: `commit` 은 포커스를 잃을 때 한 번 저장(편집), `change` 는 칠 때마다(초안). */
  labelMode: { kind: "commit"; onCommit: (key: ChecklistRowItem["key"], label: string) => void } | {
    kind: "change";
    onChange: (key: ChecklistRowItem["key"], label: string) => void;
  };
  onReorder: ChecklistReorderSave<ChecklistRowItem["key"]>;
  onGradeChange: (key: ChecklistRowItem["key"], grade: ChecklistGrade) => void;
  onPointsChange: (key: ChecklistRowItem["key"], points: number) => void;
  /** 「제출자에게 숨기기」(#906) — 있으면 줄마다 스위치를 그린다. */
  onHiddenChange?: (key: ChecklistRowItem["key"], hidden: boolean) => void;
  onDelete: (key: ChecklistRowItem["key"]) => void;
}): ReactNode {
  const [rows, setRows] = useState(items);
  // 부모는 렌더마다 새 배열을 내려주므로 identity 가 아니라 내용(순서·라벨·필수)이 바뀔 때만 맞춘다 —
  // 아니면 끌어 놓은 순서가 저장이 끝나기도 전에 되돌아간다.
  const signature = items
    .map((item) => `${item.key}\u0000${item.label}\u0000${item.grade}\u0000${item.points}\u0000${item.hidden ? 1 : 0}`)
    .join("\u0001");
  useEffect(() => setRows(items), [signature]); // eslint-disable-line react-hooks/exhaustive-deps

  // 옮기기는 렌더 사이에도 지금 값을 읽어야 해서(연타·저장 완료 콜백) ref 로 들고 있다.
  const rowsRef = useRef(rows);
  const itemsRef = useRef(items);
  const onReorderRef = useRef(onReorder);
  useEffect(() => {
    rowsRef.current = rows;
    itemsRef.current = items;
    onReorderRef.current = onReorder;
  });
  const [moveTo] = useState(() =>
    createChecklistMover<ChecklistRowItem>({
      getRows: () => rowsRef.current,
      getServerRows: () => itemsRef.current,
      setRows: (next) => {
        rowsRef.current = next;
        setRows(next);
      },
      save: (keys) => onReorderRef.current(keys),
    }),
  );

  const [dragKey, setDragKey] = useState<ChecklistRowItem["key"] | null>(null);
  const [overIndex, setOverIndex] = useState<number | null>(null);
  const handleRefs = useRef(new Map<ChecklistRowItem["key"], HTMLElement>());
  const refocusKey = useRef<ChecklistRowItem["key"] | null>(null);

  // 키보드로 옮긴 뒤에는 DOM 이 다시 놓이며 포커스가 풀리므로 같은 손잡이에 되돌린다.
  useEffect(() => {
    if (refocusKey.current !== null) {
      handleRefs.current.get(refocusKey.current)?.focus();
      refocusKey.current = null;
    }
  }, [rows]);

  const locked = readOnly || lockedStructure;

  return (
    <ul data-testid={listTestId} className="divide-y divide-rule">
      {rows.map((item, index) => {
        const testId = rowTestId(item, index);
        return (
          <li
            key={item.key}
            data-testid={testId}
            onDragOver={(event) => {
              if (dragKey === null) return;
              event.preventDefault();
              setOverIndex(index);
            }}
            onDrop={(event) => {
              if (dragKey === null) return;
              event.preventDefault();
              moveTo(dragKey, index);
              setDragKey(null);
              setOverIndex(null);
            }}
            className={`flex flex-wrap items-center gap-2.5 px-4 py-2.5 ${
              dragKey !== null && overIndex === index && dragKey !== item.key ? "bg-paper" : ""
            } ${dragKey === item.key ? "opacity-40" : ""}`}
          >
            {locked ? (
              <span aria-hidden className="w-5 shrink-0 text-center text-ink/15">
                ⋮⋮
              </span>
            ) : (
              <span
                ref={(node) => {
                  if (node) handleRefs.current.set(item.key, node);
                  else handleRefs.current.delete(item.key);
                }}
                role="button"
                tabIndex={0}
                draggable
                data-testid={`${testId}-drag-handle`}
                aria-label={`${index + 1}번 항목 순서 바꾸기 — 끌거나 위·아래 화살표`}
                onDragStart={(event) => {
                  event.dataTransfer.effectAllowed = "move";
                  // Firefox 는 setData 가 있어야 끌기가 시작된다.
                  event.dataTransfer.setData("text/plain", String(item.key));
                  const row = event.currentTarget.closest("li");
                  if (row) event.dataTransfer.setDragImage(row, 16, 16);
                  setDragKey(item.key);
                }}
                onDragEnd={() => {
                  setDragKey(null);
                  setOverIndex(null);
                }}
                onKeyDown={(event) => {
                  if (event.key === "ArrowUp" || event.key === "ArrowDown") {
                    event.preventDefault();
                    refocusKey.current = item.key;
                    moveTo(item.key, index + (event.key === "ArrowUp" ? -1 : 1));
                  }
                }}
                className="w-5 shrink-0 cursor-grab text-center select-none text-ink/30 hover:text-ink focus-visible:text-ink focus-visible:outline focus-visible:outline-1 focus-visible:outline-ink active:cursor-grabbing"
              >
                ⋮⋮
              </span>
            )}
            <span className="w-4 shrink-0 font-mono text-[11.5px] text-ink/30">{index + 1}</span>
            {labelMode.kind === "commit" ? (
              <input
                data-testid={`${testId}-label-input`}
                aria-label={`${index + 1}번 항목`}
                defaultValue={item.label}
                disabled={locked}
                onBlur={(event) => {
                  const value = event.target.value.trim();
                  if (value !== "" && event.target.value !== item.label) labelMode.onCommit(item.key, value);
                }}
                className={`${INPUT_CLASS} min-w-0 flex-1`}
              />
            ) : (
              <input
                data-testid={`${testId}-label-input`}
                aria-label={`${index + 1}번 항목`}
                value={item.label}
                disabled={locked}
                onChange={(event) => labelMode.onChange(item.key, event.target.value)}
                className={`${INPUT_CLASS} min-w-0 flex-1`}
              />
            )}
            <GradeToggle
              grade={item.grade}
              onChange={(grade) => onGradeChange(item.key, grade)}
              testId={`${testId}-required-input`}
              ariaPrefix={`${index + 1}번 항목`}
              disabled={locked}
            />
            <select
              data-testid={`${testId}-points-input`}
              aria-label={`${index + 1}번 항목 배점`}
              title="배점"
              value={item.points}
              disabled={locked}
              onChange={(event) => onPointsChange(item.key, Number(event.target.value))}
              className="w-[64px] shrink-0 border border-rule bg-surface px-1.5 py-2 text-[13.5px] text-ink focus:border-ink focus:outline-none disabled:cursor-not-allowed disabled:bg-paper disabled:text-ink/50"
            >
              {POINTS_OPTIONS.map((value) => (
                <option key={value} value={value}>
                  {value}점
                </option>
              ))}
            </select>
            {onHiddenChange ? (
              <label className="flex shrink-0 basis-full items-center gap-1 pl-[30px] text-xs text-ink/70 sm:basis-auto sm:pl-0">
                <input
                  type="checkbox"
                  data-testid={`${testId}-hidden-input`}
                  checked={item.hidden === true}
                  disabled={readOnly}
                  onChange={(event) => onHiddenChange(item.key, event.target.checked)}
                  className="accent-attention"
                />
                제출자에게 숨기기
              </label>
            ) : null}
            {lockedStructure ? null : (
              <button
                type="button"
                data-testid={`${testId}-delete`}
                disabled={readOnly}
                onClick={() => onDelete(item.key)}
                className={`${buttonClass("danger", "sm")} shrink-0`}
              >
                삭제
              </button>
            )}
          </li>
        );
      })}
    </ul>
  );
}
