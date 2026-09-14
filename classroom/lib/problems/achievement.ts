// 달성률 표시 문구 (#289/#290, CONTEXT.md 「달성률」) — 문제 중심 탭과 참여자 ×
// 문제 격자의 달성률 행이 같은 함수를 써서 같은 문구를 낸다(#290 AC "달성률
// 행의 값이 문제 중심 탭의 값과 정확히 같다").
//
// 참여자가 0명이면 "0%"가 아니라 "—"로 비운다 — 참여자가 있는데 아무도 못 푼
// 것(0%)과 아직 아무도 없어 집계 자체가 의미 없는 것을 구별해야 한다. 예전에는
// 「아직 없음」이라고 썼는데 「아무도 못 풀었다」로 읽혔고, 좁은 칸에서 줄이
// 밀렸다(2026-09-14). 그 이유는 화면에 글자로 늘어놓지 않고 읽기 도구에만
// `describeAchievementRate`로 말한다.
type AchievementInput = {
  passed_count: number;
  member_count: number;
  pass_rate: number | null;
};

function hasMembers(problem: AchievementInput): boolean {
  return problem.member_count !== 0 && problem.pass_rate !== null;
}

export function formatAchievementRate(problem: AchievementInput): string {
  if (!hasMembers(problem)) return "—";
  return `${Math.round((problem.pass_rate as number) * 100)}% · ${problem.passed_count}/${problem.member_count}명`;
}

/** 읽기 도구용 — 「—」가 무엇을 뜻하는지 말로 풀어 준다. */
export function describeAchievementRate(problem: AchievementInput): string {
  return `달성률 ${hasMembers(problem) ? formatAchievementRate(problem) : "참여자 없음"}`;
}
