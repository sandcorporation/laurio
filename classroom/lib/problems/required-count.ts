// 강사 문제 표의 「필수」 열 — 참여자 화면의 「필수 n개」·진행 분모와 같은 수다.
// 문법 검사가 켜진 문제는 자동 항목 「소스에 문법 오류가 없다」도 필수로 센다(#1396).
import { requiredSummary } from "../submissions/latest-attempts";

export function problemRequiredCount(problem: {
  checklist_items: ReadonlyArray<{ id: number; label: string; required: boolean }>;
  syntax_check_enabled: boolean;
}): number {
  return requiredSummary({ status: "pending", score: null }, problem.checklist_items, problem.syntax_check_enabled).total;
}
