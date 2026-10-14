// 클래스 상세의 탭 셋(#633, 시안 v2). 주소가 탭을 말한다 — 새로 고쳐도, 링크를 보내도 그 탭이다.
//
//   /classes/{id}                    문제 탭(기본)
//   /classes/{id}?tab=participants   참여자 탭
//   /classes/{id}?tab=instructors    강사 탭
//
// 모르는 값은 문제 탭으로 떨어진다. 참여자·강사 탭의 내용은 각자 티켓(#634·#635)이 이 자리에 짠다.
export const DETAIL_TABS = ["problems", "participants", "instructors"] as const;
export type DetailTab = (typeof DETAIL_TABS)[number];

export const DETAIL_TAB_LABEL: Record<DetailTab, string> = {
  problems: "문제",
  participants: "참여자",
  instructors: "강사",
};

export function parseDetailTab(raw: string | null): DetailTab {
  return (DETAIL_TABS as readonly string[]).includes(raw ?? "") ? (raw as DetailTab) : "problems";
}

export function detailTabHref(classId: number, tab: DetailTab): string {
  return tab === "problems" ? `/classes/${classId}` : `/classes/${classId}?tab=${tab}`;
}
