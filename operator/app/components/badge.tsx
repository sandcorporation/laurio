// 배지는 두 종류뿐이다(#422, 부모 #421) — **중립**(대기·정보)과 **판정**(통과
// 초록·주의 빨강). 지급 대기 셋은 중립 배지에 글자로만 갈리고, 색으로 겁주지
// 않는다(ADR-0020) — 셋 다 「누군가의 차례」이지 실패가 아니다.
//
// 판정(pass/attention)은 통과·미충족처럼 실제로 갈리는 판정에만 쓴다 — 대기에
// 쓰면 색이 뜻을 잃는다(spec #421 user story 17).
import type { ReactNode } from "react";

export type BadgeTone = "neutral" | "pass" | "attention";

const TONE_CLASS: Record<BadgeTone, string> = {
  neutral: "border-rule text-ink/62",
  pass: "border-verified text-verified",
  attention: "border-attention text-attention",
};

export function Badge({
  tone = "neutral",
  children,
  testId,
}: {
  tone?: BadgeTone;
  children: ReactNode;
  testId?: string;
}) {
  return (
    <span
      data-testid={testId}
      data-tone={tone}
      className={`inline-block whitespace-nowrap rounded-sm border px-1.5 py-0.5 text-[11px] leading-[15px] ${TONE_CLASS[tone]}`}
    >
      {children}
    </span>
  );
}
