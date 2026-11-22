// 체크리스트 판정의 세 값(#811, ADR-0067) — 충족·미충족·확인 불가. 서버는 `verdict` 를 늘 싣지만, 없는
// 응답(옛 모양)은 `is_met` 에서 읽는다. 확인 불가는 충족이 아니다(`is_met` 은 false).

export type VerdictValue = "met" | "unmet" | "unverifiable";

export const VERDICT_LABEL: Record<VerdictValue, string> = {
  met: "충족",
  unmet: "미충족",
  unverifiable: "확인 불가",
};

export function verdictOf(verdict: { is_met: boolean; verdict?: VerdictValue | null }): VerdictValue {
  if (verdict.verdict === "met" || verdict.verdict === "unmet" || verdict.verdict === "unverifiable") {
    return verdict.verdict;
  }
  return verdict.is_met ? "met" : "unmet";
}

// 판정 출처(#1283) — staged 갈래만 싣는다.
export const SOURCE_LABEL: Record<"machine" | "model", string> = {
  machine: "기계 판정",
  model: "AI 판정",
};

// 근거 인용(#1284) — `경로:줄` 또는 `경로:줄-줄`.
export function citationText(citation: { path: string; start_line: number; end_line: number }): string {
  const lines =
    citation.end_line === citation.start_line ? `${citation.start_line}` : `${citation.start_line}-${citation.end_line}`;
  return `${citation.path}:${lines}`;
}

export function verdictFromMet(met: boolean): VerdictValue {
  return met ? "met" : "unmet";
}

// 항목 앞 네모 표식 — 충족(채움) · 미충족(붉은 테두리) · 확인 불가(점선 잉크) · 아직 판정 없음(옅은 테두리).
export function verdictMarkerClass(verdict: VerdictValue | null): string {
  if (verdict === null) return "border-rule";
  if (verdict === "met") return "border-success bg-success";
  if (verdict === "unverifiable") return "border-dashed border-ink/45";
  return "border-error";
}
