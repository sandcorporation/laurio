// 채점이 연결 때문에 멈췄을 때 제출 현황 배너와 「완성도 순위」 확인 단계가 하는 말(#1397). 서버의 사유
// "no_api_key" 하나에 원인 넷(연결 없음·거부됨·크레딧 소진·서버 연결 불가)이 실리므로, 원인은 「채점」 카드와
// 같은 `scoringStatus` 로 가른다. 원인의 낱말과 동사는 알림 문구(`lib/notifications/format.ts`)를 따르고,
// 단추는 문장의 동사를 쓴다.
import { knownOr } from "../util/known-or";
import { scoringStatus, type ScoringStatus } from "./scoring-status";

export type ScoringBlockSurface = "submissions" | "quality";

type Note = { message: string; actionLabel: string };

// `connected` 는 클래스 정보를 읽은 뒤에 채점이 멈춘 경우다 — 원인을 지어내지 않는다.
const NOTES: Record<ScoringStatus["kind"], Record<ScoringBlockSurface, string> & { actionLabel: string }> = {
  missing: {
    submissions:
      "채점 연결이 없어 참여자의 제출이 채점되지 않고 있습니다 — 클래스 설정에서 채점 키를 넣으면 밀린 제출부터 채점됩니다.",
    quality: "채점 연결이 없어 채점할 수 없습니다 — 클래스 설정에서 채점 키를 넣어 주세요.",
    actionLabel: "클래스 설정에서 넣기",
  },
  rejected: {
    submissions: "채점 키가 거부되어 채점이 멈췄습니다 — 클래스 설정에서 새 키를 저장해 주세요.",
    quality: "채점 키가 거부되어 채점할 수 없습니다 — 클래스 설정에서 새 키를 저장해 주세요.",
    actionLabel: "클래스 설정에서 저장하기",
  },
  exhausted: {
    submissions: "채점 키의 크레딧이 떨어져 채점이 멈췄습니다 — 충전하면 밀린 제출부터 이어서 채점됩니다.",
    quality: "채점 키의 크레딧이 떨어져 채점할 수 없습니다 — 충전해 주세요.",
    actionLabel: "클래스 설정 열기",
  },
  unreachable: {
    submissions: "채점 서버에 닿지 않아 채점이 멈췄습니다 — 서버가 다시 열리면 밀린 제출부터 이어서 채점됩니다.",
    quality: "채점 서버에 닿지 않아 채점할 수 없습니다 — 서버가 다시 열리면 채점할 수 있습니다.",
    actionLabel: "클래스 설정 열기",
  },
  connected: {
    submissions: "채점이 멈춰 있습니다 — 클래스 설정에서 채점 연결을 확인해 주세요.",
    quality: "지금은 채점할 수 없습니다 — 클래스 설정에서 채점 연결을 확인해 주세요.",
    actionLabel: "클래스 설정 열기",
  },
};

export function scoringBlockNote(
  classroom: Parameters<typeof scoringStatus>[0] | null,
  surface: ScoringBlockSurface,
): Note {
  const note = knownOr(NOTES, classroom ? scoringStatus(classroom).kind : "connected", NOTES.connected);
  return { message: note[surface], actionLabel: note.actionLabel };
}
