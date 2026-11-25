// 강의실 탭 제목 조립 (#393, #1431). 화면 이름이 맨 앞에 서고, 문제 제목·클래스 이름이 있으면
// 그 뒤에 붙는다 — 「문제 편집 · 반복문 연습 · 파이썬 기초반 · Codemit」. 같은 클래스·문제를 여는
// 화면들(클래스 첫 화면·설정, 문제 편집·제출 현황)이 이름만으로는 탭에서 갈리지 않았다.
// 조각이 하나도 없으면(불러오기 전 포함) 화면 이름만 쓴다.
export type ClassroomTabTitleParts = {
  screenName: string;
  className?: string | null;
  problemTitle?: string | null;
};

function nonEmpty(value: string | null | undefined): value is string {
  return typeof value === "string" && value.trim() !== "";
}

export function buildClassroomTabTitle({
  screenName,
  className,
  problemTitle,
}: ClassroomTabTitleParts): string {
  const label = [screenName, problemTitle, className].filter(nonEmpty).join(" · ");
  return `${label} · Codemit`;
}
