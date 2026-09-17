import { describe, expect, it } from "vitest";

import type { ProblemTemplateListItem, ProblemTemplateRow } from "./api";
import { selectPickerCandidate } from "./picker-selection";
import type { ImportableProblemRow } from "../problems/api";

const publicItem: ProblemTemplateListItem = {
  share_code: "abc",
  title: "fetch 로 목록 그리기",
  publisher_display_name: "김강사",
  created_at: "2026-09-01T00:00:00Z",
};

const publicDetail: ProblemTemplateRow = {
  id: 1,
  share_code: "abc",
  title: "fetch 로 목록 그리기",
  description: "설명입니다",
  submission_formats: ["source"],
  grading_strictness: "normal",
  grading_guideline_text: "",
  syntax_check_enabled: true,
  publisher_display_name: "김강사",
  created_at: "2026-09-01T00:00:00Z",
  taken_down: false,
  checklist_items: [{ label: "항목1", required: true, order: 0 }],
  is_mine: false,
};

const mineItem: ProblemTemplateRow = {
  ...publicDetail,
  share_code: "mine-1",
};

const otherItem: ImportableProblemRow = {
  id: 10,
  classroom_id: 5,
  classroom_name: "웹 스터디",
  title: "다른 클래스 문제",
  description: "다른 클래스 설명",
  submission_formats: ["repository"],
  syntax_check_enabled: false,
  checklist_items: [{ label: "다른항목", required: false, order: 0 }],
};

describe("selectPickerCandidate", () => {
  it("고른 항목이 없으면 null이다", () => {
    expect(
      selectPickerCandidate({
        tab: "public",
        selectedKey: null,
        publicItems: [publicItem],
        publicDetail: null,
        mineItems: null,
        otherItems: null,
      }),
    ).toBeNull();
  });

  it("공개 탭은 목록 항목과 상세를 합쳐 보여준다", () => {
    const result = selectPickerCandidate({
      tab: "public",
      selectedKey: "public:abc",
      publicItems: [publicItem],
      publicDetail,
      mineItems: null,
      otherItems: null,
    });
    expect(result).toEqual({
      key: "public:abc",
      title: "fetch 로 목록 그리기",
      meta: "김강사 · 2026. 9. 1. 공개",
      description: "설명입니다",
      checklistItems: [{ label: "항목1", required: true, order: 0 }],
    });
  });

  it("상세가 아직 다른 항목의 것이면(또는 없으면) 설명·체크리스트는 null이다", () => {
    const result = selectPickerCandidate({
      tab: "public",
      selectedKey: "public:abc",
      publicItems: [publicItem],
      publicDetail: null,
      mineItems: null,
      otherItems: null,
    });
    expect(result?.description).toBeNull();
    expect(result?.checklistItems).toBeNull();

    const stale = selectPickerCandidate({
      tab: "public",
      selectedKey: "public:abc",
      publicItems: [publicItem],
      publicDetail: { ...publicDetail, share_code: "other-code" },
      mineItems: null,
      otherItems: null,
    });
    expect(stale?.description).toBeNull();
  });

  it("내가 올린 것 탭은 목록 항목 자체에 설명·체크리스트가 있다", () => {
    const result = selectPickerCandidate({
      tab: "mine",
      selectedKey: "mine:mine-1",
      publicItems: null,
      publicDetail: null,
      mineItems: [mineItem],
      otherItems: null,
    });
    expect(result).toEqual({
      key: "mine:mine-1",
      title: "fetch 로 목록 그리기",
      meta: "2026. 9. 1. 공개",
      description: "설명입니다",
      checklistItems: [{ label: "항목1", required: true, order: 0 }],
    });
  });

  it("내 다른 클래스에서 탭은 클래스 이름을 meta로 쓴다", () => {
    const result = selectPickerCandidate({
      tab: "other-classes",
      selectedKey: "other:10",
      publicItems: null,
      publicDetail: null,
      mineItems: null,
      otherItems: [otherItem],
    });
    expect(result).toEqual({
      key: "other:10",
      title: "다른 클래스 문제",
      meta: "웹 스터디",
      description: "다른 클래스 설명",
      checklistItems: [{ label: "다른항목", required: false, order: 0 }],
    });
  });

  it("목록이 아직 준비되지 않았으면(null) null이다", () => {
    expect(
      selectPickerCandidate({
        tab: "mine",
        selectedKey: "mine:mine-1",
        publicItems: null,
        publicDetail: null,
        mineItems: null,
        otherItems: null,
      }),
    ).toBeNull();
  });

  it("선택된 키가 지금 목록에 없으면(탭이 바뀌었거나 목록이 좁혀졌으면) null이다", () => {
    expect(
      selectPickerCandidate({
        tab: "public",
        selectedKey: "public:missing",
        publicItems: [publicItem],
        publicDetail: null,
        mineItems: null,
        otherItems: null,
      }),
    ).toBeNull();
  });
});
