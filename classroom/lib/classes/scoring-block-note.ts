// 채점이 연결 때문에 멈췄을 때 제출 현황 배너와 「완성도 순위」 확인 단계가 하는 말(#1397). 서버의 사유
// "no_api_key" 하나에 원인 넷(연결 없음·거부됨·크레딧 소진·서버 연결 불가)이 실리므로, 원인은 「채점」 카드와
// 같은 `scoringStatus` 로 가른다. 원인의 낱말과 동사는 알림 문구(`lib/notifications/format.ts`)를 따르고,
// 단추는 문장의 동사를 쓴다. 채점 키는 소유자만 바꾸므로(#561) 공동 강사에게는 소유자에게 부탁하는 문장을 주고
// 단추는 내지 않는다(#1421). 채점 모델은 공동 강사도 문제 편집에서 바꾸므로(`update_problem` owner=False)
// `modelRejectedNote` 는 역할과 상관없이 같은 문장이고 단추만 갈 곳이 다르다(#1425).
import { knownOr } from "../util/known-or";
import { scoringStatus, scoringStatusTone, type ScoringStatus } from "./scoring-status";

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
  classroom:
    | (Parameters<typeof scoringStatus>[0] & {
        role?: "owner" | "co_instructor";
      })
    | null,
  surface: ScoringBlockSurface,
): Note {
  const kind = classroom ? scoringStatus(classroom).kind : "connected";
  const owner = knownOr(OWNER, kind, OWNER.connected);
  // 역할을 모르면(클래스 정보를 못 읽음) 소유자 문구를 주되 단추는 내지 않는다 — 갈 곳이 열릴지 모른다.
  if (classroom?.role === "co_instructor") {
    return {
      message: knownOr(CO_INSTRUCTOR, kind, CO_INSTRUCTOR.connected)[surface],
      actionLabel: null,
    };
  }
  return {
    message: owner[surface],
    actionLabel: classroom?.role === "owner" ? owner.actionLabel : null,
  };
}

// 채점 모델이 키에 거부된 사유(#403) — 모델을 바꾸면 풀리고, 공동 강사도 바꾼다(#1425).
// 거부 표시는 문제 모델을 바꿀 때 그 문제 것이 지워지고, 클래스 기본 모델을 바꿀 때는 모델이 빈 문제만 지워진다.
// 그래서 문제가 자기 모델을 쓰면 역할과 상관없이 문제 편집의 채점 모델 칸으로, 모델이 비었고 소유자면 클래스 설정으로 보낸다(#1429).
export function modelRejectedNote(
  role: "owner" | "co_instructor" | null | undefined,
  classId: number,
  problemId: number,
  problemModel: string | null | undefined = "",
): { message: string; actionLabel: string | null; href: string | null } {
  const message = "이 키로 쓸 수 없는 채점 모델입니다 — 채점 모델을 바꿔주세요.";
  if (role !== "owner" && role !== "co_instructor") return { message, actionLabel: null, href: null };
  const inherits = !problemModel;
  // 공동 강사는 문제 편집에서 그 문제만 고친다 — 같은 기본 모델을 쓰는 다른 문제는 계속 멈춰 있으니
  // 원인이 클래스 기본 모델임을 말하고 소유자에게 부탁하게 한다(#1441-3, 키 사유의 부탁 문장과 짝).
  const ownerAsk =
    role === "co_instructor" && inherits
      ? " 클래스 기본 모델이 원인입니다 — 같은 기본 모델을 쓰는 다른 문제도 멈춰 있으니 소유자에게 클래스 설정의 기본 모델을 바꿔 달라고 하세요."
      : "";
  return {
    message: `${message}${ownerAsk}`,
    actionLabel: "채점 모델 바꾸기",
    href:
      role === "owner" && inherits
        ? `/classes/${classId}/settings#scoring-model`
        : `/classes/${classId}/problems/${problemId}#scoring-model`,
  };
}

/** 「채점」 카드가 공동 강사에게 붙이는 할 일 한 줄(#1431) — 소유자는 카드의 단추가 있으니 없다. */
export function coInstructorCardHint(
  classroom: Parameters<typeof scoringBlockNote>[0],
): string | null {
  if (classroom?.role !== "co_instructor") return null;
  if (scoringStatusTone(scoringStatus(classroom)) !== "warning") return null;
  return scoringBlockNote(classroom, "quality").message;
}

/** 제출 현황에서 펼친 시도가 「채점 대기」면 멈춘 까닭과 고칠 곳(#1436 7번) — 아니면 null.
 * 사유가 모델 거부면 클래스 연결이 아니라 문제의 채점 모델을 말한다(#1425·#1429). */
export function attemptWaitingNote(
  attempt: { status: string; pending_reason?: string | null; problem_id: number; problem_model?: string },
  classroom: Parameters<typeof scoringBlockNote>[0],
  classId: number,
): (Note & { href: string | null; settingsAnchor: string | undefined }) | null {
  if (attempt.status !== "needs_setup") return null;
  if (attempt.pending_reason === "model_rejected") {
    return {
      ...modelRejectedNote(classroom?.role, classId, attempt.problem_id, attempt.problem_model),
      settingsAnchor: "scoring-model",
    };
  }
  return { ...scoringBlockNote(classroom, "submissions"), href: null, settingsAnchor: undefined };
}
