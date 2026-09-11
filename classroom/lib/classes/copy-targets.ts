// 대상 클래스 고르기 — 문제 복사(「다른 클래스로 복사」)와 템플릿 가져오기
// (/templates/{shareCode})가 같이 쓴다(#335). 보관된 클래스는 대상이 될 수
// 없다(#326 — 백엔드가 403으로 이미 막는다, `classroom/api.py`의
// `copy_problem`·`template_api.py`의 `import_template`) — 화면은 애초에
// 고를 수 없게 걸러 「골랐는데 403」을 없앤다. 후보가 하나도 없는 것과
// 후보는 있지만 전부 보관된 것을 구별해야 안내 문구가 맞는다.
export type CopyTargetSelection<T extends { archived: boolean }> =
  | { kind: "no-classes" }
  | { kind: "all-archived" }
  | { kind: "ready"; classes: T[] };

export function selectCopyTargets<T extends { archived: boolean }>(classes: T[]): CopyTargetSelection<T> {
  if (classes.length === 0) return { kind: "no-classes" };
  const available = classes.filter((c) => !c.archived);
  if (available.length === 0) return { kind: "all-archived" };
  return { kind: "ready", classes: available };
}
