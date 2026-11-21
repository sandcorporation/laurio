// 운영자 점수 정정 화면(#1183, 스펙 #1178)이 쓰는 타입 — 응답 모양은 생성 타입 그대로다.
import type { components } from "@codemit/bff-client/schema";

export type ScoreCorrectionList = components["schemas"]["ScoreCorrectionListOut"];
export type ScoreCorrection = components["schemas"]["ScoreCorrectionOut"];
export type ScoredSubmission = components["schemas"]["ScoredSubmissionOut"];
export type ScoreCorrectionRequestResult = components["schemas"]["ScoreCorrectionRequestOut"];
