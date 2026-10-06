// 「모델별 예상 채점 비용」 표를 펼쳐 두었는지(#619) — 그 브라우저에서만 기억한다. 저장소를
// 읽거나 쓰지 못하면(사생활 보호 창·막힌 사이트 데이터) 접힘으로 동작하고 던지지 않는다.
const KEY = "codemit.classroom.scoring-cost-table.open";

export function readCostTableOpen(storage: Storage | null): boolean {
  try {
    return storage?.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

export function writeCostTableOpen(storage: Storage | null, open: boolean): void {
  try {
    if (open) storage?.setItem(KEY, "1");
    else storage?.removeItem(KEY);
  } catch {
    // 기억하지 못할 뿐 — 지금 화면의 펼침은 그대로다.
  }
}
