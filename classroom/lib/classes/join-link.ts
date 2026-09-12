// 가입 링크가 지금 쓸모 있는지 — 보관된 클래스는 새 가입을 받지 않으므로
// (docs/features/classroom.md 「보관」절) 링크도 「다시 뽑기」도 쓸모가
// 없다(#351). 클래스 상세(app/classes/[id]/page.tsx)의 JoinLinkSection이
// 이 값으로 링크를 보여줄지, 왜 못 쓰는지 말할지를 가른다.
export type JoinLinkAvailability = "active" | "archived";

export function joinLinkAvailability(archived: boolean): JoinLinkAvailability {
  return archived ? "archived" : "active";
}
