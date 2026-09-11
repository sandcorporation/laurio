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

// 고를 것이 정확히 하나면 그것을 기본값으로 낸다(#349) — 처음 쓰는 사람은
// 대개 클래스가 하나뿐인데, 그때마저 빈 선택으로 시작하면 「가져오기」가
// 왜 막혀 있는지 모른 채 멈춘다. 둘 이상이면 실수로 잘못된 곳에 담기지
// 않도록 여전히 사람이 고른다.
export function defaultCopyTarget<T extends { archived: boolean }>(classes: T[]): T | null {
  const selection = selectCopyTargets(classes);
  if (selection.kind === "ready" && selection.classes.length === 1) {
    return selection.classes[0];
  }
  return null;
}
