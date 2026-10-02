// 클래스 상세의 사용량(#494, 부모 #491) — 응답 모양은 생성 타입 그대로다
// (lib/usage/types.ts 와 같은 이유). 사람 한 명을 가리키는 값(사용자 id·이름·
// 제출 id)은 응답에 애초에 없다 — 클래스·문제의 이름과 집계 숫자뿐이다.
import type { components } from "@codemit/bff-client/schema";

export type ClassUsage = components["schemas"]["UsageClassDetailOut"];
export type ClassUsageProblem = components["schemas"]["UsageProblemOut"];
export type ClassUsageDay = components["schemas"]["UsageClassDayOut"];
