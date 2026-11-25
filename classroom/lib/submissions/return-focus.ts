import type { SubmitBlockedReason } from "./api";
import { blockedChange } from "./blocked-change";

// 숨김 안내로 바뀌었다가 제출 화면으로 돌아올 때(#1528·#1535 ②) 할 일을 정하는 판단 — 화면 배선은 이 결과만 따른다.
// 안내 문구 비우기·채우기와 초점 옮기기는 따로 정한다: 문구는 지금 막힘 여부가, 초점은 사라진 안내 안에 있었는지가 가른다.
export type ReturnState = {
  // 조회 상태. loading 은 화면을 바꾸지 않는 사이라 판단하지 않는다.
  status: "loading" | "ready" | "notFound" | "error";
  // 숨김 안내(폼을 잃은 화면)로 바뀐 적이 있고 아직 돌아오지 않았다.
  lost: boolean;
  // 이전 조회에서 폼이 보였다 — notFound 가 폼을 잃은 것인지 가른다.
  hadForm: boolean;
  reason: SubmitBlockedReason;
  // 지금 초점이 body(또는 없음)이면 사라진 안내와 함께 떨어진 것이다. 다른 칸이면 빼앗지 않는다.
  focusAtBody: boolean;
  hasDraft: boolean;
};

export type ReturnAction = {
  lost: boolean;
  // null 이면 지금 안내를 그대로 둔다(loading).
  note: string | null;
  focus: "none" | "blocked-note" | "draft" | "title";
};

export function returnAction(s: ReturnState): ReturnAction {
  if (s.status === "loading") return { lost: s.lost, note: null, focus: "none" };
  // 다시 엶 안내는 ready 화면의 것이다 — 숨김·오류 화면으로 바뀌면 비워야 다음 다시 엶에서 비었다 채워져 또 읽힌다.
  // 오류는 숨김 안내에서 폼을 잃은 사실을 지우지 않는다(오류 뒤 회복에도 초점 복구가 남는다).
  if (s.status === "notFound") return { lost: s.lost || s.hadForm, note: "", focus: "none" };
  if (s.status === "error") return { lost: s.lost, note: "", focus: "none" };
  // ready: 막혔으면 「제출할 수 있습니다」는 걷고 이유는 막힘 안내가 말한다 — 초점은 사라진 안내 안에 있었을 때 그 안내로.
  if (s.reason !== null) {
    return { lost: false, note: "", focus: s.lost && s.focusAtBody ? "blocked-note" : "none" };
  }
  if (!s.lost) return { lost: false, note: "", focus: "none" };
  const note = blockedChange("hidden", null).note;
  if (!s.focusAtBody) return { lost: false, note, focus: "none" };
  return { lost: false, note, focus: s.hasDraft ? "draft" : "title" };
}
