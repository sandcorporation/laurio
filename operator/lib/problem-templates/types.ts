// 신고된 템플릿 검토(#320)가 쓰는 타입 — 응답 모양은 생성 타입 그대로다
// (lib/appeals/types.ts와 같은 이유, #148).
import type { components } from "@laurio/bff-client/schema";

export type ReportedTemplate = components["schemas"]["ReportedTemplateOut"];
export type ProblemTemplate = components["schemas"]["ProblemTemplateOut"];

export type ModerationDecision = "takedown" | "dismiss";

export const MODERATION_DECISION_LABELS: Record<ModerationDecision, string> = {
  takedown: "내림",
  dismiss: "기각",
};
