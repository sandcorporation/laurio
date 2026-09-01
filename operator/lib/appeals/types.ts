// 이의 큐·상세(#66)가 백엔드에서 받는 모양. backend/appeals/schemas.py의
// AppealOut/AppealDetailOut/ScoreSnapshotOut/RulingOut과 손으로 맞춘 타입이다 —
// 운영자 앱은 공개 앱과 달리 생성된 openapi 타입을 쓰지 않는다(이 앱에는
// generate:api 스텝이 없다, use-queue-counts.ts가 이미 같은 방식으로 raw fetch
// 응답에 타입만 씌운다).
export type AppealStatus = "pending" | "upheld" | "rejected";

export type AppealSummary = {
  id: number;
  submission_id: number;
  reason: string;
  status: AppealStatus;
  ruling_note: string;
  correction_amount: number | null;
  ruled_at: string | null;
  created_at: string;
};

export type ScoreSnapshot = {
  percentage: string;
  model_version: string;
  reasoning: unknown[];
  created_at: string;
};

export type AppealRuling = {
  decision: "upheld" | "rejected";
  ruled_by_id: number;
  ruled_by_username: string;
  note: string;
  ruled_at: string;
  correction_amount: number | null;
  correction_journal_entry_id: number | null;
};

export type AppealDetail = AppealSummary & {
  score: ScoreSnapshot;
  ruling: AppealRuling | null;
};

export const APPEAL_STATUS_LABELS: Record<AppealStatus, string> = {
  pending: "심판 대기",
  upheld: "인용",
  rejected: "기각",
};
