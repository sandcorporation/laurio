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

export function verdictFromMet(met: boolean): VerdictValue {
  return met ? "met" : "unmet";
}

// 항목 앞 네모 표식 — 충족(채움) · 미충족(붉은 테두리) · 확인 불가(점선 잉크) · 아직 판정 없음(옅은 테두리).
export function verdictMarkerClass(verdict: VerdictValue | null): string {
  if (verdict === null) return "border-rule";
  if (verdict === "met") return "border-verified bg-verified";
  if (verdict === "unverifiable") return "border-dashed border-ink/45";
  return "border-attention";
}
