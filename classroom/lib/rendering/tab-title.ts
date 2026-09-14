// 강의실 탭 제목 조립 (#393). 문제 제목·클래스 이름처럼 그 화면을 구체적으로
// 가리키는 조각이 있으면 그것으로 탭을 구별하고, 하나도 없으면(불러오기
// 전을 포함해) 화면 이름만 쓴다 — 「반복문 연습 · 파이썬 기초반 · Codemit」
// 처럼 화면 이름을 굳이 더 얹지 않는다, 문제·클래스 이름 자체가 이미 그
// 화면을 충분히 가리키기 때문이다.
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
  const specific = [problemTitle, className].filter(nonEmpty);
  const label = specific.length > 0 ? specific.join(" · ") : screenName;
  return `${label} · Codemit`;
}
