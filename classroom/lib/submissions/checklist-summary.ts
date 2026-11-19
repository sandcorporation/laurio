// 학생 체크리스트 카드의 맨 위 한 줄(#985) — 「통과까지 1개 남음 · 필수 1/2 · 심화 0/1」.
// 필수 m/n 은 `requiredSummary` 가 정한 값을 그대로 받는다(통과 규칙은 거기·서버가 하나다).
import type { VerdictValue } from "@/lib/submissions/verdict";

export type ChecklistSummaryInput = {
  /** 채점이 끝난 시도가 있으면 그 판정, 없으면 null(대기·채점 중·시도 없음). */
  judged: { passed: boolean; perfect: boolean | null | undefined } | null;
  required: { met: number | null; total: number; unmetCount: number };
  /** 제출자에게 보이는 심화 항목의 판정(판정 전이면 null). */
  advanced: { total: number; verdicts: ReadonlyArray<VerdictValue | null> };
  /** 숨은 심화 항목 — 채점된 점수의 `hidden_summary`. 없으면 null. */
  hidden: { total: number; met: number } | null;
  /** 필수·심화 줄 중 「확인 불가」 판정의 수. */
  unverifiable: number;
};

export function checklistSummaryLine(input: ChecklistSummaryInput): string {
  const { judged, required, advanced, hidden, unverifiable } = input;
  const advancedTotal = advanced.total + (hidden?.total ?? 0);
  const requiredPart = required.total === 0 ? "필수 없음" : null;

  if (!judged) {
    const parts = [requiredPart ?? `필수 ${required.total}개`];
    if (advancedTotal > 0) parts.push(`심화 ${advancedTotal}개`);
    return parts.join(" · ");
  }

  const lead = judged.perfect === true
    ? "완벽"
    : judged.passed
      ? "통과"
      : required.unmetCount > 0
        ? `통과까지 ${required.unmetCount}개 남음`
        : "미통과";
  const parts = [lead];
  parts.push(requiredPart ?? `필수 ${required.met ?? 0}/${required.total}`);
  if (advancedTotal > 0) {
    const met = advanced.verdicts.filter((verdict) => verdict === "met").length + (hidden?.met ?? 0);
    parts.push(`심화 ${met}/${advancedTotal}`);
  }
  if (unverifiable > 0) parts.push(`확인 불가 ${unverifiable}개`);
  return parts.join(" · ");
}

/** 줄 오른쪽의 상태 글자 — 색·모양만으로 말하지 않는다. */
export function verdictStatusText(verdict: VerdictValue | null, required: boolean): string {
  if (verdict === null) return "아직";
  if (verdict === "met") return "통과";
  if (verdict === "unverifiable") return "확인 불가";
  return required ? "미통과" : "아직";
}

/** 줄 앞 표식의 글자꼴 — 충족 ✓ · 미충족 ✕ · 확인 불가 ? · 판정 없음(심화의 미충족 포함) ○. */
export function verdictGlyph(verdict: VerdictValue | null, required: boolean): string {
  if (verdict === "met") return "✓";
  if (verdict === "unverifiable") return "?";
  if (verdict === "unmet" && required) return "✕";
  return "○";
}
