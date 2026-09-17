// 클래스 설정의 「이름」 카드가 저장 버튼 하나로 클래스 이름과 강사 이름을
// 함께 받는다. 바뀐 칸만 PATCH 에 싣는다 — 안 바뀐 칸까지 보내면 다른 탭에서
// 방금 고친 값을 이 화면의 옛 값으로 덮는다. 둘 다 비울 수 없는 값이라 한쪽이
// 비어 있으면 아무것도 보내지 않는다(버튼도 꺼진다).

export type ClassNames = { name: string; instructorDisplayName: string };

export type ClassNamesPatch = Partial<{ name: string; instructor_display_name: string }>;

export function classNamesPatch(saved: ClassNames, draft: ClassNames): ClassNamesPatch | null {
  const name = draft.name.trim();
  const instructorDisplayName = draft.instructorDisplayName.trim();
  if (name === "" || instructorDisplayName === "") return null;

  const patch: ClassNamesPatch = {};
  if (name !== saved.name) patch.name = name;
  if (instructorDisplayName !== saved.instructorDisplayName) {
    patch.instructor_display_name = instructorDisplayName;
  }
  return Object.keys(patch).length === 0 ? null : patch;
}
