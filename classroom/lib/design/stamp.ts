// 판정 도장(#963) — 한 판정에 도장 하나. 완벽이면 완벽 도장만 찍고 통과 도장은 겹치지 않는다.
export type StampKind = "passed" | "perfect";

export function stampKind(passed: boolean, perfect: boolean | null | undefined): StampKind | null {
  if (perfect === true) return "perfect";
  return passed ? "passed" : null;
}

export const STAMP_LABEL: Record<StampKind, string> = { passed: "통과", perfect: "완벽" };

// 「처음 볼 때」 — 같은 브라우저에서 그 도장(scope + 판정)을 이전에 렌더한 적이 없을 때.
const PREFIX = "codemit:stamp-seen:";

export function stampStorageKey(scope: string, kind: StampKind): string {
  return `${PREFIX}${scope}:${kind}`;
}

/** 처음이면 true 를 돌려주고 본 것으로 적는다. 저장소를 못 쓰면 false(움직임 없이 그린다). */
export function consumeFirstView(scope: string, kind: StampKind, storage: Pick<Storage, "getItem" | "setItem">): boolean {
  try {
    const key = stampStorageKey(scope, kind);
    if (storage.getItem(key) !== null) return false;
    storage.setItem(key, "1");
    return true;
  } catch {
    return false;
  }
}
