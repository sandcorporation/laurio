// 템플릿 선택 시트(#443, 부모 #432)가 왼쪽에서 고른 항목을 오른쪽 상세에
// 무엇으로 그릴지 — 순수 함수로 뽑아 둔다. 세 탭이 서로 다른 자원(공개된
// 문제·내가 올린 것·내 다른 클래스에서)이라 항목의 모양이 갈리는데, 이
// 함수 하나가 그 셋을 공통 미리보기 모양으로 좁힌다. 가져오기 실행
// (`runImport`)은 API 호출이라 이 함수 밖(컴포넌트)에 남는다.
import type { ImportableProblemRow } from "@/lib/problems/api";

import type { ProblemTemplateListItem, ProblemTemplateRow } from "./api";

export type PickerTab = "public" | "mine" | "other-classes";

export type PickerCandidatePreview = {
  key: string;
  title: string;
  meta: string;
  description: string | null;
  checklistItems: { label: string; required: boolean }[] | null;
};

export function formatPickerDate(value: string): string {
  return new Date(value).toLocaleDateString("ko-KR");
}

export function selectPickerCandidate(input: {
  tab: PickerTab;
  selectedKey: string | null;
  /** `null`이면 아직 준비되지 않은 목록이다(불러오는 중·오류). */
  publicItems: ProblemTemplateListItem[] | null;
  /** 공개 템플릿은 목록에 설명·체크리스트가 없어 고른 항목의 상세를 따로
   *  받는다 — 지금 상세가 고른 항목의 것이 아니면(다른 항목을 고른 직후,
   *  아직 새 상세가 오기 전) 호출부가 `null`을 넘긴다. */
  publicDetail: ProblemTemplateRow | null;
  mineItems: ProblemTemplateRow[] | null;
  otherItems: ImportableProblemRow[] | null;
}): PickerCandidatePreview | null {
  const { tab, selectedKey, publicItems, publicDetail, mineItems, otherItems } = input;
  if (!selectedKey) return null;

  if (tab === "public") {
    if (!publicItems) return null;
    const item = publicItems.find((i) => `public:${i.share_code}` === selectedKey);
    if (!item) return null;
    const detail = publicDetail && publicDetail.share_code === item.share_code ? publicDetail : null;
    return {
      key: selectedKey,
      title: item.title,
      meta: `${item.publisher_display_name} · ${formatPickerDate(item.created_at)} 공개`,
      description: detail?.description ?? null,
      checklistItems: detail?.checklist_items ?? null,
    };
  }

  if (tab === "mine") {
    if (!mineItems) return null;
    const item = mineItems.find((i) => `mine:${i.share_code}` === selectedKey);
    if (!item) return null;
    return {
      key: selectedKey,
      title: item.title,
      meta: `${formatPickerDate(item.created_at)} 공개`,
      description: item.description,
      checklistItems: item.checklist_items,
    };
  }

  if (!otherItems) return null;
  const item = otherItems.find((i) => `other:${i.id}` === selectedKey);
  if (!item) return null;
  return {
    key: selectedKey,
    title: item.title,
    meta: item.classroom_name,
    description: item.description,
    checklistItems: item.checklist_items,
  };
}
