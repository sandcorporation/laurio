// 체크리스트 항목 입력칸 아래 한 줄(#810). 문장의 출처는 백엔드
// `classroom/gradability_hint.py` 의 `GRADABILITY_FORM_NOTE` 이고, 두 곳이 같음을
// `backend/tests/test_classroom_gradability_hint.py` 가 지킨다(vitest 는 파이썬을 못 읽는다).
export const GRADABILITY_FORM_NOTE =
  "채점은 소스·설정·README 의 정적 내용만 확인합니다 — 실행·접속 결과는 「…하는 코드가 있다」로 씁니다.";

/** 저장 응답의 `gradability_warnings` 한 건 — 백엔드 `GradabilityWarningOut` 과 같은 모양. */
export type GradabilityWarning = { checklist_item_id: number; text: string; reason: string };

/** 걸린 항목 옆에 보이는 한 줄 — 「~일 수 있다」 어조, 저장은 막지 않는다. */
export function gradabilityWarningLine(reason: string): string {
  return `채점이 확인하지 못할 수 있습니다 — ${reason}`;
}

const HANDOFF_PREFIX = "codemit:gradability:";

/** 문제 만들기 화면에서 상세 화면으로 넘어갈 때 경고를 건넨다(한 번 읽으면 지운다). */
export function stashWarnings(storage: Pick<Storage, "setItem">, problemId: number, warnings: GradabilityWarning[]): void {
  if (warnings.length === 0) return;
  try {
    storage.setItem(HANDOFF_PREFIX + problemId, JSON.stringify(warnings));
  } catch {
    // 저장소를 못 쓰는 환경 — 경고는 없어도 화면은 맞다.
  }
}

export function takeWarnings(storage: Pick<Storage, "getItem" | "removeItem">, problemId: number): GradabilityWarning[] {
  try {
    const raw = storage.getItem(HANDOFF_PREFIX + problemId);
    if (raw === null) return [];
    storage.removeItem(HANDOFF_PREFIX + problemId);
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as GradabilityWarning[]) : [];
  } catch {
    return [];
  }
}
