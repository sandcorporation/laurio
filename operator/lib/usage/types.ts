// 「사용 현황」(#492, 부모 #491)이 쓰는 타입 — 응답 모양은 생성 타입 그대로다
// (lib/appeals/types.ts 와 같은 이유, #148). 응답에는 집계 숫자만 있다 — 사람
// 한 명을 가리키는 값(id·이름)이 애초에 없다.
import type { components } from "@codemit/bff-client/schema";

export type DailyUsage = components["schemas"]["UsageDailyOut"];
export type UsageDay = components["schemas"]["UsageDayOut"];
export type ClassUsage = components["schemas"]["ClassUsageOut"];
