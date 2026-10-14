// 클래스 상세 「채점」 카드의 상태 한 줄(#633). 새 조건을 만들지 않는다 — 예전 배너 넷
// (`missing-scoring-key-banner.ts`)의 조건을 그대로 순서대로 읽는다: 연결 없음 → 거부됨 →
// 크레딧 소진 → 서버 연결 불가, 어느 것도 아니면 연결됨. 보관된 클래스는 새 제출을 받지
// 않으므로 배너가 뜨지 않던 것처럼 문제로 치지 않는다.
import {
  shouldShowExhaustedCreditBanner,
  shouldShowMissingScoringKeyBanner,
  shouldShowRejectedScoringKeyBanner,
  shouldShowUnreachableServerBanner,
} from "./missing-scoring-key-banner";

type StatusInput = {
  archived: boolean;
  has_openai_key: boolean;
  openai_key_status: "verified" | "unverified" | "rejected" | null;
  scoring_quota_exhausted: boolean;
  scoring_server_unreachable: boolean;
  scoring_connection_kind: string;
  openai_key_masked: string | null;
  scoring_server_host: string | null;
};

export type ScoringStatus =
  | { kind: "connected"; connection: string }
  | { kind: "missing"; problem: boolean }
  | { kind: "rejected" }
  | { kind: "exhausted" }
  | { kind: "unreachable" };

export const SCORING_STATUS_LABEL = {
  connected: "연결됨",
  missing: "연결 없음",
  rejected: "거부됨",
  exhausted: "크레딧 소진",
  unreachable: "서버 연결 불가",
} as const;

/** 「OpenAI 키 · sk-…7f2a」 / 「호환 서버 · host」 — 종류와 마스킹된 식별자. */
export function describeConnection(c: StatusInput): string {
  if (c.scoring_connection_kind === "compatible_server") {
    return c.scoring_server_host ? `호환 서버 · ${c.scoring_server_host}` : "호환 서버";
  }
  return c.openai_key_masked ? `OpenAI 키 · ${c.openai_key_masked}` : "OpenAI 키";
}

export function scoringStatus(c: StatusInput): ScoringStatus {
  if (shouldShowMissingScoringKeyBanner(c)) return { kind: "missing", problem: true };
  if (shouldShowRejectedScoringKeyBanner(c)) return { kind: "rejected" };
  if (shouldShowExhaustedCreditBanner(c)) return { kind: "exhausted" };
  if (shouldShowUnreachableServerBanner(c)) return { kind: "unreachable" };
  if (!c.has_openai_key) return { kind: "missing", problem: false };
  return { kind: "connected", connection: describeConnection(c) };
}

/** 배지 톤 — 문제(연결 없음·거부·소진·연결 불가)는 attention, 연결됨은 verified, 보관 클래스의 「연결 없음」은
 * 문제가 아니라 neutral. 클래스 상세의 채점 카드와 설정의 상태 한 줄이 같이 쓴다(#669). */
export function scoringStatusTone(status: ScoringStatus): "verified" | "attention" | "neutral" {
  if (status.kind === "connected") return "verified";
  if (status.kind === "missing" && !status.problem) return "neutral";
  return "attention";
}

/** 설정의 상태 한 줄(#669) — 카드와 같은 낱말·톤에, 아직 검증되지 않은 OpenAI 키면 「미검증」만 덧붙인다. */
export function settingsStatusBadges(c: StatusInput): { label: string; tone: "verified" | "attention" | "neutral" }[] {
  const status = scoringStatus(c);
  const badges: { label: string; tone: "verified" | "attention" | "neutral" }[] = [
    { label: SCORING_STATUS_LABEL[status.kind], tone: scoringStatusTone(status) },
  ];
  if (status.kind === "connected" && c.scoring_connection_kind === "openai_key" && c.openai_key_status === "unverified") {
    badges.push({ label: "미검증", tone: "neutral" });
  }
  return badges;
}
