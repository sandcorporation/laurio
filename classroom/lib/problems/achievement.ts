// 달성률 표시 문구 (#289/#290, CONTEXT.md 「달성률」) — 문제 중심 탭과 참여자 ×
// 문제 격자의 달성률 행이 같은 함수를 써서 같은 문구를 낸다(#290 AC "달성률
// 행의 값이 문제 중심 탭의 값과 정확히 같다").
//
// 분모가 0이면 "0%"가 아니라 "아직 없음"으로 말한다 — 참여자가 있는데 아무도
// 못 푼 것(0%)과 아직 아무도 없어 집계 자체가 의미 없는 것을 구별해야 한다.
export function formatAchievementRate(problem: {
  passed_count: number;
  member_count: number;
  pass_rate: number | null;
}): string {
  if (problem.member_count === 0 || problem.pass_rate === null) {
    return "아직 없음";
  }
  return `${Math.round(problem.pass_rate * 100)}% (${problem.passed_count}/${problem.member_count}명)`;
}
