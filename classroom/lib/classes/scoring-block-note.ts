// 채점이 연결 때문에 멈췄을 때 제출 현황 배너와 「완성도 순위」 확인 단계가 하는 말(#1397). 서버의 사유
// "no_api_key" 하나에 원인 넷(연결 없음·거부됨·크레딧 소진·서버 연결 불가)이 실리므로, 원인은 「채점」 카드와
// 같은 `scoringStatus` 로 가른다. 원인의 낱말과 동사는 알림 문구(`lib/notifications/format.ts`)를 따르고,
// 단추는 문장의 동사를 쓴다. 채점 연결은 소유자만 바꾸므로(#561) 공동 강사에게는 소유자에게 부탁하는 문장을 주고
// 단추는 내지 않는다(#1421).
import { knownOr } from "../util/known-or";
import { scoringStatus, type ScoringStatus } from "./scoring-status";

export type ScoringBlockSurface = "submissions" | "quality";

type Note = { message: string; actionLabel: string | null };

type Entry = Record<ScoringBlockSurface, string> & { actionLabel: string };

// `connected` 는 클래스 정보를 읽은 뒤에 채점이 멈춘 경우다 — 원인을 지어내지 않는다.
const OWNER: Record<ScoringStatus["kind"], Entry> = {
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

// 공동 강사 — 같은 원인에 같은 낱말, 할 수 있는 일(소유자에게 부탁)만 말한다.
const CO_INSTRUCTOR: Record<ScoringStatus["kind"], Record<ScoringBlockSurface, string>> = {
  missing: {
    submissions: "채점 연결이 없어 참여자의 제출이 채점되지 않고 있습니다 — 소유자에게 채점 키를 넣어 달라고 하세요.",
    quality: "채점 연결이 없어 채점할 수 없습니다 — 소유자에게 채점 키를 넣어 달라고 하세요.",
  },
  rejected: {
    submissions: "채점 키가 거부되어 채점이 멈췄습니다 — 소유자에게 새 키를 저장해 달라고 하세요.",
    quality: "채점 키가 거부되어 채점할 수 없습니다 — 소유자에게 새 키를 저장해 달라고 하세요.",
  },
  exhausted: {
    submissions: "채점 키의 크레딧이 떨어져 채점이 멈췄습니다 — 소유자가 충전하면 밀린 제출부터 이어서 채점됩니다.",
    quality: "채점 키의 크레딧이 떨어져 채점할 수 없습니다 — 소유자에게 충전해 달라고 하세요.",
  },
  unreachable: OWNER.unreachable,
  connected: {
    submissions: "채점이 멈춰 있습니다 — 소유자에게 채점 연결을 확인해 달라고 하세요.",
    quality: "지금은 채점할 수 없습니다 — 소유자에게 채점 연결을 확인해 달라고 하세요.",
  },
};

export function scoringBlockNote(
  classroom: (Parameters<typeof scoringStatus>[0] & { role?: "owner" | "co_instructor" }) | null,
  surface: ScoringBlockSurface,
): Note {
  const kind = classroom ? scoringStatus(classroom).kind : "connected";
  const owner = knownOr(OWNER, kind, OWNER.connected);
  // 역할을 모르면(클래스 정보를 못 읽음) 소유자 문구를 주되 단추는 내지 않는다 — 갈 곳이 열릴지 모른다.
  if (classroom?.role === "co_instructor") {
    return { message: knownOr(CO_INSTRUCTOR, kind, CO_INSTRUCTOR.connected)[surface], actionLabel: null };
  }
  return { message: owner[surface], actionLabel: classroom?.role === "owner" ? owner.actionLabel : null };
}
