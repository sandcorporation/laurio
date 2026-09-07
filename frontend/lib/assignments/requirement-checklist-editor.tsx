"use client";

// 과제의 Requirement 체크리스트를 쓰는 작은 편집기 (#214, ADR-0028).
//
// `console/contests/_components/requirement-draft-panel.tsx`를 재사용하지 않는다
// (#214 스코프 지시) — 그 패널은 AI grill 대화 사이드바와 상금·상금미달 배지에
// 묶여 있고 과제에는 둘 다 없다(ADR-0028/0029). 여기는 그보다 훨씬 작다: 항목을
// 추가·삭제·순서 변경(위/아래 버튼 — 드래그 앤 드롭 라이브러리를 새로 들이지
// 않는다)하고 각 항목의 본문과 필수/선택 등급만 고른다.
//
// **과제 만들기(#214)와 상세 화면 수정(#217)이 이 컴포넌트를 함께 쓴다** — 백엔드
// 생성·수정 스키마 둘 다 `RequirementIn`(`text`·`grade`) 모양을 받으므로, 화면
// 쪽에서도 같은 편집 상태 모양을 두 자리에서 따로 만들지 않는다.
import { useId } from "react";

export type RequirementDraft = {
  // React key용 — 백엔드로는 나가지 않는다(RequirementIn에는 id가 없다: 생성이든
  // 수정 통째교체든 서버가 새 id를 부여한다).
  key: string;
  text: string;
  grade: "required" | "optional";
};

let draftCounter = 0;

export function createEmptyRequirementDraft(): RequirementDraft {
  draftCounter += 1;
  return { key: `draft-${draftCounter}-${Date.now()}`, text: "", grade: "required" };
}

// 저장된 Requirement(`RequirementOut` — id·order를 갖는다)를 편집 상태로 들여올 때
// 쓴다 — 상세 화면(#217)이 조회 응답을 폼 상태로 바꾸는 유일한 자리다.
export function requirementDraftsFromOut(
  requirements: { id: number; text: string; grade: string }[],
): RequirementDraft[] {
  return requirements.map((r) => ({
    key: `saved-${r.id}`,
    text: r.text,
    grade: r.grade === "optional" ? "optional" : "required",
  }));
}

export function requirementDraftsToIn(
  requirements: RequirementDraft[],
): { text: string; grade: string }[] {
  return requirements
    .filter((r) => r.text.trim() !== "")
    .map((r) => ({ text: r.text.trim(), grade: r.grade }));
}

type Props = {
  requirements: RequirementDraft[];
  onChange: (next: RequirementDraft[]) => void;
  disabled?: boolean;
  testIdPrefix?: string;
};

// 백엔드 `RequirementIn.text`(contests/schemas.py)와 같은 상한 — 화면에서 넘겨도
// 어차피 422로 튕기므로, 여기서 미리 막아 둔다.
const TEXT_MAX_LENGTH = 500;

export function RequirementChecklistEditor({
  requirements,
  onChange,
  disabled = false,
  testIdPrefix = "requirement-editor",
}: Props) {
  const legendId = useId();

  function update(index: number, patch: Partial<RequirementDraft>) {
    onChange(requirements.map((r, i) => (i === index ? { ...r, ...patch } : r)));
  }

  function remove(index: number) {
    onChange(requirements.filter((_, i) => i !== index));
  }

  function moveUp(index: number) {
    if (index === 0) return;
    const next = [...requirements];
    [next[index - 1], next[index]] = [next[index], next[index - 1]];
    onChange(next);
  }

  function moveDown(index: number) {
    if (index === requirements.length - 1) return;
    const next = [...requirements];
    [next[index], next[index + 1]] = [next[index + 1], next[index]];
    onChange(next);
  }

  function add() {
    onChange([...requirements, createEmptyRequirementDraft()]);
  }

  return (
    <fieldset
      className="flex flex-col gap-3"
      aria-labelledby={legendId}
      data-testid={testIdPrefix}
    >
      <legend id={legendId} className="text-sm font-medium">
        요구사항 체크리스트 (선택)
      </legend>

      {requirements.length === 0 ? (
        <p className="text-sm text-ink/60" data-testid={`${testIdPrefix}-empty-hint`}>
          요구사항이 없으면 마감 후 채점이 항목별로 판정할 기준이 없어 점수가 나오지
          않습니다. 지금 비워 두고 나중에 추가할 수 있습니다.
        </p>
      ) : null}

      <ul className="flex flex-col gap-3">
        {requirements.map((requirement, index) => (
          <li
            key={requirement.key}
            className="flex flex-col gap-2 border border-rule p-3"
            data-testid={`${testIdPrefix}-item-${index}`}
          >
            <textarea
              value={requirement.text}
              onChange={(event) => update(index, { text: event.target.value })}
              maxLength={TEXT_MAX_LENGTH}
              rows={2}
              disabled={disabled}
              placeholder="예: 로그인 폼에 이메일 형식 검증이 있다"
              data-testid={`${testIdPrefix}-item-${index}-text`}
              className="border border-rule bg-surface px-3 py-2 text-sm"
            />
            <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
              <select
                value={requirement.grade}
                onChange={(event) =>
                  update(index, {
                    grade: event.target.value === "optional" ? "optional" : "required",
                  })
                }
                disabled={disabled}
                data-testid={`${testIdPrefix}-item-${index}-grade`}
                className="border border-rule bg-surface px-2 py-1"
              >
                <option value="required">필수</option>
                <option value="optional">선택</option>
              </select>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => moveUp(index)}
                  disabled={disabled || index === 0}
                  data-testid={`${testIdPrefix}-item-${index}-up`}
                  className="border border-rule px-2 py-1 disabled:opacity-30"
                >
                  위로
                </button>
                <button
                  type="button"
                  onClick={() => moveDown(index)}
                  disabled={disabled || index === requirements.length - 1}
                  data-testid={`${testIdPrefix}-item-${index}-down`}
                  className="border border-rule px-2 py-1 disabled:opacity-30"
                >
                  아래로
                </button>
                <button
                  type="button"
                  onClick={() => remove(index)}
                  disabled={disabled}
                  data-testid={`${testIdPrefix}-item-${index}-remove`}
                  className="border border-rule px-2 py-1 disabled:opacity-30"
                >
                  삭제
                </button>
              </div>
            </div>
          </li>
        ))}
      </ul>

      <button
        type="button"
        onClick={add}
        disabled={disabled}
        data-testid={`${testIdPrefix}-add`}
        className="w-fit border border-ink px-4 py-2 text-sm hover:bg-ink hover:text-paper disabled:opacity-50"
      >
        + 요구사항 추가
      </button>
    </fieldset>
  );
}
