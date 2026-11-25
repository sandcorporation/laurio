// 초대 화면이 무엇을 보일지(#561, #1381). 이미 이 클래스의 강사면 초대의 상태와 무관하게
// 클래스로 가는 링크다 — 수락한 사람이 같은 링크를 다시 열어도 「새 링크」를 찾지 않게.
import type { CoInstructorInvitePreview } from "./api";

export type InviteView = "already_instructor" | "unusable" | "acceptable";

export function inviteView(info: Pick<CoInstructorInvitePreview, "status" | "already_instructor">): InviteView {
  if (info.already_instructor) return "already_instructor";
  return info.status === "pending" ? "acceptable" : "unusable";
}
