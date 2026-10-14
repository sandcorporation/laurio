// 체크리스트 순서 옮기기(#637·#670) — `ChecklistRows` 가 끌기·키보드 이동에 쓰는 순수 로직.
//
// 줄은 바뀐 순서를 곧바로 보이고 저장을 시작한다. 저장이 `Promise<boolean>` 을 돌려주면(문제 편집)
// 그 저장이 끝날 때까지 다음 이동을 막고 — ↑↓ 연타로 PATCH 가 겹치지 않게 — 실패하면 서버가
// 아는 순서(`getServerRows`)로 되돌린다. 초안처럼 저장이 아무것도 돌려주지 않으면 막지 않는다.

export type ChecklistReorderSave<K> = (orderedKeys: K[]) => void | Promise<boolean>;

export function createChecklistMover<T extends { key: unknown }>(deps: {
  getRows: () => T[];
  getServerRows: () => T[];
  setRows: (rows: T[]) => void;
  save: ChecklistReorderSave<T["key"]>;
}): (key: T["key"], target: number) => void {
  let inFlight = false;
  return (key, target) => {
    if (inFlight) return;
    const rows = deps.getRows();
    const from = rows.findIndex((row) => row.key === key);
    if (from < 0 || target < 0 || target >= rows.length || target === from) return;
    const next = [...rows];
    const [moved] = next.splice(from, 1);
    next.splice(target, 0, moved);
    deps.setRows(next);
    const saving = deps.save(next.map((row) => row.key));
    if (!saving) return;
    inFlight = true;
    const settle = (ok: boolean) => {
      inFlight = false;
      if (!ok) deps.setRows(deps.getServerRows());
    };
    void saving.then(settle, () => settle(false));
  };
}
