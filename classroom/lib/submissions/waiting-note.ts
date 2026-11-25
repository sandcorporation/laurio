// 채점이 강사 쪽 설정(채점 키·채점 모델) 때문에 멈춘 시도 옆의 한 줄(#346·#1422).
// 참여자에게는 다시 낼 필요가 없다는 것이, 강사 본인의 시도에는 풀어야 할 일이 말이 된다 — 채점 키와
// 채점 모델은 소유자만 바꾸므로(#561) 공동 강사에게는 소유자에게 부탁하라고 한다.
export type WaitingReason = "no_api_key" | "model_rejected";
export type ViewerRole = "owner" | "co_instructor" | null | undefined;

export function waitingNote(reason: WaitingReason, viewerRole: ViewerRole): string {
  if (viewerRole === "owner") {
    return reason === "no_api_key"
      ? "채점 키를 넣으면 이어서 채점됩니다"
      : "채점 모델을 바꾸면 이어서 채점됩니다";
  }
  if (viewerRole === "co_instructor") {
    return reason === "no_api_key"
      ? "소유자에게 채점 키를 넣어 달라고 하세요"
      : "소유자에게 채점 모델을 바꿔 달라고 하세요";
  }
  return "강사의 채점 설정 때문에 멈췄습니다 — 다시 낼 필요 없습니다";
}
